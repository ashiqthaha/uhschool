// Copyright (c) 2026, ashiqthaha.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Tutor", {
	before_load(frm) {
		const set_options = () => frm.fields_dict.timezone.set_data(frappe.all_timezones);
		if (frappe.all_timezones) return set_options();
		frappe.call("frappe.core.doctype.user.user.get_timezones").then((r) => {
			frappe.all_timezones = r.message.timezones;
			set_options();
		});
	},
});
