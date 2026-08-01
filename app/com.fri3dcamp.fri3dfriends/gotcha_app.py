# gotcha_app.py -- app-level Gotcha glue (Phase 2 Layer B).
#
# Ties the pure gotcha.py (GotchaState/GotchaSync/GameConfig) to the live
# BLEProximity scanner and drives sync, the §7 connectivity check and the
# game-block/game-context updates on the OS loop. NO lvgl: the Activity reads the
# getters and renders. TaskManager/urequests/usocket are imported lazily so this
# module imports on a host, but it is only exercised on-device (not host-tested;
# the pure half it relies on is).
#
# Proven path: the gotcha.b1 probe (probes/gotcha_b1_pkg/) drove this exact flow
# end-to-end on two real badges (enroll -> sync -> v2 beacon -> mutual target).

import time

import gotcha
import ble_proximity as bp

SYNC_S = 300                       # §5.4; jittered/overridden by the tunable
CONN_EVERY_MS = 30000              # §7: re-check reachability this often
RETRY_MS = 60000                   # back into sync soon after a failure

FULLNAME = "com.fri3dcamp.fri3dfriends"


def _app_version():
    """This app's version from its MANIFEST (D31). The fleet histogram and the
    update nudge both read app_version, so a hardcoded literal lies the moment the
    build drifts past it -- always report the real version."""
    import json as _json
    for base in ("/apps", "/builtin/apps"):
        try:
            with open(base + "/" + FULLNAME + "/MANIFEST.JSON") as f:
                return _json.load(f).get("version", "?")
        except Exception:
            pass
    return "?"

# Dutch status labels (D26). Mirrors server app.STATUS_NL; kept local so the
# chip is right with no network.
_STATUS_NL = {
    "active": "LEEFT", "protected": "beschermd", "dead": "UIT",
    "opted_out": "uitgeschreven", "dormant": "badge slaapt",
    "stale": "niet gezien", "kicked": "verwijderd", "retired": "oude badge",
}


def _host_port(url):
    """'http://192.168.1.57:8080' -> ('192.168.1.57', 8080). None if unparseable."""
    if not isinstance(url, str) or not url:
        return None
    s = url
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0]
    if ":" in s:
        host, port = s.rsplit(":", 1)
        try:
            return host, int(port)
        except ValueError:
            return host, 80
    return s, 80           # the shipped camp URLs are implicit :80/:443


def _dev_name(fallback):
    try:
        import machine
        return "Badge" + ("".join("%02x" % x for x in machine.unique_id()))[-4:]
    except Exception:
        return fallback or "Badge"


def _board():
    try:
        from mpos import board as b
        return "2024" if getattr(b, "fri3d_2024", None) else "2026"
    except Exception:
        return "2026"


