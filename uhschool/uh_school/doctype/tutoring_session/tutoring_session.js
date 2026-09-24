// Copyright (c) 2026, ashiqthaha.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Tutoring Session", {
	refresh(frm) {
		if (frm.is_new() || ["Cancelled", "No-show"].includes(frm.doc.status)) return;
		frm.add_custom_button(__("Join video"), () => {
			window.open(`/join?session=${encodeURIComponent(frm.doc.name)}`, "_blank");
		}).addClass("btn-primary");
	},
});
