"""Loopback-only interface for the Coordinator input gate; no generation/storage."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from .coordinator import prepare_brief

STATIC = Path(__file__).parent / "static"
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/style.css": ("style.css", "text/css; charset=utf-8"),
         "/app.js": ("app.js", "text/javascript; charset=utf-8"),
         "/hostess.jpg": ("hostess.jpg", "image/jpeg")}
MAX_BODY = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not write customer input or request paths to console logs.

    def respond(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, status, payload):
        self.respond(status, json.dumps(payload).encode())

    def valid_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self):
        if not self.valid_host():
            return self.json_response(403, {"error": "Invalid host"})
        entry = FILES.get(self.path)
        if not entry:
            return self.json_response(404, {"error": "Not found"})
        self.respond(200, (STATIC / entry[0]).read_bytes(), entry[1])

    def do_POST(self):
        expected_origin = "http://" + self.headers.get("Host", "")
        if not self.valid_host() or self.headers.get("Origin") != expected_origin:
            return self.json_response(403, {"error": "Same-origin requests required"})
        if self.path != "/api/brief":
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
        result = prepare_brief(payload)
        result.pop("brief")  # No persistent records or client-side copy of approved data.
        self.json_response(200 if result["status"] == "accepted" else 422, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"SiteStarter input gate: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
