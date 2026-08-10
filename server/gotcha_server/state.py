"""Time-derived game state: truce windows, quiet hours, streak decay, status.

Everything here is a **pure function of stored timestamps and the current time**.
Nothing is scheduled, nothing mutates a counter. That is a deliberate copy of
§2.2's argument for deriving streak decay from `last_kill_at`: the backend may be
unreachable for hours (§6, §10.3), so any design where correctness depends on a
timer having fired at the right moment is wrong. Ask the question at read time
and the answer is right whether the server was up or not.

The one thing that *does* mutate is the ring, because a target pointer cannot be
derived -- `reconcile.py` acts on the derivations here.
"""

from . import clock
from .config import DEFAULTS

# Status values (§9.6 table A). `protected`, `dormant` and `stale` are derived;
# the rest are stored in players.base_status.
ACTIVE = "active"
PROTECTED = "protected"
DEAD = "dead"
OPTED_OUT = "opted_out"
DORMANT = "dormant"
STALE = "stale"
KICKED = "kicked"
RETIRED = "retired"

# Statuses that hold a ring slot as a *target* (i.e. are attackable-or-soon).
# `stale` is the asymmetric one: it hunts, it is not hunted (§9.6).
IN_RING_AS_TARGET = (ACTIVE, PROTECTED)
# Statuses that still hunt (hold a target pointer of their own).
HUNTS = (ACTIVE, PROTECTED, STALE)


# ---------------------------------------------------------------------------
# Interval algebra -- used by decay (subtract truce) and dormancy (subtract
# truce + quiet + grace + server outages).
# ---------------------------------------------------------------------------

def merge_intervals(intervals):
    """Union of [(a, b), ...], sorted, half-open, empty ones dropped."""
    out = []
    for a, b in sorted((min(x, y), max(x, y)) for x, y in intervals if x != y):
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def clip(intervals, t0, t1):
    """Clip a merged interval list to [t0, t1]."""
    out = []
    for a, b in intervals:
        a2, b2 = max(a, t0), min(b, t1)
        if b2 > a2:
            out.append((a2, b2))
    return out


def total(intervals):
    return sum(b - a for a, b in intervals)


def daily_window(from_hm, to_hm, t0, t1):
    """Every occurrence of a camp-local daily window overlapping [t0, t1].

    Handles the wrap: 22:00-08:00 is one interval per night, not two per day.
    """
    fh, fm = from_hm
    th, tm = to_hm
    start_min = fh * 60 + fm
    end_min = th * 60 + tm
    span = (end_min - start_min) % (24 * 60)
    if span == 0:
        return []                       # a zero-length or all-day window: ignore
    out = []
    # Walk from the day before t0 (a window may have opened yesterday and still
    # be running) to the day after t1.
    day = clock.day_start(t0) - 86400
    last = clock.day_start(t1) + 86400
    while day <= last:
        a = day + start_min * 60
        b = a + span * 60
        if b > t0 and a < t1:
            out.append((a, b))
        day += 86400
    return merge_intervals(out)


# ---------------------------------------------------------------------------
# Truce (D7, §10.4) and personal quiet hours (§10.4a, D25)
# ---------------------------------------------------------------------------

def camp_truce_intervals(game, t0, t1, db=None):
    """Camp-wide truce time in [t0, t1]: the nightly window plus any host-called
    truces. Host truces are read from `truce_intervals` because decay has to
    subtract them retroactively, long after the host has switched them off."""
    ivals = daily_window(clock.parse_hm(game["truce_from"], (22, 0)),
                         clock.parse_hm(game["truce_to"], (8, 0)), t0, t1)
    if db is not None:
        rows = db.all(
            "SELECT from_ts, to_ts FROM truce_intervals "
            "WHERE game_id=? AND from_ts < ? AND (to_ts IS NULL OR to_ts > ?)",
            (game["id"], t1, t0))
        for r in rows:
            ivals.append((r["from_ts"], r["to_ts"] if r["to_ts"] is not None else t1))
    return clip(merge_intervals(ivals), t0, t1)


