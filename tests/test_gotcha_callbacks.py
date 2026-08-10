"""Phase 4 (plan §5.6): host tests for the additive victim-side effect callbacks
on GotchaController.

beacon_service builds a headless GotchaController (no Activity UI) to answer
REVEAL/ATTACK in the background; it needs buzzer/LED cues on reveal, attack,
dodge and kill. Those fire through four optional `on_*` callbacks on the
controller, which default to None (the foreground Activity leaves them unset and
drives effects through its own renderer, so this is purely additive). These tests
prove each callback fires with the right arguments on the right victim-side path
and that the None-default path is a safe no-op.
"""
import time as _stdtime

import pytest

# gotcha_app was written to run on-device, so it calls the MicroPython `time`
# ticks_* helpers (ticks_ms/ticks_add/ticks_diff), which CPython's stdlib `time`
# lacks. The module references them as attributes on the `time` module object at
# call time, so we shim them onto the real module before the controller runs.
_T0 = getattr(_stdtime, "monotonic", _stdtime.time)()


def _ticks_ms():
    return int((_stdtime.monotonic() - _T0) * 1000)


def _ticks_add(a, b):
    return a + b


def _ticks_diff(later, earlier):
    return later - earlier


_stdtime.ticks_ms = _ticks_ms
_stdtime.ticks_add = _ticks_add
_stdtime.ticks_diff = _ticks_diff

import gotcha
import gotcha_app


class FakeBLE(object):
    """Tolerant stand-in for the BLEProximity surface the controller touches from
    the victim paths. Anything we did not name is a no-op; the callbacks under
    test never depend on radio state."""

    _ble = None

    def __getattr__(self, name):
        return lambda *a, **k: None


def _make_controller(on_engaged=None, on_killed=None, on_dodged=None, on_spotted=None):
    """An enrolled, in-game controller with the truce disabled (truce_from ==
    truce_to -> _in_window False) so the victim paths are not short-circuited.

    A FRESH state file per controller. A fixed path is persisted to and reloaded
    on the next construction, so the victim tests' killed_by events accumulated
    across runs until the 40-slot queue was full of KEEP_TYPES -- at which point
    add() correctly refuses everything else and the heartbeat tests started
    failing for a reason that had nothing to do with the heartbeat."""
    import tempfile
    path = tempfile.mkdtemp(prefix="gc_cb_") + "/gotcha.json"
    gc = gotcha_app.GotchaController(
        FakeBLE(), state_path=path, log=lambda m: None,
        on_engaged=on_engaged, on_killed=on_killed,
        on_dodged=on_dodged, on_spotted=on_spotted)
    # Disable the camp truce deterministically (quiet stays None -> no personal).
    gc.cfg.d["truce_from"] = "00:00"
    gc.cfg.d["truce_to"] = "00:00"
    gc.enrolled = True                      # _in_game() == enrolled
    gc.state.d["pid"] = "ME"
    gc.state.d["soul"] = "deadbeef"
    gc.state.d["commitment"] = "cafef00d"
    gc.state.d["target"] = {"pid": "NEXT"}
    gc.state.d["state"] = {"alive": True, "streak": 0}
    gc.state.d["dodges"] = {}
    return gc


def test_none_callbacks_are_noop_on_all_paths():
    """The Activity default (all callbacks None) never raises on any victim path."""
    gc = _make_controller()                 # all None
    gc.apply_reveal({"t": "ME", "h": "H"})
    gc.apply_attack({"v": "ME", "a": "A"}, conn=0)
    gc._on_duel_dodge(gc._duel)
    gc._on_duel_kill(gc._duel)
    # No exception -> pass.


def test_on_spotted_fires_on_reveal():
    seen = []
    gc = _make_controller(on_spotted=lambda h: seen.append(h))
    gc.apply_reveal({"t": "ME", "h": "HUNTER42"})
    assert seen == ["HUNTER42"]


def test_on_spotted_not_fired_when_refused():
    """A wrong-target reveal is dropped before the callback fires."""
    seen = []
    gc = _make_controller(on_spotted=lambda h: seen.append(h))
    gc.apply_reveal({"t": "NOT_ME", "h": "H"})   # wrong_target -> 'no_game' path? no: t!=pid
    assert seen == []                             # verdict != 'ok' -> no callback


