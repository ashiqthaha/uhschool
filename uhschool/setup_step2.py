"""
Uh-school step 2: login modes, family accounts, Headmaster role, Session Attendance.

Run on the server (developer_mode must be on):
    bench --site dev.uhschool.local execute uhschool.setup_step2.run

Safe to re-run: anything that already exists is skipped.
"""

import frappe

ADMIN = {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1,
         "report": 1, "export": 1, "print": 1, "email": 1, "share": 1}
HEADMASTER = {"role": "Headmaster", "read": 1, "report": 1, "export": 1, "print": 1}


def f(fieldname, fieldtype, label=None, **kw):
    d = {"fieldname": fieldname, "fieldtype": fieldtype,
         "label": label or fieldname.replace("_", " ").title()}
    d.update(kw)
    return d


NEW_FIELDS = {
    "Student": [
        f("login_section", "Section Break", "Login"),
        f("login_mode", "Select", options="Through parent\nOwn login",
          default="Through parent", reqd=1,
          description="Own login: the kid signs in with a username. "
                      "Through parent: the parent opens the kid's account from theirs."),
        f("user", "Link", "Account", options="User", read_only=1),
        f("username", "Data", read_only=1, in_list_view=1),
    ],
    "Guardian": [
        f("plan_section", "Section Break", "Plan",
          description="Base plan: 1 kid and 1 spectator slot. Everything else is an add-on."),
        f("extra_students", "Int", "Add-on: extra kids", default="0"),
        f("extra_spectators", "Int", "Add-on: extra spectator slots", default="0",
          description="Each slot lets one more device watch a session at the same time."),
        f("plan_col", "Column Break"),
        f("student_limit", "Int", "Kids allowed", read_only=1, default="1"),
        f("spectator_limit", "Int", "Spectator slots", read_only=1, default="1"),
        f("consent_section", "Section Break", "Consent"),
        f("consent_given", "Check", "Parent consent recorded",
          description="Covers the child's account, session recordings if enabled, "
                      "and logging of viewing devices and IP addresses."),
        f("consent_on", "Datetime", "Consent recorded on", read_only=1),
    ],
}

SESSION_ATTENDANCE = {
    "name": "Session Attendance",
    "autoname": "format:ATT-{######}",
    "in_create": 1,      # created by the system, not by hand
    "read_only": 1,
    "sort_field": "creation",
    "fields": [
        f("tutoring_session", "Link", options="Tutoring Session", reqd=1,
          in_list_view=1, in_standard_filter=1),
        f("user", "Link", options="User", in_list_view=1, in_standard_filter=1),
        f("participant_role", "Select", "Role",
          options="Tutor\nStudent\nSpectator\nStaff", in_list_view=1, in_standard_filter=1),
        f("identity", "Data", "LiveKit identity", unique=1,
          description="Account + device ID. One row per device connection."),
        f("col_1", "Column Break"),
        f("token_issued_at", "Datetime"),
        f("joined_at", "Datetime", in_list_view=1),
        f("left_at", "Datetime"),
        f("duration_seconds", "Int", "Duration (seconds)"),
        f("device_section", "Section Break", "Device"),
        f("device_type", "Data", in_list_view=1),
        f("os", "Data", "OS"),
        f("browser", "Data"),
        f("col_2", "Column Break"),
        f("ip_address", "Data", "IP address"),
        f("user_agent", "Small Text"),
    ],
    "permissions": [ADMIN, HEADMASTER],
}

HEADMASTER_READS = ["Guardian", "Student", "Tutor", "Tutoring Session", "Progress Log"]


def ensure_role(name, desk_access):
    if not frappe.db.exists("Role", name):
        frappe.get_doc({"doctype": "Role", "role_name": name,
                        "desk_access": desk_access}).insert()
        print(f"  + role {name}")


def run():
    if not frappe.conf.developer_mode:
        frappe.throw("Turn on developer_mode first.")

    module = frappe.db.get_value("DocType", "Student", "module")

    ensure_role("Headmaster", 1)

    # new fields on existing DocTypes
    for dt, fields in NEW_FIELDS.items():
        doc = frappe.get_doc("DocType", dt)
        added = []
        for fld in fields:
            if not doc.get("fields", {"fieldname": fld["fieldname"]}):
                doc.append("fields", fld)
                added.append(fld["fieldname"])
        if added:
            doc.save()
            print(f"  + {dt}: {', '.join(added)}")

    # Headmaster can read the core records
    for dt in HEADMASTER_READS:
        doc = frappe.get_doc("DocType", dt)
        if not doc.get("permissions", {"role": "Headmaster"}):
            doc.append("permissions", HEADMASTER)
            doc.save()
            print(f"  + Headmaster can read {dt}")

    # attendance log
    if not frappe.db.exists("DocType", SESSION_ATTENDANCE["name"]):
        frappe.get_doc({"doctype": "DocType", "module": module, "custom": 0,
                        "track_changes": 0, "istable": 0, **SESSION_ATTENDANCE}).insert()
        print("  + Session Attendance")

    # kids with their own login sign in by username
    frappe.db.set_single_value("System Settings", "allow_login_using_user_name", 1)
    print("  + username login enabled")

    frappe.db.commit()

    # existing families: keep any add-ons already set, and grandfather extra kids
    for name in frappe.get_all("Guardian", pluck="name"):
        g = frappe.db.get_value("Guardian", name,
                                ["extra_students", "extra_spectators"], as_dict=True)
        kids = frappe.db.count("Student", {"guardian": name, "active": 1})
        extra_kids = max(g.extra_students or 0, kids - 1)
        extra_slots = g.extra_spectators or 0
        frappe.db.set_value("Guardian", name, {
            "extra_students": extra_kids, "extra_spectators": extra_slots,
            "student_limit": 1 + extra_kids, "spectator_limit": 1 + extra_slots,
        }, update_modified=False)
        if extra_kids > (g.extra_students or 0):
            print(f"  = {name}: {kids} active kids, extra kids add-on set to {extra_kids}")
    frappe.db.commit()

    # backfill accounts for records that already exist
    for name in frappe.get_all("Guardian", pluck="name"):
        g = frappe.get_doc("Guardian", name)
        if not g.user and g.email:
            g.save()
            print(f"  + family account for {g.full_name}")
        elif not g.user:
            print(f"  ! {g.full_name} has no email, add one and save")
    for name in frappe.get_all("Student", pluck="name"):
        s = frappe.get_doc("Student", name)
        if not s.user:
            s.save()
            print(f"  + account for {s.first_name}: username {s.username}")

    frappe.db.commit()
    print("\nDone.")
