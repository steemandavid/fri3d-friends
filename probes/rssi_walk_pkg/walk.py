# walk.py -- prompted RSSI-walk activity for the Gotcha trend spike (multi-walk).
#
# Walks one after another in a single session: after each walk it asks "nog een?"
# (A = another, X = quit). Each walk is logged to its OWN files so all are kept:
#   /walk_<N>.csv         (t_ms, rssi) -- raw adverts, timestamps per-walk (t0 reset)
#   /walk_<N>_markers.csv (t_ms, kind) -- one line per A press: start/approach_end/
#                                         stand_end/retreat_end/lateral_end/obstacle_end
# analyze_rssi.py pairs walk_<N>.csv with walk_<N>_markers.csv automatically. Launch
# "RSSI Walk" from the launcher; follow prompts; pull the walk_* files afterwards.
import asyncio
import bluetooth
import json
import sys
import time

sys.path.insert(0, "/apps/com.fri3dcamp.fri3dfriends")
from ble_proximity import parse_payload  # noqa: E402

import lvgl as lv  # noqa: E402
from mpos import Activity, TaskManager  # noqa: E402

SCAN_RESULT = getattr(bluetooth, "_IRQ_SCAN_RESULT", 5)

# (title, body, marker). marker is written when A is pressed on that screen.
# phase 0 writes "start"; phase 6 is the "another walk?" prompt (__repeat__).
SCREENS = [
    ("KLAAR?", "Sta op ~40m van het doelwit.\n\nDruk A om te starten", "start"),
    ("1 NADEREN", "Loop naar ~1m van het doelwit.\n\nA: als je er bent", "approach_end"),
    ("2 STIL STAAN", "Blijf ~30s stil staan.\n\nA: na 30s", "stand_end"),
    ("3 WIJKEN", "Loop terug naar ~40m.\n\nA: als je er bent", "retreat_end"),
    ("4 ZIJWAARTS", "Kruis op ~5m afstand.\n\nA: als je klaar bent", "lateral_end"),
    ("5 OBSTAKEL", "Ga achter een tent of voertuig staan.\n\nA: als je er bent", "obstacle_end"),
    ("KLAAR", "Wandeling %{n}% opgeslagen.\n\nNog een wandeling?\nA: ja    X: nee", "__repeat__"),
]

_pending = []
S = {"count": 0, "last": 0, "phase": 0, "t0": 0, "f": None, "mf": None,
     "ble": None, "target": "", "running": False, "walk": 0}


def _irq(event, data):
    if event != SCAN_RESULT:
        return
    try:
        _at, _addr, _t, rssi, adv = data
        if len(_pending) < 512:
            _pending.append((time.ticks_ms(), rssi, bytes(adv)))
    except Exception:
        pass


def _drain():
    global _pending
    f = S["f"]
    if not f or not _pending:
        return
    want = S["target"]
    batch = _pending
    _pending = []
    t0 = S["t0"]
    for t_ms, rssi, adv in batch:
        info = parse_payload(adv)
        if info is None:
            continue
        if want and not (info["name"] == want or info["name"].startswith(want)):
            continue
        f.write("%d,%d\n" % (time.ticks_diff(t_ms, t0), rssi))
        S["count"] += 1
        S["last"] = rssi


