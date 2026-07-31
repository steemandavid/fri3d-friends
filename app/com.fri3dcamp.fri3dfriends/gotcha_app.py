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

    def __init__(self, ble, state_path, log=None):
        self.ble = ble
        self.state = gotcha.GotchaState(state_path)
        self.sync = gotcha.GotchaSync(self.state)
        self.cfg = gotcha.GameConfig()
        self.log = log or (lambda m: None)
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
        self._api_host = None
        self._game_block = None
        self._target_pid = None
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
        self._next_sync_ms = 0
        self._next_conn_ms = 0
        self._apply_prox_filter()

    def stop(self):
        self._running = False

    def _apply_prox_filter(self):
        self.ble.set_prox_filter(self.cfg.get("PROX_ALPHA_UP"),
                                 self.cfg.get("PROX_ALPHA_DOWN"))

    # -- main drive (every Activity tick) ------------------------------------
    def tick(self, now_ms, wifi_up, sound_on):
        self.sound_on = sound_on
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
                and not self._bar_lit()):
            self._kick(self._do_sync())
        self._refresh_view()

    def _bar_lit(self):
        # HUNT_SYNC_DEFER (§5.4): don't sync while the radar bar is lit.
        return self.radar_segs >= int(self.cfg.get("PING_FROM_SEG") or 3)

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
            ok = await self.sync.enroll(self.enroll_url or self.api_url,
                                        self._badge_key(), _dev_name(self.name),
                                        self.groups, "0.11.0", _board())
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
                self._next_sync_ms = time.ticks_add(time.ticks_ms(),
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

    def _make_game_block(self):
        if not self.state.is_enrolled():
            return None
        s = self.state.d.get("state") or {}
        gf = bp.GFLAG_ALIVE
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
        return "%s  ·  streak %d  ·  %d kills" % (base, streak, kills)

    def target_line_text(self):
        """The target strip: name, or a why-not state (Dutch)."""
        if self.halted:
            return "WAPENSTILSTAND"
        if self.radar_halted():
            return (self.target_name or "?") + " — slaapt"
        if self.target_prox is None:
            return (self.target_name or "?") + " — zoek..."
        return self.target_name or "?"

    def no_network(self):
        return self.online is False

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