def test_on_engaged_fires_on_attack():
    seen = []
    gc = _make_controller(on_engaged=lambda a, hold: seen.append((a, hold)))
    gc.apply_attack({"v": "ME", "a": "ATK7"}, conn=1)
    assert len(seen) == 1
    attacker, hold = seen[0]
    assert attacker == "ATK7"
    assert hold > 0                              # a real hold window (KILL_HOLD_MS)


def test_on_engaged_not_fired_on_refused_attack():
    seen = []
    gc = _make_controller(on_engaged=lambda a, hold: seen.append((a, hold)))
    gc.apply_attack({"v": "NOT_ME", "a": "A"}, conn=1)   # wrong_target -> refused
    assert seen == []


def test_on_dodged_fires_on_escape():
    seen = []
    gc = _make_controller(on_dodged=lambda a: seen.append(a))
    gc._duel_attacker = "ATK7"
    gc._duel_conn = 1
    gc._on_duel_dodge(gc._duel)
    assert seen == ["ATK7"]


def test_on_killed_fires_on_death():
    seen = []
    gc = _make_controller(on_killed=lambda a: seen.append(a))
    gc._duel_attacker = "ATK7"
    gc._duel_conn = 1
    gc._on_duel_kill(gc._duel)
    assert seen == ["ATK7"]
    # Death also rotated the soul/commitment and marked us dead.
    assert gc.state.d["soul"] != "deadbeef"
    assert (gc.state.d.get("state") or {}).get("alive") is False


def test_full_engage_then_escape_drives_on_dodged():
    """apply_attack starts a live duel; a link-drop tick resolves it to a dodge,
    which fires on_dodged -- the path beacon_service's victim tick will run."""
    seen = []
    gc = _make_controller(on_engaged=lambda a, h: seen.append(("eng", a)),
                          on_dodged=lambda a: seen.append(("dodge", a)))
    gc.apply_attack({"v": "ME", "a": "ATK7"}, conn=1)
    assert ("eng", "ATK7") in seen
    # Advance the hold with the link DOWN -> escape -> _on_duel_dodge -> on_dodged.
    import time as _t
    start = _t.ticks_ms()
    for _ in range(200):
        gc._tick_duel(_t.ticks_ms())
        if not gc._duel.active():
            break
        _t.sleep(0.01)
    assert ("dodge", "ATK7") in seen


def test_callback_exception_is_swallowed():
    """A misbehaving callback must not abort the duel/reveal (best-effort)."""
    def boom(*a, **k):
        raise RuntimeError("boom")
    gc = _make_controller(on_spotted=boom, on_engaged=boom,
                          on_dodged=boom, on_killed=boom)
    gc.apply_reveal({"t": "ME", "h": "H"})          # must not raise
    gc.apply_attack({"v": "ME", "a": "A"}, conn=0)  # must not raise
    gc._duel_attacker = "A"
    gc._duel_conn = 0
    gc._on_duel_dodge(gc._duel)
    gc._on_duel_kill(gc._duel)


# ---------------------------------------------------------------------------
# §9.3 / §8.10.3: _do_sync queues a heartbeat then flushes before the GET sync.
# The badge historically queued kills/reveals/dodges but never flushed them, and
# never sent a heartbeat -- so kills never reached the server. These prove the
# wiring (heartbeat queued in the §9.3 order, flush called, sync still called)
# without touching the network: a fake sync client records every call.
# ---------------------------------------------------------------------------

class _FakeSync(object):
    def __init__(self):
        self.flushed = 0
        self.synced = 0
        self.order = []

    async def flush_events(self, base, limit=200):
        self.flushed += 1
        self.order.append("flush")
        return {"accepted": []}

    async def sync(self, base):
        self.synced += 1
        self.order.append("sync")
        return None                 # a failed/empty sync still leaves hb queued+flushed


def _enrolled_controller():
    gc = _make_controller()
    gc.api_url = "http://x"
    gc.state.d["enrolled"] = True
    gc.state.d["player_key"] = "k" * 64
    gc.sync = _FakeSync()
    return gc


def test_do_sync_queues_heartbeat_then_flushes_then_syncs():
    import asyncio
    gc = _enrolled_controller()
    asyncio.run(gc._do_sync())
    # Exactly one heartbeat queued, flush called once, sync called once.
    hbs = [e for e in gc.state.queue.peek_batch(200)
           if e.get("type") == "heartbeat"]
    assert len(hbs) == 1
    assert gc.sync.flushed == 1
    assert gc.sync.synced == 1
    assert gc.sync.order == ["flush", "sync"]          # §9.3 order preserved


