"""Move the system clock to UTC (runs once, on `bench migrate`).

Until now datetimes were stored in the old system time zone (e.g. America/New_York).
This converts every stored datetime in Uh-school's own tables to UTC, gives every login a
home time zone, then sets System Settings → Time Zone = UTC.

Frappe's own tables (logs, versions, etc.) are left as they are: their older timestamps
will read a few hours off. That's pre-launch test history only.
"""

from datetime import UTC
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone

DOCTYPES = (
    "Guardian", "Student", "Tutor", "Tutor Availability",
    "Tutoring Session", "Session Attendance", "Progress Log",
)


def execute():
    old = get_system_timezone()
    if old in ("UTC", "Etc/UTC"):
        return
    old_tz = ZoneInfo(old)

    for doctype in DOCTYPES:
        if not frappe.db.exists("DocType", doctype):
            continue
        fields = ["creation", "modified"] + [
            df.fieldname for df in frappe.get_meta(doctype).fields if df.fieldtype == "Datetime"
        ]
        rows = frappe.db.sql(f"select name, {', '.join(f'`{f}`' for f in fields)} from `tab{doctype}`",
                             as_dict=True)
        for row in rows:
            updates = {
                f: get_datetime(row[f]).replace(tzinfo=old_tz).astimezone(UTC).replace(tzinfo=None)
                for f in fields if row[f]
            }
            if updates:
                sets = ", ".join(f"`{f}` = %({f})s" for f in updates)
                frappe.db.sql(f"update `tab{doctype}` set {sets} where name = %(name)s",
                              {**updates, "name": row.name})

    # every login gets a home time zone
    from uhschool.timezones import set_user_timezone, sync_family

    for guardian in frappe.get_all("Guardian", pluck="name"):
        sync_family(guardian)
    for t in frappe.get_all("Tutor", filters={"user": ["is", "set"]}, fields=["user", "timezone"]):
        set_user_timezone(t.user, t.timezone or "Asia/Kolkata")
    # staff and admins keep seeing the desk in the old local time
    for user in frappe.get_all("User", filters={"user_type": "System User", "time_zone": ["is", "not set"]},
                               pluck="name"):
        set_user_timezone(user, old)
    set_user_timezone("Administrator", frappe.db.get_value("User", "Administrator", "time_zone") or old)

    # saving the doc (not just the value) also updates the defaults the desk boots with
    settings = frappe.get_single("System Settings")
    settings.time_zone = "UTC"
    settings.flags.ignore_mandatory = True
    settings.save(ignore_permissions=True)
    frappe.cache.delete_value("time_zone")
    frappe.clear_cache()
