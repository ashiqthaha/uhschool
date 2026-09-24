"""Video sessions: Frappe issues every LiveKit join token and keeps the attendance log.

Site config keys (bench --site <site> set-config <key> <value>):
    livekit_api_key, livekit_api_secret   required
    livekit_url            public signaling URL, e.g. wss://rtc-uhschool.ashiqthaha.com
    livekit_host           server-side API URL (default http://localhost:7880)
    video_app_url          our Meet fork (default /meet, served on this same site via the tunnel)
    video_join_before_min  how early people may join (default 10)
    video_join_after_min   how long after the end people may join (default 15)
"""

import json
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import frappe
import requests
from frappe import _
from frappe.utils import cint, get_datetime, get_system_timezone, now_datetime

STAFF_ROLES = {"System Manager", "Headmaster"}
VIEWER_ROLES = ("Spectator", "Staff")
PENDING_GRACE = timedelta(minutes=2)  # a token counts toward a slot while its device is connecting
TOKEN_TTL = timedelta(minutes=15)  # time allowed to connect; LiveKit refreshes it once connected

SLOT_IN_USE = _(
    "Your viewing slot is in use on another device. Close the class on that device, "
    "or add an extra viewing slot to your family plan."
)


# ---------------------------------------------------------------- config


def _conf(key, default=None):
    return frappe.conf.get(key) or default


def _keys():
    key, secret = _conf("livekit_api_key"), _conf("livekit_api_secret")
    if not key or not secret:
        frappe.throw(_("Video isn't set up on this site yet."))
    return key, secret


def join_window(session):
    start = get_datetime(session.starts_at)
    end = start + timedelta(minutes=cint(session.duration))
    return (
        start - timedelta(minutes=cint(_conf("video_join_before_min", 10))),
        end + timedelta(minutes=cint(_conf("video_join_after_min", 15))),
    )


# ---------------------------------------------------------------- who is joining


def decide_role(session, user):
    """Return (participant_role, display_name) for this user in this session, or throw."""
    tutor = frappe.db.get_value("Tutor", session.tutor, ["user", "full_name"], as_dict=True)
    if tutor and tutor.user == user:
        return "Tutor", tutor.full_name

    student = frappe.db.get_value(
        "Student", session.student, ["user", "first_name", "guardian"], as_dict=True
    )
    if student and student.user == user:
        return "Student", student.first_name

    if student and frappe.db.get_value("Guardian", student.guardian, "user") == user:
        return "Spectator", _("Parent of {0}").format(student.first_name)

    if STAFF_ROLES & set(frappe.get_roles(user)):
        return "Staff", frappe.utils.get_fullname(user)

    frappe.throw(_("You're not part of this class."), frappe.PermissionError)


def spectator_slots_in_use(guardian, user, device_id):
    """Viewer devices this family has open right now, not counting this device."""
    now = now_datetime()
    return frappe.db.sql(
        """
        select count(*) from `tabSession Attendance` a
        join `tabTutoring Session` s on s.name = a.tutoring_session
        join `tabStudent` st on st.name = s.student
        where st.guardian = %(guardian)s
          and a.participant_role = 'Spectator'
          and a.left_at is null
          and a.token_issued_at > %(day_ago)s
          and (a.joined_at is not null or a.token_issued_at > %(pending_since)s)
          and a.identity not like %(this_device)s
        """,
        {
            "guardian": guardian,
            "day_ago": now - timedelta(days=1),
            "pending_since": now - PENDING_GRACE,
            "this_device": f"{user}|{device_id}|%",
        },
    )[0][0]


# ---------------------------------------------------------------- device details


def _client_ip():
    headers = frappe.request.headers if frappe.request else {}
    return headers.get("CF-Connecting-IP") or frappe.local.request_ip


