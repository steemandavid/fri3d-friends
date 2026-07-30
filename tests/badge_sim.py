"""The badge simulator -- Phase 1's test harness (plan §11).

"Fully testable with the badge-simulator pytest fixture (N fake badges driving
enroll/sync/events over HTTP); no badge required."

This is deliberately written as *the badge*, not as a test helper: it holds a
soul, a `player_key` and an offline event queue, it signs with the badge's own
`gotcha.py` (hand-rolled MicroPython HMAC and canonical JSON), and it verifies
every response signature and nonce the way §6.2 requires the real badge to. So
the API tests double as an interop test in both directions, and the eventual
`GotchaSync` on-device implementation has a reference to match.

What it does NOT simulate: BLE. Kills are produced by handing one badge another's
soul directly, which is exactly what a completed handshake does (§5.3).
"""

import json
import os
import uuid

import gotcha                       # the badge's own module (app/ is on sys.path)


class BadgeError(Exception):
    pass


class BadgeSim:
    def __init__(self, server, badge_key, display_name, groups=None,
                 app_version="0.11.0", board="2026"):
        self.server = server
        self.client = server.client
        self.badge_key = badge_key
        self.display_name = display_name
        self.groups = list(groups or [])
        self.app_version = app_version
        self.board = board

        self.pid = None
        self.player_key = None
        self.soul = gotcha.make_soul()
        self.queue = []              # the offline queue (D6)
        self.last_sync = None
        self.config = {}
        self.target = None
        self.clock_offset_s = 0      # the real badge corrects its RTC with this

    # -- helpers -----------------------------------------------------------
    @property
    def commitment(self):
        return gotcha.commitment(self.soul)

    def now(self):
        return self.server.clock.now() + self.clock_offset_s

    def rotate_soul(self):
        """A fresh soul per life (§3.4): a replayed soul fails because the
        commitment has rotated."""
        self.soul = gotcha.make_soul()
        return self.commitment

    # -- enrollment (§9.2, over HTTPS in production) ------------------------
    def enroll(self):
        body = {"badge_key": self.badge_key, "display_name": self.display_name,
                "groups": self.groups, "commitment": self.commitment,
                "app_version": self.app_version, "board": self.board}
        r = self.client.post("/v1/enroll", json=body)
        if r.status_code != 200:
            raise BadgeError("enroll failed: %s %s" % (r.status_code, r.text))
        d = r.json()
        self.pid = int(d["pid"])
        self.player_key = d["player_key"]
        return d

    # -- signed transport (§6.2) -------------------------------------------
    def _signed(self, method, path, body_obj=None):
        if self.player_key is None:
            raise BadgeError("not enrolled")
        body = b"" if body_obj is None else json.dumps(body_obj).encode("utf-8")
        ts = self.now()
        nonce = os.urandom(8).hex()
        sig = gotcha.sign_request(self.player_key, method, path, ts, nonce, body)
        headers = {"X-Pid": str(self.pid), "X-Ts": str(ts), "X-Nonce": nonce,
                   "X-Sig": sig}
        if body:
            headers["Content-Type"] = "application/json"
        r = self.client.request(method, path, content=body or None, headers=headers)
        return r, nonce

    def _open_envelope(self, r, nonce):
        """Verify and unwrap a signed response, exactly as §6.2 obliges the badge
        to: discard anything unsigned, mis-signed or nonce-mismatched."""
        if r.status_code != 200:
            raise BadgeError("http %s: %s" % (r.status_code, r.text))
        env = r.json()
        for k in ("ts", "nonce", "sig", "payload"):
            if k not in env:
                raise BadgeError("unsigned response (missing %s)" % k)
        if env["nonce"] != nonce:
            raise BadgeError("nonce mismatch")
        if not gotcha.sig_ok(self.player_key, env["ts"], env["nonce"],
                             env["payload"], env["sig"]):
            raise BadgeError("bad response signature")
        return env["payload"]

    # -- the one thing the badge polls (§9.2, D13) --------------------------
    def sync(self, flush=True):
        """Queue a heartbeat, flush the queue, then sync -- the real order (§9.3:
        the heartbeat is queued once per SYNC_S, immediately before the flush)."""
        self.heartbeat()
        if flush:
            self.flush()
        r, nonce = self._signed("GET", "/v1/sync")
        payload = self._open_envelope(r, nonce)
        self.last_sync = payload
        self.config = payload.get("config", {})
        self.target = payload.get("target")
        return payload

    def flush(self):
        """POST the offline queue. Only accepted events leave the queue --
        rejected ones are dropped, retried ones would loop forever."""
        if not self.queue:
            return {"accepted": [], "rejected": []}
        batch = list(self.queue)
        r, nonce = self._signed("POST", "/v1/events", {"events": batch})
        payload = self._open_envelope(r, nonce)
        done = set(payload.get("accepted", []))
        done |= {x.get("uuid") for x in payload.get("rejected", [])}
        self.queue = [e for e in self.queue if e.get("uuid") not in done]
        return payload

    def leaderboard(self, board="total", limit=50):
        path = "/v1/leaderboard?board=%s&limit=%d" % (board, limit)
        r, nonce = self._signed("GET", path)
        return self._open_envelope(r, nonce)

    # -- events (§9.3) -----------------------------------------------------
    def _queue(self, etype, **payload):
        ev = {"uuid": str(uuid.uuid4()), "type": etype, "at": self.now(),
              "ticks": 0}
        ev.update(payload)
        self.queue.append(ev)
        return ev

    def heartbeat(self, target_seen_ago_s=None, peers_seen=3, battery=80,
                  background=False):
        return self._queue("heartbeat", alive=True,
                           target_seen_ago_s=target_seen_ago_s,
                           peers_seen=peers_seen, battery=battery,
                           groups=self.groups, background=background,
                           app_version=self.app_version)

    def report_kill(self, victim, rssi=-62, as_kind="target"):
        """Report a kill. `victim` is another BadgeSim -- the soul comes from it,
        which is what a completed handshake gives you and nothing else does."""
        return self._queue("kill", victim_pid=victim.pid,
                           soul=victim.soul.hex(), rssi=rssi, **{"as": as_kind})

    def report_death(self, attacker):
        """The victim's half. The badge is authoritative for its own death
        (§9.6), and it rotates its soul on the spot (§3.4)."""
        new_commitment = self.rotate_soul()
        return self._queue("killed_by", attacker_pid=attacker.pid,
                           new_commitment=new_commitment)

    def report_dodge(self, attacker=None, victim=None, rssi_at_escape=-80):
        kw = {}
        if attacker is not None:
            kw["attacker_pid"] = attacker.pid
        if victim is not None:
            kw["victim_pid"] = victim.pid
        return self._queue("dodge", rssi_at_escape=rssi_at_escape, **kw)

    def report_attack_started(self, victim):
        return self._queue("attack_started", victim_pid=victim.pid)

    def report_reveal(self, target, rssi=-75):
        return self._queue("reveal", target_pid=target.pid, rssi=rssi)

    def report_revealed(self, hunter):
        return self._queue("revealed", hunter_pid=hunter.pid)

    def optout(self):
        return self._queue("optout")

    def optin(self):
        return self._queue("optin")

    def set_quiet(self, from_hm, to_hm):
        """Personal quiet hours ride the heartbeat (§10.4a), so the badge just
        includes them next time it beats."""
        ev = self._queue("heartbeat", alive=True, peers_seen=2, battery=80,
                         groups=self.groups,
                         quiet={"from": from_hm, "to": to_hm})
        return ev

    # -- convenience for the tests ----------------------------------------
    def kill(self, victim, rssi=-62):
        """The whole two-sided exchange: both halves reported, both flushed.

        This is the common case in the field -- the victim's badge reports its own
        death immediately and the assassin's report follows -- and the server has
        to dedupe them onto one death (§10.3).
        """
        self.report_kill(victim, rssi=rssi)
        victim.report_death(self)
        a = self.flush()
        v = victim.flush()
        return a, v
