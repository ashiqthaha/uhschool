from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, get_system_timezone, get_time

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _to_time(value):
    # Time fields come back from the DB as timedelta, from the form as str
    if isinstance(value, timedelta):
        return (datetime.min + value).time()
    return get_time(value)


class TutoringSession(Document):
    def validate(self):
        if cint(self.duration) <= 0:
            frappe.throw(_("Duration must be more than 0 minutes."))
        if self.status == "Cancelled":
            return
        self.check_active()
        self.check_tutor_availability()
        self.check_overlap("tutor")
        self.check_overlap("student")

    @property
    def start(self):
        return get_datetime(self.starts_at)

    @property
    def end(self):
        return self.start + timedelta(minutes=cint(self.duration))

    def check_active(self):
        if not frappe.db.get_value("Tutor", self.tutor, "active"):
            frappe.throw(_("Tutor {0} is not active.").format(self.tutor))
        if not frappe.db.get_value("Student", self.student, "active"):
            frappe.throw(_("Student {0} is not active.").format(self.student))

    def check_tutor_availability(self):
        tutor = frappe.get_doc("Tutor", self.tutor)
        sys_tz = ZoneInfo(get_system_timezone())
        tutor_tz = ZoneInfo(tutor.timezone or "Asia/Kolkata")

        local_start = self.start.replace(tzinfo=sys_tz).astimezone(tutor_tz)
        local_end = local_start + timedelta(minutes=cint(self.duration))
        day = WEEKDAYS[local_start.weekday()]

        for slot in tutor.availability:
            if slot.weekday != day:
                continue
            if (local_start.date() == local_end.date()
                    and _to_time(slot.start_time) <= local_start.time()
                    and local_end.time() <= _to_time(slot.end_time)):
                return

        frappe.throw(_(
            "{0} isn't available then. That's {1} {2}–{3} in the tutor's time ({4})."
        ).format(tutor.full_name, day, local_start.strftime("%H:%M"),
                 local_end.strftime("%H:%M"), tutor_tz.key))

    def check_overlap(self, field):
        clash = frappe.db.sql(
            f"""
            select name, starts_at from `tabTutoring Session`
            where `{field}` = %(value)s
              and name != %(name)s
              and status != 'Cancelled'
              and starts_at < %(end)s
              and date_add(starts_at, interval duration minute) > %(start)s
            limit 1
            """,
            {"value": self.get(field), "name": self.name or "", "start": self.start, "end": self.end},
            as_dict=True,
        )
        if clash:
            frappe.throw(_("This {0} already has session {1} at {2}.").format(
                field, clash[0].name, clash[0].starts_at))
