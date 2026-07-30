"""Time-derived rules: truce, quiet hours, streak decay, dormancy, staleness.

These are the rules most likely to be wrong in a way nobody notices until 03:00
on the Saturday of the camp, so they get tested against the clock rather than
against the API.
"""
import gotcha_server.clock as clock
from gotcha_server import state
from gotcha_server.config import DEFAULTS
from gotcha_server.db import Database

from conftest import CAMP_FRIDAY_10H


def _row(**kw):
    """A dict standing in for a sqlite3.Row -- state.py only ever indexes by key."""
    base = {"pid": 1001, "streak_at_last_kill": 0, "last_kill_at": None,
            "best_streak": 0, "base_status": "active", "protected_until": None,
            "last_sync_at": None, "last_seen_at": None, "enrolled_at": CAMP_FRIDAY_10H,
            "respawn_at": None, "quiet_from": None, "quiet_to": None}
    base.update(kw)
    return base


def _game(**kw):
    base = {"id": 1, "truce_from": "22:00", "truce_to": "08:00",
            "truce_active": 0, "truce_until": None, "state": "running"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# The nightly truce window
# ---------------------------------------------------------------------------

def test_nightly_truce_wraps_midnight_as_one_interval():
    """22:00-08:00 is one interval per night, not two per day. Getting this wrong
    is how you end up with a truce that lapses at midnight."""
    g = _game()
    t0 = CAMP_FRIDAY_10H                       # Friday 10:00
    ivals = state.camp_truce_intervals(g, t0, t0 + 48 * 3600)
    assert len(ivals) == 2                     # Fri night and Sat night
    for a, b in ivals:
        assert b - a == 10 * 3600
        assert clock.local_hm(a) == (22, 0)
        assert clock.local_hm(b) == (8, 0)


def test_truce_active_at_night_not_at_noon():
    g = _game()
    friday_23h = CAMP_FRIDAY_10H + 13 * 3600
    saturday_noon = CAMP_FRIDAY_10H + 26 * 3600
    assert state.camp_truce_active(g, friday_23h)
    assert not state.camp_truce_active(g, saturday_noon)
    assert state.truce_until(g, friday_23h) == CAMP_FRIDAY_10H + 22 * 3600


def test_host_truce_button_is_instant_and_bounded():
    g = _game(truce_active=1, truce_until=CAMP_FRIDAY_10H + 600)
    assert state.camp_truce_active(g, CAMP_FRIDAY_10H)
    assert not state.camp_truce_active(g, CAMP_FRIDAY_10H + 700)


# ---------------------------------------------------------------------------
# Personal quiet hours (§10.4a)
# ---------------------------------------------------------------------------

def test_quiet_defaults_to_the_camp_truce():
    """"Setting nothing changes nothing" -- the default window is the truce."""
    assert state.quiet_window(_row(), _game()) == ((22, 0), (8, 0))


def test_quiet_is_clamped_to_bounds_and_contains_the_truce():
    g = _game()
    # Legal: 20:30 - 09:00
    assert state.quiet_window(_row(quiet_from="20:30", quiet_to="09:00"), g) \
        == ((20, 30), (9, 0))
    # Too early an evening start is clamped to QUIET_EARLIEST.
    assert state.quiet_window(_row(quiet_from="17:00", quiet_to="09:00"), g)[0] == (20, 0)
    # Too late a morning end is clamped to QUIET_LATEST.
    assert state.quiet_window(_row(quiet_from="21:00", quiet_to="14:00"), g)[1] == (10, 0)
    # A window that would NOT contain the camp truce is pushed back so it does:
    # becoming attackable at 02:00 must be impossible.
    q = state.quiet_window(_row(quiet_from="23:30", quiet_to="01:00"), g)
    assert q == ((22, 0), (8, 0))


def test_in_quiet_evening_and_afternoon():
    g = _game()
    p = _row(quiet_from="20:00", quiet_to="09:00")
    assert state.in_quiet(p, g, CAMP_FRIDAY_10H + 11 * 3600)      # 21:00
    assert state.in_quiet(p, g, CAMP_FRIDAY_10H + 22 * 3600)      # 08:00 next day
    assert not state.in_quiet(p, g, CAMP_FRIDAY_10H + 5 * 3600)   # 15:00


def test_pair_halted_if_either_side_is_quiet():
    """§10.4: the halt is per-pair and evaluated locally -- your radar goes dark
    if EITHER side is in a truce or in quiet hours."""
    g = _game()
    ts = CAMP_FRIDAY_10H + 10 * 3600 + 1800                      # 20:30
    early = _row(pid=1, quiet_from="20:00", quiet_to="09:00")
    normal = _row(pid=2)
    assert state.in_quiet(early, g, ts)
    assert not state.in_quiet(normal, g, ts)
    assert state.pair_halted(normal, early, g, ts)
    assert state.pair_halted(early, normal, g, ts)
    assert not state.pair_halted(normal, _row(pid=3), g, ts)


# ---------------------------------------------------------------------------
# Streak decay (§2.2)
# ---------------------------------------------------------------------------

def test_streak_survives_the_grace_period_then_decays():
    g = _game()
    t0 = CAMP_FRIDAY_10H
    p = _row(streak_at_last_kill=5, last_kill_at=t0)
    assert state.derived_streak(p, g, DEFAULTS, t0 + 3600) == 5           # 1 h
    assert state.derived_streak(p, g, DEFAULTS, t0 + 3 * 3600) == 5       # exactly grace
    assert state.derived_streak(p, g, DEFAULTS, t0 + 5 * 3600) == 4       # +2 h
    assert state.derived_streak(p, g, DEFAULTS, t0 + 7 * 3600) == 3
    assert state.derived_streak(p, g, DEFAULTS, t0 + 30 * 3600) == 0      # floors at 0


def test_decay_excludes_the_camp_truce_but_not_personal_quiet_hours():
    """The single most abusable line in §2.2, so it gets its own test.

    A streak of 7 must survive 3 + 14 = 17 *playable* hours (§2.4), and a player
    who declares 20:00-10:00 quiet hours must NOT stop their own decay.
    """
    g = _game()
    t0 = CAMP_FRIDAY_10H                      # Friday 10:00
    normal = _row(streak_at_last_kill=7, last_kill_at=t0)
    sleeper = _row(streak_at_last_kill=7, last_kill_at=t0,
                   quiet_from="20:00", quiet_to="10:00")

    # Saturday 10:00 is 24 h later, of which 10 h were the camp truce: 14 h
    # active, 3 h of grace, 11 h of decay -> -5.
    saturday_10h = t0 + 24 * 3600
    assert state.active_seconds_since(g, t0, saturday_10h) == 14 * 3600
    assert state.derived_streak(normal, g, DEFAULTS, saturday_10h) == 2
    # The sleeper decays by exactly as much: quiet hours cost crown, not safety.
    assert state.derived_streak(sleeper, g, DEFAULTS, saturday_10h) == 2


def test_streak_of_seven_survives_seventeen_playable_hours():
    """§2.4's stated intent: "A streak of 7 survives 3 + 14 = 17 playable hours"."""
    g = _game()
    t0 = CAMP_FRIDAY_10H
    p = _row(streak_at_last_kill=7, last_kill_at=t0)
    # 17 playable hours = 12 h before the truce + 10 h truce + 5 h after.
    assert state.derived_streak(p, g, DEFAULTS, t0 + 12 * 3600 + 10 * 3600 + 4 * 3600) >= 1
    assert state.derived_streak(p, g, DEFAULTS, t0 + 12 * 3600 + 10 * 3600 + 6 * 3600) == 0


def test_bounty_follows_the_live_streak_not_the_high_water_mark():
    g = _game()
    t0 = CAMP_FRIDAY_10H
    p = _row(streak_at_last_kill=3, last_kill_at=t0, best_streak=9)
    assert state.has_bounty(p, g, DEFAULTS, t0 + 3600)
    assert not state.has_bounty(p, g, DEFAULTS, t0 + 6 * 3600)   # decayed to 2


# ---------------------------------------------------------------------------
# Dormancy (§2.4, §10.3, §10.4) and staleness (§10.1)
# ---------------------------------------------------------------------------

def _db_with_beats(minutes, start):
    d = Database(":memory:")
    for i in range(minutes):
        d.execute("INSERT INTO sync_beats(minute_ts, n) VALUES(?, ?)",
                  ((start + i * 60) // 60 * 60, 5))
    d.commit()
    return d


def test_dormancy_needs_twelve_active_hours():
    g = _game()
    t0 = CAMP_FRIDAY_10H
    d = _db_with_beats(24 * 60, t0)            # server up throughout
    p = _row(last_sync_at=t0)
    assert not state.is_dormant(p, g, d, t0 + 6 * 3600)
    assert not state.is_dormant(p, g, d, t0 + 11 * 3600)
    # 13 h after a 10:00 sync it is 23:00: one of those hours was truce, so 12
    # count -- the badge has just tipped over DORMANT_H.
    assert state.is_dormant(p, g, d, t0 + 13 * 3600)
    d.close()


def test_badge_switched_off_overnight_is_not_dormant_by_morning():
    """§10.4: "Dormancy accounting pauses during truce plus a 1 h grace, so a
    badge switched off overnight is not spliced out of the ring by morning." """
    g = _game()
    t0 = CAMP_FRIDAY_10H + 11 * 3600           # Friday 21:00, last sync
    d = _db_with_beats(20 * 60, t0)
    p = _row(last_sync_at=t0)
    saturday_9h = CAMP_FRIDAY_10H + 23 * 3600  # 12 wall hours later
    assert not state.is_dormant(p, g, d, saturday_9h)
    d.close()


def test_early_sleeper_gets_their_personal_window_excluded_too():
    """A badge switched off at 20:00 must not be spliced out by morning either
    (§10.4a's dormancy row)."""
    g = _game()
    t0 = CAMP_FRIDAY_10H + 10 * 3600           # Friday 20:00
    d = _db_with_beats(20 * 60, t0)
    early = _row(last_sync_at=t0, quiet_from="20:00", quiet_to="09:00")
    plain = _row(last_sync_at=t0)
    saturday_10h = CAMP_FRIDAY_10H + 24 * 3600
    assert not state.is_dormant(early, g, d, saturday_10h)
    # The plain player's 20:00-22:00 is NOT excused, so they accumulate more.
    assert state.dormancy_seconds(plain, g, d, saturday_10h) > \
        state.dormancy_seconds(early, g, d, saturday_10h)
    d.close()


def test_server_outage_does_not_mass_dormant_the_camp():
    """§10.3's warning, tested: with no sync_beats at all (the server was down),
    no time counts towards dormancy."""
    g = _game()
    t0 = CAMP_FRIDAY_10H
    d = Database(":memory:")                   # no beats: nobody synced, ever
    p = _row(last_sync_at=t0)
    assert state.dormancy_seconds(p, g, d, t0 + 20 * 3600) == 0
    assert not state.is_dormant(p, g, d, t0 + 20 * 3600)
    d.close()


def test_staleness_is_six_hours_unseen():
    t0 = CAMP_FRIDAY_10H
    p = _row(last_seen_at=t0)
    assert not state.is_stale(p, t0 + 5 * 3600)
    assert state.is_stale(p, t0 + 6 * 3600)


def test_status_precedence():
    g = _game()
    d = _db_with_beats(60, CAMP_FRIDAY_10H)
    t = CAMP_FRIDAY_10H + 600
    assert state.status_of(_row(last_sync_at=CAMP_FRIDAY_10H,
                                last_seen_at=CAMP_FRIDAY_10H), g, d, t) == state.ACTIVE
    assert state.status_of(_row(base_status="dead", respawn_at=t + 1800,
                                last_sync_at=CAMP_FRIDAY_10H), g, d, t) == state.DEAD
    assert state.status_of(_row(protected_until=t + 60, last_sync_at=CAMP_FRIDAY_10H,
                                last_seen_at=CAMP_FRIDAY_10H), g, d, t) == state.PROTECTED
    assert state.status_of(_row(base_status="kicked"), g, d, t) == state.KICKED
    # Unseen for 7 h but syncing fine -> stale, which still hunts.
    stale = _row(last_sync_at=t - 60, last_seen_at=t - 7 * 3600)
    assert state.status_of(stale, g, d, t) == state.STALE
    assert state.STALE in state.HUNTS
    assert state.STALE not in state.IN_RING_AS_TARGET
    d.close()
