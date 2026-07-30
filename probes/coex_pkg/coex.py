# coex.py -- Phase 0 spikes 1, 3 and 4: ONE condition per launch.
#
#   #3  Third GATT service: do exchange + setup + GOTCHA fit in ONE
#       gatts_register_services call? Answered at startup, written to
#       /coex_gatt.json immediately (NimBLE allows the call once per power-on,
#       so this is only meaningful on the first launch after a reset).
#   #1  WiFi + BLE coexistence  ) both answered by comparing the per-condition
#   #4  Scan duty reduction     ) advert rate and worst presence gap.
#
# Deliberately does NOT touch WiFi. An earlier version toggled WiFi from inside
# the activity; the wifi service takes foreground when it reconnects, which
# pauses this activity and silently ends the run. WiFi state and any traffic
# load are driven from the HOST before/around the launch (tools/run_coex.sh).
#
# Reads /coex_cfg.json  {"label": str, "interval_us": int, "window_us": int,
#                        "dur_ms": int}
# Writes /coex_<label>.csv   (t_ms,rssi,name)
#        /coex_<label>.json  (summary incl. wifi state observed during the run)
import asyncio
import bluetooth
import json
import sys
import time

sys.path.insert(0, "/apps/com.fri3dcamp.fri3dfriends")
from ble_proximity import parse_payload  # noqa: E402

import lvgl as lv  # noqa: E402
from mpos import Activity, TaskManager, WifiService  # noqa: E402

SCAN_RESULT = getattr(bluetooth, "_IRQ_SCAN_RESULT", 5)
SETTLE_MS = 3000

_pending = []
S = {"running": False, "n": 0, "last": 0}


def save_json(path, obj):
    """json.dump(obj, open(path,"w")) LOSES the data on MicroPython -- the file
    object is never flushed or closed, so the buffer dies with it. Always this."""
    f = open(path, "w")
    try:
        json.dump(obj, f)
        f.flush()
    finally:
        f.close()


def _irq(event, data):
    if event != SCAN_RESULT:
        return
    try:
        _at, _addr, _t, rssi, adv = data
        if len(_pending) < 512:
            _pending.append((time.ticks_ms(), rssi, bytes(adv)))
    except Exception:
        pass


# ---------------------------------------------------------------- spike #3
def probe_gatt(ble):
    """Register exchange + setup + GOTCHA in ONE call. Returns a result dict."""
    U = bluetooth.UUID
    F_READ = getattr(bluetooth, "FLAG_READ", 0x02)
    F_WRITE = getattr(bluetooth, "FLAG_WRITE", 0x08)
    F_WNR = getattr(bluetooth, "FLAG_WRITE_NO_RESPONSE", 0x04)
    F_NOTIFY = getattr(bluetooth, "FLAG_NOTIFY", 0x10)
    exch = (U("6e400010-b5a3-f393-e0a9-e50e24dcca9e"), (
        (U("6e400011-b5a3-f393-e0a9-e50e24dcca9e"), F_READ),
        (U("6e400012-b5a3-f393-e0a9-e50e24dcca9e"), F_WRITE | F_WNR),
    ))
    setup = (U("6e400020-b5a3-f393-e0a9-e50e24dcca9e"), (
        (U("6e400021-b5a3-f393-e0a9-e50e24dcca9e"), F_WRITE | F_WNR),
        (U("6e400022-b5a3-f393-e0a9-e50e24dcca9e"), F_READ),
        (U("6e400023-b5a3-f393-e0a9-e50e24dcca9e"), F_WRITE | F_WNR),
        (U("6e400024-b5a3-f393-e0a9-e50e24dcca9e"), F_READ | F_NOTIFY),
        (U("6e400025-b5a3-f393-e0a9-e50e24dcca9e"), F_READ),
        (U("6e400026-b5a3-f393-e0a9-e50e24dcca9e"), F_WRITE | F_WNR),
    ))
    gotcha = (U("6e400030-b5a3-f393-e0a9-e50e24dcca9e"), (
        (U("6e400031-b5a3-f393-e0a9-e50e24dcca9e"), F_WRITE | F_WNR),    # ATTACK
        (U("6e400032-b5a3-f393-e0a9-e50e24dcca9e"), F_READ | F_NOTIFY),  # DUEL
        (U("6e400033-b5a3-f393-e0a9-e50e24dcca9e"), F_READ),             # SPOILS
        (U("6e400034-b5a3-f393-e0a9-e50e24dcca9e"), F_WRITE | F_WNR),    # REVEAL
    ))
    out = {"attempted": 3, "services": ["exchange", "setup", "gotcha"]}
    try:
        handles = ble.gatts_register_services((exch, setup, gotcha))
        out["ok"] = True
        out["handle_groups"] = len(handles)
        out["handles"] = [[int(h) for h in grp] for grp in handles]
        try:
            ble.gatts_set_buffer(handles[2][2], 512, True)   # SPOILS read
            out["buffer_512_ok"] = True
        except Exception as e:
            out["buffer_512_ok"] = False
            out["buffer_err"] = repr(e)
    except Exception as e:
        out["ok"] = False
        out["err"] = repr(e)
    return out


