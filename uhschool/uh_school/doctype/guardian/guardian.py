import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime


class Guardian(Document):
    def validate(self):
        if not self.user and not self.email:
            frappe.throw(_("A family account needs an email address."))
        self.set_plan_limits()
        if self.consent_given and not self.consent_on:
            self.consent_on = now_datetime()
        if not self.consent_given:
            self.consent_on = None

    def set_plan_limits(self):
        # base plan: 1 kid + 1 spectator slot; add-ons on top
        extra_kids = max(0, cint(self.extra_students))
        extra_slots = max(0, cint(self.extra_spectators))
        self.extra_students, self.extra_spectators = extra_kids, extra_slots
        self.student_limit = 1 + extra_kids
        self.spectator_limit = 1 + extra_slots

        if not self.is_new():
            active = frappe.db.count("Student", {"guardian": self.name, "active": 1})
            if active > self.student_limit:
                frappe.throw(_("This family has {0} active kids but the plan allows {1}. "
                               "Deactivate a kid or keep the add-on.").format(
                                   active, self.student_limit))

    def on_update(self):
        if self.user:
            return
        existing = frappe.db.exists("User", self.email)
        if existing:
            user = frappe.get_doc("User", existing)
        else:
            user = frappe.get_doc({
                "doctype": "User",
                "email": self.email,
                "first_name": self.full_name,
                "user_type": "Website User",
                "send_welcome_email": 0,
            }).insert(ignore_permissions=True)
        user.flags.ignore_permissions = True
        user.add_roles("Guardian")
        self.db_set("user", user.name)