def camp_truce_active(game, ts=None, db=None):
    """Is a camp-wide truce on right now? (nightly schedule OR host button)"""
    ts = clock.now() if ts is None else ts
    if game["truce_active"]:
        until = game["truce_until"]
        if until is None or ts < until:
            return True
    return bool(clip(camp_truce_intervals(game, ts - 1, ts + 1, db), ts, ts + 1))


def truce_until(game, ts=None, db=None):
    """When the current camp truce ends (best effort, for the badge's banner)."""
    ts = clock.now() if ts is None else ts
    if game["truce_active"] and game["truce_until"]:
        return int(game["truce_until"])
    ivals = clip(camp_truce_intervals(game, ts, ts + 86400, db), ts, ts + 86400)
    for a, b in ivals:
        if a <= ts < b:
            return int(b)
    return None


def quiet_window(player, game, config=None):
    """A player's personal quiet window as ((h, m), (h, m)), clamped to the
    §10.4a bounds. Default is exactly the camp truce, so setting nothing changes
    nothing -- and the camp truce is always contained in it.

    `config` supplies QUIET_EARLIEST/QUIET_LATEST. Passing it matters: those are
    live tunables (§5.4), and the INGEST path (events._h_heartbeat) already
    clamps with the tuned values. This read path used to fall through to
    clamp_quiet's hardcoded 20:00/10:00 defaults, so the two disagreed the moment
    a host moved the bounds -- a window stored under the tuned bounds was then
    re-clamped to the defaults on every read, silently ignoring the setting."""
    cfg = config or {}
    d_from = clock.parse_hm(game["truce_from"], (22, 0))
    d_to = clock.parse_hm(game["truce_to"], (8, 0))
    q_from = clock.parse_hm(player["quiet_from"], d_from) if player["quiet_from"] else d_from
    q_to = clock.parse_hm(player["quiet_to"], d_to) if player["quiet_to"] else d_to
    return clamp_quiet(q_from, q_to, d_from, d_to,
                       cfg.get("QUIET_EARLIEST", "20:00"),
                       cfg.get("QUIET_LATEST", "10:00"))