class CoexActivity(Activity):
    def onCreate(self):
        scr = lv.obj()
        self._t = lv.label(scr)
        self._t.set_style_text_font(lv.font_montserrat_16, 0)
        self._t.set_pos(8, 6)
        self._t.set_text("COEX SPIKE")
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
        if not S["running"]:
            S["running"] = True
            self._task = TaskManager.create_task(self._run())

    def onBackPressed(self, screen):
        S["running"] = False
        return False

    def _say(self, msg):
        try:
            self._b.set_text(msg)
        except Exception:
            pass

    async def _run(self):
        try:
            await self._body()
        except Exception as e:
            # Never die silently -- an unhandled exception here cost a whole run.
            try:
                f = open("/coex_err.txt", "w")
                f.write("%r\n" % (e,))
                f.flush()
                f.close()
            except Exception:
                pass
            self._say("ERROR %r" % (e,))
        S["running"] = False

    async def _body(self):
        try:
            cfg = json.load(open("/coex_cfg.json"))
        except Exception:
            cfg = {}
        label = cfg.get("label", "run")
        interval = int(cfg.get("interval_us", 120000))
        window = int(cfg.get("window_us", 60000))
        dur_ms = int(cfg.get("dur_ms", 60000))

        ble = bluetooth.BLE()
        for _ in range(20):
            try:
                ble.active(True)
                if ble.active():
                    break
            except Exception:
                pass
            await asyncio.sleep_ms(300)

        # ---- spike #3: only possible before anything else registers services ----
        try:
            import os
            done = "coex_gatt.json" in os.listdir("/")
        except Exception:
            done = False
        if not done:
            self._say("spike 3: 3 GATT services in one call...")
            try:
                save_json("/coex_gatt.json", probe_gatt(ble))
            except Exception:
                pass
            await asyncio.sleep_ms(300)

        ble.irq(_irq)
        try:
            ble.gap_scan(None)
        except Exception:
            pass
        await asyncio.sleep_ms(300)
        ble.gap_scan(0, interval, window)

        t_settle = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t_settle) < SETTLE_MS:
            del _pending[:]
            await asyncio.sleep_ms(200)

        wifi_seen = []
        peers = {}
        hits = []
        t0 = time.ticks_ms()
        while S["running"] and time.ticks_diff(time.ticks_ms(), t0) < dur_ms:
            batch = _pending[:]
            del _pending[:]
            for t_ms, rssi, adv in batch:
                info = parse_payload(adv)
                if info is None:
                    continue
                nm = info["name"]
                rel = time.ticks_diff(t_ms, t0)
                hits.append((rel, rssi, nm))
                p = peers.get(nm)
                if p is None:
                    peers[nm] = [1, rel, rel, rel]      # n, first, last, maxgap
                else:
                    gap = rel - p[2]
                    p[0] += 1
                    p[2] = rel
                    if gap > p[3]:
                        p[3] = gap
                S["n"] += 1
                S["last"] = rssi
            try:
                wifi_seen.append(1 if WifiService.is_connected() else 0)
            except Exception:
                pass
            el = time.ticks_diff(time.ticks_ms(), t0)
            self._say("%s\n%ds/%ds\nadverts %d  peers %d\nlast rssi %d" % (
                label, el // 1000, dur_ms // 1000, len(hits), len(peers), S["last"]))
            await asyncio.sleep_ms(150)

        dur = max(1, time.ticks_diff(time.ticks_ms(), t0)) / 1000.0
        try:
            ble.gap_scan(None)
        except Exception:
            pass

        f = open("/coex_%s.csv" % label, "w")
        f.write("# t_ms,rssi,name label=%s window=%d interval=%d\n" % (label, window, interval))
        for rel, rssi, nm in hits:
            f.write("%d,%d,%s\n" % (rel, rssi, nm))
        f.flush()
        f.close()

        per = {}
        for nm, p in peers.items():
            tail = int(dur * 1000) - p[2]
            per[nm] = {"n": p[0], "rate": round(p[0] / dur, 2),
                       "max_gap_s": round(max(p[3], tail) / 1000.0, 1)}
        summary = {
            "label": label, "interval_us": interval, "window_us": window,
            "duty_pct": round(100.0 * window / interval, 1),
            "dur_s": round(dur, 1), "adverts": len(hits),
            "rate": round(len(hits) / dur, 2), "peers": len(peers), "per_peer": per,
            "wifi_connected_frac": (round(sum(wifi_seen) / len(wifi_seen), 2)
                                    if wifi_seen else None),
        }
        save_json("/coex_%s.json" % label, summary)
        self._say("DONE %s\nadverts %d  rate %.2f/s\npeers %d" % (
            label, len(hits), summary["rate"], len(peers)))
