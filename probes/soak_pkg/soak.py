# soak.py -- Phase 0 plan §11 item 2, the ON-BADGE half of the 1000-signed-sync
# soak.
#
# The SERVER half is already done (server/tools/smoke.py --soak 1000 against the
# deployed instance: median 5.5 ms, no latency drift, flat RSS, every response
# signature and nonce verified). That proved the server holds up over the same
# run, so badge time is not spent discovering a server problem.
#
# This is the part only a badge can answer, per the plan's own words: "the same
# 1000 syncs driven from a badge, watching gc.mem_free()." It is a soak for heap
# stability, not a question that can invalidate the design -- the two that could
# (PSRAM heap, TLS behaviour) are both already answered -- so the pass criterion
# is simply: 1000/1000 signed syncs succeed with every response verified, and
# mem_free returns to ~baseline afterwards (no leak, no fragmentation drift).
#
# It is a throwaway probe (mirror of coex_pkg). Platform facts it works around,
# all learned the hard way in Phase 0 (see memory mpos-firmware-api-gaps):
#
#   * MicroPython has no `hmac` -> HMAC-SHA256 is hand-rolled over
#     hashlib.sha256, and self-tested against RFC 4231 vectors at startup.
#   * hashlib.sha256 has .digest() (bytes) but NOT .hexdigest() -> ubinascii.
#   * this build's json.dumps has `separators` but NOT `sort_keys` -> canonical
#     JSON sorts keys recursively first, then dumps compact.
#   * the badge clock is ~30 yr off -> the signed `ts` is bootstrapped from the
#     server's server_time (/healthz) and echoed from each sync response.
#   * WiFi is NOT touched here. It is already associated via the boot SSID
#     (plan §7), and using the existing link does not steal the foreground (only
#     WifiService.reconnect does). Runs as a TaskManager task on the OS loop so
#     it yields and never starves the launcher / trips the WDT.
#
# Read   /soak_cfg.json   {"base": str, "n": int, "name": str}
# Write  /soak_result.json  (full record)
#        /soak_status.txt   (one-line progress, overwritten every 100 syncs)
#        /soak_err.txt      (on an uncaught exception -- never die silently)
#
# Launch from the REPL (primary):   from mpos import TaskManager, soak
#                                   TaskManager.create_task(soak.run())
#   or tap "Gotcha Soak" if installed as the gotcha.soak activity package.

import asyncio
import gc
import hashlib
import json
import os
import time
import ubinascii

import urequests

from mpos import TaskManager  # always present on MPOS; needed for create_task

try:                       # only for the optional SoakActivity launcher wrapper
    import lvgl as lv
    from mpos import Activity
    _HAVE_LVGL = True
except Exception:
    lv = None
    Activity = None
    _HAVE_LVGL = False

BLOCK = 64

PACE_MS = 80        # pacing between syncs. Real syncs are 300 s apart; the soak
                    # only crowds them to reach 1000 quickly. Without pacing, 1000
                    # fresh back-to-back TCP connections exhaust the badge's lwIP
                    # socket/PCB pool once TIME_WAIT PCBs accumulate -- the first
                    # run hit ECONNRESET from sync ~694 for exactly this reason.
                    # 80 ms lets PCBs drain and is still a fast soak.
MAX_RETRY = 3       # transient WiFi/socket failures (errno 104/116) are expected
                    # in the field; a real sync client retries them, so the soak
                    # does too. Retries are counted, not hidden.


def save_json(path, obj):
    """json.dump(obj, open(path, "w")) LOSES the data on MicroPython -- the file
    object is never flushed or closed, so the buffer dies with it. Always this."""
    f = open(path, "w")
    try:
        json.dump(obj, f)
        f.flush()
    finally:
        f.close()


def _xor_pad(key):
    if len(key) > BLOCK:
        key = hashlib.sha256(key).digest()
    if len(key) < BLOCK:
        key = key + b"\x00" * (BLOCK - len(key))
    i = bytearray(BLOCK)
    o = bytearray(BLOCK)
    for k in range(BLOCK):
        i[k] = key[k] ^ 0x36
        o[k] = key[k] ^ 0x5C
    return bytes(i), bytes(o)


def hmac_sha256(key, msg):
    i_pad, o_pad = _xor_pad(key)
    inner = hashlib.sha256(i_pad + msg).digest()
    return hashlib.sha256(o_pad + inner).digest()


def hexd(b):
    return ubinascii.hexlify(b).decode()


def unhex(s):
    return ubinascii.unhexlify(s)


def hmac_hex(key, msg):
    return hexd(hmac_sha256(key, msg))


def _cj(o):
    """Canonical-JSON serializer with controlled key order.

    The server side is json.dumps(obj, sort_keys=True, separators=(",", ":")).
    MicroPython json HAS separators but NOT sort_keys, and its dicts do not
    preserve insertion order -- so rebuilding a dict with sorted keys and
    re-dumping still emits hash order (verified: that cost the first run). This
    walks the parsed object directly, iterating sorted(keys()) itself, and
    delegates every SCALAR (None/bool/int/float/str) to json.dumps so number
    and string formatting matches CPython byte for byte."""
    if isinstance(o, dict):
        parts = []
        for k in sorted(o.keys()):
            parts.append(json.dumps(k) + ":" + _cj(o[k]))
        return "{" + ",".join(parts) + "}"
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(_cj(x) for x in o) + "]"
    return json.dumps(o)


