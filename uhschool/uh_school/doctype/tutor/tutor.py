# Copyright (c) 2026, ashiqthaha.com and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from uhschool.timezones import set_user_timezone, validate_timezone


class Tutor(Document):
    def validate(self):
        self.timezone = (self.timezone or "").strip() or "Asia/Kolkata"
        validate_timezone(self.timezone)

    def on_update(self):
        set_user_timezone(self.user, self.timezone)
