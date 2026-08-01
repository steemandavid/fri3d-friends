# fri3d_friends.py — "!Fri3d Friends" (Group Nametag + BLE Proximity Finder).
#
# A MicroPythonOS Activity that runs on BOTH the Fri3d Camp 2024 badge and the
# Fri3d Camp 2026 badge (both ESP32-S3 + MicroPythonOS). Shows your name (big,
# scrolls when long) and your group(s) as full-width coloured pills, and quietly
# alerts you when another badge sharing one of your groups comes within Bluetooth
# range.
#
# Interaction is a single on-badge MENU navigated with the joystick (v0.10.0),
# which also fixes the 2026 OS-drawer bug: the badge keypad drives the shared
# default LVGL focus group, and a button press against an EMPTY group falls back
# to the OS top bar (the drawer pops open). Our menu rows/buttons are that
# group's ONLY members while we are foregrounded, so the keypad drives them, not
# the bar. We write no navigation/key-mapping code -- LVGL moves focus on the
# joystick and fires CLICKED on ENTER for free.
#   joystick up/down = move highlight (native LVGL focus)
#   A   (ENTER)      = activate the focused row
#   X   (back)       = close the topmost overlay, or quit if none is open
#
# Board differences are abstracted at runtime (2024: GPIO46 buzzer + 296x240;
# 2026: GPIO38 buzzer + 320x240 + backlight). See DESIGN.md "2024 vs 2026".

import os
import sys
import math
import time
import json
import gc
import asyncio

APP_DIR = "/apps/com.fri3dcamp.fri3dfriends"
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import lvgl as lv
from mpos import Activity, TaskManager, BatteryManager, lights
import mpos

from ble_proximity import (
    BLEProximity, build_own_table, hash_groups, fnv1a_16,
    parse_groups_field, new_groups_from, merge_groups,
    EVICT_MS, RSSI_FLOOR_DEFAULT, MAX_GROUPS,
)
from contact_exchange import ContactExchange, add_received, GROUPS_FIELD
from ble_setup import (
    SetupService, setup_name, SETUP_WINDOW_MS,
    config_to_settings, settings_to_config, RANGE_PRESETS, SETTINGS_KEYS,
)
from identity import auto_nickname

FULLNAME = "com.fri3dcamp.fri3dfriends"

# Static Web-Bluetooth setup page (GitHub Pages). The badge shows a QR of this
# URL + its own id so a phone lands on the right badge in the chooser.
SETUP_URL_BASE = "https://steemandavid.github.io/fri3d-friends/setup/"


def _read_version():
    """Read this app's version from its MANIFEST.JSON ('?' if not found)."""
    for base in ("/apps", "/builtin/apps"):
        try:
            with open(base + "/" + FULLNAME + "/MANIFEST.JSON") as f:
                return json.load(f).get("version", "?")
        except Exception:
            pass
    return "?"


def _asset_bytes(name):
    """Read a binary asset from this app's folder (or builtin), or None."""
    for base in ("/apps", "/builtin/apps"):
        try:
            with open(base + "/" + FULLNAME + "/" + name, "rb") as f:
                return f.read()
        except Exception:
            pass
    return None


def _unique_id():
    """The board's fused id bytes (for the auto-nickname), or b"" if unreadable.

    machine.unique_id() needs no radio, unlike the BLE MAC behind the
    `Fri3d-XXXX` setup id -- and a fresh badge with no groups never powers the
    radio at all. See identity.py for why the two names look deliberately
    different rather than nearly-but-not-quite the same.
    """
    try:
        from machine import unique_id
        return unique_id()
    except Exception:
        return b""