def test_do_sync_dedups_prior_unsent_heartbeat():
    # Two back-to-back syncs must not leave two heartbeats in the queue -- only
    # the latest truth matters, and a stale one would upload twice.
    import asyncio
    gc = _enrolled_controller()
    asyncio.run(gc._do_sync())
    asyncio.run(gc._do_sync())
    hbs = [e for e in gc.state.queue.peek_batch(200)
           if e.get("type") == "heartbeat"]
    assert len(hbs) == 1


def test_do_sync_no_heartbeat_when_not_enrolled():
    import asyncio
    gc = _enrolled_controller()
    gc.state.d["enrolled"] = False              # never-enrolled / opted-out
    asyncio.run(gc._do_sync())
    hbs = [e for e in gc.state.queue.peek_batch(200)
           if e.get("type") == "heartbeat"]
    assert hbs == []
    assert gc.sync.flushed == 0                  # nothing to flush pre-enrollment


def test_do_sync_flush_failure_does_not_block_sync():
    # WiFi is down ~98% of the time; a flush error must never swallow the sync.
    import asyncio
    gc = _enrolled_controller()

    async def boom(base, limit=200):
        raise OSError("down")
    gc.sync.flush_events = boom
    asyncio.run(gc._do_sync())                   # must not raise
    assert gc.sync.synced == 1
    hbs = [e for e in gc.state.queue.peek_batch(200)
           if e.get("type") == "heartbeat"]
    assert len(hbs) == 1                          # heartbeat still queued for next time


# ---------------------------------------------------------------------------
# §9.3 heartbeat CONTENT: the signals the server's dormancy/anti-cheat logic
# reads. Shape is covered in test_gotcha.py; these pin what _queue_heartbeat
# actually puts in them, which is where the clock-domain bug lived.
# ---------------------------------------------------------------------------

class _PeerBLE(FakeBLE):
    """A FakeBLE that can hold one target peer with a ticks_ms last_seen."""

    def __init__(self, peer=None, count=0):
        self._peer = peer
        self._count = count

    def peer_by_pid(self, pid):
        return self._peer

    def peer_count(self):
        return self._count


def _hb_of(gc):
    hbs = [e for e in gc.state.queue.peek_batch(200)
           if e.get("type") == "heartbeat"]
    assert len(hbs) == 1
    return hbs[0]


def test_heartbeat_target_seen_ago_uses_the_ticks_clock():
    # last_seen_ms is a ticks_ms() reading (monotonic uptime), NOT wall clock.
    # Differencing it against time.time()*1000 produced ~8e8 seconds, which the
    # server clamped to 48 h and then dropped, silently killing the §10.1
    # sighting channel exactly when the target WAS in range.
    gc = _enrolled_controller()
    gc.ble = _PeerBLE(peer={"last_seen_ms": _stdtime.ticks_ms() - 12000})
    gc._queue_heartbeat()
    assert _hb_of(gc)["target_seen_ago_s"] in (11, 12, 13)


def test_heartbeat_target_seen_ago_is_zero_when_target_is_right_here():
    gc = _enrolled_controller()
    gc.ble = _PeerBLE(peer={"last_seen_ms": _stdtime.ticks_ms()})
    gc._queue_heartbeat()
    assert _hb_of(gc)["target_seen_ago_s"] == 0


def test_heartbeat_omits_target_seen_ago_with_no_target_in_range():
    gc = _enrolled_controller()
    gc.ble = _PeerBLE(peer=None)
    gc._queue_heartbeat()
    assert "target_seen_ago_s" not in _hb_of(gc)


def test_heartbeat_carries_the_personal_quiet_window():
    # §10.4a: the heartbeat is the ONLY channel that gets the badge-owned quiet
    # window to the server, which needs it for the ingest re-check and the
    # dormancy pause.
    gc = _enrolled_controller()
    gc.configure({"quiet": {"from": "20:00", "to": "08:00"}}, "Otter", ["G"])
    gc._queue_heartbeat()
    assert _hb_of(gc)["quiet"] == {"from": "20:00", "to": "08:00"}


