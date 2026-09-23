"""
Uh-school: create roles and core DocTypes in the uhschool app.

Run on the server:
    bench --site dev.uhschool.local execute uhschool.setup_doctypes.run

Needs developer_mode = 1 so the DocTypes are written into the app as JSON
files (and can be committed to git). Safe to re-run: existing DocTypes are skipped.
"""

import frappe

LEVELS = "Beginner\nCan speak\nCan read\nCan write"
WEEKDAYS = "Monday\nTuesday\nWednesday\nThursday\nFriday\nSaturday\nSunday"

ADMIN = {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1,
         "report": 1, "export": 1, "print": 1, "email": 1, "share": 1}


def f(fieldname, fieldtype, label=None, **kw):
    d = {"fieldname": fieldname, "fieldtype": fieldtype,
         "label": label or fieldname.replace("_", " ").title()}
    d.update(kw)
    return d


def tutor_perm(**rights):
    return {"role": "Tutor", "read": 1, **rights}


DOCTYPES = [
    # --- child table first, Tutor depends on it ---
    {
        "name": "Tutor Availability",
        "istable": 1,
        "editable_grid": 1,
        "fields": [
            f("weekday", "Select", options=WEEKDAYS, reqd=1, in_list_view=1),
            f("start_time", "Time", reqd=1, in_list_view=1),
            f("end_time", "Time", reqd=1, in_list_view=1),
        ],
        "permissions": [],
    },
    {
        "name": "Guardian",
        "autoname": "format:GRD-{#####}",
        "title_field": "full_name",
        "fields": [
            f("full_name", "Data", reqd=1, in_list_view=1),
            f("user", "Link", "Portal User", options="User"),
            f("email", "Data", options="Email", in_list_view=1),
            f("phone", "Data", options="Phone"),
            f("timezone", "Data", default="America/New_York",
              description="IANA name, e.g. America/New_York"),
            f("preferred_contact", "Select", options="Email\nPhone\nWhatsApp", default="WhatsApp"),
        ],
        "permissions": [ADMIN, tutor_perm()],
    },
    {
        "name": "Student",
        "autoname": "format:STU-{#####}",
        "title_field": "first_name",
        "fields": [
            f("first_name", "Data", reqd=1, in_list_view=1),
            f("last_name", "Data"),
            f("guardian", "Link", options="Guardian", reqd=1, in_list_view=1, in_standard_filter=1),
            f("age_band", "Select", options="5-7\n8-10\n11-13\n14-17", in_list_view=1),
            f("malayalam_level", "Select", options=LEVELS, default="Beginner",
              in_list_view=1, in_standard_filter=1),
            f("active", "Check", default="1"),
        ],
        "permissions": [ADMIN, tutor_perm()],
    },
    {
        "name": "Tutor",
        "autoname": "format:TUT-{#####}",
        "title_field": "full_name",
        "fields": [
            f("full_name", "Data", reqd=1, in_list_view=1),
            f("user", "Link", "Login User", options="User"),
            f("timezone", "Data", default="Asia/Kolkata",
              description="IANA name, e.g. Asia/Kolkata"),
            f("active", "Check", default="1", in_list_view=1),
            f("bio", "Small Text"),
            f("availability_section", "Section Break", "Weekly Availability (tutor's local time)"),
            f("availability", "Table", options="Tutor Availability"),
        ],
        "permissions": [ADMIN, tutor_perm()],
    },
    {
        "name": "Tutoring Session",
        "autoname": "format:SES-{#####}",
        "fields": [
            f("student", "Link", options="Student", reqd=1, in_list_view=1, in_standard_filter=1),
            f("guardian", "Link", options="Guardian", fetch_from="student.guardian", read_only=1),
            f("tutor", "Link", options="Tutor", reqd=1, in_list_view=1, in_standard_filter=1),
            f("col_1", "Column Break"),
            f("starts_at", "Datetime", reqd=1, in_list_view=1),
            f("duration", "Int", "Duration (mins)", default="30", reqd=1),
            f("status", "Select", options="Scheduled\nCompleted\nCancelled\nNo-show",
              default="Scheduled", in_list_view=1, in_standard_filter=1),
            f("meeting_link", "Data", options="URL"),
        ],
        "permissions": [ADMIN, tutor_perm(write=1, create=1)],
    },
    {
        "name": "Progress Log",
        "autoname": "format:LOG-{#####}",
        "fields": [
            f("tutoring_session", "Link", options="Tutoring Session", reqd=1, in_list_view=1),
            f("student", "Link", options="Student", fetch_from="tutoring_session.student",
              read_only=1, in_list_view=1, in_standard_filter=1),
            f("tutor", "Link", options="Tutor", fetch_from="tutoring_session.tutor", read_only=1),
            f("level_assessment", "Select", options=LEVELS),
            f("visible_to_guardian", "Check", default="1"),
            f("notes_section", "Section Break"),
            f("topics_covered", "Small Text"),
            f("homework", "Small Text"),
            f("tutor_notes", "Text", description="Private to tutors unless shown to guardian"),
        ],
        "permissions": [ADMIN, tutor_perm(write=1, create=1)],
    },
]


def ensure_role(name, desk_access):
    if not frappe.db.exists("Role", name):
        frappe.get_doc({"doctype": "Role", "role_name": name,
                        "desk_access": desk_access}).insert()
        print(f"  + role {name}")


def run():
    if not frappe.conf.developer_mode:
        frappe.throw("Turn on developer_mode first: "
                     "bench --site <site> set-config developer_mode 1")

    modules = frappe.get_all("Module Def", filters={"app_name": "uhschool"}, pluck="name")
    if not modules:
        frappe.throw("No module found for app 'uhschool' — is the app installed on this site?")
    module = modules[0]
    print(f"Module: {module}")

    ensure_role("Tutor", 1)
    ensure_role("Guardian", 0)

    for spec in DOCTYPES:
        name = spec["name"]
        if frappe.db.exists("DocType", name):
            print(f"  = {name} (exists, skipped)")
            continue
        doc = {"doctype": "DocType", "module": module, "custom": 0,
               "track_changes": 1, "istable": 0, **spec}
        frappe.get_doc(doc).insert()
        print(f"  + {name}")

    frappe.db.commit()

    path = frappe.get_module_path(module, "doctype", "tutoring_session")
    print(f"\nDone. Put tutoring_session.py in:\n  {path}/")
