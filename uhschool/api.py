import frappe
from frappe import _


@frappe.whitelist(methods=["POST"])
def switch_to_student(student):
    """A parent opens their child's account (Through parent mode only)."""
    s = frappe.db.get_value(
        "Student", student, ["user", "guardian", "login_mode", "active"], as_dict=True
    )
    if not s:
        frappe.throw(_("Student not found."), frappe.DoesNotExistError)

    guardian_user = frappe.db.get_value("Guardian", s.guardian, "user")
    if not guardian_user or frappe.session.user != guardian_user:
        frappe.throw(_("You can only open your own children's accounts."),
                     frappe.PermissionError)
    if s.login_mode != "Through parent":
        frappe.throw(_("This child signs in with their own login."))
    if not s.active or not s.user:
        frappe.throw(_("This child's account isn't active."))

    frappe.local.login_manager.login_as(s.user)
    return {"redirect": "/lms"}