def test_configure_clamps_a_hand_edited_quiet_window():
    """Prior review D-50: clamp_quiet ran only on the BLE-setup path, so a
    hand-edited config.json reached truce_active raw. An unclamped
    {"from":"12:00","to":"13:00"} is a midday self-halt -- truce_active reports a
    truce all afternoon, so the player can neither be attacked nor attack."""
    gc = _enrolled_controller()
    gc.configure({"quiet": {"from": "12:00", "to": "13:00"}}, "Otter", ["G"])
    q = gc.quiet
    # Snapped into the legal night band (QUIET_EARLIEST..QUIET_LATEST), or
    # rejected outright -- either way, never left as a midday window.
    assert q is None or (q["from"], q["to"]) != ("12:00", "13:00")
    if q is not None:
        assert q["from"] >= "20:00" or q["from"] <= "10:00"


def test_configure_keeps_a_legal_quiet_window():
    gc = _enrolled_controller()
    gc.configure({"quiet": {"from": "20:00", "to": "08:00"}}, "Otter", ["G"])
    assert gc.quiet == {"from": "20:00", "to": "08:00"}


def test_heartbeat_omits_quiet_when_none_is_set():
    gc = _enrolled_controller()
    gc.configure({}, "Otter", ["G"])
    gc._queue_heartbeat()
    assert "quiet" not in _hb_of(gc)


def test_sync_does_not_clobber_a_locally_configured_quiet_window():
    # The server's me.quiet defaults to the camp truce, so taking it
    # unconditionally reverted a parent's 20:00 window to 22:00 on first sync.
    import asyncio
    gc = _enrolled_controller()
    gc.configure({"quiet": {"from": "20:00", "to": "08:00"}}, "Otter", ["G"])

    async def sync(base):
        return {"me": {"quiet": {"from": "22:00", "to": "08:00"}}}
    gc.sync.sync = sync
    asyncio.run(gc._do_sync())
    assert gc.quiet == {"from": "20:00", "to": "08:00"}


def test_sync_adopts_the_server_quiet_window_when_none_is_configured():
    import asyncio
    gc = _enrolled_controller()
    gc.configure({}, "Otter", ["G"])

    async def sync(base):
        return {"me": {"quiet": {"from": "22:00", "to": "08:00"}}}
    gc.sync.sync = sync
    asyncio.run(gc._do_sync())
    assert gc.quiet == {"from": "22:00", "to": "08:00"}


def test_heartbeat_never_uploads_the_servers_echoed_quiet_default():
    """Regression: a badge with NO personal window must not send one back.

    _do_sync adopts the server's `me.quiet` into self.quiet so truce_active has
    something to evaluate, but that value is the server's DEFAULT (the camp
    truce) for a player who set nothing. Uploading it stored a phantom personal
    window the player never chose -- and since §2.2 pauses streak decay only for
    the CAMP truce, that phantom silently bleeds crown overnight."""
    import asyncio
    gc = _enrolled_controller()
    gc.configure({}, "Otter", ["G"])                 # no local quiet
    assert gc._quiet_cfg is None

    async def sync(base):
        return {"me": {"quiet": {"from": "22:00", "to": "08:00"}}}
    gc.sync.sync = sync
    asyncio.run(gc._do_sync())
    assert gc.quiet == {"from": "22:00", "to": "08:00"}   # adopted for local use
    assert "quiet" not in _hb_of(gc)                      # ...but NOT uploaded


def test_heartbeat_reports_death_honestly():
    gc = _enrolled_controller()
    gc.state.d["state"] = {"alive": False}
    gc._queue_heartbeat()
    assert _hb_of(gc)["alive"] is False


def test_heartbeat_peers_seen_comes_from_the_raw_peer_count():
    # peer_count() counts everyone in range; current_peers() is friends-only and
    # would report 0 for a badge standing in a crowd of strangers.
    gc = _enrolled_controller()
    gc.ble = _PeerBLE(count=17)
    gc._hb_peers = gc.ble.peer_count()      # what both tick() callers now pass
    gc._queue_heartbeat()
    assert _hb_of(gc)["peers_seen"] == 17


# ---------------------------------------------------------------------------
# §8.10.3: the fleet banner -- a NEW host broadcast or version nudge surfaced
# once per change via take_fleet_banner() (the renderer polls it when no
# duel/arrival banner owns the strip).
# ---------------------------------------------------------------------------

@pytest.fixture
def nudge_controller(monkeypatch):
    """Factory for a controller with _app_version() pinned.

    _app_version() reads the on-device MANIFEST, which the host has no /apps copy
    of, so it has to be faked. Via monkeypatch, NOT a bare module assignment: an
    unrestored patch of a module global leaks into every later test in the
    session and makes the suite order-dependent."""
    def make(my_version):
        gc = _make_controller()
        gc.state.d["enrolled"] = True
        gc.sync = _FakeSync()
        monkeypatch.setattr(gotcha_app, "_app_version", lambda: my_version)
        return gc
    return make


