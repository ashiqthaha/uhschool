from datetime import timedelta
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import now_datetime

from uhschool.timezones import format_for_user, user_timezone
from uhschool.video import STAFF_ROLES, join_window

no_cache = 1


def get_context(context):
    user = frappe.session.user
    if user == "Guest":
        target = "/join" + (f"?session={quote(frappe.form_dict.session)}" if frappe.form_dict.session else "")
        frappe.local.flags.redirect_location = f"/login?redirect-to={quote(target)}"
        raise frappe.Redirect

    context.title = _("Classes")
    context.no_breadcrumbs = True
    context.auto_join = frappe.form_dict.session or ""
    context.tz, context.sessions = my_sessions(user)
    return context


def my_sessions(user):
    """Classes from 3 hours ago to 7 days ahead that this user can join, in their home time zone."""
    tutors = frappe.get_all("Tutor", filters={"user": user}, pluck="name")
    students = frappe.get_all("Student", filters={"user": user}, pluck="name")
    guardians = frappe.get_all("Guardian", filters={"user": user}, fields=["name", "timezone"])
    is_staff = bool(STAFF_ROLES & set(frappe.get_roles(user)))

    tz = user_timezone(user)  # the person's home time zone

    now = now_datetime()
    filters = {
        "status": ["in", ["Scheduled", "Completed"]],
        "starts_at": ["between", [now - timedelta(hours=3), now + timedelta(days=7)]],
    }
    if not is_staff:
        kids = students + frappe.get_all(
            "Student", filters={"guardian": ["in", [g.name for g in guardians] or [""]]}, pluck="name")
        or_filters = {"tutor": ["in", tutors or [""]], "student": ["in", kids or [""]]}
    else:
        or_filters = None

    rows = frappe.get_all(
        "Tutoring Session", filters=filters, or_filters=or_filters,
        fields=["name", "student", "tutor", "starts_at", "duration", "status"],
        order_by="starts_at asc", limit=50,
    )

    out = []
    for r in rows:
        opens, closes = join_window(r)
        if now > closes:
            continue
        out.append({
            "name": r.name,
            "student": frappe.db.get_value("Student", r.student, "first_name"),
            "tutor": frappe.db.get_value("Tutor", r.tutor, "full_name"),
            "when": format_for_user(r.starts_at, tz=tz),
            "duration": r.duration,
            "can_join": opens <= now,
            "opens": format_for_user(opens, tz=tz, fmt="%I:%M %p").lstrip("0"),
        })
    return tz, out
