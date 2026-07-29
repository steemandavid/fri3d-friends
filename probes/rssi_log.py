# rssi_log.py -- RSSI trend / WiFi-BLE-coexistence / scan-duty logger probe.
#
# Runs on the badge's asyncio loop (NOT a blocking mpremote script): MPOS
# dispatches BLE scan IRQs through its one event loop, so a sync time.sleep_ms
# loop would block the loop and receive ZERO adverts. This module exposes an
# async run() coroutine that the OS loop pumps; start it with TaskManager and
# poll the module globals (count / last_rssi / done) with short, non-blocking
# mpremote execs -- that keeps USB-CDC healthy (a long blocking BLE script is
# the known wedge on this build).
#
# It scans continuously with an EXPLICIT interval/window (the ble_proximity.py
# trick that disables NimBLE's duplicate filter, so every advert is reported),
# locks onto ONE HSNT peer -- the "advertiser" badge, which just runs the
# !Fri3d Friends app (or its background beacon_service) -- and logs every advert:
#
#     t_ms,rssi
#
# tools/analyze_rssi.py replays that raw stream through any
# (alpha_fast, alpha_slow, deadband) to score the "warmer/colder" promise
# (plan §8.8.2a) and yields advert-rate / presence-gap / dup-filter diagnostics
# for the WiFi-coexistence (spike #1) and scan-duty (spike #4) tests.
#
# Parameters come from /rssi_cfg.json (written by tools/rssi_walk.sh):
#   { "name": "Otter42", "secs": 120, "window_us": 60000, "interval_us": 120000,
#     "out": "/rssi_log.csv" }
#   name "" = lock onto the first HSNT beacon seen.

import asyncio
import bluetooth
import gc
import json
import sys
import time

APP_DIR = "/apps/com.fri3dcamp.fri3dfriends"
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
from ble_proximity import parse_payload  # noqa: E402  (reuse the real HSNT parser)

SCAN_RESULT = getattr(bluetooth, "_IRQ_SCAN_RESULT", 5)  # named const absent on this build
REARM_MS = 30000
PENDING_MAX = 512
FLUSH_MS = 1000
TICK_MS = 50

CFG = {"name": "", "secs": 120, "window_us": 60000, "interval_us": 120000, "out": "/rssi_log.csv"}

# module-level state the host polls (short, non-blocking execs)
count = 0           # adverts logged so far
last_rssi = 0
last_t = 0
fast = None
slow = None
done = False
status = "idle"

_pending = []


def load_cfg():
    try:
        with open("/rssi_cfg.json") as f:
            CFG.update(json.load(f))
    except Exception:
        pass
    return CFG


_dbg = {"irq": 0, "appended": 0, "drain": 0, "parsed": 0, "locked": 0, "mismatch": 0}


def _irq(event, data):
    try:
        _dbg["irq"] += 1
    except Exception:
        pass
    if event != SCAN_RESULT:
        return
    try:
        _addr_type, addr, _adv_type, rssi, adv_data = data
        if len(_pending) < PENDING_MAX:
            _pending.append((time.ticks_ms(), rssi, bytes(addr), bytes(adv_data)))
            _dbg["appended"] += 1
    except Exception:
        pass                       # an IRQ must never raise


def _drain(f, cfg, t0):
    """Process queued adverts: parse, filter by name, append to the CSV.

    Filters by the advertiser's NAME each advert (a name maps to one badge and
    survives any address behaviour -- locking a single BLE address lost nearly
    every advert in testing). An empty `name` logs every HSNT beacon."""
    global count, last_rssi, last_t, _pending
    if not _pending:
        return
    _dbg["drain"] += 1
    want = cfg.get("name", "")
    batch = _pending
    _pending = []               # atomic rebind: IRQ keeps appending to the NEW list
    for t_ms, rssi, addr, adv in batch:
        info = parse_payload(adv)
        if info is None:
            continue
        _dbg["parsed"] += 1
        if want and not (info["name"] == want or info["name"].startswith(want)):
            continue            # not the requested target
        dt = time.ticks_diff(t_ms, t0)
        f.write("%d,%d\n" % (dt, rssi))
        count += 1
        last_rssi = rssi
        last_t = dt


def _live():
    global fast, slow
    if count == 0:
        return "...no adverts yet (is the advertiser running + in range?)"
    a_f, a_s = 0.30, 0.06
    fast = (1 - a_f) * (fast if fast is not None else last_rssi) + a_f * last_rssi
    slow = (1 - a_s) * (slow if slow is not None else last_rssi) + a_s * last_rssi
    return "t=%5.1fs n=%5d rssi=%4d fast=%.1f slow=%.1f trend=%+.1f" % (
        last_t / 1000.0, count, last_rssi, fast, slow, fast - slow)


async def run():
    """The logging loop. Start with TaskManager.create_task(rssi_log.run())."""
    global done, status
    cfg = load_cfg()
    status = "scanning target=%r duty=%.0f%%" % (cfg.get("name") or "<lock first>",
                                                 100.0 * cfg["window_us"] / cfg["interval_us"])
    print("== rssi_log ", status, " secs=", cfg.get("secs"), " out=", cfg["out"])
    ble = bluetooth.BLE()
    for _ in range(20):                       # boot-robust: BLE may not be ready
        try:                                  # the instant a boot service starts
            ble.active(True)
            if ble.active():
                break
        except Exception:
            pass
        await asyncio.sleep_ms(300)
    ble.irq(_irq)
    ble.gap_scan(0, cfg["interval_us"], cfg["window_us"])
    t0 = time.ticks_ms()
    f = open(cfg["out"], "w")
    f.write("# t_ms,rssi  target=%s window=%d interval=%d\n" % (
        cfg.get("name") or "<locked>", cfg["window_us"], cfg["interval_us"]))
    next_rearm = time.ticks_add(t0, REARM_MS)
    last_flush = t0
    deadline = 0 if not cfg.get("secs") else time.ticks_add(t0, int(cfg["secs"]) * 1000)
    gc.collect()
    try:
        while True:
            now = time.ticks_ms()
            if deadline and time.ticks_diff(deadline, now) <= 0:
                status = "reached %ss" % cfg.get("secs")
                break
            if time.ticks_diff(now, next_rearm) >= 0:
                try:
                    ble.gap_scan(0, cfg["interval_us"], cfg["window_us"])
                except Exception:
                    pass
                next_rearm = time.ticks_add(now, REARM_MS)
            _drain(f, cfg, t0)
            if time.ticks_diff(now, last_flush) >= FLUSH_MS:
                f.flush()
                print("  ", _live())
                last_flush = now
            await asyncio.sleep_ms(TICK_MS)   # yields -> OS loop pumps -> BLE IRQs fire
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    finally:
        try:
            ble.gap_scan(None)
        except Exception:
            pass
        try:
            ble.active(False)
        except Exception:
            pass
        try:
            f.flush()
            f.close()
        except Exception:
            pass
        done = True
        status = "done n=%d" % count
        print("== done: %d adverts -> %s" % (count, cfg["out"]))
