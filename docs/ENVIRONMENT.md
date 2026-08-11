# Environment and configuration

Use `.env.example` as the template; `.env` is local-only and is intentionally
not committed. `python scripts/bootstrap.py --check-only` reports a missing
`.env` without creating it. CI should inject a temporary environment.

Important controls include `START_TEACHER_FRONTEND`, `START_VOICE_SERVICE`,
`CHILD_MEDIA_MODE=browser|agent`, `ROBOT_CONTROL_MODE`, `DIALOGUE_ENABLED`,
`DIALOGUE_TTS_MODE`, `AI_CHAT_PROVIDER`, `VOICE_PYTHON_SERVICE_URL`,
`CAPTURE_DEVICE_REGISTRY_PATH`, `CHILD_MEDIA_AGENT_KEY` and
`ROBOT_RUNTIME_KEY`. YAML/config files may persist runtime mode changes; a
session stores the effective mode and profile/version metadata where available.

Python dependencies are in `requirements.txt`; optional heavy analyzers are in
`requirements-optional-analyzers.txt`; teacher dependencies are pinned by
`teacher_frontend/package-lock.json`; Robot Runtime dependencies are isolated
under `robot_runtime/requirements.txt`.

Production URLs are all on the Server origin:

- teacher: `http://<server-ip>:8080/teacher/`
- child: `http://<server-ip>:8080/child`
- monitor/config: `http://<server-ip>:8080/server`
- local Robot Runtime UI: `http://127.0.0.1:19091/ui`

`START_TEACHER_FRONTEND=1` means “ensure the production bundle is built”; it no
longer means “start a persistent Vite development server”. For standalone UI
development, run Vite explicitly on 5173 and keep its backend proxy settings.
The packaged DollSer setting is COM3; deployments using another physical port
must change and validate `DollSer/bin/data/Settings.xml` before packaging.
