# AGENTS.md — Uh-school (Frappe app)

Context for Codex. Task prompts arrive through the uhschool-bridge repo; each one is a single scoped task.
A prompt whose first line is `target: meet` runs in `~/uhschool-meet` instead of the app root.

## What this is
Uh-school: one-on-one online tutoring (Malayalam for US-born kids first). Frappe v16 app `uhschool`,
bench at `~/frappe-bench`, site `dev.uhschool.local`, developer_mode on, `bench start` runs in tmux session `bench`.
Public URL is served through a Cloudflare tunnel.

## Layout
- App root (your working dir): `~/frappe-bench/apps/uhschool`
- DocTypes: `uhschool/uh_school/doctype/<name>/` (JSON + .py + .js)
- Video: `uhschool/video.py` (LiveKit tokens, webhook, scheduler `close_finished_sessions`)
- `/join` web page: `uhschool/www/join.*`
- API: `uhschool/api.py` (e.g. `switch_to_student`)
- Meet fork (Next.js, separate repo): `~/uhschool-meet`, branch `uhschool`, basePath `/meet`

## Domain rules (don't break these)
- Guardian = family account; saving it creates a Website User (role Guardian). Limits: `student_limit`, `spectator_limit`.
- Student: `login_mode` (Through parent / Own login); saving creates a User (LMS Student) with username login.
- Roles: Tutor (desk), Guardian (no desk), Headmaster (desk, reads core records + attendance), System Manager = Admin.
- Video: tutor + kid publish; parent = spectator (subscribe-only, hidden); staff = hidden watcher.
  Spectator slots are counted per device at token issue. Room name = Tutoring Session name.
- Session Attendance is read-only, system-created, one row per device connection; visible only to Admin/Headmaster.

## Frappe v16 gotchas
- `frappe.get_all(doctype, fields, ...)`: fields is the 2nd positional arg — always pass `filters=` by keyword.
- Timezones: system time zone is UTC and every stored Datetime is UTC. Each person's home zone is `User.time_zone`.
  Web pages and messages must convert with `uhschool/timezones.py` (`to_user_time`, `to_system_time`, `format_for_user`).
  Tutor Availability stays in tutor-local wall time (default Asia/Kolkata).

## Sandbox
By default you run sandboxed: you can write only inside your working dir (and /tmp), and there is no network, so
`bench execute`, the database, Redis, npm/pip installs and web access won't work. If a task needs one of those, say so
under **Doubts** instead of working around it. A prompt that starts with `sandbox: off` runs unsandboxed; every rule
below still applies.

## Rules for every task
1. Stay inside the app root (or `~/uhschool-meet` when the prompt says so). Do only what the prompt asks.
2. Never read, print or edit `~/frappe-bench/sites/*/site_config.json` or `common_site_config.json`, and never
   put keys, secrets or passwords in code or output.
3. Do not run `bench migrate`, `bench restart`, `bench build`, `bench update`, `sudo`, `systemctl`, or anything that
   changes the database or services. List the commands the human should run in your final message instead.
4. Do not `git commit`, `git push`, or change branches. Leave changes uncommitted for review.
5. Match existing code style. Keep changes minimal; no new dependencies unless the prompt allows it.
6. If a file you need doesn't exist or the prompt conflicts with the code, stop and say so rather than guessing.

## Final message format
End with exactly these sections:
- **Changed files** — path + one line each
- **What I did** — short
- **Run next** — exact commands for the human (migrate/restart/build), or "none"
- **Test** — how to verify in the browser or with `bench execute`
- **Doubts** — anything unverified, or "none"