def parse_user_agent(ua):
    ua = ua or ""
    if re.search(r"iPad|Tablet|Android(?!.*Mobile)", ua):
        device = "Tablet"
    elif re.search(r"Mobi|iPhone|Android", ua):
        device = "Mobile"
    else:
        device = "Desktop"

    os_name = next(
        (name for pattern, name in (
            (r"Android", "Android"), (r"iPhone|iPad|iPod", "iOS"), (r"Windows", "Windows"),
            (r"Mac OS X|Macintosh", "macOS"), (r"CrOS", "ChromeOS"), (r"Linux", "Linux"),
        ) if re.search(pattern, ua)),
        "Other",
    )
    browser = next(
        (name for pattern, name in (
            (r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"SamsungBrowser", "Samsung Internet"),
            (r"Firefox/|FxiOS", "Firefox"), (r"Chrome/|CriOS", "Chrome"), (r"Safari/", "Safari"),
        ) if re.search(pattern, ua)),
        "Other",
    )
    return device, os_name, browser


# ---------------------------------------------------------------- join token


@frappe.whitelist(methods=["POST"])
def get_token(session, device_id):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Please sign in to join the class."), frappe.AuthenticationError)

    device_id = re.sub(r"[^A-Za-z0-9-]", "", device_id or "")[:40]
    if len(device_id) < 8:
        frappe.throw(_("This browser didn't send a device ID. Reload the page and try again."))

    doc = frappe.db.get_value(
        "Tutoring Session", session,
        ["name", "student", "tutor", "starts_at", "duration", "status"], as_dict=True,
    )
    if not doc:
        frappe.throw(_("Class not found."), frappe.DoesNotExistError)

    role, display_name = decide_role(doc, user)

    if doc.status == "Cancelled":
        frappe.throw(_("This class was cancelled."))
    if doc.status == "No-show":
        frappe.throw(_("This class is over. It was marked as a no-show."))
    opens, closes = join_window(doc)
    now = now_datetime()
    if now < opens:
        wait = int((opens - now).total_seconds() // 60) + 1
        frappe.throw(_("You can join {0} minutes before class starts. Joining opens in {1} minute(s).").format(
            cint(_conf("video_join_before_min", 10)), wait))
    if now > closes:
        frappe.throw(_("This class has ended."))

    if role == "Spectator":
        guardian = frappe.db.get_value("Student", doc.student, "guardian")
        limit = cint(frappe.db.get_value("Guardian", guardian, "spectator_limit")) or 1
        # lock the family row so two devices can't take the last slot at the same moment
        frappe.db.sql("select name from `tabGuardian` where name = %s for update", guardian)
        if spectator_slots_in_use(guardian, user, device_id) >= limit:
            frappe.throw(SLOT_IN_USE, title=_("Viewing slot in use"))

    identity = f"{user}|{device_id}|{secrets.token_hex(3)}"
    ua = frappe.get_request_header("User-Agent") or ""
    device_type, os_name, browser = parse_user_agent(ua)
    frappe.get_doc({
        "doctype": "Session Attendance",
        "tutoring_session": doc.name,
        "user": user,
        "participant_role": role,
        "identity": identity,
        "token_issued_at": now,
        "device_type": device_type,
        "os": os_name,
        "browser": browser,
        "ip_address": _client_ip(),
        "user_agent": ua[:1000],
    }).insert(ignore_permissions=True)

    token = make_token(doc.name, identity, display_name, role)
    url = _conf("livekit_url")
    video_app = _conf("video_app_url", "/meet").rstrip("/")
    return {
        "role": role,
        "room": doc.name,
        "url": url,
        "token": token,
        # after the #, so the token never reaches a server or its logs
        "join_url": f"{video_app}/class#" + urlencode({"url": url, "token": token}),
    }


def make_token(room, identity, display_name, role):
    from livekit import api

    key, secret = _keys()
    publishes = role in ("Tutor", "Student")
    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_subscribe=True,
        can_publish=publishes,
        can_publish_data=publishes,
        can_update_own_metadata=False,
        hidden=not publishes,  # parents and staff watch without appearing in the class
    )
    return (
        api.AccessToken(key, secret)
        .with_identity(identity)
        .with_name(display_name or "")
        .with_metadata(json.dumps({"role": role}))
        .with_attributes({"role": role})
        .with_ttl(TOKEN_TTL)
        .with_grants(grants)
        .to_jwt()
    )


