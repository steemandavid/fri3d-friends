# beacon_service.py — background BLE service for "!Fri3d Friends".
#
# Two jobs, both while the app is NOT on the screen stack (DESIGN.md §12):
#
#   1. BEACON (always, when it owns the radio): advertise the same proximity
#      beacon the app sends, so a closed badge stays visible to friends.
#
#   2. GOTCHA VICTIM RESponder (Phase 4, plan §5.6 / D3): bring up the GATT
#      server and run the VICTIM half of the game only -- accept inbound REVEAL
#      and ATTACK writes, run the hold timer, dodge accounting, soul release,
#      target handover, the reveal flash + chirp (§5.7) and protection state
#      (§5.8) -- with effects delivered through buzzer + LEDs only (no UI). It
#      must NOT scan and must NOT attack: hunting requires the app to be open.
#      Without this, "close the app" is perfect invincibility (D3).
#
# Radio ownership (single BLE() stack, single adv set -- the most fragile area,
# plan §5.6):
#   - App anywhere on the screen stack -> the service holds OFF the radio: the
#     Activity begins/suspends/tears down BLE through its own lifecycle. The
#     service does a SOFT release (forgets its state, NEVER calls active(False))
#     so it can never wipe a GATT registration the app just made. The app's
#     onPause active(False) clears the table on its way out.
#   - App not on the stack -> the service owns the radio: ensure_radio()
#     registers the GATT services (its write-probe self-heal re-registers after
#     the app's active(False) wiped them), then it advertises connectable with
#     the game block.
# Both owners build their OWN controller/exchange stack; only one is ever live.
#
# Cadence: the watchdog ticks FAST (~250 ms) while it owns the radio -- a victim
# must drain the ATTACK queue and advance the duel hold promptly -- and SLOW
# (~2 s) while idle, just polling for the app to leave the stack.

import sys
import json

APP_DIR = "/apps/com.fri3dcamp.fri3dfriends"
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from ble_proximity import BLEProximity, build_payload, build_own_table, \
    hash_groups, ADV_MS, RSSI_FLOOR_DEFAULT
from identity import auto_nickname
# Import the sibling game modules at TOP LEVEL (not lazily in _build_stack): the
# service runs from a boot context where the app dir may have dropped off
# sys.path by the time the watchdog ticks, and a lazy `import contact_exchange`
# then fails with "no module named" even though the file is present. ble_proximity
# works at boot precisely because it is imported here, so the siblings (same dir,
# same light top-level imports) do too -- they land in sys.modules at boot and
# stay findable. gotcha_app / gotcha_gatt / contact_exchange keep bluetooth /
# machine / lvgl out of their own top level (lazy), so this import is cheap.
import contact_exchange as _ce_mod
import gotcha_app as _gc_mod
import gotcha_gatt as _gg_mod
import state_backup as _sb_mod

try:
    from mpos import Service, TaskManager
except ImportError:              # host-side unit tests: no mpos on CPython
    TaskManager = None

    class Service:
        def __init__(self):
            pass


POLL_MS_RADIO = 250              # victim-responder tick while we own the radio
POLL_MS_IDLE = 2000              # app-open / unconfigured poll cadence
REFRESH_POLLS = 12               # re-assert the beacon every ~3 s of radio ticks

# Buzzer GPIO (DESIGN.md "2024 vs 2026"; 2024=GPIO46, 2026=GPIO38).
BUZZER_PIN_2024 = 46
BUZZER_PIN_2026 = 38


def _unique_id():
    """The board's fused id bytes, or b"" off-device (host tests)."""
    try:
        import machine
        return machine.unique_id()
    except Exception:
        return b""


def _detect_2026():
    """True on the 2026 board (5 LEDs, GPIO38 buzzer). Mirrors fri3d_friends."""
    try:
        from mpos import DeviceInfo
        if str(DeviceInfo.get_hardware_id()).startswith("fri3d_2026"):
            return True
    except Exception:
        pass
    try:
        import mpos
        _ = mpos.io_expander.version
        return True
    except Exception:
        return False


def _read_config(app_dir=APP_DIR):
    """config.json as a dict, or None if unreadable."""
    try:
        with open(app_dir + "/config.json") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    return None


