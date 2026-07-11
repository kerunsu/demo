"""Reference voice-partner HTTP server for local联调. Partner may replace entirely."""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from partner_impl import process_turn

ROOT = Path(__file__).resolve().parent


def load_partner_env():
    env_path = ROOT / "partner.env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


load_partner_env()

HOST = os.environ.get("PARTNER_HOST", "127.0.0.1")
PORT = int(os.environ.get("PARTNER_PORT", "9876"))
API_KEY = os.environ.get("PARTNER_API_KEY", "")


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        if not API_KEY:
            return True
        return self.headers.get("x-voice-partner-key") == API_KEY

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") == "/health":
            return json_response(
                self,
                200,
                {"status": "ok", "provider": "reference-partner", "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            )
        return json_response(self, 404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "Unknown route"}})

    def do_POST(self):  # noqa: N802
        if self.path != "/v1/voice-turn":
            return json_response(self, 404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "Unknown route"}})
        if not self._authorized():
            return json_response(self, 401, {"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid API key"}})
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return json_response(self, 400, {"ok": False, "error": {"code": "BAD_JSON", "message": "Invalid JSON"}})
        started = time.time()
        try:
            result = process_turn(payload)
            if result.get("ok"):
                meta = result.setdefault("metadata", {})
                meta.setdefault("latencyMs", int((time.time() - started) * 1000))
            return json_response(self, 200, result)
        except Exception as exc:  # noqa: BLE001
            return json_response(
                self,
                500,
                {"ok": False, "error": {"code": "PARTNER_FAILURE", "message": str(exc)[:200]}},
            )

    def log_message(self, _format, *_args):
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"voice-partner reference server on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