def clamp_quiet(q_from, q_to, d_from=(22, 0), d_to=(8, 0),
                earliest="20:00", latest="10:00"):
    """Enforce QUIET_EARLIEST/QUIET_LATEST and the containment rule (§10.4a).

    A window that would start after the camp truce begins, or end before it
    ends, is clamped back to the camp truce -- otherwise a player could declare
    23:00-01:00 and become attackable at 02:00, inside the camp truce, which the
    rest of the design assumes cannot happen.
    """
    e_h, e_m = clock.parse_hm(earliest, (20, 0))
    l_h, l_m = clock.parse_hm(latest, (10, 0))
    earliest_min = e_h * 60 + e_m
    latest_min = l_h * 60 + l_m
    d_from_min = d_from[0] * 60 + d_from[1]
    d_to_min = d_to[0] * 60 + d_to[1]

    # Evening side: no earlier than QUIET_EARLIEST, no later than the truce start.
    f = max(earliest_min, min(q_from[0] * 60 + q_from[1], d_from_min))
    # Morning side: no earlier than the truce end, no later than QUIET_LATEST.
    t = max(d_to_min, min(q_to[0] * 60 + q_to[1], latest_min))
    return (f // 60, f % 60), (t // 60, t % 60)


def in_quiet(player, game, ts=None, config=None):
    """Is this player inside their personal quiet window right now?

    Symmetric by construction (§10.4a): callers use this for both "can be
    attacked" and "may attack". An asymmetric version would be an
    invulnerability exploit and every kid would find it on Friday afternoon.
    """
    ts = clock.now() if ts is None else ts
    q_from, q_to = quiet_window(player, game, config)
    return bool(clip(daily_window(q_from, q_to, ts - 1, ts + 1), ts, ts + 1))


def quiet_intervals(player, game, t0, t1, config=None):
    q_from, q_to = quiet_window(player, game, config)
    return clip(daily_window(q_from, q_to, t0, t1), t0, t1)


def pair_halted(a, b, game, ts=None, db=None, config=None):
    """§10.4: the halt is per-pair -- radar dark, attacks refused -- if EITHER
    side is in a camp truce or in personal quiet hours."""
    ts = clock.now() if ts is None else ts
    if camp_truce_active(game, ts, db):
        return True
    return in_quiet(a, game, ts, config) or in_quiet(b, game, ts, config)


# ---------------------------------------------------------------------------
# Streak decay (§2.2) -- idempotent, derived from last_kill_at
# ---------------------------------------------------------------------------

def active_seconds_since(game, since, ts, db=None):
    """Wall seconds from `since` to `ts` minus overlapping CAMP truce intervals.

    Personal quiet hours are deliberately NOT excluded (§2.2): if they were, a
    player could declare 20:00-10:00, become both unkillable and undecaying for
    fourteen hours a day, and hold the crown by sleeping.
    """
    if since is None or ts <= since:
        return 0
    return (ts - since) - total(camp_truce_intervals(game, since, ts, db))


def derived_streak(player, game, config=None, ts=None, db=None):
    """The live streak after decay (§2.2). Never mutates anything."""
    ts = clock.now() if ts is None else ts
    cfg = config or DEFAULTS
    base = int(player["streak_at_last_kill"] or 0)
    if base <= 0 or player["last_kill_at"] is None:
        return max(0, base)
    grace = int(cfg.get("STREAK_GRACE_S", DEFAULTS["STREAK_GRACE_S"]))
    step = int(cfg.get("STREAK_DECAY_S", DEFAULTS["STREAK_DECAY_S"])) or 1
    active = active_seconds_since(game, int(player["last_kill_at"]), ts, db)
    if active <= grace:
        return base
    return max(0, base - int((active - grace) // step))


def has_bounty(player, game, config=None, ts=None, db=None):
    """Live streak >= BOUNTY_STREAK makes you fair game for everyone (rule 10)."""
    cfg = config or DEFAULTS
    if not cfg.get("bounty_enabled", True):
        return False
    return derived_streak(player, game, cfg, ts, db) >= int(
        cfg.get("BOUNTY_STREAK", DEFAULTS["BOUNTY_STREAK"]))


# ---------------------------------------------------------------------------
# Dormancy and staleness (§2.4, §10.1, §10.3)
# ---------------------------------------------------------------------------

OUTAGE_GAP_MIN = 20        # a silence this long means the server was not listening


def outage_intervals(db, t0, t1, gap_min=OUTAGE_GAP_MIN):
    """Stretches of [t0, t1] during which the server heard nothing from anyone.

    §10.3: "Dormancy must pause when global sync volume collapses, or a server
    outage would mass-dormant the entire camp and shred the ring."

    Deliberately measured as a *gap*, not as a per-minute quorum: with 700 badges
    on a 300 s jittered schedule every minute has traffic, but a quiet night or a
    small dev deployment can easily have single idle minutes without anything
    being wrong. Only a silence of `gap_min` minutes or more is evidence that the
    server, not the badge, was the thing that was absent.

    **This function is coupled to `HUNT_SYNC_DEFER_MAX_S` (§5.4):** a badge that
    defers its sync mid-chase is silent on purpose, and at this layer that is
    indistinguishable from an outage. The deferral cap must stay below `gap_min`;
    see the comment on the constant in `config.py`.

    The 60 s bucketing rounds in the safe direction for that coupling. A silence is
    measured from `bucket_of(previous_sync) + 60` to `bucket_of(next_sync)`, so the
    measured gap is always *shorter* than the real one -- never longer. The cost is
    at most 60 s of sensitivity to genuine outages, which is the right way round:
    failing to declare an outage loses a little dormancy accuracy, whereas
    declaring one that did not happen pauses dormancy for the whole camp.
    """
    rows = db.all(
        "SELECT minute_ts FROM sync_beats WHERE minute_ts >= ? AND minute_ts < ? "
        "AND n > 0 ORDER BY minute_ts", (t0 // 60 * 60 - 60, t1 + 60))
    heard = [int(r["minute_ts"]) for r in rows]
    span = gap_min * 60
    out = []
    prev = t0
    for m in heard:
        if m - prev >= span:
            out.append((prev, m))
        prev = max(prev, m + 60)
    if t1 - prev >= span:
        out.append((prev, t1))
    return clip(merge_intervals(out), t0, t1)


def dormancy_seconds(player, game, db, ts=None, config=None):
    """Seconds since this badge's last sync that legitimately count towards
    dormancy: wall time minus the camp truce, minus the player's personal quiet
    window, minus a grace period after each, minus server outages.

    A badge switched off at 20:00 must not be spliced out of the ring by morning
    (§10.4, §10.4a), and neither must the whole camp because the server was down
    (§10.3).
    """
    ts = clock.now() if ts is None else ts
    cfg = config or DEFAULTS
    since = player["last_sync_at"] or player["enrolled_at"]
    if since is None or ts <= since:
        return 0
    grace = int(cfg.get("DORMANT_GRACE_S", DEFAULTS["DORMANT_GRACE_S"]))
    excluded = camp_truce_intervals(game, since, ts, db)
    excluded += quiet_intervals(player, game, since, ts, cfg)
    excluded += outage_intervals(db, since, ts)
    # Extend each excluded window by the grace period, then merge: a badge
    # powered on at 08:30 has an hour to get a sync in before the clock restarts.
    excluded = merge_intervals([(a, b + grace) for a, b in excluded])
    return (ts - since) - total(clip(excluded, since, ts))


def is_dormant(player, game, db, ts=None, config=None):
    cfg = config or DEFAULTS
    limit = int(cfg.get("DORMANT_H", DEFAULTS["DORMANT_H"])) * 3600
    return dormancy_seconds(player, game, db, ts, cfg) >= limit


def is_stale(player, ts=None, config=None):
    """Not seen by *anyone* for TARGET_STALE_H (§10.1). Being seen means someone
    reported you in a heartbeat's `target_seen_ago_s`, revealed you, or duelled
    you -- all of which prove a badge was physically near another badge."""
    ts = clock.now() if ts is None else ts
    cfg = config or DEFAULTS
    limit = int(cfg.get("TARGET_STALE_H", DEFAULTS["TARGET_STALE_H"])) * 3600
    seen = player["last_seen_at"]
    if seen is None:
        seen = player["enrolled_at"]
    return seen is not None and (ts - seen) >= limit


def is_protected(player, ts=None):
    ts = clock.now() if ts is None else ts
    pu = player["protected_until"]
    return pu is not None and ts < pu


def status_of(player, game, db, ts=None, config=None):
    """The player's exclusive status (§9.6 table A), derived.

    Order matters: a kicked player is kicked even if their badge is dormant, and
    a dead player is dead even inside their spawn protection.
    """
    ts = clock.now() if ts is None else ts
    base = player["base_status"]
    if base in (KICKED, RETIRED, OPTED_OUT):
        return base
    if base == DEAD:
        return DEAD
    if is_dormant(player, game, db, ts, config):
        return DORMANT
    if is_protected(player, ts):
        return PROTECTED
    if is_stale(player, ts, config):
        return STALE
    return ACTIVE


def respawn_due(player, ts=None):
    ts = clock.now() if ts is None else ts
    return (player["base_status"] == DEAD
            and player["respawn_at"] is not None
            and ts >= player["respawn_at"])
