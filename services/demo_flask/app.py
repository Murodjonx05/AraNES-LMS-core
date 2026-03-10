import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("SERVICE_PORT", "8080"))

TASKS = [
    {"id": 1, "title": "Learn Python", "done": True},
    {"id": 2, "title": "Build a plugin", "done": False},
    {"id": 3, "title": "Ship it", "done": False},
]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self._json(200, {"status": "ok"})
        elif path == "/tasks":
            self._json(200, TASKS)
        elif path == "/info":
            self._json(200, {
                "plugin": "demo_flask",
                "version": "1.0.0",
                "runtime": "python-stdlib",
                "description": "Pure-stdlib HTTP plugin with no framework dependencies",
            })
        else:
            self._json(404, {"detail": "not found"})

    def _json(self, code: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"demo_flask listening on 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()
