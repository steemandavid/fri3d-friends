"""Pytest conftest: make the on-device app module and the backend importable.

`ble_proximity.py` lives in the app folder; here we put that folder first on
sys.path so the host tests can `import ble_proximity` straight away, without a
full device tree. The module keeps `import bluetooth`/`mpos`/`lvgl` out of the
pure wire-format functions' import path (they are imported lazily inside the
radio wrapper), so this import succeeds on CPython.

`server/` goes on the path too, so `import gotcha_server` works. The backend
fixtures live here: a FakeClock-driven app on an in-memory SQLite database, and
the **badge simulator** (§11's Phase 1 harness) -- N fake badges driving
enroll/sync/events over real HTTP against the real ASGI app. The simulator signs
with the *badge's own* `gotcha.py` implementation, not the server's, so every
test that talks to the API is also an interop test of the hand-rolled MicroPython
HMAC against the stdlib verifier.
"""
import os
import sys

import pytest

_APP_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "app", "com.fri3dcamp.fri3dfriends")
)
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

_SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)


# A fixed, boring start time: Friday 14 August 2026, 10:00 camp-local (badges are
# handed out Friday morning). Being mid-morning matters -- it is outside the
# 22:00-08:00 truce, so tests do not accidentally start inside a truce.
CAMP_FRIDAY_10H = 1786694400          # 2026-08-14 10:00:00 +02:00 (verified)


@pytest.fixture
def fake_clock():
    from gotcha_server.clock import FakeClock
    return FakeClock(CAMP_FRIDAY_10H)


@pytest.fixture
def db():
    from gotcha_server.db import Database
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def server(db, fake_clock):
    """A running app with a fake clock, ready for badges to enroll into.

    Returns a small holder rather than the bare app because nearly every test
    needs the db and the clock as well.
    """
    from starlette.testclient import TestClient

    from gotcha_server import clock as clock_mod
    from gotcha_server import service
    from gotcha_server.app import create_app
    from gotcha_server.config import Settings

    prev = clock_mod.set_clock(fake_clock)
    app = create_app(Settings(db_path=":memory:", secret="test-secret",
                              admin_password="hunter2"), db=db,
                     clock_impl=fake_clock)
    client = TestClient(app)

    class Holder:
        def __init__(self):
            self.app = app
            self.client = client
            self.db = db
            self.clock = fake_clock

        @property
        def game(self):
            return service.current_game(db)

        def start_game(self):
            """Put the game in `running` and build the ring (what the host's
            Start button does)."""
            g = self.game
            self.admin_post("/v1/admin/game/%d/state" % g["id"], {"state": "running"})
            return self.game

        def admin_login(self, host="tester"):
            r = client.post("/admin/login", data={"host": host, "password": "hunter2"},
                            follow_redirects=False)
            assert r.status_code == 303, r.text
            return r

        def admin_post(self, path, body=None):
            self.admin_login()
            r = client.post(path, json=body or {})
            assert r.status_code == 200, r.text
            return r.json()

        def admin_get(self, path):
            self.admin_login()
            r = client.get(path)
            assert r.status_code == 200, r.text
            return r.json()

        def advance(self, seconds):
            fake_clock.advance(seconds)

    holder = Holder()
    yield holder
    client.close()
    clock_mod.set_clock(prev)


@pytest.fixture
def badges(server):
    """Factory: `badges(n)` -> n enrolled simulated badges (§11's harness)."""
    from badge_sim import BadgeSim

    made = []

    def _make(n=1, groups=None, name_prefix="Otter"):
        out = []
        for i in range(n):
            b = BadgeSim(server, badge_key="aabbccddee%02x" % (len(made) + i),
                         display_name="%s %d" % (name_prefix, len(made) + i + 1),
                         groups=list(groups or []))
            b.enroll()
            out.append(b)
        made.extend(out)
        return out[0] if n == 1 else out

    return _make