def _atomic_write_json(path, obj):
    """Write JSON to `path` via a temp file + rename (atomic on LittleFS/FAT).
    A power-off mid-write then can't corrupt the file into an unloadable state
    (which every loader silently turns into {}/[] — total, unnoticed data loss)."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.rename(tmp, path)


def _now_str():
    """Local wall-clock as 'YYYY-MM-DDTHH:MM:SS' (accurate once NTP-synced)."""
    try:
        t = time.localtime()
        return "%04d-%02d-%02dT%02d:%02d:%02d" % (t[0], t[1], t[2], t[3], t[4], t[5])
    except Exception:
        return ""

try:
    W = mpos.DisplayMetrics.width()
    H = mpos.DisplayMetrics.height()
except Exception:
    W, H = 296, 240

# The on-badge menu (v0.10.0): a single joystick-navigated list that replaced
# the old A/B/Y/START button-legend. Geometry for the nametag's "Menu" affordance
# button and the menu overlay rows. Uses W/H, so defined AFTER the display metrics.
MENU_BTN_W = 96
MENU_BTN_H = 20
MENU_BTN_Y = H - 24                 # bottom of the nametag
MENU_PAD = 10                       # overlay side margin
MENU_W = W - 2 * MENU_PAD
MENU_TITLE_Y = 10
MENU_ROWS_TOP = 40
MENU_ROW_H = 26
MENU_MAX = 7                        # + Gotcha demo / Stoppen-Meedoen when enrolled

BANNER_MS_DEFAULT = 5000
TICK_MS = 30

# Name: rendered in a bundled TrueType Montserrat at NAME_FONT_SIZE (1.5x the
# largest built-in font_montserrat_28) via FontManager — a FIXED font, not a
# transform-scaled one (scaling a scrolling label starves the CPU). Falls back to
# font_montserrat_28 if the TTF can't be loaded. Long names marquee-scroll.
NAME_FONT_SIZE = 42               # 1.5 × 28
NAME_TTF = "M:apps/com.fri3dcamp.fri3dfriends/montserrat_name.ttf"
NAME_TOP = 22
NAME_H_SCALED = 52                # ~line height of the 42px name font
NAME_W = W - 40

BATT_X = W - 72
BATT_Y = 8

# Live clock: top-LEFT, same font/colour as the battery % (top-right). Inset ~2
# chars from the edge so the curved screen corner doesn't clip it.
CLOCK_X = 24
CLOCK_Y = 8

NTP_RESYNC_MS = 10 * 60 * 1000    # keep the RTC NTP-synced ~every 10 min on WiFi

# Friend LEDs: one RGB LED per nearby friend, slowly + dimly breathing that
# friend's group colour. 2024 badge has 4 physical LEDs, 2026 has 5 (firmware
# get_led_count() reports 5 on both, so key off the board).
LED_BREATHE_MS = 3800             # one full breathe cycle
LED_DIM_MIN = 0.015               # min brightness fraction (nearly off at trough)
LED_DIM_MAX = 0.18                # max brightness fraction (dim peak)
LED_UPDATE_MS = 60                # LED refresh cadence (smooth enough for a slow breathe)
LED_FLASH_MS = 900                # arrival/exchange flash holds this long before breathing resumes

# Group pills: full width, stacked vertically, below the name.
PILL_MARGIN_X = 16
PILL_TOP = NAME_TOP + NAME_H_SCALED + 8     # clear of the scaled name
PILL_H = 22
PILL_GAP = 4
MAX_PILLS = 4

# Buzzer GPIO (see DESIGN.md "2024 vs 2026"). Buttons are no longer polled
# directly: the keypad drives the LVGL focus group, so no pin maps remain.
BUZZER_PIN_2024 = 46
BUZZER_PIN_2026 = 38
# DEV: suppress the physical buzzer entirely (people are sleeping during the
# night test). With this True the PWM is never initialised, so _sting/_ping_chirp
# no-op physically; the hunt ping still runs its logic and bumps self._g_pings so
# it is observable in gotcha_dbg.txt. Flip to False to re-enable sound.
SILENT = True

COL_BG = 0x0B0E14
COL_NAME = 0xFFFFFF
COL_NEAR = 0xFFE066
COL_NONE = 0x6A7280
COL_HINT = 0xFF8C42
COL_BATT = 0x8FA8B8
COL_BANNER = 0x143A2A
COL_MUTED = 0x7B8AA0
COL_PANEL = 0x121826
COL_CARD = 0x162033
COL_CARD_LINE = 0x28324A
COL_BAR_ON = 0x9FE0A0
COL_BAR_OFF = 0x2A3346


def _detect_2026():
    try:
        if str(mpos.DeviceInfo.get_hardware_id()).startswith("fri3d_2026"):
            return True
    except Exception:
        pass
    try:
        _ = mpos.io_expander.version
        return True
    except Exception:
        return False


def _hsv(h, s=0.85, v=0.6):
    h = h % 360
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c
    if h < 60:    r, g, b = c, x, 0
    elif h < 120: r, g, b = x, c, 0
    elif h < 180: r, g, b = 0, c, x
    elif h < 240: r, g, b = 0, x, c
    elif h < 300: r, g, b = x, 0, c
    else:         r, g, b = c, 0, x
    return int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)


def _sig_from_id(gid):
    return (gid * 137.508) % 360, 440 + (gid % 12) * 55


def _col(hexv):
    return lv.color_hex(hexv)


def _rssi_bars(rssi):
    try:
        lvl = (int(rssi) + 100) // 15
    except Exception:
        lvl = 0
    return 0 if lvl < 0 else (4 if lvl > 4 else lvl)


class Fri3dFriends(Activity):
    def __init__(self):
        super().__init__()
        self._ble = BLEProximity()
        # Gotcha (Phase 2). self._gc is created in _setup_gotcha() (needs config +
        # the live screen). A Gotcha fault degrades to "no game", never "no
        # nametag" (§8.6) -- every entry point is try/except-wrapped.
        self._gc = None
        self._g_chip = None
        self._g_target = None
        self._g_bars = []
        self._g_chip_last = None
        self._g_target_last = None
        self._g_dbg_last = None
        self._g_log = []
        # First-run Gotcha consent overlay (§13).
        self._consent = None
        self._consent_open = False
        self._consent_rows = []
        self._config = {}
        self._own_table = []
        self._unconfigured = False
        self._is_2026 = False
        self._has_backlight = False
        self._sound = True
        self._banner_ms = BANNER_MS_DEFAULT
        self._detail = False
        # Focus-group bookkeeping (the drawer fix). _all_focusables = every
        # focusable we build (clean teardown target); _focus_objs = the reachable
        # set for the current state; _focus_held = False while paused.
        self._all_focusables = []
        self._focus_objs = []
        self._focus_held = False
        self._focus_hl = None     # resolved focus-highlight helper (add_focus_border)
        self._task = None
        self._t0 = 0
        self._last_input_ms = 0
        self._banner = None
        self._banner_bg = None
        self._banner_until = 0
        self._banner_is_arrival = False
        self._alert_names = []
        self._buzzer = None
        self._buzzer_until = 0           # buzzer busy until this (ping priority)
        self._g_last_ping_ms = 0         # last hunt ping (drop-not-queue, §8.8.6)
        self._g_pings = 0                 # hunt pings fired (observable when SILENT)
        self._spotted_was = False        # prior is_spotted (Reveal gold-flash edge, §5.7)
        self._dimmed = False
        self._led_next_ms = 0
        self._led_override_until = 0
        self._led_last = None
        self._batt_next_ms = 0
        self._name_lbl = None
        self._name_font = None
        self._batt_lbl = None
        self._clock_lbl = None
        self._clock_last = None
        self._clock_next_ms = 0
        self._next_ntp_ms = 0
        self._ntp_busy = False
        self._contact = {}
        self._exch = ContactExchange()
        self._exchanging = False
        self._exch_task = None
        # BLE phone-setup (Web Bluetooth). The setup GATT service is registered
        # together with the exchange service (single gatts_register_services call).
        self._setup = SetupService(APP_DIR, self._exch, on_saved=self._reload_config)
        self._exch.attach_setup(self._setup)
        self._setup_task = None
        self._setup_open = False          # True while a configured-badge setup window runs
        self._setup_info_lbl = None       # Configure-me info/hint line
        self._setup_last = None
        self._setup_next_ms = 0
        self._setup_win_deadline = 0
        self._pending_begin = False       # begin proximity once setup session ends
        self._overlay = None              # configured-badge window overlay (create-once)
        self._overlay_qr = None
        self._overlay_qr_box = None
        self._overlay_code_lbl = None
        self._overlay_count_lbl = None
        self._overlay_qr_last = None
        self._qr = None
        self._qr_box = None
        self._qr_last = None
        self._setup_widgets = []
        self._reload_pending = False
        self._setup_skipped = False       # user chose "skip for now" on Configure-me
        # Post-swap "join my friend's group?" prompt (v0.9.0). Deferred out of
        # _do_exchange because button edges are swallowed while _exchanging.
        self._pending_adopt = None        # (peer_name, [group, ...]) once a swap offers new groups
        self._adopt_groups = []           # the offered groups while the prompt is up
        self._adopt_ticked = []           # parallel list of bools
        self._adopt_count = 0             # number of group rows currently shown
        self._adopt_open = False
        self._adopt_panel = None          # create-once prompt overlay
        self._adopt_title_lbl = None
        self._adopt_rows = []             # focusable group rows (lv.button)
        self._adopt_row_labels = []       # parallel label per group row
        self._adopt_join = None           # the "Meedoen" confirm button
        self._adopt_last = None
        # On-badge settings editor (MicroPythonOS SettingsActivity).
        self._settings_prefs = None
        self._settings_pending = False    # harvest prefs on the next onResume
        self._splash_scr = None
        self._splash_logo = None
        self._splash_task = None
        self._entered = False
        self._pills = []
        self._friends_lbl = None
        self._friends_top = PILL_TOP
        self._detail_panel = None
        self._detail_header = None
        self._detail_rows = []
        # On-badge menu (v0.10.0). _menu_btn is the nametag's single focusable
        # affordance (also keeps the focus group non-empty so the OS drawer
        # can't grab a press); _menu is the create-once overlay.
        self._menu_btn = None
        self._menu = None
        self._menu_rows = []              # pre-built lv.button rows
        self._menu_row_labels = []
        self._menu_actions = []           # action key per shown row
        self._menu_count = 0              # number of rows currently shown
        self._menu_open = False
        self._cfg_rows = []               # Configure-me mini-menu focusable rows
        self._setup_close_btn = None      # setup-window overlay "Sluiten" focusable
        self._friends_last = None
        self._detail_header_last = None
        self._batt_last = None

    # ------------------------------------------------------------------ config
    def _load_config(self):
        cfg = {"groups": [], "name": "", "rssi_floor": RSSI_FLOOR_DEFAULT,
               "sound": True, "banner_ms": BANNER_MS_DEFAULT}
        try:
            with open(APP_DIR + "/config.json", "r") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
        if not isinstance(cfg.get("groups"), list):
            cfg["groups"] = []
        cfg["name"] = (cfg.get("name") or "").strip()
        try:
            rf = int(cfg.get("rssi_floor", RSSI_FLOOR_DEFAULT))
        except (TypeError, ValueError):
            rf = RSSI_FLOOR_DEFAULT
        cfg["rssi_floor"] = rf
        board = cfg.get("board")
        if board == "2026":
            self._is_2026 = True
        elif board == "2024":
            self._is_2026 = False
        else:
            self._is_2026 = _detect_2026()
        self._sound = bool(cfg.get("sound", True))
        try:
            self._banner_ms = int(cfg.get("banner_ms", BANNER_MS_DEFAULT))
        except (TypeError, ValueError):
            self._banner_ms = BANNER_MS_DEFAULT
        if self._banner_ms < 500:        # 0/negative would hide every banner
            self._banner_ms = BANNER_MS_DEFAULT
        contact = cfg.get("contact")
        if not isinstance(contact, dict):
            contact = {}
        cfg["contact"] = contact
        # Auto-nickname (v0.9.0): a badge with no name still shows one, so it is
        # useful straight out of the box instead of being inert until someone
        # with an internet-connected phone helps (issue #4). Derived, never
        # written to flash: auto_nickname() is pure and deterministic, so the
        # name is stable across reboots and can never fight a phone-side save.
        if not cfg["name"]:
            cfg["name"] = auto_nickname(_unique_id())
        self._contact = contact
        self._config = cfg
        self._own_table = build_own_table(cfg["groups"])
        ids = [gid for _, gid in self._own_table]
        # The gate is now GROUPS ONLY -- the name is always populated. Groups are
        # never auto-assigned (a shared default would make every badge match every
        # other badge and turn the arrival alert into camp-wide noise), so "no
        # group" still means "stay off the air".
        self._unconfigured = not ids
        self._setup_skipped = bool(cfg.get("setup_skipped"))

    def _save_config(self, key, value):
        try:
            with open(APP_DIR + "/config.json", "r") as f:
                cfg = json.load(f)
            cfg[key] = value
            _atomic_write_json(APP_DIR + "/config.json", cfg)
        except Exception:
            pass

    # ------------------------------------------------------------- Gotcha (P2)
    # Every entry point is wrapped so a Gotcha fault degrades to "no game",
    # never "no nametag" (plan §8.6). self._gc is created in _setup_gotcha()
    # (needs the live screen + config); the controller owns state/sync/connectivity
    # and the renderer here reads its getters.
    def _setup_gotcha(self):
        if self._gc is not None:
            return
        try:
            import gotcha_app
            self._gc = gotcha_app.GotchaController(
                self._ble, APP_DIR + "/gotcha.json", log=self._gc_log)
            self._gc.set_exchange(self._exch)
            self._gc.configure(self._config.get("gotcha"),
                               self._config.get("name"), self._config.get("groups"))
            # Phase 3a Reveal (§5.7): attach the Gotcha GATT responder to the same
            # one-shot service registration as exchange+setup, route inbound REVEAL
            # writes through BLEProximity's IRQ, and give the controller the responder.
            try:
                import gotcha_gatt
                svc = gotcha_gatt.GotchaService(on_reveal=self._gc.apply_reveal)
                self._exch.attach_gotcha(svc)
                self._gc.set_service(svc)
                self._ble.set_gatt_dispatch(svc.handle_irq)
            except Exception as e:
                self._gc_log("gotcha svc err %r" % (e,))
        except Exception as e:
            self._gc_log("setup err %r" % (e,))
            self._gc = None
            return
        # Pre-built hidden widgets (set_text/toggle only -- never delete, §8.4).
        scr = self._scr
        self._g_chip = self._label(scr, 8, H - 42, "", COL_NEAR,
                                   font=lv.font_montserrat_12)
        self._g_target = self._label(scr, 8, H - 24, "", COL_NAME,
                                     font=lv.font_montserrat_14)
        try:
            self._g_target.set_long_mode(lv.label.LONG_MODE.WRAP)
            self._g_target.set_width(W - 40)
        except Exception:
            pass
        # The hunt strip is the focusable A-action row (§5.7 D29): pressing A does
        # the strongest legal thing (reveal now; attack/abort in Phase 3b). Made
        # clickable + focusable so joystick nav can reach it; the Menu button stays
        # the default focus. (Focus routing verified on-badge in the probe.)
        try:
            self._g_target.add_flag(lv.obj.FLAG.CLICKABLE)
            self._make_focusable(self._g_target)
            self._bind_event(self._g_target, self._on_hunt_activate, lv.EVENT.CLICKED)
        except Exception:
            pass
        bx = W - 30
        for i in range(5):
            bh = 4 + i * 2
            self._g_bars.append(self._rbox(scr, bx, H - 12 - bh, 3, bh,
                                           COL_BAR_OFF, radius=1))
            bx += 4
        self._build_consent(scr)

    def _gc_log(self, msg):
        self._g_log.append(str(msg))
        if len(self._g_log) > 24:
            self._g_log = self._g_log[-24:]

    def _gc_start(self):
        if self._gc is not None:
            try:
                self._gc.start()
            except Exception as e:
                self._gc_log("start err %r" % (e,))

    def _gc_stop(self):
        if self._gc is not None:
            try:
                self._gc.stop()
            except Exception:
                pass

    def _gotcha_toggle(self):
        # Opt out / back in (§13). Controller persists it, drops/re-raises the
        # game block, and re-syncs on opt-in. A banner confirms the change.
        if self._gc is None:
            return
        try:
            if self._gc.is_opted_out():
                self._gc.opt_in()
                self._show_banner("Gotcha: je doet weer mee")
            else:
                self._gc.opt_out()
                self._show_banner("Gotcha: je bent gestopt")
            self._wake()
        except Exception as e:
            self._gc_log("toggle err %r" % (e,))

    async def _gotcha_demo(self):
        # §8.4 demo: walk the colour language so the first time a player sees a
        # colour is not the first time it matters. Re-flashes each step so the
        # LED override stays active against the main loop's _update_leds. Sound
        # is muted under SILENT; the colours + captions carry it.
        if self._gc is None:
            return
        steps = [
            ((0, 0, 255), "VER -- doel in de buurt"),
            ((255, 150, 0), "DICHTBIJ -- nadert"),
            ((255, 0, 0), "AANVALLEN -- op raakafstand"),
            ((255, 200, 0), "ONTHULLEN -- goud"),
            ((0, 255, 0), "GOTCHA -- punt gescoord"),
        ]
        try:
            for (r, g, b), cap in steps:
                self._show_banner(cap)
                for _ in range(2):      # hold ~1.6 s, re-flash to keep override
                    self._flash_leds(r, g, b)
                    await asyncio.sleep_ms(800)
            self._hide_banner()
            self._led_last = None       # let _update_leds repaint normally
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    # ------------------------------------------------------------- consent (§13)
    def _build_consent(self, scr):
        # First-run "join the game?" overlay, modelled on the Configure-me
        # mini-menu: a short explanation + 3 focusable rows. Shown once per boot
        # when a live game is detected and the badge has never joined. Built once,
        # hidden; only ever show/hide (never delete -- §8.4 landmine #1).
        ov = self._rbox(scr, 0, 0, W, H, COL_BG, radius=0)
        try:
            ov.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except Exception:
            pass
        self._label(ov, 0, 12, "Gotcha", COL_HINT,
                    font=lv.font_montserrat_24, center=True)
        exp = self._label(ov, 0, 46,
                          "Een spel: andere spelers zien als je dichtbij bent "
                          "en kunnen je pakken.", COL_NONE,
                          font=lv.font_montserrat_14, center=True)
        try:
            exp.set_long_mode(lv.label.LONG_MODE.WRAP)
        except Exception:
            pass
        self._consent_rows = []
        cw = W - 2 * MENU_PAD
        items = [("Meedoen", "join"),
                 ("Niet meedoen", "decline"),
                 ("Laat zien wat de badge doet", "demo")]
        for i, (label, action) in enumerate(items):
            row = lv.button(ov)
            row.set_size(cw, MENU_ROW_H)
            row.set_pos(MENU_PAD, 110 + i * MENU_ROW_H)
            try:
                row.set_style_bg_color(_col(COL_CARD), 0)
                row.set_style_bg_opa(lv.OPA.COVER, 0)
                row.set_style_radius(8, 0)
                row.set_style_border_width(0, 0)
                row.set_style_shadow_width(0, 0)
                row.set_style_pad_all(0, 0)
            except Exception:
                pass
            lbl = lv.label(row)
            lbl.set_text(label)
            lbl.set_style_text_color(_col(COL_NAME), 0)
            lbl.set_style_text_font(lv.font_montserrat_16, 0)
            try:
                lbl.align(lv.ALIGN.LEFT_MID, 10, 0)
            except Exception:
                lbl.set_pos(10, 4)
            self._make_focusable(row)
            self._bind_event(row, self._make_consent_cb(action), lv.EVENT.CLICKED)
            self._consent_rows.append(row)
        ov.add_flag(lv.obj.FLAG.HIDDEN)
        self._consent = ov

    def _make_consent_cb(self, action):
        def cb(e):
            self._do_consent_action(action)
        return cb

    def _do_consent_action(self, action):
        self._wake()
        if action == "join":
            self._gc.request_enroll()
            self._close_consent()
        elif action == "decline":
            self._gc.decline_consent()
            self._close_consent()
        elif action == "demo":
            # Close so the demo colours are visible; the tick re-raises consent
            # afterwards (still never-joined + not declined).
            self._close_consent()
            TaskManager.create_task(self._gotcha_demo())

    def _open_consent(self):
        if self._consent is None or self._consent_open:
            return
        try:
            self._consent.remove_flag(lv.obj.FLAG.HIDDEN)
            self._consent.move_foreground()
        except Exception:
            pass
        self._consent_open = True
        self._set_focus(self._consent_rows)

    def _close_consent(self):
        self._consent_open = False
        if self._consent is not None:
            try:
                self._consent.add_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass
        self._establish_focus()

    def _maybe_show_consent(self):
        # Only on the plain nametag (not splash/swap/setup/menu) and when the
        # controller says consent is needed. Highest-priority overlay.
        if (self._consent is None or self._consent_open or not self._entered
                or self._menu_open or self._exchanging or self._setup_open
                or self._setup_task is not None or self._adopt_open or self._detail):
            return
        try:
            if self._gc is not None and self._gc.consent_needed():
                self._open_consent()
        except Exception:
            pass

    def _gc_tick(self, now):
        if self._gc is None:
            return
        try:
            self._gc.tick(now, self._wifi_connected(), self._sound)
        except Exception as e:
            self._gc_log("tick err %r" % (e,))
        self._maybe_show_consent()

    def _on_hunt_activate(self, e):
        # A/ENTER on the hunt strip: do the strongest legal action (§5.7 D29).
        gc = self._gc
        if gc is None:
            return
        act = gc.strip_action()
        if act == "reveal":
            gc.request_reveal()
        # 'attack'/'abort' arrive with Phase 3b; 'radar'/'none' -> no-op here (the
        # menu is opened via the Menu button, not the hunt strip).

    def _ensure_gatt_services(self):
        # Register the Gotcha (+ exchange + setup) GATT services on the radio
        # BLEProximity brought up, so a live-game badge is REVEAL/ATTACK-reachable
        # (plan §5.1). Idempotent (the one-shot _svc_ready guard inside). Called
        # after ble.begin; the exact register-vs-advertise order is probe-verified.
        if self._exch is None:
            return
        try:
            import bluetooth
            self._exch.ensure_radio(bluetooth)
        except Exception as e:
            self._gc_log("gatt reg err %r" % (e,))

    def _gatt_busy(self):
        # The radio's single connection slot is taken (we are revealing, or a
        # central is connected to us) -> skip _update_leds (§5.5).
        gc = self._gc
        return gc is not None and gc.gatt_busy()

    def _render_spotted(self, now):
        # Drive the target-side Reveal effect (§5.7): on the rising edge of
        # is_spotted, fire the gold LED flash (REVEAL_FLASH_MS) + a chirp. The
        # _led_override_until set by _flash_leds holds the gold steady and keeps
        # _update_leds from redrawing the hunt bar during the flash.
        gc = self._gc
        if gc is None:
            return
        spotted = gc.is_spotted(now)
        if spotted and not self._spotted_was:
            try:
                ms = int(gc.cfg.get("REVEAL_FLASH_MS") or 2500)
                self._flash_leds(255, 200, 0, ms=ms)     # bright gold on every LED
            except Exception:
                pass
            if self._sound:
                try:
                    TaskManager.create_task(self._sting(2200))   # chirp
                except Exception:
                    pass
        self._spotted_was = spotted

    def _set_gotcha_bars(self, segs, halted):
        if halted:
            segs = 0
        if segs <= 0:
            on = _col(0x4488ff)
            lit = 0
        elif segs >= 5:
            on = _col(0xff4444)
            lit = 5
        elif segs >= 3:
            on = _col(0xffaa00)
            lit = segs
        else:
            on = _col(0x4488ff)
            lit = segs
        off = _col(COL_BAR_OFF)
        for i, b in enumerate(self._g_bars):
            try:
                b.set_style_bg_color(on if i < lit else off, 0)
            except Exception:
                pass

    def _render_gotcha(self):
        gc = self._gc
        if gc is None or self._g_chip is None:
            return
        try:
            if gc.enrolled:
                chip = gc.status_chip_text()
                if chip != self._g_chip_last:
                    self._g_chip_last = chip
                    self._g_chip.set_text(chip)
                self._g_chip.remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                self._g_chip.add_flag(lv.obj.FLAG.HIDDEN)

            halted = gc.radar_halted()
            if gc.show_strip():
                line = gc.target_line_text()
                if line != self._g_target_last:
                    self._g_target_last = line
                    self._g_target.set_text(line)
                self._g_target.remove_flag(lv.obj.FLAG.HIDDEN)
                self._set_gotcha_bars(gc.radar_segs, halted)
            elif gc.enrolled and gc.no_network():
                if self._g_target_last != "net":
                    self._g_target_last = "net"
                    self._g_target.set_text("geen netwerk -- WiFi in Instellingen")
                self._g_target.remove_flag(lv.obj.FLAG.HIDDEN)
                self._set_gotcha_bars(0, True)
            else:
                self._g_target.add_flag(lv.obj.FLAG.HIDDEN)
                self._set_gotcha_bars(0, True)
            self._g_dbg(gc, halted)
        except Exception as e:
            self._gc_log("render err %r" % (e,))

    def _g_dbg(self, gc, halted):
        # Dev-only: a change-gated one-line status file so the host can read what
        # the chip/strip/radar are showing (BLE wedges exec; cp still works).
        # Writes only on a state change -> negligible flash wear. Remove for camp.
        try:
            line = "enr=%s online=%s halt=%s segs=%d prox=%s pings=%d chip=%s tgt=%s" % (
                gc.enrolled, gc.online, halted, gc.radar_segs,
                gc.target_prox, self._g_pings, gc.status_chip_text(), gc.target_line_text())
            if line != self._g_dbg_last:
                self._g_dbg_last = line
                f = open(APP_DIR + "/gotcha_dbg.txt", "w")
                f.write(line + "\n")
                f.flush()
                f.close()
        except Exception:
            pass

    # ------------------------------------------------------- focus group (drawer fix)
    # The badge keypad drives the shared DEFAULT LVGL focus group. While our app
    # is foregrounded that group is otherwise EMPTY, so any press would fall back
    # to the OS top bar and pop the drawer. We keep our own focusables as the
    # group's only members -> the keypad drives them, never the bar. Membership is
    # reconciled to the active state's set on every transition and dropped on
    # pause so the launcher / editor get a clean group.
    def _bind_event(self, obj, cb, ev):
        # add_event_cb takes (cb, filter, user_data) on current LVGL builds;
        # older bindings take (cb, filter). Try both so a signature mismatch
        # can't crash the whole UI build.
        try:
            obj.add_event_cb(cb, ev, None)
            return
        except Exception:
            pass
        try:
            obj.add_event_cb(cb, ev)
        except Exception:
            pass

    def _make_focusable(self, obj):
        """Build-time: mark `obj` as one of our focusables. Adds a focus
        highlight (mpos.ui.add_focus_border on this build, or a rolled-our-own
        border fallback if no helper exists) and resets the dim timer on FOCUSED
        so joystick moves alone keep the screen awake. Registered in
        _all_focusables so teardown removes exactly our objects, never another
        component's."""
        if self._focus_hl is not None:
            try:
                self._focus_hl(obj)
            except Exception:
                self._focus_hl = None   # broken helper -> roll our own below
        if self._focus_hl is None:
            self._bind_event(obj, lambda e: self._set_focus_border(obj, True), lv.EVENT.FOCUSED)
            self._bind_event(obj, lambda e: self._set_focus_border(obj, False), lv.EVENT.DEFOCUSED)
        self._bind_event(obj, self._on_focused_wake, lv.EVENT.FOCUSED)
        self._all_focusables.append(obj)

    def _set_focus_border(self, obj, on):
        # Rolled-our-own focus highlight (only used when the OS helper is absent).
        try:
            obj.set_style_border_width(3 if on else 0, 0)
            if on:
                obj.set_style_border_color(_col(COL_NEAR), 0)
                obj.set_style_border_opa(lv.OPA.COVER, 0)
        except Exception:
            pass

    def _resolve_focus_highlight(self):
        # This OS exposes the helper as mpos.ui.add_focus_border (the pre-0.15
        # name); newer builds also re-export it as mpos.add_focus_highlight. Try
        # both; if neither exists _make_focusable rolls its own border.
        self._focus_hl = None
        try:
            from mpos.ui import add_focus_border
            self._focus_hl = add_focus_border
        except Exception:
            try:
                from mpos import add_focus_highlight
                self._focus_hl = add_focus_highlight
            except Exception:
                self._focus_hl = None

    def _on_focused_wake(self, e):
        self._wake()

    def _focus_first(self):
        if self._focus_objs:
            try:
                lv.group_focus_obj(self._focus_objs[0])
            except Exception:
                pass

    def _apply_focus(self):
        g = lv.group_get_default()
        if not g:
            return
        # Remove EVERY focusable we ever built, then re-add only the active set.
        # This LVGL build exposes removal as the top-level lv.group_remove_obj
        # (there is no group.remove_obj method), and add_focus_border enrols
        # objects at build time, so a plain diff would leak stale hidden rows.
        for o in self._all_focusables:
            try:
                lv.group_remove_obj(o)
            except Exception:
                pass
        if not self._focus_held:
            return
        for o in self._focus_objs:
            try:
                g.add_obj(o)
            except Exception:
                pass

    def _set_focus(self, objs):
        """Make the keypad's reachable set EXACTLY `objs` for the current state."""
        self._focus_objs = list(objs)
        self._apply_focus()
        self._focus_first()

    def _establish_focus(self):
        """Re-derive the focus set for the current foreground state (on resume,
        after _release_focus emptied the group)."""
        self._focus_held = True
        if self._consent_open:
            objs = self._consent_rows
        elif self._menu_open:
            objs = self._menu_rows[:self._menu_count]
        elif self._adopt_open:
            objs = self._adopt_rows[:self._adopt_count] + [self._adopt_join]
        elif self._setup_open:
            objs = [self._setup_close_btn]
        elif self._show_setup_screen():
            objs = list(self._cfg_rows)
        else:
            objs = [self._menu_btn]
        self._set_focus(objs)

    def _release_focus(self):
        """onPause/onStop/onDestroy: empty the group of our objects. The active
        set stays in _focus_objs so onResume can re-establish the current state."""
        self._focus_held = False
        self._apply_focus()

    def _wake(self):
        self._last_input_ms = time.ticks_ms()
        if self._dimmed:
            self._set_brightness(255)
            self._dimmed = False

    # ------------------------------------------------------------------ buzzer
    def _setup_buzzer(self):
        if SILENT:
            self._buzzer = None            # no PWM -> every beep is physically mute
            return
        try:
            from machine import PWM, Pin
            pin = BUZZER_PIN_2026 if self._is_2026 else BUZZER_PIN_2024
            self._buzzer = PWM(Pin(pin), freq=2000, duty_u16=0)
        except Exception:
            self._buzzer = None

    async def _sting(self, freq):
        if SILENT or not self._sound or not self._buzzer:
            return
        # Sound priority (§8.8.6): an arrival sting pre-empts the hunt ping. Mark
        # the buzzer busy so a due ping is dropped rather than queued/overlapped.
        self._buzzer_until = time.ticks_add(time.ticks_ms(), 250)
        try:
            self._buzzer.freq(int(freq))
            self._buzzer.duty_u16(16000)
            await asyncio.sleep_ms(120)
            self._buzzer.freq(int(freq) * 3 // 2)
            await asyncio.sleep_ms(90)
            self._buzzer.duty_u16(0)
        except Exception:
            pass

    def _hunt_ping(self, now):
        # The hunt ping (§8.8.6): a short FALLING chirp, rate = how close, silent
        # below PING_FROM_SEG, a double-tap at kill range. Lowest sound priority
        # -> dropped (never queued) if the buzzer is busy or any gate fails. Only
        # the hunter hears it; suppressed by truce/quiet/mute. Buzzer PWM does not
        # disable IRQs (unlike lights.write), so it is safe alongside the scan.
        gc = self._gc
        # NOTE: do NOT bail on `self._buzzer is None` -- under SILENT the buzzer is
        # never initialised, but the ping logic (+ the observable pings counter)
        # must still run. The physical chirp is gated separately below.
        if (gc is None or not gc.enrolled or not self._sound or gc.radar_halted()
                or gc.target_prox is None):
            return
        if time.ticks_diff(now, self._buzzer_until) < 0:
            return                        # buzzer busy -> drop this ping
        try:
            import gotcha
            ping = gotcha.hunt_ping(gc.target_prox, now, self._g_last_ping_ms,
                                    gc.cfg, enabled=gc.cfg.get("PING_ENABLED"))
        except Exception:
            return
        if ping is None:
            return                        # below the silent floor, or not due
        self._g_last_ping_ms = now
        self._g_pings += 1                # observable even when SILENT (dbg)
        if not SILENT and self._buzzer:
            TaskManager.create_task(self._ping_chirp(ping[0], ping[1], ping[3]))

    async def _ping_chirp(self, freq, burst_ms, taps):
        # Falling chirp (freq -> 0.75f), distinguishable from the rising arrival
        # sting. Quieter than an alert. `taps` doubles it at kill range.
        if not self._buzzer:
            return
        self._buzzer_until = time.ticks_add(time.ticks_ms(), 120)
        try:
            for t in range(taps if taps > 1 else 1):
                self._buzzer.freq(int(freq))
                self._buzzer.duty_u16(9000)
                await asyncio.sleep_ms(burst_ms)
                self._buzzer.freq(int(freq) * 3 // 4)
                await asyncio.sleep_ms(max(15, burst_ms // 2))
                self._buzzer.duty_u16(0)
                if taps > 1 and t < taps - 1:
                    await asyncio.sleep_ms(70)      # double-tap gap
        except Exception:
            pass

    # ------------------------------------------------------------------ display
    def _setup_display(self):
        self._has_backlight = False
        if self._is_2026:
            try:
                mpos.io_expander.lcd_brightness = 100
                self._has_backlight = True
            except Exception:
                self._has_backlight = False

    def _set_brightness(self, v):
        if not self._has_backlight:
            return
        try:
            mpos.io_expander.lcd_brightness = max(0, min(100, int(v * 100 // 255)))
        except Exception:
            self._has_backlight = False

    def _load_name_font(self):
        # Load the bundled Montserrat TTF at NAME_FONT_SIZE via the OS FontManager
        # (renders TrueType at any size — a fixed font, not a transform). Fall back
        # to the largest built-in bitmap font if unavailable.
        try:
            from mpos import FontManager
            f = FontManager.getFont(size=NAME_FONT_SIZE, ttf=NAME_TTF)
            if f:
                return f
        except Exception:
            pass
        return lv.font_montserrat_28

    # ------------------------------------------------------------------ widgets
    def _label(self, scr, x, y, text, color, font=None, center=False, w=W):
        lbl = lv.label(scr)
        lbl.set_text(text)
        lbl.set_style_text_color(_col(color), 0)
        if font:
            lbl.set_style_text_font(font, 0)
        if center:
            lbl.set_width(w)
            lbl.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
            lbl.set_pos(x, y)
        else:
            lbl.set_pos(x, y)
        return lbl

    def _rbox(self, parent, x, y, w, h, color, opa=lv.OPA.COVER, radius=0):
        o = lv.obj(parent)
        o.remove_style_all()
        o.set_size(w, h)
        o.set_pos(x, y)
        o.set_style_bg_color(_col(color), 0)
        o.set_style_bg_opa(opa, 0)
        if radius:
            o.set_style_radius(radius, 0)
        return o

    def _make_bars(self, parent, x, y):
        bars = []
        bx = x
        for i in range(4):
            bh = 3 + i * 2
            bars.append(self._rbox(parent, bx, y + (9 - bh), 3, bh, COL_BAR_OFF, radius=1))
            bx += 4
        return bars

    def _set_bars(self, bars, level):
        for i, b in enumerate(bars):
            try:
                b.set_style_bg_color(_col(COL_BAR_ON if i < level else COL_BAR_OFF), 0)
            except Exception:
                pass

    def _color_for_gid(self, gid):
        # None-tolerant (C5): a game-admitted peer has no shared group, and
        # _sig_from_id(None) would raise inside the blanket-caught render tick and
        # silently kill the LED bar, clock and battery for the rest of the hunt.
        if gid is None:
            return COL_MUTED
        hue, _ = _sig_from_id(gid)
        r, g, b = _hsv(hue)
        return (r << 16) | (g << 8) | b

    def _short(self, s, n):
        # ASCII "..." rather than U+2026: the built-in lvgl fonts are ASCII-only,
        # so a real ellipsis renders as a missing glyph. Costs 2 chars of width.
        s = (s or "").strip()
        return s if len(s) <= n else s[: max(1, n - 3)] + "..."

    def _build_menu_button(self, scr):
        # The nametag's single focusable affordance: a "Menu" pill at the bottom.
        # It is the only object in the focus group on the nametag (so the OS
        # drawer can't grab a press), and pressing A/ENTER opens the menu. On the
        # 2026 touch badge a tap works too (buttons are clickable).
        btn = lv.button(scr)
        btn.set_size(MENU_BTN_W, MENU_BTN_H)
        btn.set_pos((W - MENU_BTN_W) // 2, MENU_BTN_Y)
        try:
            btn.set_style_bg_color(_col(COL_PANEL), 0)
            btn.set_style_bg_opa(lv.OPA.COVER, 0)
            btn.set_style_radius(MENU_BTN_H // 2, 0)
            btn.set_style_border_width(1, 0)
            btn.set_style_border_color(_col(COL_CARD_LINE), 0)
            btn.set_style_shadow_width(0, 0)
        except Exception:
            pass
        mlbl = lv.label(btn)
        mlbl.set_text("Menu")
        mlbl.set_style_text_color(_col(COL_HINT), 0)
        mlbl.set_style_text_font(lv.font_montserrat_14, 0)
        try:
            mlbl.center()
        except Exception:
            pass
        self._make_focusable(btn)
        self._bind_event(btn, self._on_menu_btn_clicked, lv.EVENT.CLICKED)
        self._menu_btn = btn

    # ------------------------------------------------------------------ pills (full width, stacked)
    def _place_pills(self, scr):
        # Build MAX_PILLS pill slots ONCE at fixed positions; _refresh_pills
        # populates / hides them in place as the group set changes. Pre-building
        # (never creating/deleting per change) dodges the "deleting live widgets
        # crashes this build" landmine, so a freshly-added group's pill appears
        # immediately with no reboot.
        self._pills = []
        pw = W - 2 * PILL_MARGIN_X
        for i in range(MAX_PILLS):
            pill = self._rbox(scr, PILL_MARGIN_X, PILL_TOP + i * (PILL_H + PILL_GAP),
                              pw, PILL_H, COL_NONE, radius=PILL_H // 2)
            try:
                pill.set_style_border_width(1, 0)
                pill.set_style_border_color(_col(0xFFFFFF), 0)
                pill.set_style_border_opa(50, 0)
            except Exception:
                pass
            lbl = lv.label(pill)
            lbl.set_text("")
            lbl.set_style_text_color(_col(0xFFFFFF), 0)
            lbl.set_style_text_font(lv.font_montserrat_16, 0)
            try:
                lbl.set_long_mode(lv.label.LONG_MODE.SCROLL_CIRCULAR)
                lbl.set_width(pw - 16)
            except Exception:
                pass
            try:
                lbl.align(lv.ALIGN.LEFT_MID, 8, 0)
            except Exception:
                lbl.set_pos(8, 4)
            pill.add_flag(lv.obj.FLAG.HIDDEN)
            self._pills.append((pill, lbl))
        self._refresh_pills()

    def _refresh_pills(self):
        # Populate the pre-built pill slots from the current group set and tuck
        # the friends line under whichever pills are showing. Safe any time after
        # _place_pills -- including right after a live group add (adopt / save).
        if not self._pills:
            self._friends_top = PILL_TOP
            return
        groups = self._own_table[:MAX_PILLS]
        n = len(groups)
        for i, (pill, lbl) in enumerate(self._pills):
            if i < n:
                gname, gid = groups[i]
                hue, _ = _sig_from_id(gid)
                r, g, b = _hsv(hue, s=0.6, v=0.5)
                col = (r << 16) | (g << 8) | b
                try:
                    pill.set_style_bg_color(_col(col), 0)
                    lbl.set_text(gname)
                    pill.remove_flag(lv.obj.FLAG.HIDDEN)
                except Exception:
                    pass
            else:
                try:
                    pill.add_flag(lv.obj.FLAG.HIDDEN)
                except Exception:
                    pass
        self._friends_top = (PILL_TOP + n * (PILL_H + PILL_GAP) + 2) if n else PILL_TOP
        if self._friends_lbl is not None:
            try:
                self._friends_lbl.set_y(self._friends_top)
            except Exception:
                pass

    # ------------------------------------------------------------------ detail panel
    def _make_detail_row(self, panel, index, card_w):
        y = 30 + index * (30 + 4)
        row = self._rbox(panel, 4, y, card_w - 8, 30, COL_CARD, radius=8)
        try:
            row.set_style_border_width(1, 0)
            row.set_style_border_color(_col(COL_CARD_LINE), 0)
        except Exception:
            pass
        dot = self._rbox(row, 8, 9, 11, 11, COL_NONE, radius=5)
        name = lv.label(row)
        name.set_pos(26, 2)
        name.set_style_text_color(_col(COL_NAME), 0)
        name.set_style_text_font(lv.font_montserrat_16, 0)
        grp = lv.label(row)
        grp.set_pos(26, 16)
        grp.set_style_text_color(_col(COL_MUTED), 0)
        grp.set_style_text_font(lv.font_montserrat_12, 0)
        dbm = lv.label(row)
        dbm.set_pos(card_w - 16 - 36, 4)
        dbm.set_style_text_color(_col(COL_MUTED), 0)
        dbm.set_style_text_font(lv.font_montserrat_12, 0)
        age = lv.label(row)
        age.set_pos(card_w - 16 - 36, 17)
        age.set_style_text_color(_col(COL_MUTED), 0)
        age.set_style_text_font(lv.font_montserrat_12, 0)
        bars = self._make_bars(row, card_w - 16 - 52, 8)
        self._detail_rows.append({"row": row, "dot": dot, "name": name, "grp": grp,
                                  "bars": bars, "dbm": dbm, "age": age})

    def _fill_row(self, slot, peer):
        name, gname, gid, rssi, age = peer
        lvl = _rssi_bars(rssi)
        dbm = "%ddB" % int(rssi)
        ag = "%ds" % (int(age) // 1000)
        col = self._color_for_gid(gid)
        key = (name, gname, dbm, ag, lvl, col)
        if slot.get("last") == key:        # skip lvgl re-render when unchanged
            return
        slot["last"] = key
        try:
            slot["dot"].set_style_bg_color(_col(col), 0)
        except Exception:
            pass
        try:
            slot["name"].set_text(self._short(name, 16))
        except Exception:
            pass
        self._set_bars(slot["bars"], lvl)
        try:
            slot["dbm"].set_text(dbm)
        except Exception:
            pass
        try:
            slot["grp"].set_text(self._short(gname or "?", 18))
        except Exception:
            pass
        try:
            slot["age"].set_text(ag)
        except Exception:
            pass

    def _show_row(self, slot, show):
        if slot.get("vis") == show:        # don't re-set the flag every tick
            return
        slot["vis"] = show
        try:
            if show:
                slot["row"].remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                slot["row"].add_flag(lv.obj.FLAG.HIDDEN)
        except Exception:
            pass

    # ------------------------------------------------------------------ splash
    def _build_splash(self, scr):
        # A full-screen OVERLAY on the main screen, NOT a separate screen. A
        # second screen pushed via setContentView leaves a "ghost" entry on the
        # OS screen stack: after _enter_main pushes the nametag, pressing X (OS
        # back) pops the nametag and reveals this splash again, then a second X
        # quits — the "X shows the splash" bug. As an overlay we setContentView
        # ONCE (onCreate), so X quits cleanly. Hidden (never deleted — deleting a
        # live widget crashes this build) once the 3 s elapse.
        # Mirrors the proven PNG pattern in org.fri3d.hwtest (in-memory decode).
        sp = self._rbox(scr, 0, 0, W, H, COL_BG, radius=0)
        try:
            sp.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except Exception:
            pass

        # Explicit vertical layout (H=240) so nothing overlaps: title / version /
        # author up top, the 96px logo in the middle with clear gaps above and
        # below, and the Makerspace attribution pinned near the bottom.
        title = lv.label(sp)
        title.set_text("!Fri3d Friends")
        title.set_style_text_color(_col(COL_NEAR), 0)
        title.set_style_text_font(lv.font_montserrat_24, 0)
        title.align(lv.ALIGN.TOP_MID, 0, 16)

        ver = lv.label(sp)
        ver.set_text("v" + _read_version())
        ver.set_style_text_color(_col(COL_NONE), 0)
        ver.set_style_text_font(lv.font_montserrat_14, 0)
        ver.align(lv.ALIGN.TOP_MID, 0, 50)

        who = lv.label(sp)
        who.set_text("door David Steeman")
        who.set_style_text_color(_col(COL_NAME), 0)
        who.set_style_text_font(lv.font_montserrat_16, 0)
        who.align(lv.ALIGN.TOP_MID, 0, 72)

        logo = _asset_bytes("fri3dfriends.png")     # 96x96 app logo
        if logo:
            try:
                li = lv.image(sp)
                li.set_src(lv.image_dsc_t({"data_size": len(logo), "data": logo}))
                li.align(lv.ALIGN.TOP_MID, 0, 100)   # top at y=100 -> bottom ~196
                # Keep a Python-side reference to the PNG bytes for as long as the
                # splash image widget lives, so the buffer can't be GC'd out from
                # under the C binding.
                self._splash_logo = logo
            except Exception:
                pass

        org = lv.label(sp)
        org.set_text("Makerspace Baasrode")
        org.set_style_text_color(_col(COL_BAR_ON), 0)
        org.set_style_text_font(lv.font_montserrat_16, 0)
        org.align(lv.ALIGN.BOTTOM_MID, 0, -14)       # top ~y=210
        return sp

    async def _splash_then_enter(self):
        try:
            await asyncio.sleep_ms(3000)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        self._enter_main()

    def _enter_main(self):
        if self._entered:
            return
        self._entered = True
        # Reveal the nametag by HIDING the splash overlay (never delete it —
        # deleting a live widget hard-crashes this build; confirmed on-device on
        # all three badges 2026-07-15). The content view was already set once in
        # onCreate, so there is no second setContentView and thus no ghost splash
        # on the OS screen stack.
        if self._splash_scr is not None:
            try:
                self._splash_scr.add_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass

    # ------------------------------------------------------------------ UI build
    def _build_idle(self, scr):
        scr.set_style_bg_color(_col(COL_BG), 0)
        scr.set_style_bg_opa(lv.OPA.COVER, 0)

        # Widgets shared by both layouts, built exactly once. The banner is
        # deliberately built LAST so it z-stacks above everything; if the
        # nametag is built later (first-time configure), it is re-raised.
        if self._show_setup_screen():
            self._build_setup(scr)
        else:
            self._build_nametag(scr)
        self._clock_lbl = self._label(scr, CLOCK_X, CLOCK_Y, "--:--", COL_BATT,
                                      font=lv.font_montserrat_14)
        # Create-once overlays (hidden; never deleted -- deleting live widgets
        # hard-crashes this build). Built for both layouts: a Configure-me badge
        # reaches the setup window via its "Telefoon-setup" row, so it needs the
        # setup overlay too, and will swap to the nametag (menu overlay) later.
        self._build_menu(scr)
        self._build_setup_overlay(scr)
        self._build_adopt_panel(scr)
        self._build_banner(scr)

    def _build_menu(self, scr):
        # The on-badge menu overlay: a full-screen panel with a title, a column
        # of MENU_MAX pre-built lv.button rows (only ever set_text + hidden/shown
        # -- never created/deleted per open), and a footer hint. Each row is
        # focusable (joystick moves focus natively, A fires CLICKED). Hidden until
        # _open_menu populates and shows it.
        ov = self._rbox(scr, 0, 0, W, H, COL_BG, radius=0)
        try:
            ov.set_style_border_width(2, 0)
            ov.set_style_border_color(_col(COL_HINT), 0)
            ov.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except Exception:
            pass
        self._label(ov, 0, MENU_TITLE_Y, "Menu", COL_HINT,
                    font=lv.font_montserrat_24, center=True)
        self._menu_rows = []
        self._menu_row_labels = []
        for i in range(MENU_MAX):
            row = lv.button(ov)
            row.set_size(MENU_W, MENU_ROW_H)
            row.set_pos(MENU_PAD, MENU_ROWS_TOP + i * MENU_ROW_H)
            try:
                row.set_style_bg_color(_col(COL_CARD), 0)
                row.set_style_bg_opa(lv.OPA.COVER, 0)
                row.set_style_radius(8, 0)
                row.set_style_border_width(0, 0)
                row.set_style_shadow_width(0, 0)
                row.set_style_pad_all(0, 0)
            except Exception:
                pass
            lbl = lv.label(row)
            lbl.set_text("")
            lbl.set_style_text_color(_col(COL_NAME), 0)
            lbl.set_style_text_font(lv.font_montserrat_16, 0)
            try:
                lbl.align(lv.ALIGN.LEFT_MID, 10, 0)
            except Exception:
                lbl.set_pos(10, 4)
            self._make_focusable(row)
            self._bind_event(row, self._make_menu_cb(i), lv.EVENT.CLICKED)
            row.add_flag(lv.obj.FLAG.HIDDEN)
            self._menu_rows.append(row)
            self._menu_row_labels.append(lbl)
        self._label(ov, 0, H - 18, "joystick: kies   X: terug", COL_BATT,
                    font=lv.font_montserrat_12, center=True)
        ov.add_flag(lv.obj.FLAG.HIDDEN)
        self._menu = ov

    def _show_setup_screen(self):
        """True when the blocking Configure-me screen should be shown: no group
        AND the user hasn't chosen "skip for now" (persisted as `setup_skipped`).
        A skipped badge falls through to a normal nametag under its auto-nickname
        — the point of issue #4 — and can still set up later via the menu
        (Telefoon-setup / Instellingen)."""
        return self._unconfigured and not self._setup_skipped

    def _build_setup(self, scr):
        # First-run "Stel me in" layout, redesigned (v0.10.0) as a 3-row
        # mini-menu: Op badge instellen / Telefoon-setup / Overslaan. Every
        # widget is tracked in _setup_widgets so a save (over BLE) can HIDE
        # (never delete -- deleting live widgets crashes this build) the lot and
        # swap to the nametag in place. The phone-setup QR lives in the
        # setup-window overlay (opened by the "Telefoon-setup" row): the 240px
        # screen can't fit three rows AND a scannable QR together.
        info = self._label(scr, 0, 184, "geen telefoon? kies 'Op badge instellen'",
                           COL_NONE, font=lv.font_montserrat_12, center=True)
        self._setup_info_lbl = info
        self._setup_widgets = [
            self._label(scr, 0, 36, "Stel me in", COL_HINT,
                        font=lv.font_montserrat_24, center=True),
            self._label(scr, 0, 66, "kies een optie", COL_NONE,
                        font=lv.font_montserrat_14, center=True),
            info,
        ]
        self._cfg_rows = []
        cfg_items = [("Op badge instellen", "settings"),
                     ("Telefoon-setup", "phone"),
                     ("Overslaan", "skip")]
        cw = W - 2 * MENU_PAD
        for i, (label, action) in enumerate(cfg_items):
            row = lv.button(scr)
            row.set_size(cw, MENU_ROW_H)
            row.set_pos(MENU_PAD, 88 + i * MENU_ROW_H)
            try:
                row.set_style_bg_color(_col(COL_CARD), 0)
                row.set_style_bg_opa(lv.OPA.COVER, 0)
                row.set_style_radius(8, 0)
                row.set_style_border_width(0, 0)
                row.set_style_shadow_width(0, 0)
                row.set_style_pad_all(0, 0)
            except Exception:
                pass
            lbl = lv.label(row)
            lbl.set_text(label)
            lbl.set_style_text_color(_col(COL_NAME), 0)
            lbl.set_style_text_font(lv.font_montserrat_16, 0)
            try:
                lbl.align(lv.ALIGN.LEFT_MID, 10, 0)
            except Exception:
                lbl.set_pos(10, 4)
            self._make_focusable(row)
            self._bind_event(row, self._make_cfg_cb(action), lv.EVENT.CLICKED)
            self._setup_widgets.append(row)
            self._cfg_rows.append(row)

    def _build_setup_overlay(self, scr):
        # Setup window overlay: a full-screen panel with the setup QR + on-screen
        # code + countdown + a "Sluiten" focusable. Built ONCE and hidden (never
        # deleted). The Sluiten button gives the keypad a target while the window
        # is open so the OS drawer can't grab a press (plan risk #4); A closes the
        # window, as does X (onBackPressed). Sits below the banner (built after).
        ov = self._rbox(scr, 0, 0, W, H, COL_BG, radius=0)
        try:
            ov.set_style_border_width(2, 0)
            ov.set_style_border_color(_col(COL_HINT), 0)
            ov.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except Exception:
            pass
        self._label(ov, 0, 6, "Telefoon-setup", COL_HINT, font=lv.font_montserrat_24, center=True)
        self._label(ov, 0, 34, "scan met je telefoon (bluetooth)", COL_NONE,
                    font=lv.font_montserrat_14, center=True)
        try:
            box = self._rbox(ov, (W - 128) // 2, 50, 128, 128, 0xFFFFFF, radius=6)
            qr = lv.qrcode(box)
            qr.set_size(108)
            qr.set_dark_color(_col(0x000000))
            qr.set_light_color(_col(0xFFFFFF))
            qr.center()
            self._overlay_qr = qr
            self._overlay_qr_box = box
        except Exception:
            self._overlay_qr = None
            self._overlay_qr_box = None
        self._overlay_code_lbl = self._label(ov, 0, 182, "", COL_NEAR,
                                             font=lv.font_montserrat_16, center=True)
        self._overlay_count_lbl = self._label(ov, 0, 200, "", COL_NONE,
                                              font=lv.font_montserrat_12, center=True)
        close = lv.button(ov)
        close.set_size(96, 22)
        close.set_pos((W - 96) // 2, 212)
        try:
            close.set_style_bg_color(_col(COL_PANEL), 0)
            close.set_style_bg_opa(lv.OPA.COVER, 0)
            close.set_style_radius(11, 0)
            close.set_style_border_width(1, 0)
            close.set_style_border_color(_col(COL_CARD_LINE), 0)
            close.set_style_shadow_width(0, 0)
        except Exception:
            pass
        clbl = lv.label(close)
        clbl.set_text("Sluiten")
        clbl.set_style_text_color(_col(COL_HINT), 0)
        clbl.set_style_text_font(lv.font_montserrat_14, 0)
        try:
            clbl.center()
        except Exception:
            pass
        self._make_focusable(close)
        self._bind_event(close, self._on_setup_close_clicked, lv.EVENT.CLICKED)
        self._setup_close_btn = close
        ov.add_flag(lv.obj.FLAG.HIDDEN)
        self._overlay = ov

    def _build_adopt_panel(self, scr):
        # Post-swap "join my friend's group(s)?" prompt, rebuilt (v0.10.0) as
        # focusable lv.button rows: A toggles a group's tick, a final "Meedoen"
        # row confirms -> _adopt_groups_now. Same create-once/hide discipline
        # (deleting live widgets hard-crashes this build). The tick is "[x]"/"[ ]"
        # text in the row label; the OS focus highlight marks the selected row.
        pw = W - 24
        pn = self._rbox(scr, (W - pw) // 2, 24, pw, H - 56, COL_PANEL, radius=10)
        try:
            pn.set_style_border_width(2, 0)
            pn.set_style_border_color(_col(COL_NEAR), 0)
            pn.set_style_pad_all(4, 0)
            pn.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except Exception:
            pass
        self._adopt_title_lbl = lv.label(pn)
        self._adopt_title_lbl.set_text("")
        self._adopt_title_lbl.set_style_text_color(_col(COL_NEAR), 0)
        self._adopt_title_lbl.set_style_text_font(lv.font_montserrat_16, 0)
        self._adopt_title_lbl.set_width(pw - 16)
        self._adopt_title_lbl.set_pos(6, 4)
        self._adopt_rows = []
        self._adopt_row_labels = []
        rw = pw - 16
        # Rows start below a TWO-line title (montserrat_16 ~19 px/line -> 2 lines
        # reach ~y=44); start at 50. 5 rows x 20 px -> last row ~y=130, then the
        # Meedoen row at ~154, clear of the panel bottom.
        for i in range(MAX_GROUPS):
            row = lv.button(pn)
            row.set_size(rw, 20)
            row.set_pos(6, 50 + i * 20)
            try:
                row.set_style_bg_color(_col(COL_CARD), 0)
                row.set_style_bg_opa(lv.OPA.COVER, 0)
                row.set_style_radius(6, 0)
                row.set_style_border_width(0, 0)
                row.set_style_shadow_width(0, 0)
                row.set_style_pad_all(0, 0)
            except Exception:
                pass
            lbl = lv.label(row)
            lbl.set_text("")
            lbl.set_style_text_color(_col(COL_NAME), 0)
            lbl.set_style_text_font(lv.font_montserrat_14, 0)
            try:
                lbl.set_width(rw - 12)
                lbl.set_long_mode(lv.label.LONG_MODE.DOT)
                lbl.align(lv.ALIGN.LEFT_MID, 6, 0)
            except Exception:
                lbl.set_pos(6, 2)
            self._make_focusable(row)
            self._bind_event(row, self._make_adopt_cb(i), lv.EVENT.CLICKED)
            row.add_flag(lv.obj.FLAG.HIDDEN)
            self._adopt_rows.append(row)
            self._adopt_row_labels.append(lbl)
        join = lv.button(pn)
        join.set_size(rw, 22)
        join.set_pos(6, 50 + MAX_GROUPS * 20 + 4)
        try:
            join.set_style_bg_color(_col(COL_BANNER), 0)
            join.set_style_bg_opa(lv.OPA.COVER, 0)
            join.set_style_radius(8, 0)
            join.set_style_border_width(0, 0)
            join.set_style_shadow_width(0, 0)
            join.set_style_pad_all(0, 0)
        except Exception:
            pass
        jlbl = lv.label(join)
        jlbl.set_text("Meedoen")
        jlbl.set_style_text_color(_col(COL_NEAR), 0)
        jlbl.set_style_text_font(lv.font_montserrat_16, 0)
        try:
            jlbl.center()
        except Exception:
            pass
        self._make_focusable(join)
        self._bind_event(join, self._on_adopt_join_clicked, lv.EVENT.CLICKED)
        self._adopt_join = join
        pn.add_flag(lv.obj.FLAG.HIDDEN)
        self._adopt_panel = pn

    def _build_nametag(self, scr):
        cfg = self._config
        # Name: bundled 42px TrueType font (1.5× the built-in max), single line,
        # scrolls when too long. Fixed font, not transform-scaled (scaling a
        # scrolling label re-renders every frame and starves the CPU).
        self._name_lbl = self._label(scr, (W - NAME_W) // 2, NAME_TOP, cfg["name"],
                                     COL_NAME, font=self._name_font, center=True, w=NAME_W)
        try:
            self._name_lbl.set_long_mode(lv.label.LONG_MODE.SCROLL_CIRCULAR)
        except Exception:
            pass

        self._batt_lbl = self._label(scr, BATT_X, BATT_Y, "--%", COL_BATT, font=lv.font_montserrat_14)

        # Group pills (full width, stacked) -> sets self._friends_top.
        self._place_pills(scr)

        # Friends line directly under the pills. Inset from the curved edges and
        # WRAP so long names ("David Steeman ON4BDS") wrap onto the next line
        # instead of being clipped by the rounded screen corner.
        fw = W - 40
        self._friends_lbl = self._label(scr, (W - fw) // 2, self._friends_top,
                                        "vrienden zoeken...", COL_NONE,
                                        font=lv.font_montserrat_14, center=True, w=fw)
        try:
            self._friends_lbl.set_long_mode(lv.label.LONG_MODE.WRAP)
        except Exception:
            pass

        # A-button detail panel (hidden by default).
        dpw = W - 48
        self._detail_panel = self._rbox(scr, (W - dpw) // 2, 60, dpw, H - 64, COL_PANEL, radius=10)
        try:
            self._detail_panel.set_style_border_width(2, 0)
            self._detail_panel.set_style_border_color(_col(COL_NEAR), 0)
            self._detail_panel.set_style_pad_all(4, 0)
        except Exception:
            pass
        self._detail_header = lv.label(self._detail_panel)
        self._detail_header.set_text("VRIENDEN DICHTBIJ")
        self._detail_header.set_style_text_color(_col(COL_NEAR), 0)
        self._detail_header.set_style_text_font(lv.font_montserrat_16, 0)
        self._detail_header.set_pos(8, 6)
        for i in range(6):
            self._make_detail_row(self._detail_panel, i, dpw)
        self._detail_panel.add_flag(lv.obj.FLAG.HIDDEN)

        # The nametag's single focusable affordance (opens the menu). Built once
        # with the nametag (also from _swap_setup_for_nametag).
        self._build_menu_button(scr)

    def _build_banner(self, scr):
        # Alert banner (hidden), on top.
        self._banner_bg = lv.obj(scr)
        self._banner_bg.remove_style_all()
        self._banner_bg.set_size(W - 24, 46)
        self._banner_bg.set_style_bg_color(_col(COL_BANNER), 0)
        self._banner_bg.set_style_bg_opa(lv.OPA.COVER, 0)
        self._banner_bg.set_style_radius(10, 0)
        self._banner_bg.set_style_border_width(2, 0)
        self._banner_bg.set_style_border_color(_col(COL_NEAR), 0)
        self._banner_bg.align(lv.ALIGN.CENTER, 0, 0)
        self._banner = lv.label(self._banner_bg)
        self._banner.set_style_text_color(_col(0xFFFFFF), 0)
        self._banner.set_style_text_font(lv.font_montserrat_18, 0)
        self._banner.set_width(W - 40)
        self._banner.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        self._banner.center()
        self._hide_banner()

    # ------------------------------------------------------------------ banner
    def _show_banner(self, text, is_arrival=False):
        if self._banner is None or self._banner_bg is None:
            return
        self._banner.set_text(text)
        self._banner_bg.remove_flag(lv.obj.FLAG.HIDDEN)
        self._banner_until = time.ticks_add(time.ticks_ms(), self._banner_ms)
        self._banner_is_arrival = is_arrival

    def _hide_banner(self):
        # Clear the arrival state too so a later arrival never coalesces into a
        # stale (minutes-old) name list left over from a previous alert window.
        self._alert_names = []
        self._banner_is_arrival = False
        if self._banner_bg is None:
            return
        self._banner_bg.add_flag(lv.obj.FLAG.HIDDEN)
        self._banner_until = 0

    def _coalesced_text(self, arrivals):
        by_group = {}
        for a in arrivals:
            by_group.setdefault(a["shared_name"] or "?", []).append(a["name"] or "?")
        if len(by_group) == 1:
            g, names = next(iter(by_group.items()))
            names_s = ", ".join(names)
            extra = "  +%d more" % (len(arrivals) - len(names)) if len(arrivals) > len(names) else ""
            return ("%s nearby (%s)" % (names_s, g))[:60] + extra
        total = sum(len(v) for v in by_group.values())
        first = next(iter(by_group))
        return "%s + %d nearby" % (by_group[first][0], total - 1) if total > 1 else by_group[first][0]

    # ------------------------------------------------------------------ alerts
    def _fire_alert(self, arrivals):
        if not arrivals:
            return
        ids = [a["shared_id"] for a in arrivals if a["shared_id"] is not None]
        lowest = min(ids) if ids else 0
        hue, freq = _sig_from_id(lowest)
        r, g, b = _hsv(hue)
        self._flash_leds(r, g, b)
        self._show_banner(self._coalesced_text(arrivals), is_arrival=True)
        self._wake()
        TaskManager.create_task(self._sting(freq))

    def _flash_leds(self, r, g, b, ms=None):
        # A brief bright flash on all LEDs; the per-friend breathing (below)
        # resumes automatically once the override window elapses. `ms` overrides the
        # default hold (the Reveal gold flash holds REVEAL_FLASH_MS, §5.7).
        try:
            n = self._led_count()
            for i in range(n):
                lights.set_led(i, r, g, b)
            lights.write()
            hold = ms if ms else LED_FLASH_MS
            self._led_override_until = time.ticks_add(time.ticks_ms(), hold)
            self._led_last = None       # force a breathing redraw after the flash
        except Exception:
            pass

    # ---- per-friend breathing LEDs ----
    def _led_count(self):
        # 4 physical LEDs on 2024, 5 on 2026 (get_led_count() over-reports 5 on 2024).
        return 5 if self._is_2026 else 4

    def _update_leds(self, now):
        # Gotcha owns the whole strip while a game is live (§8.8.1): the radar bar
        # from the target's rssi_prox, dark when no target / truce. Otherwise the
        # per-friend breathing LEDs (one per nearby group-mate) -- unchanged.
        if time.ticks_diff(now, self._led_next_ms) < 0:
            return
        self._led_next_ms = time.ticks_add(now, LED_UPDATE_MS)
        if self._led_override_until and time.ticks_diff(now, self._led_override_until) < 0:
            return                      # a flash is currently showing
        n = self._led_count()
        if self._gc is not None and self._gc.enrolled:
            frame = self._led_hunt_frame(now, n)
        else:
            frame = self._led_friend_frame(now, n)
        if frame == self._led_last:     # skip redundant writes (dark/steady cost 0)
            return
        self._led_last = frame
        try:
            for i, (r, g, b) in enumerate(frame):
                lights.set_led(i, r, g, b)
            lights.write()
        except Exception:
            pass

    def _led_hunt_frame(self, now, n):
        # The §8.8.2 radar bar: [(r,g,b)]*n, brightness+breathe applied, dark when
        # halted/no target. Frame-cacheable (the caller dedups the whole frame).
        try:
            import gotcha
            gc = self._gc
            return gotcha.hunt_bar(gc.target_prox, now, gc.cfg, n,
                                   halted=gc.radar_halted())
        except Exception:
            return [(0, 0, 0)] * n

    def _led_friend_frame(self, now, n):
        # One LED per nearby friend, slowly + dimly breathing that friend's group
        # colour (friend 1 -> LED 0, friend 2 -> LED 1, ...). Others off.
        peers = [] if self._unconfigured else self._ble.current_peers()
        frame = []
        span = LED_DIM_MAX - LED_DIM_MIN
        for i in range(n):
            if i < len(peers):
                gid = peers[i][2]
                hue, _ = _sig_from_id(gid if gid is not None else 0)
                r, g, b = _hsv(hue, s=0.9, v=1.0)
                # gentle per-LED phase stagger so they don't pulse in lockstep
                phase = (now + i * (LED_BREATHE_MS // max(1, n))) % LED_BREATHE_MS
                s = LED_DIM_MIN + span * (0.5 - 0.5 * math.cos(2 * math.pi * phase / LED_BREATHE_MS))
                frame.append((int(r * s), int(g * s), int(b * s)))
            else:
                frame.append((0, 0, 0))
        return frame

    # ------------------------------------------------------------------ lifecycle
    def onCreate(self):
        self._load_config()
        self._resolve_focus_highlight()
        self._setup_buzzer()
        self._setup_display()
        self._name_font = self._load_name_font()
        # Build the nametag, then the splash as a full-screen overlay ON TOP of
        # it (built last so it z-stacks above the banner). setContentView is
        # called EXACTLY ONCE here — the splash is hidden after 3 s to reveal the
        # nametag, so there is only one entry on the OS screen stack and X quits
        # cleanly (no ghost splash — see _build_splash).
        self._scr = lv.obj()
        self._build_idle(self._scr)
        self._setup_gotcha()
        self._splash_scr = self._build_splash(self._scr)
        self.setContentView(self._scr)
        # add_focus_border enrols every focusable in the default group at build
        # time; onResume's _establish_focus reconciles it to exactly the active
        # state's set, so nothing needs doing here (the activity isn't
        # interactive until resume).

    def onResume(self, screen):
        super().onResume(screen)
        self._t0 = time.ticks_ms()
        self._last_input_ms = time.ticks_ms()
        self._dimmed = False
        # The OS already NTP-syncs on WiFi connect; defer our first resync so the
        # (blocking) ntptime.settime() call never hitches app launch.
        self._next_ntp_ms = time.ticks_add(time.ticks_ms(), NTP_RESYNC_MS)
        self._set_brightness(255)
        # Returning from the on-badge settings editor (a sub-Activity pauses us).
        if self._settings_pending:
            self._harvest_settings()
        if not self._unconfigured:
            try:
                self._ble.begin(self._config["groups"], self._config["name"],
                                self._config["rssi_floor"])
            except Exception:
                pass
            self._ensure_gatt_services()
        # A group-less badge (Configure-me or skipped) brings the radio up on
        # demand: a contact swap or a "Telefoon-setup" window; _teardown_ble()
        # powers it back down. No standing proximity beacon (nothing to match on).
        # Re-establish our focusables as the default group's only members (the
        # group was emptied by _release_focus on pause so the launcher/editor
        # got a clean group).
        self._establish_focus()
        self._gc_start()
        if not self._entered and self._splash_task is None:
            self._splash_task = TaskManager.create_task(self._splash_then_enter())
        self._task = TaskManager.create_task(self._loop())

    def onPause(self, screen):
        super().onPause(screen)
        self._release_focus()
        self._stop_task()
        self._stop_setup()
        self._teardown_ble()
        self._gc_stop()
        self._set_brightness(255)
        self._led_last = None
        try:
            lights.clear()
            lights.write()
        except Exception:
            pass

    def onStop(self, screen):
        self._release_focus()
        self._stop_task()
        self._stop_setup()
        self._teardown_ble()
        try:
            lights.clear()
            lights.write()
        except Exception:
            pass

    def onDestroy(self, screen):
        self._release_focus()
        self._stop_task()
        self._stop_setup()
        self._teardown_ble()
        try:
            if self._buzzer:
                self._buzzer.duty_u16(0)
                self._buzzer.deinit()
        except Exception:
            pass

    def _stop_task(self):
        if self._task is not None:
            try:
                self._task.cancel()
            except Exception:
                pass
            self._task = None
        if self._splash_task is not None:
            try:
                self._splash_task.cancel()
            except Exception:
                pass
            self._splash_task = None
        # Cancel an in-flight contact swap too — otherwise it outlives the
        # Activity by up to 5 s and touches LVGL widgets / BLE on a torn-down app
        # (the D-1 use-after-free hazard class). run_window re-raises the cancel.
        if self._exch_task is not None:
            try:
                self._exch_task.cancel()
            except Exception:
                pass
            self._exch_task = None
        # Cancel an in-flight Reveal connect too (§5.5/F-4: a leaving Activity must
        # not leave a GATT task touching a torn-down radio). _do_reveal's finally
        # resumes BLEProximity before the cancel propagates.
        if self._gc is not None:
            try:
                self._gc.cancel_reveal()
            except Exception:
                pass

    def _teardown_ble(self):
        try:
            self._ble.end()
        except Exception:
            pass
        # proximity.end() only powers the radio down if PROXIMITY owned it. A
        # badge with no groups never calls begin(), so a swap or setup session
        # is the only thing that ever brought BLE up — hand it the off switch.
        try:
            self._exch.radio_off()
        except Exception:
            pass

    # ------------------------------------------------------------------ main loop
    async def _loop(self):
        last = time.ticks_ms()
        while True:
            try:
                now = time.ticks_ms()
                dt = time.ticks_diff(now, last)
                last = now
                # Post-swap adopt prompt: open once the swap task has finished.
                # (Was driven from _handle_buttons; the raw-poll model is gone.)
                if (self._pending_adopt is not None and not self._exchanging and
                        not self._menu_open and self._setup_task is None):
                    self._open_adopt()
                # During a contact swap, keep the loop out of the radio's way:
                # skip the periodic refreshers — especially _update_leds, whose
                # WS2812 lights.write() disables IRQs and starves the short GATT
                # connection (causing it to fail/drop). The exchange task owns the
                # BLE for its ~5 s window; resume normal work when it's done.
                if self._exchanging:
                    await asyncio.sleep_ms(TICK_MS)
                    continue
                if self._setup_open:
                    # A configured-badge setup window owns the radio for its
                    # ~2 min: keep the loop out of it (no LED writes / scan that
                    # would starve the GATT link) but keep the overlay live.
                    self._refresh_setup(now)
                    self._refresh_clock(now)
                    if self._banner_until and time.ticks_diff(now, self._banner_until) >= 0:
                        self._hide_banner()
                    await asyncio.sleep_ms(TICK_MS)
                    continue
                if self._reload_pending:
                    self._reload_pending = False
                    self._apply_reload()
                # First-run handoff: proximity begins only once the setup session
                # that just saved has fully torn down (so they never advertise at
                # the same time). See _apply_reload's was_unconfigured branch.
                if self._pending_begin and self._setup_task is None:
                    self._pending_begin = False
                    try:
                        self._ble.begin(self._config["groups"], self._config["name"],
                                        self._config["rssi_floor"])
                    except Exception:
                        pass
                    self._ensure_gatt_services()
                self._ble.tick(now, dt)
                self._gc_tick(now)
                self._render_gotcha()
                self._hunt_ping(now)
                self._drain_arrivals()
                self._refresh_nearby()
                self._render_spotted(now)
                # While a setup session runs, or a Gotcha GATT connection is live
                # (§5.5), skip LED writes — the WS2812 write disables IRQs and
                # would starve the GATT link (field bug 2 / plan §2.3).
                if self._setup_task is None and not self._gatt_busy():
                    self._update_leds(now)
                self._refresh_battery(now)
                self._refresh_clock(now)
                self._refresh_setup(now)
                self._resync_time(now)
                if self._banner_until and time.ticks_diff(now, self._banner_until) >= 0:
                    self._hide_banner()
                if (self._has_backlight and not self._dimmed and
                        time.ticks_diff(now, self._last_input_ms) > 30000 and
                        not self._ble.has_peers()):
                    self._set_brightness(60)
                    self._dimmed = True
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep_ms(TICK_MS)

    def _drain_arrivals(self):
        if self._unconfigured:
            return
        arrivals = self._ble.take_arrivals()
        if not arrivals:
            return
        now = time.ticks_ms()
        # Only coalesce into a banner that is ITSELF an arrival banner still
        # showing — never into a "Geruild met X" / "Instellingen opgeslagen" banner
        # (that would silently rewrite it and skip the LED flash + sting).
        if (self._banner_is_arrival and self._banner_until and
                time.ticks_diff(now, self._banner_until) < 0):
            self._alert_names.extend(arrivals)
            try:
                self._banner.set_text(self._coalesced_text(self._alert_names))
            except Exception:
                pass
        else:
            self._alert_names = list(arrivals)
            self._fire_alert(self._alert_names)

    def _refresh_nearby(self):
        if self._friends_lbl is None:
            return
        if self._unconfigured:
            # Skipped, group-less badge: the nametag works, but there is nothing
            # to match on yet. Stand in for the friends list with the two ways to
            # fix that — neither of which needs a phone or the internet.
            new_txt = "nog geen groep - druk Y bij een vriend,\nof START om in te stellen"
            if new_txt != self._friends_last:
                try:
                    self._friends_lbl.set_text(new_txt)
                    self._friends_lbl.set_style_text_color(_col(COL_HINT), 0)
                except Exception:
                    pass
                self._friends_last = new_txt
            return
        peers = self._ble.current_peers()
        n = len(peers)
        if n:
            names = ", ".join(p[0] for p in peers)
            if len(names) > 90:          # wraps to ~3 lines; cap absurdly long lists
                names = names[:87] + "..."
            new_txt = "Vrienden dichtbij: " + names
        else:
            new_txt = "vrienden zoeken..."
        if new_txt != self._friends_last:
            try:
                self._friends_lbl.set_text(new_txt)
                self._friends_lbl.set_style_text_color(_col(COL_NEAR if n else COL_NONE), 0)
            except Exception:
                pass
            self._friends_last = new_txt
        for i, slot in enumerate(self._detail_rows):
            if i < n:
                self._fill_row(slot, peers[i])
                self._show_row(slot, True)
            else:
                self._show_row(slot, False)
        new_hdr = (("VRIENDEN DICHTBIJ %d" % n) if n else "nog geen vrienden dichtbij")
        if new_hdr != self._detail_header_last and self._detail_header is not None:
            try:
                self._detail_header.set_text(new_hdr)
            except Exception:
                pass
            self._detail_header_last = new_hdr

    # ------------------------------------------------------------------ battery
    def _refresh_battery(self, now):
        if self._batt_lbl is None or time.ticks_diff(now, self._batt_next_ms) < 0:
            return
        self._batt_next_ms = time.ticks_add(now, 5000)
        txt = self._battery_text()
        if txt != self._batt_last:
            try:
                self._batt_lbl.set_text(txt)
            except Exception:
                pass
            self._batt_last = txt

    def _battery_text(self):
        try:
            pct = BatteryManager.get_battery_percentage()
            if pct is None:
                return "--%"
            return "%d%%" % pct
        except Exception:
            return ""

    # ------------------------------------------------------------------ clock + NTP
    def _refresh_clock(self, now):
        if self._clock_lbl is None or time.ticks_diff(now, self._clock_next_ms) < 0:
            return
        self._clock_next_ms = time.ticks_add(now, 1000)
        try:
            t = time.localtime()
            txt = "%02d:%02d" % (t[3], t[4])
        except Exception:
            txt = "--:--"
        if txt != self._clock_last:
            try:
                self._clock_lbl.set_text(txt)
            except Exception:
                pass
            self._clock_last = txt

    def _resync_time(self, now):
        # Keep the RTC NTP-synced ~every 10 min while on WiFi (onResume defers the
        # first sync so it never hitches launch). ntptime.settime() briefly
        # blocks, so run it off the loop.
        if self._ntp_busy or time.ticks_diff(now, self._next_ntp_ms) < 0:
            return
        self._next_ntp_ms = time.ticks_add(now, NTP_RESYNC_MS)
        if not self._wifi_connected():
            return
        self._ntp_busy = True
        # ntptime.settime() is a BLOCKING network call — run it in a thread so it
        # never freezes the asyncio loop (which would stall the UI / an in-flight
        # contact exchange). Fall back to a task if _thread is unavailable. If
        # BOTH dispatch paths fail, clear _ntp_busy so resync isn't stuck off
        # for the rest of the session.
        try:
            import _thread
            _thread.start_new_thread(self._ntp_blocking, ())
        except Exception:
            try:
                TaskManager.create_task(self._ntp_sync())
            except Exception:
                self._ntp_busy = False

    def _ntp_blocking(self):
        try:
            import ntptime
            ntptime.settime()
        except Exception:
            pass
        finally:
            self._ntp_busy = False

    async def _ntp_sync(self):
        self._ntp_blocking()

    @staticmethod
    def _wifi_connected():
        try:
            from mpos import WifiService
            return bool(WifiService.is_connected())
        except Exception:
            return False

    # ------------------------------------------------------------------ contact exchange
    def _exch_log(self, msg):
        try:
            with open(APP_DIR + "/exch.log", "a") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    def _outgoing_contact(self):
        # What the swap sends alongside the name. Auto-include the badge's own
        # group(s) as a contact field (a user-defined field of the same name in
        # `contact` wins). Empty values are omitted.
        #
        # The receiver uses this field to offer "join my friend's group" — the
        # only zero-typing way into a group — so build_contact_envelope() treats
        # GROUPS_FIELD as protected and drops it LAST under size pressure.
        out = dict(self._contact) if isinstance(self._contact, dict) else {}
        groups = [g for g in (self._config.get("groups") or []) if g]
        if groups:
            out.setdefault(GROUPS_FIELD, ", ".join(groups))
        return out

    async def _do_exchange(self):
        self._exchanging = True
        t0 = time.ticks_ms()
        try:
            # BLE + LVGL share the ESP32's limited heap. Defragment before the
            # radio-heavy swap window so a malloc mid-exchange is less likely to
            # fail and panic-reboot the badge (the swap otherwise works most of
            # the time; this is a mitigation, not a confirmed root cause).
            gc.collect()
            self._show_banner("contacten ruilen...")
            self._wake()
            name = self._config.get("name", "") or "Anoniem"
            rec = await self._exch.run_window(self._ble, name, self._outgoing_contact())
            self._exch_log("%s board=%s %dms rec=%r trace=%s" % (
                _now_str(), "2026" if self._is_2026 else "2024",
                time.ticks_diff(time.ticks_ms(), t0), rec,
                " | ".join(self._exch.dbg)))
            if rec:
                rec["received_at"] = _now_str()
                try:
                    rec["received_ticks"] = time.ticks_ms()
                except Exception:
                    rec["received_ticks"] = 0
                self._store_contact(rec)
                self._flash_leds(*_hsv(180))
                TaskManager.create_task(self._sting(660))
                self._show_banner("Geruild met %s" % (rec.get("name") or "?"))
                self._offer_groups(rec)
            else:
                self._show_banner("niemand aan het ruilen")
        except asyncio.CancelledError:
            raise            # app exiting mid-swap — don't touch widgets, just unwind
        except Exception:
            try:
                self._show_banner("Ruilen mislukt")
            except Exception:
                pass
        finally:
            self._exchanging = False
            self._exch_task = None

    def _contacts_path(self):
        return APP_DIR + "/contacts.json"

    def _load_contacts(self):
        try:
            with open(self._contacts_path()) as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def _store_contact(self, rec):
        store = self._load_contacts()
        add_received(store, rec)
        try:
            _atomic_write_json(self._contacts_path(), store)
        except Exception:
            pass

    # --------------------------------------------------------- adopt a friend's group
    def _offer_groups(self, rec):
        """Queue the "join my friend's group(s)?" prompt after a swap.

        Only QUEUES it: we're still inside _do_exchange with self._exchanging
        True, so prompting here would render a panel whose focusable rows would
        fight the swap for the radio. The main loop picks the flag up once the
        swap task has finished — same deferral idiom as
        _reload_pending / _pending_begin.
        """
        # Clear first: a swap that offers nothing new must not leave an EARLIER
        # swap's offer queued, or the prompt would pop up naming the wrong peer.
        self._pending_adopt = None
        try:
            fields = rec.get("fields") or {}
            offered = parse_groups_field(fields.get(GROUPS_FIELD))
            fresh = new_groups_from(self._config.get("groups"), offered)
            if fresh:
                self._pending_adopt = (rec.get("name") or "?", fresh)
        except Exception:
            pass

    def _open_adopt(self):
        peer, groups = self._pending_adopt
        self._pending_adopt = None
        if not groups or self._adopt_panel is None:
            return
        self._adopt_groups = groups[:MAX_GROUPS]
        # Unchecked by default: the user explicitly ticks the group(s) they want
        # to join, so nothing is joined silently or by accident.
        self._adopt_ticked = [False] * len(self._adopt_groups)
        self._adopt_count = len(self._adopt_groups)
        self._adopt_open = True
        self._adopt_last = None
        n = self._adopt_count
        try:
            self._adopt_title_lbl.set_text(
                "%s zit in %d groepen\nWelke meedoen?" % (peer, n) if n > 1
                else "Meedoen met groep van %s?" % peer)
        except Exception:
            pass
        self._refresh_adopt()
        try:
            self._adopt_panel.remove_flag(lv.obj.FLAG.HIDDEN)
            self._adopt_panel.move_foreground()
        except Exception:
            pass
        # Keep the banner above the panel (it was built after the panel).
        if self._banner_bg is not None:
            try:
                self._banner_bg.move_foreground()
            except Exception:
                pass
        # Drive the group rows + Meedoen; the OS focus highlight marks the row.
        self._set_focus(self._adopt_rows[:n] + [self._adopt_join])

    def _refresh_adopt(self):
        state = tuple(self._adopt_ticked)
        if state == self._adopt_last:
            return
        self._adopt_last = state
        for i, row in enumerate(self._adopt_rows):
            if i >= len(self._adopt_groups):
                try:
                    row.add_flag(lv.obj.FLAG.HIDDEN)
                except Exception:
                    pass
                continue
            try:
                row.remove_flag(lv.obj.FLAG.HIDDEN)
                self._adopt_row_labels[i].set_text("[%s] %s" % (
                    "x" if self._adopt_ticked[i] else " ",
                    self._adopt_groups[i]))
            except Exception:
                pass

    def _close_adopt(self):
        self._adopt_open = False
        self._adopt_groups = []
        self._adopt_ticked = []
        self._adopt_count = 0
        try:
            self._adopt_panel.add_flag(lv.obj.FLAG.HIDDEN)
        except Exception:
            pass
        # Back to the nametag (or Configure-me) affordance.
        self._establish_focus()

    def _make_adopt_cb(self, i):
        def cb(e):
            self._on_adopt_group_clicked(i)
        return cb

    def _on_adopt_group_clicked(self, i):
        self._wake()
        if 0 <= i < len(self._adopt_ticked):
            self._adopt_ticked[i] = not self._adopt_ticked[i]
        self._refresh_adopt()

    def _on_adopt_join_clicked(self, e):
        self._wake()
        chosen = [g for g, t in zip(self._adopt_groups, self._adopt_ticked) if t]
        # Closes the prompt either way; only joins the ticked groups, so picking
        # Meedoen with nothing checked just silently quits the screen.
        self._close_adopt()
        if chosen:
            self._adopt_groups_now(chosen)

    # ------------------------------------------------------- on-badge menu (v0.10.0)
    def _on_menu_btn_clicked(self, e):
        self._wake()
        self._open_menu()

    def _make_menu_cb(self, i):
        def cb(e):
            self._on_menu_row_clicked(i)
        return cb

    def _on_menu_row_clicked(self, i):
        self._wake()
        action = self._menu_actions[i] if 0 <= i < len(self._menu_actions) else None
        self._do_menu_action(action)

    def _open_menu(self):
        # Build the item list for the current state, populate the rows, show the
        # overlay and hand the keypad the rows. Suppressed during the splash and
        # any BLE-owned state (a swap / setup window owns the radio).
        if not self._entered:
            return
        if (self._menu_open or self._exchanging or self._setup_open or
                self._setup_task is not None or self._adopt_open):
            return
        items = [
            ("Vrienden dichtbij", "detail"),
            ("Contact ruilen", "swap"),
            ("Geluid: %s" % ("aan" if self._sound else "uit"), "mute"),
            ("Telefoon-setup", "setup"),
            ("Instellingen", "settings"),
        ]
        # Gotcha rows appear once a game has ever been joined (§13: opt-out is
        # always reachable in a few seconds; opt-in brings you back).
        if self._gc is not None and self._gc.ever_enrolled():
            items.append(("Gotcha demo", "gotcha_demo"))
            items.append(("Stoppen met Gotcha" if not self._gc.is_opted_out()
                          else "Meedoen met Gotcha", "gotcha_toggle"))
        self._menu_actions = [act for _, act in items]
        self._menu_count = len(items)
        for i in range(MENU_MAX):
            if i < self._menu_count:
                try:
                    self._menu_row_labels[i].set_text(items[i][0])
                    self._menu_rows[i].remove_flag(lv.obj.FLAG.HIDDEN)
                except Exception:
                    pass
            else:
                try:
                    self._menu_rows[i].add_flag(lv.obj.FLAG.HIDDEN)
                except Exception:
                    pass
        self._menu_open = True
        if self._menu is not None:
            try:
                self._menu.remove_flag(lv.obj.FLAG.HIDDEN)
                self._menu.move_foreground()
            except Exception:
                pass
        # Keep the banner above the overlay (it was built after it).
        if self._banner_bg is not None:
            try:
                self._banner_bg.move_foreground()
            except Exception:
                pass
        self._set_focus(self._menu_rows[:self._menu_count])

    def _close_menu(self):
        self._menu_open = False
        if self._menu is not None:
            try:
                self._menu.add_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass
        self._set_focus([self._menu_btn])

    def _do_menu_action(self, action):
        if action == "detail":
            self._close_menu()
            self._toggle_detail()
        elif action == "swap":
            self._close_menu()
            self._exch_task = TaskManager.create_task(self._do_exchange())
        elif action == "mute":
            # Toggle in place: stay in the menu and reflect the new state on the
            # row label so the user sees it flip.
            self._toggle_mute()
            try:
                idx = self._menu_actions.index("mute")
                self._menu_row_labels[idx].set_text(
                    "Geluid: %s" % ("aan" if self._sound else "uit"))
            except Exception:
                pass
        elif action == "setup":
            self._close_menu()
            self._open_setup_window()
        elif action == "settings":
            self._close_menu()
            self._open_settings()
        elif action == "gotcha_demo":
            self._close_menu()
            TaskManager.create_task(self._gotcha_demo())
        elif action == "gotcha_toggle":
            # Opt out / back in in place (§13). Stay in the menu and refresh the
            # row label so the change is visible immediately.
            self._gotcha_toggle()
            try:
                idx = self._menu_actions.index("gotcha_toggle")
                self._menu_row_labels[idx].set_text(
                    "Stoppen met Gotcha" if not self._gc.is_opted_out()
                    else "Meedoen met Gotcha")
            except Exception:
                pass

    def _make_cfg_cb(self, action):
        def cb(e):
            self._do_cfg_action(action)
        return cb

    def _do_cfg_action(self, action):
        # Configure-me mini-menu: the three ways off the first-run screen.
        self._wake()
        if action == "settings":
            self._open_settings()
        elif action == "phone":
            self._open_setup_window()
        elif action == "skip":
            self._skip_setup()

    def _toggle_detail(self):
        self._detail = not self._detail
        if self._detail_panel is not None:
            try:
                if self._detail:
                    self._detail_panel.remove_flag(lv.obj.FLAG.HIDDEN)
                else:
                    self._detail_panel.add_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass

    def _toggle_mute(self):
        self._sound = not self._sound
        self._save_config("sound", self._sound)
        self._flash_leds(*_hsv(0 if not self._sound else 120))

    def _on_setup_close_clicked(self, e):
        # Close the setup window from its "Sluiten" button (A) -- the same thing
        # X does via onBackPressed. Restore the prior state's focus.
        self._wake()
        self._stop_setup()
        self._establish_focus()

    def onBackPressed(self, screen):
        # X = back/close. Close the topmost overlay before letting the framework
        # finish (quit) the activity. Returning True consumes the press and keeps
        # us foregrounded; returning False (nothing open) quits to the launcher.
        if self._consent_open:
            # Consent must be acknowledged: X == "Niet meedoen" (decline, §13).
            self._do_consent_action("decline")
            return True
        if self._menu_open:
            self._close_menu()
            return True
        if self._adopt_open:
            self._close_adopt()
            return True
        if self._setup_open:
            self._stop_setup()
            self._establish_focus()
            return True
        if self._detail:
            self._toggle_detail()
            return True
        return False

    def _adopt_groups_now(self, chosen):
        """Join `chosen`, persist, and bring the beacon up under the new groups."""
        before = list(self._config.get("groups") or [])
        merged, dropped = merge_groups(before, chosen)
        added = merged[len(before):]          # what actually fit, in order
        if not added:
            if dropped:
                self._show_banner("Al in %d groepen (max %d)"
                                  % (len(before), MAX_GROUPS))
            return
        self._save_config("groups", merged)
        was_off = self._unconfigured
        self._load_config()
        self._refresh_pills()      # show the new pill(s) immediately, no reboot
        # A Configure-me badge can't reach a swap (it has no menu), so in
        # practice the nametag already exists — but the call is idempotent, so be
        # safe rather than clever.
        self._swap_setup_for_nametag()
        # Go on the air. If a beacon was already running it must be restarted to
        # advertise the new group set: end() then let the main loop begin() once
        # any setup session is down — the same active(False)/begin() cycle
        # onPause/onResume performs routinely, and ensure_radio()'s stale-handle
        # self-heal covers the GATT table it clears.
        if not was_off:
            try:
                self._ble.end()
            except Exception:
                pass
        self._pending_begin = True
        joined = ", ".join(added)
        if dropped:
            self._show_banner("%s erbij (%d paste niet, max %d)"
                              % (joined, dropped, MAX_GROUPS))
        else:
            self._show_banner("%s erbij" % joined)

    # --------------------------------------------------------- on-badge settings editor
    def _skip_setup(self):
        """\"Overslaan\" on Configure-me: drop to the nametag under the
        auto-nickname. Persisted, so the badge doesn't nag on every boot — the
        \"no group yet\" hint on the nametag is a gentler standing reminder."""
        self._setup_skipped = True
        self._save_config("setup_skipped", True)
        # Power down any radio a setup window may have brought up; nothing else
        # wants it on a group-less badge (no beacon). Idempotent + safe if none.
        self._stop_setup()
        try:
            self._exch.radio_off()
        except Exception:
            pass
        self._swap_setup_for_nametag()
        self._show_banner("Later instellen via Menu")

    def _open_settings(self):
        """Launch the OS settings editor for our config (no phone, no internet).

        MicroPythonOS owns the input modality here: touch on the 2026 badge,
        button-navigated focus + the LVGL keyboard on the button-only 2024 one —
        which is why this needs no board branching. Imported lazily so an older
        OS build without SettingsActivity degrades to "the button does nothing"
        rather than breaking the app.

        SharedPreferences is used purely as a TRANSFER BUFFER: config.json stays
        the single source of truth, seeded here and harvested in onResume.
        """
        try:
            from mpos import Intent, SettingsActivity
            try:
                from mpos import SharedPreferences
            except ImportError:          # docs show both spellings
                from mpos.config import SharedPreferences
        except Exception:
            self._show_banner("Instellen op badge vraagt nieuwere OS")
            return
        try:
            prefs = SharedPreferences(FULLNAME)
            seed = config_to_settings(self._config)
            editor = prefs.edit()
            for k, v in seed.items():
                editor.put_string(k, v)
            editor.commit()
            self._settings_prefs = prefs
            self._settings_pending = True
            intent = Intent(activity_class=SettingsActivity)
            intent.putExtra("prefs", prefs)
            intent.putExtra("settings", [
                {"title": "Je naam", "key": "name",
                 "placeholder": "Groot op de badge"},
                {"title": "Groepen", "key": "groups",
                 "placeholder": "Komma ertussen, bv. Makerspace Baasrode",
                 "note": "Iedereen in een groep typt het NET ZO."},
                {"title": "Geluid", "key": "sound", "ui": "radiobuttons",
                 "ui_options": [("Aan", "on"), ("Uit", "off")]},
                {"title": "Bereik", "key": "rssi_floor", "ui": "dropdown",
                 "ui_options": [(label, label) for label, _ in RANGE_PRESETS]},
                {"title": "Banner (sec)", "key": "banner_s", "ui": "slider",
                 "min": 1, "max": 15},
            ])
            self.startActivity(intent)
        except Exception:
            self._settings_pending = False
            self._show_banner("Instellen op badge lukt niet")

    def _harvest_settings(self):
        """Merge the editor's prefs back into config.json and apply.

        Runs on the onResume after the editor Activity finishes. Every value
        goes through settings_to_config -> sanitize_config, the same validator
        the phone page uses, so a partial or junk harvest can't corrupt or wipe
        anything: absent keys fall back to the on-disk config.
        """
        self._settings_pending = False
        prefs = self._settings_prefs
        self._settings_prefs = None
        if prefs is None:
            return
        try:
            got = {}
            for k in SETTINGS_KEYS:
                try:
                    v = prefs.get_string(k, None)
                except Exception:
                    v = None
                if v is not None:
                    got[k] = v
            if not got:
                return
            try:
                with open(APP_DIR + "/config.json", "r") as f:
                    base = json.load(f)
            except Exception:
                base = {}
            cfg = settings_to_config(got, base)
            _atomic_write_json(APP_DIR + "/config.json", cfg)
        except Exception:
            self._show_banner("Opslaan mislukt")
            return
        # Reload NOW, not via _reload_pending alone: this runs inside onResume,
        # just before onResume decides whether to begin() the beacon and with
        # which groups. Deferring the reload to the main loop would start the
        # radio on the pre-edit group set and leave it stale until an app
        # restart — exactly the thing someone editing their groups is fixing.
        was_setup_screen = self._show_setup_screen()
        try:
            self._load_config()
        except Exception:
            pass
        if was_setup_screen and not self._show_setup_screen():
            self._swap_setup_for_nametag()
        # Still hand off to the usual path for the in-place label refresh and
        # the "Config saved" banner (idempotent — it reloads the config again).
        self._reload_pending = True

    # ------------------------------------------------------------------ BLE phone setup
    def _setup_url(self, bid):
        return SETUP_URL_BASE + "?badge=" + bid

    def _open_setup_window(self):
        # Open a bounded (SETUP_WINDOW_MS) setup window. On a configured badge
        # the session suspends the proximity radio and resumes it on close; on a
        # Configure-me / skipped badge (no proximity running) it simply brings
        # the radio up for the window. Reached from the menu's "Telefoon-setup"
        # item and Configure-me's "Telefoon-setup" row.
        if (self._exchanging or self._setup_open or
                self._setup_task is not None or self._adopt_open or self._menu_open):
            return
        self._setup_open = True
        self._setup_win_deadline = time.ticks_add(time.ticks_ms(), SETUP_WINDOW_MS)
        self._show_setup_overlay()
        try:
            self._setup_task = TaskManager.create_task(self._run_setup_window())
        except Exception:
            self._setup_task = None
            self._setup_open = False
            self._hide_setup_overlay()

    async def _run_setup_window(self):
        me = asyncio.current_task()
        try:
            await self._setup.run("window", proximity=self._ble,
                                  timeout_ms=SETUP_WINDOW_MS)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            self._setup_open = False
            if self._setup_task is me:   # don't clobber a restarted session (see above)
                self._setup_task = None
            self._hide_setup_overlay()
            self._led_last = None
            # On a clean close (timeout) hand focus back to the prior state. (On
            # cancel-via-pause _focus_held is already False; onResume restores.)
            if self._focus_held:
                self._establish_focus()
            try:
                self._show_banner("Setup gesloten")
            except Exception:
                pass

    def _stop_setup(self):
        # Cancel any running setup session (configure or window) and clear
        # overlay/window state. Mirrors _stop_task's cancel-then-teardown; the
        # session's run() re-raises the cancel and tears the radio down itself.
        if self._setup_task is not None:
            try:
                self._setup.request_stop()
            except Exception:
                pass
            try:
                self._setup_task.cancel()
            except Exception:
                pass
            self._setup_task = None
        self._setup_open = False
        self._hide_setup_overlay()

    def _show_setup_overlay(self):
        if self._overlay is not None:
            try:
                self._overlay.remove_flag(lv.obj.FLAG.HIDDEN)
                self._overlay.move_foreground()
            except Exception:
                pass
        self._setup_last = None
        self._overlay_qr_last = None
        # Give the keypad a target while the window is open (the Sluiten button)
        # so the OS drawer can't grab a press.
        if self._setup_close_btn is not None:
            self._set_focus([self._setup_close_btn])

    def _hide_setup_overlay(self):
        if self._overlay is not None:
            try:
                self._overlay.add_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass

    def _refresh_setup(self, now):
        # Throttled: read the live badge id / code / (window) countdown from the
        # setup session and update the QR + on-screen text. Runs both on the
        # Configure-me screen (unconfigured) and in the window overlay.
        if time.ticks_diff(now, self._setup_next_ms) < 0:
            return
        self._setup_next_ms = time.ticks_add(now, 1000)
        if self._setup_task is None:
            return
        try:
            bid = self._setup.current_badge_id()
            code = self._setup.current_code()
        except Exception:
            return
        url = self._setup_url(bid) if bid and bid != "0000" else None
        if self._setup_open:
            # Configured-badge window overlay.
            self._update_setup_qr(self._overlay_qr, self._overlay_qr_box, url)
            self._set_lbl(self._overlay_code_lbl,
                          ("%s   code %s" % (setup_name(bid), code)) if code else setup_name(bid))
            # The window is an idle timeout that resets on BLE activity, so ask
            # the session for the true remaining time rather than counting down
            # from a fixed deadline (which would falsely hit 0 mid-transfer).
            try:
                secs = self._setup.window_secs_left()
            except Exception:
                secs = None
            if secs is None:
                secs = time.ticks_diff(self._setup_win_deadline, now) // 1000
            if secs < 0:
                secs = 0
            self._set_lbl(self._overlay_count_lbl, "sluit over %ds - Y om te sluiten" % secs)
        else:
            # Configure-me screen (unconfigured).
            self._update_setup_qr(self._qr, self._qr_box, url)
            if bid and bid != "0000":
                txt = "%s   code %s" % (setup_name(bid), code) if code else setup_name(bid)
            else:
                txt = "bluetooth starten..."
            if txt != self._setup_last:
                self._set_lbl(self._setup_info_lbl, txt)
                self._setup_last = txt

    def _update_setup_qr(self, qr, box, url):
        if qr is None or box is None:
            return
        is_configure = qr is self._qr
        last = self._qr_last if is_configure else self._overlay_qr_last
        if url == last:
            return
        try:
            if url:
                qr.update(url, len(url))
                box.remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                box.add_flag(lv.obj.FLAG.HIDDEN)
        except Exception:
            return
        if is_configure:
            self._qr_last = url
        else:
            self._overlay_qr_last = url

    @staticmethod
    def _set_lbl(lbl, text):
        if lbl is None:
            return
        try:
            lbl.set_text(text)
        except Exception:
            pass

    def _reload_config(self):
        # Called from the setup service (same asyncio loop) after a save. Defer
        # the actual apply to the main loop so it never races the BLE tick /
        # exchange window / setup session.
        self._reload_pending = True

    def _apply_reload(self):
        # Runs on the main loop after a portal save. Keep this SAFE: only reload
        # the in-memory config and do in-place label updates. Do NOT rebuild or
        # re-submit the screen here — deleting the active screen (with its
        # scrolling labels) hard-crashes + reboots the badge on this build (see
        # _enter_main), and calling setContentView() a second time re-fires this
        # Activity's own onPause/onStart/onResume (mpos.ui.view.setContentView
        # always pushes onto the global screen stack and cycles the lifecycle of
        # whichever activity owns the new screen — even when that's `self`
        # again), which would tear down and duplicate the very state we're in
        # the middle of updating (portal, main-loop task, BLE). So name +
        # contact + runtime settings AND group pills apply live (pills via
        # _refresh_pills); only the on-air beacon's group set waits for the next
        # app start (restarting BLE live is the risky part avoided here).
        if self._exchanging:
            self._reload_pending = True
            return
        was_unconfigured = self._unconfigured
        try:
            self._load_config()
        except Exception:
            pass
        if self._name_lbl is not None:
            try:
                self._name_lbl.set_text(self._config.get("name", ""))
            except Exception:
                pass
        self._refresh_pills()
        if was_unconfigured and not self._unconfigured:
            # First-time setup just completed over BLE. Hand the radio from the
            # setup session to the proximity feature WITHOUT the two advertising
            # at once: the setup session is still advertising Fri3d-XXXX during
            # its save-grace (so the phone can read back the saved config), so we
            # DON'T begin proximity here. Instead flag it — the main loop starts
            # proximity once the setup session has fully ended (_setup_task None).
            # The "Contact ruilen" menu item opens a swap task only while no
            # setup task is running, so a swap can't find a half-up radio.
            self._pending_begin = True
            self._swap_setup_for_nametag()
        self._show_banner("Instellingen opgeslagen")

    def _swap_setup_for_nametag(self):
        # In-place layout swap on the SAME live screen: hide the setup widgets
        # (never delete — deleting live widgets/screens hard-crashes this
        # build) and create the nametag widgets next to them. No
        # setContentView either: re-submitting the screen pushes the OS stack
        # and re-fires this Activity's own onPause/onResume mid-update.
        #
        # IDEMPOTENT: since v0.9.0 there are three callers (a phone save, "skip
        # for now", and adopting a group after a swap) and they can follow each
        # other. Running twice would build a SECOND nametag on top of the first.
        if self._name_lbl is not None:
            return
        for wdg in self._setup_widgets:
            try:
                wdg.add_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass
        self._setup_widgets = []
        self._qr = None          # box was hidden above; stop QR refreshes
        self._qr_box = None
        self._qr_last = None
        try:
            self._build_nametag(self._scr)
        except Exception:
            pass
        # The setup-window overlay and menu overlay are always built in
        # _build_idle, so they already exist; the guard is just a safety net.
        if self._overlay is None:
            try:
                self._build_setup_overlay(self._scr)
            except Exception:
                pass
        # New widgets were created after the banner, so re-raise it above them.
        if self._banner_bg is not None:
            try:
                self._banner_bg.move_foreground()
            except Exception:
                try:
                    self._banner_bg.move_to_index(-1)
                except Exception:
                    pass
        # Hand the keypad the nametag's new menu affordance.
        self._establish_focus()
