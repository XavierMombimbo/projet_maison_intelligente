"""Local Flutter preview with same-origin access to the development API."""

import argparse
import http.client
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class PreviewHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/v1/"):
            self.proxy_api()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/v1/"):
            self.proxy_api()
        else:
            self.send_error(405)

    def proxy_api(self):
        connection = http.client.HTTPConnection("127.0.0.1", 8001, timeout=20)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 65536:
                self.send_error(413)
                return
            headers = {name: self.headers[name] for name in
                       ("Authorization", "Content-Type", "Accept") if name in self.headers}
            connection.request(self.command, self.path, body=self.rfile.read(length), headers=headers)
            response = connection.getresponse()
            content = response.read()
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (OSError, http.client.HTTPException):
            content = json.dumps({"detail": "Serveur local indisponible sur le port 8001."}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        finally:
            connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(PreviewHandler, directory=args.directory))
    server.serve_forever()