# ---------------------------------------------------------------- webhook


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook():
    from livekit import api

    key, secret = _keys()
    body = frappe.request.get_data(as_text=True)
    auth = frappe.get_request_header("Authorization") or ""
    try:
        event = api.WebhookReceiver(api.TokenVerifier(key, secret)).receive(body, auth)
    except Exception:
        frappe.throw(_("Invalid webhook signature."), frappe.AuthenticationError)

    room = event.room.name
    if not room or not frappe.db.exists("Tutoring Session", room):
        return "ignored"

    at = _from_epoch(event.created_at)
    if event.event == "participant_joined":
        row = _row(event.participant.identity)
        if row and not row.joined_at:
            joined = _from_epoch(event.participant.joined_at) or at
            frappe.db.set_value("Session Attendance", row.name, "joined_at", joined)
        _publish_viewer_count(room)
    elif event.event == "participant_left":
        row = _row(event.participant.identity)
        if row and not row.left_at:
            _close_row(row, at)
        _publish_viewer_count(room)
    elif event.event == "room_finished":
        close_open_rows(room, at)
        settle_status(room)
    return "ok"


def _from_epoch(seconds):
    if not seconds:
        return None
    local = datetime.fromtimestamp(int(seconds), ZoneInfo(get_system_timezone()))
    return local.replace(tzinfo=None)


def _row(identity):
    if not identity:
        return None
    return frappe.db.get_value(
        "Session Attendance", {"identity": identity}, ["name", "joined_at", "left_at"], as_dict=True
    )


def _close_row(row, left_at):
    left_at = left_at or now_datetime()
    joined = get_datetime(row.joined_at) if row.joined_at else None
    frappe.db.set_value("Session Attendance", row.name, {
        "left_at": left_at,
        "duration_seconds": max(0, int((left_at - joined).total_seconds())) if joined else 0,
    })


def close_open_rows(session, at=None):
    rows = frappe.get_all(
        "Session Attendance",
        filters={"tutoring_session": session, "left_at": ["is", "not set"]},
        fields=["name", "joined_at", "left_at"],
    )
    for row in rows:
        _close_row(row, at)


def _viewer_count(session):
    return frappe.db.count("Session Attendance", {
        "tutoring_session": session,
        "participant_role": ["in", VIEWER_ROLES],
        "joined_at": ["is", "set"],
        "left_at": ["is", "not set"],
    })


def _publish_viewer_count(room):
    """Put {"viewers": N} in the room metadata; the video app shows it as the 👁 badge."""
    from livekit import api

    key, secret = _keys()
    admin = (
        api.AccessToken(key, secret)
        .with_grants(api.VideoGrants(room_admin=True, room=room))
        .with_ttl(timedelta(minutes=1))
        .to_jwt()
    )
    host = _conf("livekit_host", "http://localhost:7880").rstrip("/")
    try:
        requests.post(
            f"{host}/twirp/livekit.RoomService/UpdateRoomMetadata",
            json={"room": room, "metadata": json.dumps({"viewers": _viewer_count(room)})},
            headers={"Authorization": f"Bearer {admin}"},
            timeout=5,
        ).raise_for_status()
    except Exception:
        frappe.log_error(title=f"LiveKit: viewer count update failed for {room}")


def _attended(session, role):
    return frappe.db.exists("Session Attendance", {
        "tutoring_session": session, "participant_role": role, "joined_at": ["is", "set"],
    })


def settle_status(session, final=False):
    """Completed once tutor and kid have both been in the room.
    No-show only when final, i.e. the join window has closed without that."""
    if frappe.db.get_value("Tutoring Session", session, "status") != "Scheduled":
        return
    if _attended(session, "Tutor") and _attended(session, "Student"):
        frappe.db.set_value("Tutoring Session", session, "status", "Completed")
    elif final:
        frappe.db.set_value("Tutoring Session", session, "status", "No-show")


# ---------------------------------------------------------------- scheduler


def close_finished_sessions():
    """Every 10 minutes: settle classes whose join window has closed."""
    now = now_datetime()
    after = cint(_conf("video_join_after_min", 15))
    sessions = frappe.db.sql(
        """
        select name from `tabTutoring Session`
        where status = 'Scheduled'
          and starts_at > %(since)s
          and date_add(starts_at, interval (duration + %(after)s) minute) < %(now)s
        """,
        {"since": now - timedelta(days=3), "after": after, "now": now},
        pluck=True,
    )
    for name in sessions:
        close_open_rows(name)
        settle_status(name, final=True)
    frappe.db.commit()