class RssiWalkActivity(Activity):
    def onCreate(self):
        try:
            cfg = json.load(open("/rssi_cfg.json"))
            S["target"] = cfg.get("name", "")
        except Exception:
            S["target"] = ""
        self._focus_hl = None
        try:
            from mpos.ui import add_focus_border
            self._focus_hl = add_focus_border
        except Exception:
            self._focus_hl = None

        scr = lv.obj()
        self._title = lv.label(scr)
        self._title.set_style_text_font(lv.font_montserrat_16, 0)
        self._title.set_pos(8, 6)
        self._instr = lv.label(scr)
        try:
            self._instr.set_long_mode(lv.label.LONG_MODE.WRAP)
        except Exception:
            pass
        self._instr.set_style_text_font(lv.font_montserrat_16, 0)
        self._instr.set_pos(8, 32)
        self._instr.set_width(280)
        self._live = lv.label(scr)
        self._live.set_style_text_font(lv.font_montserrat_12, 0)
        self._live.set_pos(8, 152)

        btn = lv.button(scr)
        btn.set_size(280, 44)
        btn.set_pos(8, 178)
        self._blabel = lv.label(btn)
        self._blabel.set_text("A: volgende")
        try:
            self._blabel.center()
        except Exception:
            pass
        if self._focus_hl is not None:
            try:
                self._focus_hl(btn)
            except Exception:
                self._focus_hl = None
        try:
            btn.add_event_cb(self._on_a, lv.EVENT.CLICKED, None)
        except Exception:
            try:
                btn.add_event_cb(self._on_a, lv.EVENT.CLICKED)
            except Exception:
                pass
        self._btn = btn
        self.setContentView(scr)

    # ---- per-walk file handling ----
    def _close_walk(self):
        for k in ("f", "mf"):
            try:
                S[k].flush()
                S[k].close()
            except Exception:
                pass
            S[k] = None

    def _start_walk(self):
        self._close_walk()
        S["walk"] += 1
        n = S["walk"]
        S["f"] = open("/walk_%d.csv" % n, "w")
        S["f"].write("# t_ms,rssi target=%s walk=%d\n" % (S["target"] or "<all>", n))
        S["mf"] = open("/walk_%d_markers.csv" % n, "w")
        S["t0"] = time.ticks_ms()
        S["phase"] = 0
        S["count"] = 0
        self._show()

    def onResume(self, screen):
        super().onResume(screen)
        g = lv.group_get_default()
        if g:
            try:
                g.add_obj(self._btn)
            except Exception:
                pass
            try:
                lv.group_focus_obj(self._btn)
            except Exception:
                pass
        S["running"] = True
        self._start_walk()                                  # opens walk_1
        self._task = TaskManager.create_task(self._loop())

    def onPause(self, screen):
        super().onPause(screen)
        self._stop()

    def onDestroy(self):
        self._stop()

    def onBackPressed(self, screen):
        # X quits at any point (saving the current walk's files first).
        self._stop()
        return False

    def _show(self):
        i = S["phase"]
        title, instr, kind = SCREENS[i]
        try:
            self._title.set_text("WANDELING %d  %s" % (S["walk"], title))
            body = instr.replace("%{n}%", str(S["walk"]))
            self._instr.set_text(body)
            self._blabel.set_text("A: stoppen" if kind == "__repeat__" else "A: volgende")
        except Exception:
            pass

    def _on_a(self, e):
        i = S["phase"]
        _, _, kind = SCREENS[i]
        if kind == "__repeat__":                            # finished -> another walk
            self._start_walk()
            return
        now = time.ticks_diff(time.ticks_ms(), S["t0"]) if S["t0"] else 0
        if S["mf"]:
            try:
                S["mf"].write("%d,%s\n" % (now, kind))
                S["mf"].flush()
            except Exception:
                pass
        S["phase"] = min(i + 1, len(SCREENS) - 1)
        if SCREENS[S["phase"]][2] == "__repeat__":          # entering the done screen
            self._close_walk()                              # seal this walk's files
        self._show()

    def _stop(self):
        S["running"] = False
        self._close_walk()
        try:
            if S["ble"]:
                S["ble"].gap_scan(None)
        except Exception:
            pass
        try:
            if S["ble"]:
                S["ble"].active(False)
        except Exception:
            pass

    async def _loop(self):
        ble = bluetooth.BLE()
        for _ in range(20):                       # boot/launch-robust BLE bring-up
            try:
                ble.active(True)
                if ble.active():
                    break
            except Exception:
                pass
            await asyncio.sleep_ms(300)
        ble.irq(_irq)
        ble.gap_scan(0, 120000, 60000)
        S["ble"] = ble
        while S["running"]:
            _drain()
            try:
                self._live.set_text("walk %d  |  n=%d  rssi=%d  %s" % (
                    S["walk"], S["count"], S["last"], S["target"] or "<all>"))
            except Exception:
                pass
            try:
                if S["f"]:
                    S["f"].flush()
            except Exception:
                pass
            await asyncio.sleep_ms(200)
