#!/usr/bin/env python3
"""coex_load_server.py -- tiny HTTP endpoint for the Phase 0 coexistence spike.

The badge hammers GET /load while scanning, standing in for the §6.2 signed sync.
Responds with a ~1 KB body (a sync response is the same order of magnitude) and
logs request arrivals so the host side of the coexistence question — does BLE
scanning starve WiFi? — is visible too.

  python3 tools/coex_load_server.py [port]      # default 8099, binds 0.0.0.0
"""
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BODY = (b'{"ok":true,"cfg":{"KILL_RSSI":-65,"KILL_HOLD_MS":5000},"pad":"'
        + b"x" * 900 + b'"}')
_t0 = time.time()
_n = 0


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        global _n
        _n += 1
        if _n % 25 == 0:
            print("  %6.1fs  %d requests (%.1f/s)" % (
                time.time() - _t0, _n, _n / max(1e-9, time.time() - _t0)), flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print("coex load server on 0.0.0.0:%d  (GET /load -> %d bytes)" % (port, len(BODY)), flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
