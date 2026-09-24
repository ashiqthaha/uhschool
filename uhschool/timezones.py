"""One clock, many home time zones.

The system clock runs on UTC (System Settings → Time Zone = UTC), so every Datetime in the
database is UTC. Each person has a home time zone on their User record (User.time_zone):
  - Tutor      → Tutor.timezone
  - Guardian   → Guardian.timezone
  - Student    → their family's (Guardian's) timezone
  - Staff      → set on their own User profile
The desk converts Datetime fields to the user's time zone by itself. Web pages and messages
use to_user_time() / format_for_user() below.
"""

from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

import frappe
from frappe import _
from frappe.utils import get_datetime, get_system_timezone


@lru_cache(maxsize=1)
def _all_zones():
    return frozenset(available_timezones())


def validate_timezone(tz, label=None):
    if tz not in _all_zones():
        frappe.throw(_("{0}: '{1}' isn't a known time zone. Pick one from the list, e.g. "
                       "America/New_York or Asia/Kolkata.").format(label or _("Home time zone"), tz))


def user_timezone(user=None):
    user = user or frappe.session.user
    return frappe.db.get_value("User", user, "time_zone") or get_system_timezone()


def to_user_time(value, user=None, tz=None):
    """A stored (system clock) datetime, as an aware datetime in the user's home time zone."""
    if not value:
        return None
    stored = get_datetime(value)
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=ZoneInfo(get_system_timezone()))
    return stored.astimezone(ZoneInfo(tz or user_timezone(user)))


def to_system_time(local_value, tz):
    """A wall-clock datetime in `tz`, converted to the stored (system clock) naive datetime."""
    local = get_datetime(local_value)
    if local.tzinfo is None:
        local = local.replace(tzinfo=ZoneInfo(tz))
    return local.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def format_for_user(value, user=None, tz=None, fmt="%a %d %b, %I:%M %p"):
    local = to_user_time(value, user, tz)
    return local.strftime(fmt).replace(" 0", " ") if local else ""


def set_user_timezone(user, tz):
    if user and tz and frappe.db.get_value("User", user, "time_zone") != tz:
        frappe.db.set_value("User", user, "time_zone", tz)
        frappe.clear_cache(user=user)


def sync_family(guardian):
    """Copy the family's home time zone to the parent's login and every kid's login."""
    g = frappe.db.get_value("Guardian", guardian, ["user", "timezone"], as_dict=True)
    if not g or not g.timezone:
        return
    set_user_timezone(g.user, g.timezone)
    for kid_user in frappe.get_all("Student", filters={"guardian": guardian, "user": ["is", "set"]},
                                   pluck="user"):
        set_user_timezone(kid_user, g.timezone)


@frappe.whitelist()
def now_for_me():
    """Current time on the central clock and in the caller's home time zone (handy for checks)."""
    tz = user_timezone()
    now_utc = datetime.now(ZoneInfo("UTC"))
    return {"utc": now_utc.isoformat(timespec="seconds"), "home_time_zone": tz,
            "home": now_utc.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")}
