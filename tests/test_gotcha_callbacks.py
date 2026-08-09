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
    truce_to -> _in_window False) so the victim paths are not short-circuited."""
    gc = gotcha_app.GotchaController(
        FakeBLE(), state_path="/tmp/__gc_cb_gotcha.json", log=lambda m: None,
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