def load_beacon_config(app_dir=APP_DIR, uid=None):
    """Read config.json -> (own_ids, name), or None if unconfigured/unreadable.

    Mirrors Fri3dFriends._load_config's rule, which since v0.9.0 is GROUPS ONLY:
    an empty `name` falls back to the auto-nickname (identity.auto_nickname), so
    the background beacon advertises the same name the app shows. A badge with no
    valid group still stays off the air entirely (README promise) — groups are
    never auto-assigned, so an un-set-up badge is silent, not spamming the camp.

    `uid` is injectable for the host tests; on-device it comes from
    machine.unique_id().
    """
    cfg = _read_config(app_dir)
    if cfg is None:
        return None
    groups = cfg.get("groups")
    if not isinstance(groups, list):
        return None
    name = cfg.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        name = auto_nickname(_unique_id() if uid is None else uid)
    ids = [gid for _, gid in build_own_table(groups)]
    if not ids:
        return None
    own_ids, _ = hash_groups(groups)
    return own_ids, name


def load_service_config(app_dir=APP_DIR, uid=None):
    """The full background-responder config, or None if the badge is off the air.

    Returns {groups, name, rssi_floor, sound, gotcha, quiet}: everything the
    service needs to build a headless GotchaController and advertise connectable.
    None means 'stay silent' (no valid group) -- the same gate as
    load_beacon_config, so a background beacon and a background victim switch on
    together (a badge not advertising is not a reachable target either).
    """
    cfg = _read_config(app_dir)
    if cfg is None:
        return None
    groups = cfg.get("groups")
    if not isinstance(groups, list) or not [gid for _, gid in build_own_table(groups or [])]:
        return None
    name = cfg.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        name = auto_nickname(_unique_id() if uid is None else uid)
    try:
        rssi_floor = int(cfg.get("rssi_floor", RSSI_FLOOR_DEFAULT))
    except Exception:
        rssi_floor = RSSI_FLOOR_DEFAULT
    return {
        "groups": groups,
        "name": name,
        "rssi_floor": rssi_floor,
        "sound": bool(cfg.get("sound", True)),
        "gotcha": cfg.get("gotcha") or {},
        "quiet": cfg.get("quiet"),
    }


def app_in_stack(stack, fullname):
    """True if any activity on the screen stack belongs to `fullname`.

    Checks the whole stack, not just the top: if our Activity is buried under
    another one its BLE is already torn down (onPause), but its lifecycle will
    take the radio straight back on resume — the service must not fight it.
    Pure (operates on a list of (activity, ...) tuples) for host testing.
    """
    for entry in stack:
        act = entry[0] if entry else None
        if act is not None and getattr(act, "appFullName", None) == fullname:
            return True
    return False


_ACTIVE = None                   # bench observability: the live instance, set in onStart