class GotchaController(object):
    """Drives the badge-side game from the Activity's main loop.

    The Activity calls: configure() once from _load_config, load/start/stop at
    the lifecycle boundaries, and tick(now_ms, wifi_up, sound_on) every frame,
    then reads the getters to render. All network I/O runs on TaskManager tasks
    kicked from tick(), never on the main loop."""

    def __init__(self, ble, state_path, log=None, exchange=None):
        self.ble = ble
        self.state = gotcha.GotchaState(state_path)
        self.sync = gotcha.GotchaSync(self.state)
        self.cfg = gotcha.GameConfig()
        self.log = log or (lambda m: None)
        # Persistent, append-only duel log next to gotcha.json, so a duel walked
        # untethered (on battery, no USB) can be reviewed after re-plugging. Duels
        # are rare -> negligible flash wear. flush()+close() every line (a bare
        # os-rename-free append is fine here; we never need atomicity).
        try:
            self._logpath = state_path.rsplit("/", 1)[0] + "/duel_log.txt"
        except Exception:
            self._logpath = "duel_log.txt"
        self._exch = exchange         # ContactExchange: owns the central connect path
        # endpoints / prefs (set by configure)
        self.api_url = ""
        self.enroll_url = ""
        self.quiet = None
        self.name = ""
        self.groups = []
        self.sound_on = True
        self.auto_enroll = False       # consent (§13) drives enrollment, not auto
        self.declined = False          # consent declined this session (re-asks boot)
        # derived view state (read by the renderer)
        self.online = None             # None=unknown, True/False
        self.game_state = None         # /healthz game_state (lobby/running/...)
        self.game_live = False         # a running game exists -> consent may show
        self.enrolled = False
        self.halted = False            # MY truce/quiet
        self.tgt_halted = False        # target's truce/quiet (gflags bit3)
        self.status_nl = ""
        self.target_name = None
        self.target_prox = None
        self.radar_segs = 0
        # scheduling / guards
        self._running = False
        self._syncing = False
        self._enrolling = False
        self._next_sync_ms = 0
        self._next_conn_ms = 0
        self._last_sync_ms = None       # D5: anchor for the HUNT_SYNC_DEFER cap
        self._api_host = None
        self._game_block = None
        self._target_pid = None
        # Reveal (plan §5.7): hunter-side connect state + target-side spotted state.
        self._svc = None                # GotchaService (responder), set via set_service
        self._revealing = False         # a reveal connect is in flight (hunter side)
        self._spotted_until_ms = 0      # gold-flash deadline when WE are revealed
        self._revealed_by = None        # pid of the last hunter to reveal us
        self._reveal_msg = ""           # transient status ("onthullen...", Dutch)
        self._reveal_msg_until = 0
        self._reveal_task = None        # in-flight _do_reveal task (cancellable)
        # Duel (plan §5.3): hunter-side attack state + victim-side DuelState.
        self._attacking = False         # an attack connect is in flight (hunter side)
        self._attack_task = None        # in-flight _do_attack task (cancellable)
        self._attack_cd = {}            # victim_pid -> ticks_ms of our last attack (§5.4)
        self._duel_conn = None          # the attacker's conn_handle while we are attacked
        self._duel_attacker = None      # attacker pid while we are the victim
        self._duel = gotcha.DuelState(on_dodge=self._on_duel_dodge,
                                      on_kill=self._on_duel_kill)
        self._duel_msg = ""             # transient victim-side status (Dutch)
        self._duel_msg_until = 0
        self.state.load()
        self.enrolled = self.state.is_enrolled()

    # -- setup ---------------------------------------------------------------
    def configure(self, gotcha_cfg, name, groups):
        g = gotcha_cfg if isinstance(gotcha_cfg, dict) else {}
        self.api_url = (g.get("api") or "").strip()
        self.enroll_url = (g.get("enroll") or self.api_url).strip()
        self.quiet = g.get("quiet")
        self.name = name or ""
        self.groups = list(groups or [])
        self._api_host = _host_port(self.api_url)

    def start(self):
        self._running = True
        try:
            svc_h = dict(self._svc._h) if self._svc is not None else None
        except Exception:
            svc_h = "?"
        self._plog("---- start v%s pid=%s tgt=%s gatt=%s ----" % (
            _app_version(), self.state.d.get("pid"), self.state.target_pid(), svc_h))
        self._next_sync_ms = 0
        self._next_conn_ms = 0
        self._apply_prox_filter()
        # D22: re-advertise the v2 game block and re-arm target admission/pinning
        # right now, not only after the next sync. onResume() rebuilds the beacon
        # via begin() with no game block, and a badge booting OFFLINE with a
        # persisted target must still admit it or its radar stays dark (§10.3).
        # Clear the change-gate caches so the push is not skipped as a no-op.
        self._game_block = None
        self._target_pid = None
        self._push_game_context()

    def stop(self):
        self._running = False

    def _apply_prox_filter(self):
        self.ble.set_prox_filter(self.cfg.get("PROX_ALPHA_UP"),
                                 self.cfg.get("PROX_ALPHA_DOWN"))

    # -- main drive (every Activity tick) ------------------------------------
    def tick(self, now_ms, wifi_up, sound_on):
        self.sound_on = sound_on
        self._drain_reveals()
        self._drain_attacks()
        self._tick_duel(now_ms)
        if not self._running:
            self._refresh_view()
            return
        if wifi_up and self._api_host and time.ticks_diff(now_ms, self._next_conn_ms) >= 0:
            self._next_conn_ms = time.ticks_add(now_ms, CONN_EVERY_MS)
            self._kick(self._conn_probe())
        # Auto-enroll ONCE (first ever join). NOT on `not self.enrolled`, which is
        # also true while opted out -- that would re-enroll (GotchaState.enroll
        # resets opted_out) and silently undo an opt-out the moment after it
        # happens. Re-joining is the explicit opt-in menu action.
        if (self.auto_enroll and wifi_up and self.online
                and not self.ever_enrolled() and not self._enrolling
                and self.api_url):
            self._kick(self._do_enroll())
        if (self.enrolled and self.online and not self._syncing and self.api_url
                and time.ticks_diff(now_ms, self._next_sync_ms) >= 0
                and not self._defer_for_bar(now_ms)):
            self._kick(self._do_sync())
        self._refresh_view()

    def _bar_lit(self):
        # HUNT_SYNC_DEFER (§5.4): don't sync while the radar bar is lit.
        return self.radar_segs >= int(self.cfg.get("PING_FROM_SEG") or 3)

    def _defer_for_bar(self, now_ms):
        # HUNT_SYNC_DEFER (§5.4): hold sync while the radar bar is lit, so WiFi
        # traffic never costs a player the endgame kill. But cap that hold at
        # HUNT_SYNC_DEFER_MAX_S measured from the LAST SUCCESSFUL SYNC (the §5.4
        # anchor, D5) -- otherwise a player parked next to their target keeps the
        # bar lit forever, sync never runs, and at small scale the camp-wide
        # silence reads as a server outage and pauses dormancy for everyone.
        if not self._bar_lit():
            return False
        if self.cfg.get("HUNT_SYNC_DEFER") is False:    # admin switched deferral off
            return False
        if self._last_sync_ms is None:
            return True                                 # no sync yet to anchor from
        cap_s = int(self.cfg.get("HUNT_SYNC_DEFER_MAX_S") or 900)
        if time.ticks_diff(now_ms, self._last_sync_ms) >= cap_s * 1000:
            return False                                # cap reached: sync anyway
        return True

    def _kick(self, coro):
        try:
            from mpos import TaskManager
            TaskManager.create_task(coro)
        except Exception:
            pass

    # -- network tasks -------------------------------------------------------
    async def _conn_probe(self):
        if not self._api_host:
            self.online = False
            return
        host, port = self._api_host
        try:
            import usocket as s
            addr = s.getaddrinfo(host, port)[0][-1]
            c = s.socket()
            c.settimeout(4)
            c.connect(addr)
            c.close()
            self.online = True
            # game state (unsigned /healthz) -> drives the first-run consent gate
            try:
                import urequests
                r = urequests.get(self.api_url.rstrip("/") + "/healthz", timeout=8)
                try:
                    d = r.json() if r.status_code == 200 else None
                finally:
                    r.close()
                self.game_state = (d or {}).get("game_state")
                self.game_live = self.game_state == "running"
            except Exception:
                pass
        except Exception:
            self.online = False

    def _badge_key(self):
        try:
            ble = self.ble._ble
            if ble is not None:
                mac = ble.config("mac")          # (addr_type, bytes)
                return "".join("%02x" % x for x in mac[1])
        except Exception:
            pass
        try:
            import machine
            return "".join("%02x" % x for x in machine.unique_id())
        except Exception:
            return "badge0000"

    async def _do_enroll(self):
        if self.is_opted_out():
            return                  # never silently re-enroll an opted-out badge
        self._enrolling = True
        try:
            # D28: enroll under the player's chosen name; only auto-generate a
            # BadgeXXXX nickname when they never set one. D31: report the real
            # app version, not a hardcoded literal.
            name = (self.name or "").strip() or _dev_name(None)
            ok = await self.sync.enroll(self.enroll_url or self.api_url,
                                        self._badge_key(), name,
                                        self.groups, _app_version(), _board())
            if ok:
                self.enrolled = True
                self._next_sync_ms = 0
                self.log("gotcha enrolled pid=%s" % self.state.d.get("pid"))
        except Exception as e:
            self.log("gotcha enroll err %r" % (e,))
        finally:
            self._enrolling = False

    async def _do_sync(self):
        self._syncing = True
        try:
            payload = await self.sync.sync(self.api_url)
            if payload:
                self.cfg = gotcha.GameConfig.from_sync(payload.get("config"),
                                                        payload.get("game"))
                self._apply_prox_filter()
                self.quiet = (payload.get("me") or {}).get("quiet") or self.quiet
                self._push_game_context()
                secs = int(self.cfg.get("SYNC_S") or SYNC_S)
                # ±20% jitter (§10.3) so 700 badges don't sync on the same tick.
                try:
                    import os
                    jit = (os.urandom(1)[0] / 255.0 - 0.5) * 0.4
                except Exception:
                    jit = 0
                now = time.ticks_ms()
                self._last_sync_ms = now         # D5: anchor the deferral cap
                self._next_sync_ms = time.ticks_add(now,
                                                     int(secs * (1.0 + jit) * 1000))
            else:
                self._next_sync_ms = time.ticks_add(time.ticks_ms(), RETRY_MS)
        except Exception as e:
            self.log("gotcha sync err %r" % (e,))
            self._next_sync_ms = time.ticks_add(time.ticks_ms(), RETRY_MS)
        finally:
            self._syncing = False

    # -- radio: advertise the game block + admit/pin the target --------------
    def _push_game_context(self):
        gb = self._make_game_block()
        if gb != self._game_block:
            self._game_block = gb
            self.ble.set_game(gb)
        tp = self.state.target_pid()
        if tp != self._target_pid:
            self._target_pid = tp
            ids = {tp} if tp is not None else set()
            self.ble.set_game_context(admit_pids=ids, pin_pids=ids)
        # A live-game badge must be connectable so it can be REVEAL/ATTACK-reached
        # (plan §5.1). Off/idle stays non-connectable (no cost when no game runs).
        self.ble.set_connectable(bool(self.enrolled and self.game_live))

    def _make_game_block(self):
        if not self.state.is_enrolled():
            return None
        s = self.state.d.get("state") or {}
        # D29: reflect the real liveness in the advertised flags. D11's "peer at
        # someone's badge to see if they are safe to approach" relies on ALIVE
        # meaning alive -- broadcasting it while dead reports the opposite of the
        # truth. PROTECTED rides the same block so a fresh spawn shows as such.
        status = s.get("status") or ("active" if s.get("alive", True) else "dead")
        gf = 0
        if status != "dead":
            gf |= bp.GFLAG_ALIVE
        if status == "protected" or gotcha.protection_active(
                s.get("protected_until"), self.state.effective_now(int(time.time()))):
            gf |= bp.GFLAG_PROTECTED
        if self._duel.active():
            gf |= bp.GFLAG_UNDER_ATTACK        # §4: a hunter sees the scrum
        if int(s.get("streak") or 0) >= int(self.cfg.get("BOUNTY_STREAK")):
            gf |= bp.GFLAG_BOUNTY
        now = self.state.effective_now(int(time.time()))
        if gotcha.truce_active(now, self.cfg, self.quiet) != "none":
            gf |= bp.GFLAG_TRUCE
        return {"pid": self.state.d.get("pid"), "gflags": gf,
                "streak": int(s.get("streak") or 0)}

    def push_game_context(self):
        """Public hook for the Activity to call after begin() (re-advertise)."""
        self._push_game_context()

    # -- derived view state (read by the renderer) ---------------------------
    def _refresh_view(self):
        st = self.state.d
        s = st.get("state") or {}
        self.enrolled = self.state.is_enrolled()
        eff = self.state.effective_now(int(time.time()))
        self.halted = gotcha.truce_active(eff, self.cfg, self.quiet) != "none"
        status = s.get("status") or ("active" if s.get("alive", True) else "dead")
        self.status_nl = _STATUS_NL.get(status, status)
        tgt = st.get("target")
        self.target_name = tgt.get("name") if isinstance(tgt, dict) else None
        tp = self.state.target_pid()
        peer = self.ble.peer_by_pid(tp) if tp is not None else None
        if peer is not None:
            self.target_prox = peer.get("rssi_prox")
            self.tgt_halted = bool(peer.get("gflags", 0) & bp.GFLAG_TRUCE)
        else:
            self.target_prox = None
            self.tgt_halted = bool(isinstance(tgt, dict) and tgt.get("halted"))
        if self.halted or self.tgt_halted or peer is None or self.target_prox is None:
            self.radar_segs = 0
        else:
            f = gotcha.prox_fraction(self.target_prox, self.cfg)
            segs = int(f * 5 + 0.5)
            self.radar_segs = 5 if segs > 5 else (0 if segs < 0 else segs)

    # -- renderer getters ----------------------------------------------------
    def show_strip(self):
        """Should the nametag show the Gotcha target strip at all?"""
        return self.enrolled and self.target_name is not None

    def radar_halted(self):
        return self.halted or self.tgt_halted

    def status_chip_text(self):
        """The one-line status chip (Dutch)."""
        s = self.state.d.get("state") or {}
        streak = int(s.get("streak") or 0)
        kills = int(s.get("total") or 0)
        base = self.status_nl or "?"
        # ASCII only (D40): the built-in montserrat fonts have no U+00B7/U+2014
        # glyph, so a middle dot or em dash renders as a blank box in the
        # always-visible chip.
        return "%s  -  streak %d  -  %d kills" % (base, streak, kills)

    def target_line_text(self):
        """The target strip: name, or a why-not state (Dutch)."""
        if self.halted:
            return "WAPENSTILSTAND"
        if self.radar_halted():
            return (self.target_name or "?") + " - slaapt"
        if self.target_prox is None:
            return (self.target_name or "?") + " - zoek..."
        return self.target_name or "?"

    def no_network(self):
        return self.online is False

    # -- REVEAL (plan §5.7) -----------------------------------------------------
    def _drain_reveals(self):
        # The GotchaService queues inbound REVEAL writes from the BLE IRQ; dispatch
        # them here (on the loop thread), so the IRQ never does lvgl/event work.
        if self._svc is not None:
            try:
                self._svc.drain_reveals()
            except Exception:
                pass

    def set_service(self, svc):
        """Stash the GotchaService (responder). Its inbound writes are drained +
        dispatched from tick(); its is_busy() feeds the radio guard."""
        self._svc = svc

    def set_exchange(self, exch):
        """The ContactExchange that owns the central connect path (gatt_write)."""
        self._exch = exch

    # hunter-side (we press A to reveal someone) ----------------------------
    def revealing(self):
        """A reveal connect is in flight -> the loop must keep off the radio (§5.5)."""
        return self._revealing

    def gatt_busy(self):
        """The radio's single connection slot is taken: we are mid-reveal (hunter)
        or a central is connected to us (being revealed). The loop skips
        _update_leds in this window (lights.write starves the GATT link, §5.5)."""
        if self._revealing or self._attacking or self._duel.active():
            return True
        if self._svc is not None:
            return self._svc.is_busy()
        return False

    def _strip_action(self):
        if not self.enrolled or self.target_prox is None:
            return "none"
        now_s = self.state.effective_now(int(time.time()))
        last = self.state.d.get("last_reveal_at") or 0
        return gotcha.decide_strip_action(
            self.target_prox, last, now_s, self.cfg,
            attack_in_progress=(self._revealing or self._attacking),
            kill_enabled=True, halted=self.radar_halted())

    def strip_action(self):
        """The current escalating A-action on the hunt strip (§5.7 D29)."""
        return self._strip_action()

    def reveal_action_label(self):
        """The hunt strip's A-key label, naming the action BEFORE it is pressed
        (§5.7). Dutch, ASCII-only. None when no action is available."""
        act = self._strip_action()
        if act == "reveal":
            return "A: onthullen"
        if act == "attack":
            return "A: AANVALLEN"
        if act == "abort":
            return "A: afbreken"
        return None

    def reveal_msg_text(self, now_ms):
        """Transient hunter-side status ('onthullen...', 'onthuld', failure)."""
        if self._reveal_msg and time.ticks_diff(self._reveal_msg_until, now_ms) > 0:
            return self._reveal_msg
        return None

    def request_reveal(self):
        """The hunter pressed A on the hunt strip. If the action is 'reveal', kick
        the connect. Returns True if a reveal was started."""
        if self._revealing or not self.enrolled or self._exch is None:
            return False
        if self._strip_action() != "reveal":
            return False
        try:
            from mpos import TaskManager
            self._reveal_task = TaskManager.create_task(self._do_reveal())
        except Exception:
            pass
        return True

    def cancel_reveal(self):
        """Cancel an in-flight reveal (app pausing/stopping). _do_reveal's finally
        still runs, so BLEProximity is resumed and the radio handed back cleanly."""
        t = self._reveal_task
        self._reveal_task = None
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

    async def _do_reveal(self):
        """Connect to the target, write REVEAL, disconnect (§5.7). Clones the proven
        contact-swap connect path via ContactExchange.gatt_write, with BLEProximity
        suspended around it (single adv set + IRQ). Runs as a TaskManager task."""
        from gotcha_gatt import REVEAL_CHR
        tp = self.state.target_pid()
        addr = self.ble.addr_for_pid(tp) if tp is not None else None
        if addr is None:
            self._set_reveal_msg("doel niet in bereik", 1500)
            return
        my_pid = self.state.d.get("pid")
        group = self.groups[0] if self.groups else 0
        try:
            nonce = gotcha.new_nonce()
        except Exception:
            nonce = "n0"
        payload = gotcha.build_reveal_payload(group, my_pid, tp, nonce).encode("utf-8")
        self._revealing = True
        self._set_reveal_msg("onthullen...", 4000)
        ok = False
        try:
            try:
                self.ble.suspend()
            except Exception:
                pass
            try:
                ok = await self._exch.gatt_write(addr[0], addr[1], REVEAL_CHR,
                                                 payload, timeout_ms=4000)
            except Exception:
                ok = False
        finally:
            try:
                self.ble.resume()
            except Exception:
                pass
            self._revealing = False
            self._reveal_task = None
        now_s = self.state.effective_now(int(time.time()))
        if ok:
            self.state.d["last_reveal_at"] = now_s
            self.state.queue.add(gotcha.reveal_event(tp, rssi=self.target_prox, at=now_s))
            self.state.save()
            self._set_reveal_msg("onthuld -- zoek het gouden badge", 2500)
        else:
            self._set_reveal_msg("onthullen mislukt", 2000)

    def _set_reveal_msg(self, msg, ms):
        self._reveal_msg = msg
        self._reveal_msg_until = time.ticks_add(time.ticks_ms(), ms)

    # target-side (someone reveals us) ---------------------------------------
    def is_spotted(self, now_ms):
        """Our badge is mid gold-flash from an inbound Reveal (target side)."""
        return gotcha.spotted_active(self._spotted_until_ms, now_ms)

    def spotted_text(self):
        """The SPOTTED screen text (Dutch, ASCII). None when not spotted."""
        if self._spotted_until_ms == 0:
            return None
        return "GESIGNALEERD -- iemand heeft je gevonden"

    def apply_reveal(self, parsed):
        """on_reveal callback: an inbound REVEAL write reached us. Validates (§5.7)
        and, if ok, arms the gold flash + queues a 'revealed' event. Runs on the
        loop thread (drained from the GotchaService queue in tick)."""
        if not self.enrolled:
            return
        my_pid = self.state.d.get("pid")
        s = self.state.d.get("state") or {}
        now_s = self.state.effective_now(int(time.time()))
        truce = gotcha.truce_active(now_s, self.cfg, self.quiet)
        verdict = gotcha.validate_reveal(parsed, my_pid, s.get("alive", True),
                                         truce, bool(self.game_live))
        if verdict != "ok":
            return                   # busy/truce/dead/wrong_target/no_game -> drop
        hunter = parsed.get("h") if isinstance(parsed, dict) else None
        flash_ms = int(self.cfg.get("REVEAL_FLASH_MS") or 2500)
        self._spotted_until_ms = time.ticks_add(time.ticks_ms(), flash_ms)
        self._revealed_by = hunter
        self.state.queue.add(gotcha.revealed_event(hunter, at=now_s))
        self.state.save()

    # -- THE DUEL (plan §5.3, §5.8) --------------------------------------------
    # Hunter side: press A in kill range -> _do_attack drives the duel_session
    # central handshake. Victim side: an inbound ATTACK write starts a DuelState
    # that runs the hold timer and, on completion, discloses the soul + inherited
    # target (D10) and marks us dead.

    def attacking(self):
        """An attack connect is in flight -> the loop keeps off the radio (§5.5)."""
        return self._attacking

    def under_attack(self):
        """We are the victim of a live duel (hold running) -> the UI screams."""
        return self._duel.active()

    def duel_hold_fraction(self, now_ms):
        """0..1 progress of the current duel's hold (both attacker + victim UI)."""
        return self._duel.hold_fraction(now_ms)

    def duel_msg_text(self, now_ms):
        """Transient victim-side status ('YOU GOT AWAY!' / death), or None."""
        if self._duel_msg and time.ticks_diff(self._duel_msg_until, now_ms) > 0:
            return self._duel_msg
        return None

    def is_dead(self):
        s = self.state.d.get("state") or {}
        return not bool(s.get("alive", True))

    def respawn_left_s(self):
        """Whole seconds until respawn (optimistic; the server confirms on sync)."""
        s = self.state.d.get("state") or {}
        ra = s.get("respawn_at")
        if not ra:
            return 0
        d = int(ra) - self.state.effective_now(int(time.time()))
        return d if d > 0 else 0

    def protection_left_s(self):
        """Whole seconds of spawn/join protection left (§5.8), or 0."""
        s = self.state.d.get("state") or {}
        return gotcha.protection_left_s(s.get("protected_until"),
                                        self.state.effective_now(int(time.time())))

    def _set_duel_msg(self, msg, ms):
        self._duel_msg = msg
        self._duel_msg_until = time.ticks_add(time.ticks_ms(), ms)

    def _plog(self, msg):
        """Append a timestamped line to the persistent duel log (see __init__).
        Never raises. `msg` is a short ASCII string. Also mirrored to self.log so
        it shows in the in-memory dev log."""
        try:
            self.log(msg)
        except Exception:
            pass
        try:
            ms = time.ticks_ms()
        except Exception:
            ms = 0
        try:
            now_s = self.state.effective_now(int(time.time()))
        except Exception:
            now_s = 0
        try:
            f = open(self._logpath, "a")
            f.write("%d t=%d %s\n" % (now_s, ms, msg))
            f.flush()
            f.close()
        except Exception:
            pass

    # hunter side (we press A to attack our target) --------------------------
    def request_attack(self):
        """The hunter pressed A on the hunt strip in kill range. Kicks the duel if
        the action is 'attack' and the per-victim cooldown is clear. Returns True
        if an attack was started."""
        if self._attacking or self._revealing or not self.enrolled or self._exch is None:
            return False
        if self._strip_action() != "attack":
            return False
        tp = self.state.target_pid()
        last = self._attack_cd.get(tp)
        if not gotcha.cooldown_ready(last, time.ticks_ms(),
                                     int(self.cfg.get("ATTACK_COOLDOWN_MS"))):
            self._set_reveal_msg("nog even wachten", 1500)     # our own cooldown
            return False
        try:
            from mpos import TaskManager
            self._attack_task = TaskManager.create_task(self._do_attack())
        except Exception:
            return False
        return True

    def cancel_attack(self):
        """Cancel an in-flight attack (app pausing/stopping). _do_attack's finally
        resumes BLEProximity and hands the radio back cleanly."""
        t = self._attack_task
        self._attack_task = None
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

    async def _do_attack(self):
        """Connect to the target and run the §5.3 duel handshake as the central,
        via ContactExchange.duel_session, with BLEProximity suspended around it.
        On a kill: verify the disclosed soul, adopt the inherited target offline
        (D10), optimistically score, queue the 'kill'. Runs as a TaskManager task."""
        tp = self.state.target_pid()
        addr = self.ble.addr_for_pid(tp) if tp is not None else None
        if addr is None:
            self._set_reveal_msg("doel niet in bereik", 1500)
            return
        my_pid = self.state.d.get("pid")
        group = self.groups[0] if self.groups else 0
        try:
            nonce = gotcha.new_nonce()
        except Exception:
            nonce = "n0"
        payload = gotcha.build_attack_payload(group, my_pid, tp, gotcha.ATTACK_TARGET,
                                              nonce).encode("utf-8")
        self._plog("HUNT attack->%s prox=%s" % (tp, self.target_prox))
        now_s = self.state.effective_now(int(time.time()))
        # §5.8: sending an ATTACK ends OUR OWN protection immediately. Clear it
        # locally and queue attack_started so the server does the same on ingest.
        st = self.state.d.setdefault("state", {})
        if st.get("protected_until"):
            st["protected_until"] = None
        self.state.queue.add(gotcha.attack_started_event(tp, at=now_s))
        self.state.save()
        self._attacking = True
        self._attack_cd[tp] = time.ticks_ms()
        self._set_reveal_msg("AANVALLEN...", 12000)
        result = {"outcome": "failed"}
        try:
            try:
                self.ble.suspend()
            except Exception:
                pass
            try:
                result = await self._exch.duel_session(addr[0], addr[1], payload,
                                                        log=self._plog)
            except Exception as e:
                result = {"outcome": "failed"}
                self._plog("HUNT duel_session err %r" % (e,))
        finally:
            try:
                self.ble.resume()
            except Exception:
                pass
            self._attacking = False
            self._attack_task = None
        self._handle_duel_result(tp, result, now_s)

    def _handle_duel_result(self, victim_pid, result, now_s):
        outcome = result.get("outcome") if isinstance(result, dict) else None
        self._plog("HUNT result=%s reason=%s hold=%s dleft=%s spoils=%s" % (
            outcome, (result or {}).get("reason"), (result or {}).get("hold_ms"),
            (result or {}).get("dodges_left"),
            bool((result or {}).get("spoils"))))
        if outcome == "killed":
            spoils = result.get("spoils") or {}
            soul = spoils.get("soul")
            tgt = spoils.get("tgt")
            t = self.state.d.get("target")
            comm = t.get("commitment") if isinstance(t, dict) else None
            ok = False
            try:
                ok = bool(soul) and gotcha.verify_soul(bytes.fromhex(soul), comm)
            except Exception:
                ok = False
            if not ok:
                # The soul did not match the target's commitment -- do NOT claim a
                # kill (§3.4: no soul, no kill). The server would reject it anyway.
                self._plog("HUNT kill REJECTED bad_soul soul=%s comm=%s" % (soul, comm))
                self._set_reveal_msg("bewijs ongeldig", 2500)
                return
            s = self.state.d.setdefault("state", {})
            total, streak, best, pts = gotcha.score_preview(
                int(s.get("total") or 0), int(s.get("streak") or 0),
                int(s.get("best_streak") or 0), "target")
            s["total"], s["streak"], s["best_streak"] = total, streak, best
            s["score"] = int(s.get("score") or 0) + pts
            # D10: adopt the inherited target offline; None means the ring tail --
            # we keep hunting and the next sync assigns a fresh one.
            if isinstance(tgt, dict) and tgt.get("pid") is not None:
                self.state.d["target"] = {
                    "pid": tgt.get("pid"), "name": str(tgt.get("name") or ""),
                    "commitment": tgt.get("commitment"), "seen_ago_s": 0,
                    "halted": False}
            else:
                self.state.d["target"] = None
            self.state.queue.add(gotcha.kill_event(victim_pid, soul,
                                                   rssi=self.target_prox, at=now_s))
            self.state.save()
            self._push_game_context()          # re-pin the inherited target
            self._next_sync_ms = 0             # report the kill soon
            self._plog("HUNT KILL ok victim=%s new_tgt=%s" % (
                victim_pid, self.state.target_pid()))
            self._set_reveal_msg("GOTCHA!", 3000)
        elif outcome == "dodged":
            self.state.queue.add(gotcha.dodge_event(victim_pid=victim_pid, at=now_s))
            self.state.save()
            self._set_reveal_msg("ontsnapt!", 2500)
        elif outcome == "refused":
            self._set_reveal_msg(self._refuse_msg_nl(result.get("reason")), 2500)
        else:
            self._set_reveal_msg("aanval mislukt", 2000)

    def _refuse_msg_nl(self, reason):
        return {
            "protected": "doel beschermd",
            "busy": "doel bezig",
            "truce": "wapenstilstand",
            "dead": "doel al uit",
            "on_cooldown": "te snel achter elkaar",
            "bounty": "geen premie",
            "no_game": "geen spel",
        }.get(reason, "aanval geweigerd")

    # victim side (someone attacks us) --------------------------------------
    def _drain_attacks(self):
        if self._svc is not None:
            try:
                self._svc.drain_attacks()
            except Exception:
                pass

    def _tick_duel(self, now_ms):
        """Advance a live victim duel. link_up is 'the attacker's central is still
        connected' -- a drop before the hold elapses is the §5.3 escape."""
        if not self._duel.active():
            return
        link_up = self._svc is not None and self._svc.central_conn() is not None
        self._duel.tick(now_ms, link_up)

    def apply_attack(self, parsed, conn):
        """on_attack callback: an inbound ATTACK write reached us. Validates
        (§5.3/§5.8) and either starts the duel (notify ENGAGED) or refuses it
        (notify REFUSED with the verdict). Runs on the loop thread."""
        if not self.enrolled:
            self._refuse_attack(conn, "no_game")
            return
        s = self.state.d.get("state") or {}
        my_pid = self.state.d.get("pid")
        my_streak = int(s.get("streak") or 0)
        now_s = self.state.effective_now(int(time.time()))
        truce = gotcha.truce_active(now_s, self.cfg, self.quiet)
        attacker = parsed.get("a") if isinstance(parsed, dict) else None
        protected = gotcha.protection_active(s.get("protected_until"), now_s)
        limit = int(self.cfg.get("DODGE_LIMIT"))
        ledger = gotcha.DodgeLedger(self.state.d.setdefault("dodges", {}), limit)
        last = ledger.last_attack_s(attacker)
        cd_s = int(self.cfg.get("ATTACK_COOLDOWN_MS")) // 1000
        on_cd = last is not None and (now_s - int(last)) < cd_s
        verdict = gotcha.validate_attack(
            parsed, my_pid, my_streak, s.get("alive", True), truce,
            bool(self.game_live), self.cfg, protected=protected, on_cooldown=on_cd,
            in_duel=self._duel.active(), radio_busy=(self._revealing or self._attacking))
        if verdict != "ok":
            self._plog("VICTIM attack from=%s REFUSED verdict=%s" % (attacker, verdict))
            self._refuse_attack(conn, verdict)
            return
        decay_s = int(self.cfg.get("DODGE_DECAY_MS")) // 1000
        dodges_left = ledger.dodges_left(attacker, now_s, decay_s)
        hold_ms = (int(self.cfg.get("INSTANT_KILL_MS")) if dodges_left <= 0
                   else int(self.cfg.get("KILL_HOLD_MS")))
        ledger.note_attack(attacker, now_s)
        self._duel_conn = conn
        self._duel_attacker = attacker
        self._duel.reset()
        self._duel.begin_attack(attacker, hold_ms, dodges_left, time.ticks_ms())
        self.state.save()                      # persist the ledger stamp
        self._push_game_context()              # advertise UNDER_ATTACK (gflags)
        self._plog("VICTIM ENGAGED by=%s hold=%d dleft=%d" % (
            attacker, hold_ms, dodges_left))
        if self._svc is not None:
            self._svc.notify_duel(
                gotcha.build_duel_payload(gotcha.DUEL_ENGAGED, hold_ms=hold_ms,
                                          dodges_left=dodges_left), conn)

    def _refuse_attack(self, conn, reason):
        if self._svc is not None:
            try:
                self._svc.notify_duel(
                    gotcha.build_duel_payload(gotcha.DUEL_REFUSED, reason=reason), conn)
            except Exception:
                pass

    def _on_duel_dodge(self, duel):
        """DuelState escape callback: the attacker's link dropped before the hold
        elapsed (§5.3). Spend a dodge, tell the attacker (best-effort -- they
        already saw the drop), queue the victim-half 'dodge'."""
        now_s = self.state.effective_now(int(time.time()))
        limit = int(self.cfg.get("DODGE_LIMIT"))
        ledger = gotcha.DodgeLedger(self.state.d.setdefault("dodges", {}), limit)
        ledger.note_dodge(self._duel_attacker, now_s)
        if self._svc is not None:
            self._svc.notify_duel(gotcha.build_duel_payload(gotcha.DUEL_DODGED),
                                  self._duel_conn)
        self.state.queue.add(gotcha.dodge_event(attacker_pid=self._duel_attacker,
                                                at=now_s))
        self.state.save()
        self._push_game_context()              # clear UNDER_ATTACK
        self._plog("VICTIM DODGED (link drop) attacker=%s" % (self._duel_attacker,))
        self._set_duel_msg("ONTSNAPT!", 2500)

    def _on_duel_kill(self, duel):
        """DuelState hold-complete callback: we are killed (§5.3). Disclose the
        current soul + inherited target over SPOILS, notify KILLED, rotate to a
        fresh soul, mark dead + respawn countdown, queue 'killed_by'."""
        now_s = self.state.effective_now(int(time.time()))
        soul_hex = self.state.d.get("soul")
        target = self.state.d.get("target")
        if self._svc is not None:
            self._svc.set_spoils(gotcha.build_spoils_payload(soul_hex, target))
            self._svc.notify_duel(gotcha.build_duel_payload(gotcha.DUEL_KILLED),
                                  self._duel_conn)
        # Rotate the soul + commitment for the next life (§3.4).
        new_soul = gotcha.make_soul()
        new_comm = gotcha.commitment(new_soul)
        self.state.d["soul"] = "".join("%02x" % b for b in new_soul)
        self.state.d["commitment"] = new_comm
        s = self.state.d.setdefault("state", {})
        s["alive"] = False
        s["status"] = "dead"
        s["deaths"] = int(s.get("deaths") or 0) + 1
        s["streak"] = 0
        s["respawn_at"] = now_s + int(self.cfg.get("RESPAWN_S"))
        self.state.queue.add(gotcha.killed_by_event(self._duel_attacker, new_comm,
                                                    at=now_s))
        self.state.save()
        self._push_game_context()              # advertise dead immediately (D29)
        self._next_sync_ms = 0                 # report the death soon
        self._plog("VICTIM KILLED by=%s new_comm=%s" % (self._duel_attacker, new_comm[:12]))
        self._set_duel_msg("UITGESCHAKELD", 4000)

    # -- opt-in / opt-out (§13) ------------------------------------------------
    def ever_enrolled(self):
        """Enrolled at least once -> the menu can offer 'meedoen' again after an
        opt-out, and 'stoppen' while playing."""
        return bool(self.state.d.get("enrolled"))

    def is_opted_out(self):
        return bool(self.state.d.get("opted_out"))

    def opt_out(self):
        self.state.opt_out()
        self.state.save()
        self._push_game_context()      # drop the game block / flags immediately
        self.enrolled = False

    def opt_in(self):
        self.state.opt_in()
        self.state.save()
        self._next_sync_ms = 0         # re-join on the next sync
        self.enrolled = self.state.is_enrolled()

    # -- first-run consent (§13) ---------------------------------------------
    def consent_needed(self):
        """Show the join-acknowledgement overlay? Only before the first ever
        join, when a game is actually live, and not already declined/enrolling."""
        return (self.online and self.game_live
                and not self.ever_enrolled() and not self.declined
                and not self._enrolling)

    def request_enroll(self):
        # Consent given -> enroll now. _do_enroll no-ops if somehow opted out.
        if self.api_url and not self._enrolling:
            self._kick(self._do_enroll())

    def decline_consent(self):
        self.declined = True           # session-only: re-asks next boot until joined
