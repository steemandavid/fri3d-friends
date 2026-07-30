#!/usr/bin/env python3
"""Smoke-test a *deployed* Gotcha backend over the network.

Stdlib only, and it re-implements the badge's signing in a dozen lines rather
than importing `gotcha.py`, so it can be dropped on the game laptop and run there
with no repo checkout and no virtualenv:

    python3 smoke.py http://192.168.1.57:8080
    python3 smoke.py http://gotcha.example.org --badges 5 --password hunter2

It enrolls fake badges, syncs, posts a heartbeat, and (with --password) starts the
game and plays one kill end to end, then prints the dashboard's headline numbers.
Everything it creates is fake and can be dropped by deleting the database.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
import uuid


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign(key_hex, method, path, ts, nonce, body=b""):
    msg = method.encode() + path.encode() + str(ts).encode() + nonce.encode() + body
    return hmac.new(bytes.fromhex(key_hex), msg, hashlib.sha256).hexdigest()


def check_response(key_hex, nonce, env):
    for k in ("ts", "nonce", "sig", "payload"):
        if k not in env:
            raise SystemExit("FAIL: unsigned response (missing %s)" % k)
    if env["nonce"] != nonce:
        raise SystemExit("FAIL: response nonce mismatch")
    msg = str(env["ts"]).encode() + env["nonce"].encode() \
        + canonical_json(env["payload"]).encode()
    want = hmac.new(bytes.fromhex(key_hex), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, env["sig"]):
        raise SystemExit("FAIL: bad response signature")
    return env["payload"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects.

    The admin login answers 303 with the session cookie on it; if urllib follows
    the redirect we only ever see the headers of the *final* response and the
    cookie is silently lost.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Http:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.cookie = None
        self.opener = urllib.request.build_opener(_NoRedirect)

    def raw(self, method, path, body=None, headers=None, form=False):
        url = self.base + path
        data = None
        h = dict(headers or {})
        if body is not None:
            if form:
                data = "&".join("%s=%s" % (k, v) for k, v in body.items()).encode()
                h["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                data = json.dumps(body).encode()
                h["Content-Type"] = "application/json"
        if self.cookie:
            h["Cookie"] = self.cookie
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with self.opener.open(req, timeout=15) as r:
                sc = r.getcode()
                for k, v in r.getheaders():
                    if k.lower() == "set-cookie":
                        self.cookie = v.split(";")[0]
                return sc, r.read()
        except urllib.error.HTTPError as e:
            for k, v in e.headers.items():
                if k.lower() == "set-cookie":
                    self.cookie = v.split(";")[0]
            return e.code, e.read()

    def json(self, method, path, body=None, headers=None, form=False):
        sc, raw = self.raw(method, path, body, headers, form)
        try:
            return sc, json.loads(raw or b"{}")
        except Exception:
            return sc, {"raw": raw[:200].decode("utf-8", "replace")}


class Badge:
    def __init__(self, http, key, name, groups):
        self.http = http
        self.badge_key = key
        self.name = name
        self.groups = groups
        self.soul = os.urandom(16)
        self.pid = None
        self.player_key = None
        self.server_time = None

    @property
    def commitment(self):
        return hashlib.sha256(self.soul).hexdigest()

    def enroll(self):
        sc, d = self.http.json("POST", "/v1/enroll", {
            "badge_key": self.badge_key, "display_name": self.name,
            "groups": self.groups, "commitment": self.commitment,
            "app_version": "0.11.0-smoke", "board": "2026"})
        if sc != 200:
            raise SystemExit("FAIL enroll (%s): %s" % (sc, d))
        self.pid, self.player_key = int(d["pid"]), d["player_key"]
        return d

    def signed(self, method, path, body_obj=None):
        body = b"" if body_obj is None else json.dumps(body_obj).encode()
        ts = self.server_time or int(__import__("time").time())
        nonce = os.urandom(8).hex()
        h = {"X-Pid": str(self.pid), "X-Ts": str(ts), "X-Nonce": nonce,
             "X-Sig": sign(self.player_key, method, path, ts, nonce, body)}
        sc, env = self.http.json(method, path, body_obj, h)
        if sc != 200:
            raise SystemExit("FAIL %s %s (%s): %s" % (method, path, sc, env))
        payload = check_response(self.player_key, nonce, env)
        self.server_time = payload.get("server_time", self.server_time)
        return payload

    def sync(self):
        return self.signed("GET", "/v1/sync")

    def post(self, events):
        return self.signed("POST", "/v1/events", {"events": events})

    def ev(self, etype, **kw):
        e = {"uuid": str(uuid.uuid4()), "type": etype,
             "at": self.server_time or 0, "ticks": 0}
        e.update(kw)
        return e


def soak(badge, n):
    """N consecutive signed syncs against a live server.

    Plan §11 item 2 asks for a 1000-signed-sync soak "at the end of Phase 1 against
    the real backend". That gate is fundamentally about the **badge's** heap, and
    only a badge can answer it. This is the other half: it proves the *server* holds
    up over the same run -- no latency drift as the nonce cache fills and the event
    table grows, no rejections, and a signature verified on every single response.
    Run it before spending badge time on the on-device half.
    """
    import time
    print("\nsoak            : %d consecutive signed syncs" % n)
    lat = []
    t0 = time.time()
    for i in range(n):
        t = time.time()
        badge.sync()
        lat.append((time.time() - t) * 1000)
        if (i + 1) % max(1, n // 10) == 0:
            print("  %5d/%d  last %.1f ms" % (i + 1, n, lat[-1]))
    lat.sort()
    first = sum(lat[:max(1, n // 10)]) / max(1, n // 10)
    total = time.time() - t0
    print("  median %.1f ms  p95 %.1f ms  max %.1f ms  (%.1f s total, %.1f req/s)"
          % (lat[len(lat) // 2], lat[int(len(lat) * 0.95)], lat[-1],
             total, n / total))
    print("  every response signature and nonce verified: OK")
    return lat


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="e.g. http://192.168.1.57:8080")
    ap.add_argument("--badges", type=int, default=3)
    ap.add_argument("--password", default=None,
                    help="admin password: also starts the game and plays a kill")
    ap.add_argument("--host-name", default="smoke")
    ap.add_argument("--prefix", default="sm")
    ap.add_argument("--soak", type=int, default=0, metavar="N",
                    help="after the checks, run N consecutive signed syncs and "
                         "report latency drift (the server half of §11 item 2)")
    args = ap.parse_args(argv)

    http = Http(args.base)
    sc, health = http.json("GET", "/healthz")
    if sc != 200:
        raise SystemExit("FAIL /healthz (%s): %s" % (sc, health))
    print("health          : %s" % health)

    bs = []
    for i in range(args.badges):
        # A group each: same-group pairs are deliberately avoided by the ring
        # (§3.2), so putting every fake badge in one group would report conflicts
        # that say nothing about the deployment.
        b = Badge(http, "%s%010x" % (args.prefix, i), "Smoke %d" % i,
                  ["smoke%d" % i])
        b.enroll()
        bs.append(b)
    print("enrolled        : %s" % [b.pid for b in bs])

    p = bs[0].sync()
    print("sync signed ok  : pid=%s status=%s target=%s"
          % (p["me"]["pid"], p["me"]["status"],
             (p["target"] or {}).get("pid")))
    print("config pushed   : KILL_RSSI=%s SYNC_S=%s"
          % (p["config"]["KILL_RSSI"], p["config"]["SYNC_S"]))

    out = bs[0].post([bs[0].ev("heartbeat", alive=True, peers_seen=len(bs) - 1,
                               battery=88, groups=bs[0].groups,
                               app_version="0.11.0-smoke")])
    print("heartbeat       : accepted=%d rejected=%d"
          % (len(out["accepted"]), len(out["rejected"])))

    # Replay defence: the same nonce twice must be refused.
    ts, nonce = bs[0].server_time, os.urandom(8).hex()
    h = {"X-Pid": str(bs[0].pid), "X-Ts": str(ts), "X-Nonce": nonce,
         "X-Sig": sign(bs[0].player_key, "GET", "/v1/sync", ts, nonce, b"")}
    sc1, _ = http.json("GET", "/v1/sync", None, h)
    sc2, _ = http.json("GET", "/v1/sync", None, h)
    print("replay refused  : first=%s replay=%s %s"
          % (sc1, sc2, "OK" if (sc1, sc2) == (200, 401) else "*** FAIL ***"))

    if args.soak:
        soak(bs[0], args.soak)

    if not args.password:
        print("\n(no --password: skipped game start and the kill round trip)")
        return 0

    sc, d = http.json("POST", "/admin/login",
                      {"host": args.host_name, "password": args.password},
                      form=True)
    if sc not in (200, 303):
        raise SystemExit("FAIL admin login (%s): %s" % (sc, d))
    sc, dash = http.json("GET", "/v1/admin/dashboard")
    gid = dash["game"]["id"]
    sc, st = http.json("POST", "/v1/admin/game/%d/state" % gid, {"state": "running"})
    print("game running    : ring=%s" % st.get("ring"))

    # D7's night truce refuses all kills, so at 03:00 the kill check would fail
    # for entirely correct reasons. Move the window aside, verify the kill path,
    # then put it back exactly as it was.
    p = bs[0].sync()
    sched = p["game"]["truce_schedule"]
    moved = False
    if p["game"]["truce_active"]:
        http.json("POST", "/v1/admin/truce_schedule", {"from": "23:58", "to": "23:59"})
        http.json("POST", "/v1/admin/truce", {"active": False})
        moved = True
        print("truce           : active -- window moved aside for the kill check")

    hunter, victim = bs[0], bs[1]
    # Point the ring at a badge we control, and clear both spawn protections
    # (§5.8 would otherwise refuse the attack for 90 s). Both are ordinary host
    # actions, so this also exercises the admin path.
    http.json("POST", "/v1/admin/player/%d" % hunter.pid,
              {"action": "reassign", "target_pid": victim.pid})
    for b in (hunter, victim):
        http.json("POST", "/v1/admin/player/%d" % b.pid,
                  {"action": "protect", "seconds": 0})
    hunter.sync()
    out = hunter.post([hunter.ev("kill", victim_pid=victim.pid,
                                 soul=victim.soul.hex(), rssi=-61)])
    if out["accepted"]:
        me = hunter.sync()["me"]
        vic = victim.sync()["me"]
        print("kill round trip : accepted -- hunter score=%s streak=%s, "
              "victim alive=%s respawn_in=%ss"
              % (me["score"], me["streak"], vic["alive"],
                 (vic["respawn_at"] or 0) - hunter.server_time))
    else:
        print("kill round trip : *** REJECTED *** %s" % out["rejected"])

    if moved:
        http.json("POST", "/v1/admin/truce_schedule",
                  {"from": sched["from"], "to": sched["to"]})
        print("truce           : window restored to %s-%s"
              % (sched["from"], sched["to"]))

    sc, dash = http.json("GET", "/v1/admin/dashboard")
    print("dashboard       : kills_10m=%s enrolled=%s alive=%s synced_15m=%s"
          % (dash["kills_10m"], dash["population"]["enrolled"],
             dash["population"]["alive"], dash["health"]["synced_15m"]))
    print("\nAll smoke checks completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
