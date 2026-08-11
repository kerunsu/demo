# Deployment and rollback record

Current application entry remains `python app.py`; default backend port is
8080 (including the teacher SPA at `/teacher/`), voice service 8765 when enabled, and Robot Runtime
19091. Runtime package identity is read from `robot_runtime/VERSION` and
`releases/robot/manifest.json`; the package is not rebuilt or overwritten by
this audit.

Before release, back up `database/app.db`, session recordings, static course and
robot assets, configuration files and the release manifest. Build from a clean
environment with `npm ci`, run the explicit root tests and compile check, then
perform the browser/Runtime/hardware checklist.

Rollback: stop new profile deployment or set it to `legacy_only`, disable any
new optional panel through its feature switch, restore the previous application
package/configuration, restart and verify old SQLite/course_map/session samples.
Do not rewrite or delete historical data. The current handoff remains
conditional until the physical and browser gates in `FINAL_ACCEPTANCE.md` pass.