UPDATE_CLEAN = "UPDATE NODIG -- alles opgeslagen, update in de AppStore"
UPDATE_PENDING = "UPDATE NODIG -- even synchroniseren voor je update..."
SOFT_NUDGE = "Nieuwe versie beschikbaar -- update in de AppStore"


def test_compute_nudge_below_min_is_prominent(nudge_controller):
    gc = nudge_controller("0.10.0")
    assert gc._compute_nudge({"min_version": "0.11.0",
                              "latest_version": "0.11.5"}) == UPDATE_CLEAN
    assert gc.below_min is True


def test_compute_nudge_below_min_with_queued_events_says_sync_first(nudge_controller):
    # §8.10.4 step 3: never send a player to the AppStore holding unsent kills.
    gc = nudge_controller("0.10.0")
    gc.state.queue.add(gotcha.reveal_event(1004))
    assert gc._compute_nudge({"min_version": "0.11.0"}) == UPDATE_PENDING


def test_compute_nudge_below_latest_is_soft(nudge_controller):
    gc = nudge_controller("0.11.3")
    assert gc._compute_nudge({"min_version": "0.11.0",
                              "latest_version": "0.11.5"}) == SOFT_NUDGE
    assert gc.below_min is False


def test_compute_nudge_up_to_date_is_none(nudge_controller):
    gc = nudge_controller("0.11.5")
    assert gc._compute_nudge({"min_version": "0.11.0",
                              "latest_version": "0.11.5"}) is None
    assert gc.below_min is False


def test_compute_nudge_no_server_floor_is_none(nudge_controller):
    # An absent server constraint (older backend) must never nag.
    gc = nudge_controller("0.11.20")
    assert gc._compute_nudge(None) is None
    assert gc._compute_nudge({}) is None
    assert gc.below_min is False


def test_compute_nudge_unreadable_own_version_is_none(nudge_controller):
    # _app_version() returns '?' when the MANIFEST can't be read -> never nag,
    # and never gate hunting off a version we could not read.
    gc = nudge_controller("?")
    assert gc._compute_nudge({"min_version": "0.11.0",
                              "latest_version": "0.11.5"}) is None
    assert gc.below_min is False


def test_compute_nudge_short_server_floor_does_not_false_trigger(nudge_controller):
    # A host typing a two-segment floor ('0.11') must not put every 0.11.x badge
    # below min: a bare tuple compare would, since (0, 11) < (0, 11, 0).
    gc = nudge_controller("0.11.0")
    assert gc._compute_nudge({"min_version": "0.11"}) is None
    assert gc.below_min is False
    # Same on the soft side: 0.12.0 is not behind a 'latest' of 0.12.
    gc = nudge_controller("0.12.0")
    assert gc._compute_nudge({"min_version": "0.11", "latest_version": "0.12"}) is None


def test_take_fleet_banner_surfaces_new_broadcast_once(nudge_controller):
    gc = nudge_controller("0.11.20")
    gc.broadcast = "Ceremonie om 17:00 aan de bar"
    assert gc.take_fleet_banner() == "Ceremonie om 17:00 aan de bar"
    assert gc.take_fleet_banner() is None        # already shown; don't re-spam
    gc.broadcast = "Spel gepauzeerd"             # a NEW value re-arms it
    assert gc.take_fleet_banner() == "Spel gepauzeerd"
    assert gc.take_fleet_banner() is None


def test_take_fleet_banner_reshows_after_the_host_clears_it(nudge_controller):
    # Host sends X, clears it ("Wissen"), then sends X again an hour later. The
    # latch must have been re-armed by the clear, or the second send is swallowed.
    gc = nudge_controller("0.11.20")
    gc.broadcast = "Spel gepauzeerd"
    assert gc.take_fleet_banner() == "Spel gepauzeerd"
    gc.broadcast = None                          # cleared server-side
    assert gc.take_fleet_banner() is None
    gc.broadcast = "Spel gepauzeerd"             # same text again
    assert gc.take_fleet_banner() == "Spel gepauzeerd"


def test_take_fleet_banner_broadcast_capped_at_120(nudge_controller):
    gc = nudge_controller("0.11.20")
    gc.broadcast = "x" * 500
    assert len(gc.take_fleet_banner()) == 120