class Fri3dBeaconService(Service):
    def __init__(self):
        super().__init__()
        self._running = False
        self._task = None
        # radio-owned stack (built lazily when we take the radio)
        self._ble = None              # BLEProximity
        self._exch = None             # ContactExchange (owns GATT registration)
        self._svc = None              # GotchaService (REVEAL/ATTACK responder)
        self._gc = None               # GotchaController (headless victim)
        self._has_radio = False
        self._polls = 0
        # effects
        self._sound = True
        self._buzzer = None
        self._is_2026 = False
        self._siren_until_ms = 0      # the under-attack siren runs until this
        self._led_count = 4
        self._log = []                # small in-memory ring (bench observability)

    # ---- Service lifecycle ----
    def onStart(self, intent=None):
        global _ACTIVE
        _ACTIVE = self
        self._running = True
        self._is_2026 = _detect_2026()
        self._led_count = 5 if self._is_2026 else 4
        cfg = _read_config()
        self._sound = bool((cfg or {}).get("sound", True))
        self._setup_buzzer()
        try:
            self._task = TaskManager.create_task(self._watchdog())
        except Exception:
            self._running = False

    def onDestroy(self):
        self._running = False
        if self._task is not None:
            try:
                self._task.cancel()
            except Exception:
                pass
            self._task = None
        self._teardown_radio()

    # ---- app-state probe ----
    def _app_is_open(self):
        try:
            from mpos.ui import view
            fullname = getattr(self, "appFullName", None) or APP_DIR.split("/")[-1]
            return app_in_stack(view.screen_stack, fullname)
        except Exception:
            return True          # can't tell -> assume open, keep hands off

    # ---- buzzer / LED effect layer (Phase 4 victim cues) -------------------
    def _setup_buzzer(self):
        try:
            from machine import PWM, Pin
            pin = BUZZER_PIN_2026 if self._is_2026 else BUZZER_PIN_2024
            self._buzzer = PWM(Pin(pin), freq=2000, duty_u16=0)
        except Exception:
            self._buzzer = None

    def _leds(self, r, g, b):
        """One write of a solid colour across all LEDs. A SINGLE write -- never
        animated -- because lights.write disables IRQs and would starve the live
        GATT link that a duel holds open (the §5.3 escape is a link drop)."""
        try:
            from mpos import lights
            for i in range(self._led_count):
                lights.set_led(i, r, g, b)
            lights.write()
        except Exception:
            pass

    def _leds_clear(self):
        try:
            from mpos import lights
            lights.clear()
            lights.write()
        except Exception:
            pass

    async def _chirp(self, freq, ms=120):
        if not self._sound or not self._buzzer:
            return
        try:
            self._buzzer.freq(int(freq))
            self._buzzer.duty_u16(16000)
            import asyncio
            await asyncio.sleep_ms(ms)
            self._buzzer.duty_u16(0)
        except Exception:
            pass

    async def _siren(self):
        # The under-attack alarm (§5.3): a two-tone buzzer until the hold ends.
        # Buzzer PWM only -- it does NOT disable IRQs (unlike lights.write), so it
        # is safe alongside the live attack connection.
        import asyncio, time
        while self._running and time.ticks_diff(self._siren_until_ms, time.ticks_ms()) > 0:
            if not self._sound or not self._buzzer:
                await asyncio.sleep_ms(120)
                continue
            try:
                self._buzzer.freq(880)
                self._buzzer.duty_u16(20000)
                await asyncio.sleep_ms(220)
                if not self._running:
                    break
                self._buzzer.freq(1320)
                await asyncio.sleep_ms(180)
            except Exception:
                await asyncio.sleep_ms(120)
        if self._buzzer:
            try:
                self._buzzer.duty_u16(0)
            except Exception:
                pass

    def _start_siren(self, hold_ms):
        import time
        self._siren_until_ms = time.ticks_add(time.ticks_ms(), hold_ms + 500)
        try:
            TaskManager.create_task(self._siren())
        except Exception:
            pass

    def _stop_siren(self):
        self._siren_until_ms = 0          # the loop sees this and exits
        if self._buzzer:
            try:
                self._buzzer.duty_u16(0)
            except Exception:
                pass

    # The four victim-side effect callbacks (wired into the headless controller).
    def _on_spotted(self, hunter):
        # §5.7 reveal flash: gold LEDs + a chirp. The hunter disconnects right
        # after the write, so there is no live link for a lights.write to starve.
        self._leds(255, 200, 0)
        try:
            TaskManager.create_task(self._chirp(2200))
        except Exception:
            pass

    def _on_engaged(self, attacker, hold_ms):
        # §5.3 under-attack: ONE red LED write (held, no animation) + the siren.
        # The alarm kill switch (§8.10.1) mutes only the siren -- the red LED
        # still shows, so a muted badge is still visibly under attack.
        self._leds(255, 0, 0)
        if self._gc is not None and not self._gc.cfg.get("alarm_enabled", True):
            return
        self._start_siren(hold_ms)

    def _on_dodged(self, attacker):
        # §5.3 escape: stop the siren, green flash, relief chirp.
        self._stop_siren()
        self._leds(0, 200, 0)
        try:
            TaskManager.create_task(self._chirp(660))
        except Exception:
            pass

    def _on_killed(self, attacker):
        # §5.3 death: stop the siren, dim red, a low descending tone.
        self._stop_siren()
        self._leds(120, 0, 0)
        try:
            TaskManager.create_task(self._chirp(330, ms=400))
        except Exception:
            pass

    # ---- build the headless GATT stack (once per radio-take) ---------------
    def _build_stack(self, cfg):
        """Construct BLEProximity + ContactExchange + GotchaService + a headless
        GotchaController, wired exactly like the Activity's _setup_gotcha minus
        the UI widgets. Idempotent if the stack already exists."""
        if self._gc is not None:
            return True
        # Siblings are imported at module top level (see the comment there); just
        # reference them. A defensive path guard too, in case the boot context
        # lost the app dir from sys.path before a later re-import somewhere.
        if APP_DIR not in sys.path:
            sys.path.insert(0, APP_DIR)
        try:
            self._ble = BLEProximity()
            self._exch = _ce_mod.ContactExchange()
            gc = _gc_mod.GotchaController(
                self._ble, APP_DIR + "/gotcha.json", log=self._dbg,
                on_save=self._gc_backup_hook,
                on_engaged=self._on_engaged, on_killed=self._on_killed,
                on_dodged=self._on_dodged, on_spotted=self._on_spotted)
            gc.set_exchange(self._exch)
            gc.configure(cfg["gotcha"], cfg["name"], cfg["groups"])
            svc = _gg_mod.GotchaService(on_reveal=gc.apply_reveal,
                                        on_attack=gc.apply_attack)
            self._exch.attach_gotcha(svc)
            gc.set_service(svc)
            self._ble.set_gatt_dispatch(svc.handle_irq)
            self._gc = gc
            self._svc = svc
            return True
        except Exception as e:
            self._dbg("build err %r" % (e,))
            self._gc = None
            self._svc = None
            return False

    def _gc_backup_hook(self):
        # §8.10.4: mirror gotcha.json after every save, same as the Activity.
        try:
            _sb_mod.make_real_fs(APP_DIR).mirror("gotcha.json")
        except Exception:
            pass

    def _dbg(self, msg):
        # Best-effort ring buffer; the headless service has no screen, so this is
        # the only trace of a failed take_radio / tick. Capped to bound memory.
        self._log.append(str(msg))
        if len(self._log) > 40:
            del self._log[:20]

    # ---- radio ownership ---------------------------------------------------
    def _take_radio(self):
        cfg = load_service_config()
        if cfg is None:                     # unconfigured badge: stay silent
            self._teardown_radio()
            return
        if not self._build_stack(cfg):
            return
        # Register the GATT services BEFORE advertising: gatts_register_services
        # EBUSYs on a radio that is already advertising (Phase-3b victim bug).
        try:
            import bluetooth
            self._exch.ensure_radio(bluetooth)
        except Exception as e:
            self._dbg("ensure_radio err %r" % (e,))
        try:
            self._ble.begin(cfg["groups"], cfg["name"], cfg["rssi_floor"])
        except Exception as e:
            self._dbg("begin err %r" % (e,))
        try:
            self._gc.start()                # _push_game_context: connectable + block
        except Exception as e:
            self._dbg("gc.start err %r" % (e,))
        self._has_radio = True
        self._polls = 0
        self._dbg("TOOK radio (bg victim)")

    def _teardown_radio(self):
        # SOFT release: stop the controller + effects, but do NOT call active(False)
        # here -- the app may be mid-lifecycle and a stray active(False) would wipe
        # a GATT registration it just made (the "swap stops working" bug). The
        # app's own onPause active(False) clears the table when it leaves.
        if self._gc is not None:
            try:
                self._gc.stop()
            except Exception:
                pass
        self._stop_siren()
        self._has_radio = False
        self._gc = None                     # rebuild fresh next take (reloads state)
        self._svc = None
        self._exch = None
        self._ble = None
        self._leds_clear()

    # ---- watchdog ----------------------------------------------------------
    async def _watchdog(self):
        import asyncio, time
        while self._running:
            # One guard around body AND sleep; it must catch BaseException (a
            # Ctrl-C on the USB console is delivered as KeyboardInterrupt to the
            # running coroutine). Only cancellation (onDestroy) may end this loop.
            try:
                if self._app_is_open():
                    if self._has_radio:
                        self._teardown_radio()
                    await asyncio.sleep_ms(POLL_MS_IDLE)
                    continue
                # We own (or should own) the radio.
                if not self._has_radio:
                    self._take_radio()
                if self._gc is not None:
                    try:
                        now = time.ticks_ms()
                        self._gc.tick(now, self._wifi_up(), self._sound)
                    except Exception as e:
                        self._dbg("tick err %r" % (e,))
                    # Re-assert the beacon occasionally (another app may have
                    # touched the radio); a no-op while still advertising.
                    self._polls += 1
                    if self._polls >= REFRESH_POLLS:
                        self._polls = 0
                        self._reassert_beacon()
                await asyncio.sleep_ms(POLL_MS_RADIO)
            except asyncio.CancelledError:
                raise
            except BaseException:
                try:
                    await asyncio.sleep_ms(POLL_MS_RADIO)
                except asyncio.CancelledError:
                    raise
                except BaseException:
                    pass

    def _reassert_beacon(self):
        ble = self._ble
        try:
            if ble is None or not ble._active or not ble._adv:
                return
            import bluetooth
            ble._ble.gap_advertise(ADV_MS * 1000, adv_data=ble._adv,
                                   connectable=ble._connectable)
        except Exception:
            pass

    def _wifi_up(self):
        try:
            from mpos import WifiService
            return bool(WifiService.is_connected())
        except Exception:
            return False
