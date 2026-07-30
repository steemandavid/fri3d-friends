"""Entry point: `python -m gotcha_server.main` or the systemd unit.

Runs a single uvicorn process (§6.1: "Load is negligible: 700 badges / 300 s =
2.3 req/s, a few KB each. SQLite and a single process are ample.").

The plain-HTTP face on :80 is what badges call; :443 with a real certificate
arrives in Phase 5 (Let's Encrypt via DNS-01, §6.1). Until then `/v1/enroll` is
reachable over HTTP too, which is fine on a dev LAN and must NOT be how the camp
build ships -- the release checklist item is in §6.3.
"""

import argparse
import os

import uvicorn

from .app import create_app
from .config import Settings


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fri3d Gotcha backend")
    ap.add_argument("--host", default=os.environ.get("GOTCHA_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("GOTCHA_PORT", "8080")))
    ap.add_argument("--db", default=None, help="SQLite path (default $GOTCHA_DB)")
    ap.add_argument("--admin-password", default=None,
                    help="set/replace the admin password, then serve")
    args = ap.parse_args(argv)

    settings = Settings(db_path=args.db, admin_password=args.admin_password)
    app = create_app(settings)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info",
                access_log=True, proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
