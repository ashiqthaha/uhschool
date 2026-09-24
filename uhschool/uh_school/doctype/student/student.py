import re

import frappe
from frappe import _
from frappe.model.document import Document

from uhschool.timezones import set_user_timezone

STUDENT_EMAIL_DOMAIN = "students.uhschool.ashiqthaha.com"  # placeholder, never mailed


class Student(Document):
    def validate(self):
        if self.active:
            self.check_plan_limit()

    def check_plan_limit(self):
        limit = frappe.db.get_value("Guardian", self.guardian, "student_limit") or 1
        others = frappe.db.count("Student", {
            "guardian": self.guardian, "active": 1, "name": ["!=", self.name or ""],
        })
        if others + 1 > limit:
            frappe.throw(_("This family's plan covers {0} kid(s). "
                           "Add the 'extra kids' add-on on the family record first.").format(limit))

    def on_update(self):
        # runs after insert and after every save
        if not self.user:
            self.create_account()
        else:
            frappe.db.set_value("User", self.user, "enabled", 1 if self.active else 0)
        # kids live on their family's home time zone
        set_user_timezone(self.user, frappe.db.get_value("Guardian", self.guardian, "timezone"))

    def create_account(self):
        username = self.make_username()
        user = frappe.get_doc({
            "doctype": "User",
            "email": f"{self.name.lower()}@{STUDENT_EMAIL_DOMAIN}",
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": username,
            "user_type": "Website User",
            "send_welcome_email": 0,
            "enabled": 1 if self.active else 0,
        })
        user.insert(ignore_permissions=True)
        user.flags.ignore_permissions = True
        user.add_roles("LMS Student")
        self.db_set({"user": user.name, "username": username})

    def make_username(self):
        base = re.sub(r"[^a-z0-9]", "", (self.first_name or "").lower()) or "student"
        candidate, n = base, 1
        while frappe.db.exists("User", {"username": candidate}):
            n += 1
            candidate = f"{base}{n}"
        return candidate