def test_take_fleet_banner_nudge_after_broadcast(nudge_controller):
    # A broadcast wins first; once shown, a pending nudge surfaces on the next poll.
    gc = nudge_controller("0.11.3")
    gc.broadcast = "hallo"
    gc.nudge_text = SOFT_NUDGE
    assert gc.take_fleet_banner() == "hallo"
    assert gc.take_fleet_banner() == SOFT_NUDGE
    assert gc.take_fleet_banner() is None


def test_take_fleet_banner_none_when_nothing_new(nudge_controller):
    gc = nudge_controller("0.11.20")
    assert gc.take_fleet_banner() is None
    gc.broadcast = ""                            # empty broadcast is not shown
    assert gc.take_fleet_banner() is None


# ---------------------------------------------------------------------------
# §9.1/D31: the player-card QR the badge shows a phone.
# ---------------------------------------------------------------------------

def test_card_base_prefers_https_endpoints_in_order():
    # A phone browser opens this URL, so it wants the https endpoint, not §6.3's
    # plain-http signed-request one. Explicit `card` wins, then `enroll`, then api.
    gc = _make_controller()
    gc.configure({"api": "http://a", "enroll": "https://e", "card": "https://c"},
                 "Otter", [])
    assert gc.card_base == "https://c"
    gc.configure({"api": "http://a", "enroll": "https://e"}, "Otter", [])
    assert gc.card_base == "https://e"
    gc.configure({"api": "http://a"}, "Otter", [])
    assert gc.card_base == "http://a"
    gc.configure({}, "Otter", [])
    assert gc.card_base == ""


def test_card_url_uses_live_pid_and_token():
    gc = _make_controller()
    gc.configure({"enroll": "https://camp.example"}, "Otter", [])
    gc.state.d["pid"] = 1004
    gc.state.d["card_token"] = "1786400000.deadbeef"
    assert gc.card_url() == \
        "https://camp.example/gotcha/?badge=1004&t=1786400000.deadbeef"
    # Never synced: no token yet, but the public card still resolves.
    gc.state.d["card_token"] = None
    assert gc.card_url() == "https://camp.example/gotcha/?badge=1004"


def test_card_url_is_none_before_enrollment_or_without_an_endpoint():
    gc = _make_controller()
    gc.configure({"enroll": "https://camp.example"}, "Otter", [])
    gc.state.d["pid"] = None
    assert gc.card_url() is None            # never enrolled -> no card
    gc.configure({}, "Otter", [])
    gc.state.d["pid"] = 1004
    assert gc.card_url() is None            # no endpoint -> nothing to point at


def test_refresh_card_token_asks_for_a_sync_without_forcing_one():
    # Opening the card nudges the scheduler; it must NOT bypass the online /
    # _defer_for_bar gates (no radio grab mid-chase, nothing at all offline).
    gc = _make_controller()
    gc.enrolled = True
    gc._next_sync_ms = _stdtime.ticks_ms() + 999999
    gc.refresh_card_token()
    assert gc._next_sync_ms == 0
    # A sync already in flight is left alone.
    gc._next_sync_ms = 12345
    gc._syncing = True
    gc.refresh_card_token()
    assert gc._next_sync_ms == 12345


# ---------------------------------------------------------------------------
# §8.10.3: below min_app_version the badge stops HUNTING but stays killable.
# ---------------------------------------------------------------------------

def test_below_min_blocks_hunting_but_not_the_victim_responder(nudge_controller):
    gc = nudge_controller("0.10.0")
    gc._exch = object()                     # request_* needs an exchange present
    gc._compute_nudge({"min_version": "0.11.0"})
    assert gc.below_min is True
    assert gc.request_attack() is False
    assert gc.request_reveal() is False
    # ...and the victim side keeps working: an inbound REVEAL still lands, so an
    # out-of-date badge cannot make itself invulnerable by not updating (D3).
    seen = []
    gc._on_spotted = lambda h: seen.append(h)
    gc.apply_reveal({"t": "ME", "h": "HUNTER42"})
    assert seen == ["HUNTER42"]
    assert gc.is_spotted(_stdtime.ticks_ms()) is True


def test_up_to_date_badge_is_not_hunting_blocked(nudge_controller):
    gc = nudge_controller("0.11.5")
    gc._compute_nudge({"min_version": "0.11.0", "latest_version": "0.11.5"})
    assert gc.below_min is False
    assert gc._hunting_blocked() is False