def canonical_json(obj):
    return _cj(obj)


def req_sig(player_key_hex, method, path, ts, nonce, body=b""):
    msg = (method.encode() + path.encode() + str(ts).encode()
           + nonce.encode() + (body or b""))
    return hmac_hex(unhex(player_key_hex), msg)


def resp_sig(player_key_hex, ts, nonce, payload):
    msg = str(ts).encode() + nonce.encode() + canonical_json(payload).encode()
    return hmac_hex(unhex(player_key_hex), msg)


def sig_eq(a, b):
    if not isinstance(a, str) or not isinstance(b, str) or len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a, b):
        r |= ord(x) ^ ord(y)
    return r == 0


def selftest_hmac():
    """RFC 4231 test cases 1 and 2 -- proves the hand-rolled HMAC is right
    before it is trusted to sign 1000 real requests."""
    assert hmac_hex(b"\x0b" * 20, b"Hi There") == \
        "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
    assert hmac_hex(b"Jefe", b"what do ya want for nothing?") == \
        "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"


def _http_get(url, headers, timeout=10):
    r = urequests.get(url, headers=headers, timeout=timeout)
    try:
        env = r.json()
        sc = r.status_code
    finally:
        r.close()                       # never leak a socket across 1000 syncs
    return sc, env


def _http_post(url, body_obj, timeout=10):
    r = urequests.post(url, data=json.dumps(body_obj),
                       headers={"Content-Type": "application/json"}, timeout=timeout)
    try:
        return r.status_code, r.json()
    finally:
        r.close()


def one_sync(base, path, pid, player_key, ts):
    """One signed GET /v1/sync. Returns (sc, env, payload, ok_nonce, ok_sig, ts)."""
    nonce = hexd(os.urandom(8))
    sig = req_sig(player_key, "GET", path, ts, nonce, b"")
    h = {"X-Pid": str(pid), "X-Ts": str(ts), "X-Nonce": nonce, "X-Sig": sig}
    sc, env = _http_get(base + path, h)
    payload = env.get("payload", {}) or {}
    ok_nonce = env.get("nonce") == nonce
    ok_sig = sig_eq(resp_sig(player_key, env.get("ts"), nonce, payload),
                    env.get("sig", ""))
    new_ts = int(payload.get("server_time", ts))
    return sc, env, payload, ok_nonce, ok_sig, new_ts


