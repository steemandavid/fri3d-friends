# gotcha_b1.py -- Phase 2 Layer-B spike (throwaway).
#
# Proves the Phase 2 network+radiVert on ONE real badge against the live backend
# using the Layer-A gotcha.py / ble_proximity.py: enroll -> sync -> advertise the
# HSNT v2 game block -> admit the assigned target -> show it when seen, with a
# live rssi_prox. A second badge running this targets the first (Layer B2).
#
# Launch from the REPL:   from mpos import TaskManager, gotcha_b1 as g; TaskManager.create_task(g.run())
# or tap the "Gotcha B1" launcher icon. NOT shipped -- a probe.

import asyncio
import os
import time

import gotcha
import ble_proximity as bp

try:
    import lvgl as lv
    from mpos import Activity, TaskManager
    _HAVE_LVGL = True
except Exception:
    _HAVE_LVGL = False

BASE = "http://192.168.1.57:8080"      # the shared dev backend (Phase 0 proved reachable)
DEV_GROUP = "gotcha-dev"
SYNC_EVERY_MS = 8000                   # faster than SYNC_S=300s, for dev
STATE_PATH = "/gotcha_b1.json"


def _badge_key():
    try:
        import bluetooth
        from bluetooth import BLE
        b = BLE()
        b.active(True)
        mac = b.config("mac")          # (addr_type, bytes)
        return "".join("%02x" % x for x in mac[1])
    except Exception:
        return "".join("%02x" % x for x in os.urandom(6))


def _dev_name():
    try:
        import machine
        return "Dev" + ("".join("%02x" % x for x in machine.unique_id()))[-4:]
    except Exception:
        return "Dev????"


def _wifi_up():
    try:
        from mpos import WifiService
        return bool(WifiService.is_connected())
    except Exception:
        return False


def _game_block(st, cfg):
    """The v2 game block to put on air from cached state (pid/gflags/streak)."""
    if not st.is_enrolled():
        return None
    s = st.d.get("state", {}) or {}
    gflags = bp.GFLAG_ALIVE
    if int(s.get("streak", 0) or 0) >= int(cfg.get("BOUNTY_STREAK")):
        gflags |= bp.GFLAG_BOUNTY
    now = st.effective_now(int(time.time()))
    if gotcha.truce_active(now, cfg, st.d.get("quiet")) != "none":
        gflags |= bp.GFLAG_TRUCE
    return {"pid": st.d.get("pid"), "gflags": gflags,
            "streak": int(s.get("streak", 0) or 0)}


async def _run(say):
    cfg = gotcha.GameConfig()
    st = gotcha.GotchaState(STATE_PATH)
    st.load()
    name = _dev_name()

    if not _wifi_up():
        say("NO WIFI\njoin fri3d-badge\nin Settings")
        return
    say(name + "\nwifi ok\nenrolling...")

    sync = gotcha.GotchaSync(st)
    if not st.is_enrolled():
        ok = await sync.enroll(BASE, _badge_key(), name, [DEV_GROUP],
                               "0.11.0-b1", "probe")
        if not ok:
            say("ENROLL FAILED\ncheck backend\n" + BASE)
            return
        say(name + "\nenrolled pid=" + str(st.d.get("pid")))

    payload = await sync.sync(BASE)
    if not payload:
        say("SYNC FAILED\nbackend " + BASE)
        return

    ble = bp.BLEProximity()
    ble.set_prox_filter(cfg.get("PROX_ALPHA_UP"), cfg.get("PROX_ALPHA_DOWN"))
    adv_ok = ble.begin([DEV_GROUP], name, game=_game_block(st, cfg))

    def _retarget():
        tp = st.target_pid()
        ids = {tp} if tp is not None else set()
        ble.set_game_context(admit_pids=ids, pin_pids=ids)

    _retarget()
    tgt0 = (st.d.get("target") or {}).get("name")
    say(name + "\npid " + str(st.d.get("pid")) + "\nBLE " + ("up" if adv_ok else "ADV FAIL") +
        "\ntarget " + str(tgt0))

    last_sync = 0
    while True:
        now = time.ticks_ms()
        ble.tick(now, 300)
        tgt_pid = st.target_pid()
        peer = ble.peer_by_pid(tgt_pid) if tgt_pid is not None else None
        tname = (st.d.get("target") or {}).get("name", "?")
        s = st.d.get("state", {}) or {}
        if peer is not None:
            line = ("%s | pid %s\n%s streak %d\nTARGET %s -- SEEN\nrssi_prox %.0f"
                    % (name, st.d.get("pid"), s.get("status", "?"),
                       int(s.get("streak", 0) or 0), tname,
                       float(peer.get("rssi_prox", 0))))
        else:
            line = ("%s | pid %s\n%s streak %d\ntarget %s -- not seen"
                    % (name, st.d.get("pid"), s.get("status", "?"),
                       int(s.get("streak", 0) or 0), tname))
        say(line)

        if time.ticks_diff(now, last_sync) >= SYNC_EVERY_MS:
            last_sync = now
            if await sync.sync(BASE):
                ble.set_game(_game_block(st, cfg))
                _retarget()
        await asyncio.sleep_ms(300)


def _say_print(msg):
    print("gotcha.b1 | " + str(msg).replace("\n", " | "))
    _write_status(msg)


_status_last = 0
def _write_status(msg):
    """Also drop status to a file: BLE advertise+scan wedges USB-CDC on this
    build, but per-file `mpremote cp` still works when exec is wedged, so the
    host can poll this to watch the probe. Throttled to spare flash."""
    global _status_last
    now = time.ticks_ms()
    if time.ticks_diff(now, _status_last) < 1500:
        return
    _status_last = now
    try:
        f = open("/gotcha_b1_status.txt", "w")
        f.write(str(msg) + "\n")
        f.flush()
        f.close()
    except Exception:
        pass


async def run():
    """TaskManager.create_task(gotcha_b1.run()) -- primary launch."""
    try:
        await _run(_say_print)
    except Exception as e:
        try:
            f = open("/gotcha_b1_err.txt", "w")
            f.write("%r\n" % (e,))
            f.flush()
            f.close()
        except Exception:
            pass
        _say_print("ERROR %r" % (e,))


if _HAVE_LVGL:
    class GotchaB1Activity(Activity):
        def onCreate(self):
            scr = lv.obj()
            self._t = lv.label(scr)
            self._t.set_style_text_font(lv.font_montserrat_16, 0)
            self._t.set_pos(8, 6)
            self._t.set_text("GOTCHA B1")
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
            _write_status(msg)

        async def _wrap(self):
            try:
                await _run(self._say)
            except Exception as e:
                try:
                    f = open("/gotcha_b1_err.txt", "w")
                    f.write("%r\n" % (e,))
                    f.flush()
                    f.close()
                except Exception:
                    pass
                self._say("ERROR %r" % (e,))
