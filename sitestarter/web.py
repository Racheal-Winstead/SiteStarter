"""Loopback-only recorded-response workflow with session-owned, gated output."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from http.cookies import SimpleCookie, CookieError
from pathlib import Path
import threading

from .coordinator import prepare_brief
from .run_store import RunStore

STATIC = Path(__file__).parent / "static"
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/style.css": ("style.css", "text/css; charset=utf-8"),
         "/app.js": ("app.js", "text/javascript; charset=utf-8"),
         "/hostess.jpg": ("hostess.jpg", "image/jpeg")}
MAX_BODY = 64 * 1024
RUNS = RunStore()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not write customer input or request paths to console logs.

    def respond(self, status, body, content_type="application/json", cookie=None, download=False, preview=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", f"ss_session={cookie}; HttpOnly; SameSite=Strict; Path=/")
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="sitestarter-draft.html"')
        policy = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; sandbox; base-uri 'none'; form-action 'none'" if preview else "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self'; img-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        self.send_header("Content-Security-Policy", policy)
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, status, payload, cookie=None):
        self.respond(status, json.dumps(payload).encode(), cookie=cookie)

    def session_id(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return cookie["ss_session"].value if "ss_session" in cookie else None
        except CookieError:
            return None

    def valid_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self):
        if not self.valid_host():
            return self.json_response(403, {"error": "Invalid host"})
        parts = self.path.split("/")
        if len(parts) in (4, 5) and parts[1:3] == ["api", "runs"]:
            rid = parts[3]
            try:
                if len(parts) == 4:
                    return self.json_response(200, RUNS.snapshot(self.session_id(), rid))
                if parts[4] not in ("preview", "download"):
                    return self.json_response(404, {"error": "Not found"})
                html = RUNS.output(self.session_id(), rid)
                return self.respond(200, html.encode(), "text/html; charset=utf-8", download=parts[4] == "download", preview=True)
            except KeyError:
                return self.json_response(404, {"error": "Run unavailable or expired. Submit a new request."})
            except PermissionError:
                return self.json_response(409, {"error": "Preview and download are withheld until the run is Ready."})
        entry = FILES.get(self.path)
        if not entry:
            return self.json_response(404, {"error": "Not found"})
        self.respond(200, (STATIC / entry[0]).read_bytes(), entry[1])

    def do_POST(self):
        expected_origin = "http://" + self.headers.get("Host", "")
        if not self.valid_host() or self.headers.get("Origin") != expected_origin:
            return self.json_response(403, {"error": "Same-origin requests required"})
        parts = self.path.split("/")
        confirming = len(parts) == 5 and parts[1:3] == ["api", "runs"] and parts[4] == "confirm"
        if self.path not in ("/api/brief", "/api/runs") and not confirming:
            return self.json_response(404, {"error": "Not found"})
        if self.headers.get_content_type() != "application/json":
            return self.json_response(415, {"error": "JSON required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY or self.headers.get("Transfer-Encoding"):
                return self.json_response(413, {"error": "Request size unsupported"})
            self.connection.settimeout(10)
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError, RecursionError, OSError):
            return self.json_response(400, {"error": "Could not read JSON submission"})
        if confirming:
            try:
                if not isinstance(payload, dict) or set(payload) != {"revision"}:
                    return self.json_response(400, {"error": "A draft revision is required"})
                return self.json_response(200, RUNS.confirm(self.session_id(), parts[3], payload["revision"]))
            except KeyError:
                return self.json_response(404, {"error": "Run unavailable or expired"})
            except PermissionError:
                return self.json_response(409, {"error": "Confirmation is stale or this draft is not awaiting review"})
        result = prepare_brief(payload)
        if self.path == "/api/runs" and result["status"] == "accepted":
            try:
                sid, rid = RUNS.start(result["brief"], self.session_id())
            except OverflowError:
                return self.json_response(503, {"error": "Local preview is busy; try again later"})
            threading.Thread(target=RUNS.execute, args=(sid, rid), daemon=True).start()
            return self.json_response(202, {"status": "running", "request_id": rid}, cookie=sid)
        result.pop("brief")  # No persistent records or client-side copy of approved data.
        self.json_response(200 if result["status"] == "accepted" else 422, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"SiteStarter recorded workflow: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