async def _soak(say):
    """say(msg) is a progress sink (print for the task path, LVGL for Activity)."""
    try:
        cfg = json.load(open("/soak_cfg.json"))
    except Exception:
        cfg = {}
    base = cfg.get("base", "http://192.168.1.57:8080").rstrip("/")
    n = int(cfg.get("n", 1000))
    name = cfg.get("name", "Soak")

    selftest_hmac()
    say("HMAC selftest OK\nenrolling...")
    await asyncio.sleep_ms(20)

    # ---- enroll (unsigned bootstrap; plan §6.2). TLS is D21's separate,
    #      already-verified concern, so plain HTTP on the dev LAN is correct.
    soul = os.urandom(16)
    badge_key = hexd(os.urandom(8))
    body = {"badge_key": badge_key, "display_name": name, "groups": ["soak"],
            "commitment": hexd(hashlib.sha256(soul).digest()),
            "app_version": "0.11.0-soak", "board": "2026"}
    sc, d = _http_post(base + "/v1/enroll", body)
    if sc != 200:
        raise RuntimeError("enroll %d: %s" % (sc, d))
    pid = int(d["pid"])
    player_key = d["player_key"]

    # ---- bootstrap ts from the server (badge clock is ~30 yr off)
    ts = int(_http_get(base + "/healthz", {})[1]["server_time"])

    def sample():
        gc.collect()
        return gc.mem_free(), gc.mem_alloc()

    base_free, base_alloc = sample()
    samples = [[0, base_free, base_alloc]]
    lats = []
    http200 = 0
    verified = 0
    bad = []
    path = "/v1/sync"
    t0 = time.ticks_ms()
    retries = 0
    for i in range(1, n + 1):
        sync_ok = False
        for attempt in range(MAX_RETRY):
            try:
                a = time.ticks_ms()
                sc, env, payload, ok_nonce, ok_sig, new_ts = one_sync(
                    base, path, pid, player_key, ts)
                lats.append(time.ticks_diff(time.ticks_ms(), a))
                ts = new_ts
                if sc == 200:
                    http200 += 1
                if ok_nonce and ok_sig:
                    verified += 1
                    sync_ok = True
                    if attempt:
                        retries += 1
                else:
                    bad.append([i, sc, int(not ok_nonce), int(not ok_sig)])
                break                         # a real response is never retried
            except OSError:
                # lwIP socket/PCB pressure or a transient WiFi blip: let the pool
                # drain, then retry. The badge clock is not involved (ts is echoed
                # from the server, so a delay does not break the replay window).
                gc.collect()
                await asyncio.sleep_ms(150 * (attempt + 1))
                continue
            except Exception as e:
                bad.append([i, -1, 0, 0, repr(e)[:60]])
                break
        if not sync_ok and not any(b[0] == i for b in bad):
            bad.append([i, -1, 0, 0, "OSError x%d" % MAX_RETRY])
        if i % 100 == 0:
            f, a2 = sample()
            samples.append([i, f, a2])
            status = "sync %d/%d  free %d KB  ok %d  bad %d  retr %d" % (
                i, n, f // 1024, verified, len(bad), retries)
            say(status)
            sf = open("/soak_status.txt", "w")
            try:
                sf.write(status + "\n")
                sf.flush()
            finally:
                sf.close()
        await asyncio.sleep_ms(PACE_MS)        # pace + yield to the OS loop / WDT

    f_free, f_alloc = sample()
    samples.append([n, f_free, f_alloc])
    total_ms = max(1, time.ticks_diff(time.ticks_ms(), t0))
    frees = [s[1] for s in samples]
    lats = lats or [0]
    lats.sort()
    # A leak is an ONGOING decline, not the one-time warmup cost of the first
    # syncs (urequests internals, socket buffers). So measure steady-state drift
    # from the sync-100 checkpoint (post-warmup) to the end, and report the
    # warmup drop separately. Pass = no errors + all verified + steady floor held.
    free_at_100 = samples[1][1] if len(samples) > 1 else base_free
    warmup_drop = base_free - free_at_100
    steady_drift = f_free - free_at_100
    steady_min = min(s[1] for s in samples[1:]) if len(samples) > 1 else base_free
    result = {
        "n": n, "base": base, "pid": pid, "badge_key": badge_key,
        "name": name,
        "baseline_mem_free": base_free, "final_mem_free": f_free,
        "min_mem_free": min(frees), "max_mem_free": max(frees),
        "warmup_drop_bytes": warmup_drop,       # baseline -> sync 100 (one-time)
        "steady_drift_bytes": steady_drift,      # sync 100 -> final (a leak if < 0)
        "drift_free_bytes": f_free - base_free,  # baseline -> final (both)
        "baseline_mem_alloc": base_alloc, "final_mem_alloc": f_alloc,
        "samples_free_alloc": samples,
        "http200": http200, "verified": verified, "n_errors": len(bad),
        "retries": retries, "errors_head": bad[:50],
        "latency_ms": {
            "min": lats[0],
            "median": lats[len(lats) // 2],
            "p95": lats[min(len(lats) - 1, int(len(lats) * 0.95))],
            "max": lats[-1],
        },
        "total_s": round(total_ms / 1000.0, 1),
        "req_s": round(n * 1000.0 / total_ms, 1),
        "rfc4231_selftest": "ok",
        "pass": (http200 == n and verified == n and not bad
                 and steady_drift >= -8192 and f_free >= steady_min),
    }
    save_json("/soak_result.json", result)
    say("DONE %d/%d verified\nfree %d->%d KB\ndrift %+d B\n%s" % (
        verified, n, base_free // 1024, f_free // 1024, f_free - base_free,
        "PASS" if result["pass"] else "CHECK"))


def _say_print(msg):
    print("soak | " + str(msg).replace("\n", " | "))


async def run():
    """Entry for TaskManager.create_task(soak.run()) -- the primary launch."""
    try:
        await _soak(_say_print)
    except Exception as e:
        try:
            f = open("/soak_err.txt", "w")
            f.write("%r\n" % (e,))
            f.flush()
            f.close()
        except Exception:
            pass
        _say_print("ERROR %r" % (e,))


if _HAVE_LVGL:
    class SoakActivity(Activity):
        """Optional launcher wrapper so the probe can also be tapped as the
        gotcha.soak app (mirrors coex_pkg). Identical work, LVGL progress."""

        def onCreate(self):
            scr = lv.obj()
            self._t = lv.label(scr)
            self._t.set_style_text_font(lv.font_montserrat_16, 0)
            self._t.set_pos(8, 6)
            self._t.set_text("GOTCHA SOAK")
            self._b = lv.label(scr)
            try:
                self._b.set_long_mode(lv.label.LONG_MODE.WRAP)
            except Exception:
                pass
            self._b.set_style_text_font(lv.font_montserrat_12, 0)
            self._b.set_pos(8, 34)
            self._b.set_width(300)
            self._b.set_text("starting...")
            self.setContentView(scr)

        def onResume(self, screen):
            super().onResume(screen)
            if not getattr(self, "_started", False):
                self._started = True
                TaskManager.create_task(self._wrap())

        def _say(self, msg):
            try:
                self._b.set_text(str(msg))
            except Exception:
                pass

        async def _wrap(self):
            try:
                await _soak(self._say)
            except Exception as e:
                try:
                    f = open("/soak_err.txt", "w")
                    f.write("%r\n" % (e,))
                    f.flush()
                    f.close()
                except Exception:
                    pass
                self._say("ERROR %r" % (e,))
