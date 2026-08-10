"""The service layer: everything that touches more than one table.

This is where the ring, the derived state and the score meet the database. The
routes are thin wrappers over the functions here, so the game logic is testable
without HTTP and the HTTP layer has no rules in it.

`reconcile()` is the heart of it. Because nothing is scheduled (see state.py),
someone has to *act* on the derivations -- respawn the dead whose timer has
passed, splice out the dormant and the stale, give a target to anyone who lacks
one. `reconcile()` does exactly that and is called at the top of every sync and
every event batch, so the game repairs itself continuously as a side effect of
badges talking to it, and needs no cron, no worker and no queue.
"""

import json
import random

from . import clock, crypto, ring, scoring, state
from .config import DEFAULTS, tunables_for_badge
from .groups import clean_groups


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------

def current_game(db):
    """The one camp-wide game (D12). `game_id` stays in the schema so a second
    game needs no migration, but nothing here assumes more than one."""
    return db.one("SELECT * FROM games ORDER BY id DESC LIMIT 1")


def ensure_game(db, name="Fri3d Gotcha 2026"):
    g = current_game(db)
    if g is not None:
        return g
    db.execute(
        "INSERT INTO games(name, state, created_at, config_json) VALUES(?,?,?,?)",
        (name, "lobby", clock.now(), "{}"))
    db.commit()
    return current_game(db)


def create_game(db, name, start_at=None, end_at=None, tunables=None):
    db.execute(
        "INSERT INTO games(name, state, start_at, end_at, created_at, config_json) "
        "VALUES(?,?,?,?,?,?)",
        (name, "lobby", start_at, end_at, clock.now(),
         json.dumps(tunables or {}, sort_keys=True)))
    db.commit()
    return current_game(db)


def config_for(game):
    """Effective config: defaults with the game's admin overrides on top."""
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(game["config_json"] or "{}"))
    except Exception:
        pass
    return cfg


def _coerce_tunable(key, value):
    """Coerce an incoming admin tunable to the type of its default (D10).

    A raw, unchecked value reaches the hot path: `auth.verify_request` does
    `int(cfg["SIG_WINDOW_S"])` on *every* badge request, so a single
    `{"SIG_WINDOW_S": "ten"}` from a curl one-liner is an unsigned, camp-wide
    HTTP 500 that badges silently discard. Reject anything that will not coerce
    rather than store it and brick the camp. Returns (ok, coerced_value).
    """
    default = DEFAULTS[key]
    try:
        if isinstance(default, bool):
            if isinstance(value, bool):
                return True, value
            if isinstance(value, (int, float)):
                return True, bool(value)
            if isinstance(value, str):
                return True, value.strip().lower() in ("1", "true", "yes", "on")
            return False, None
        if isinstance(default, int):          # bool already handled above
            return True, int(value)
        if isinstance(default, float):
            return True, float(value)
        if isinstance(default, str):
            return True, str(value)
    except (TypeError, ValueError):
        return False, None
    return True, value


def set_tunables(db, game, updates):
    """Merge admin tunable edits, keeping unknown keys out of the config blob and
    coercing every value to its default's type (D10)."""
    cfg = {}
    try:
        cfg = json.loads(game["config_json"] or "{}")
    except Exception:
        cfg = {}
    known = set(DEFAULTS)
    applied, rejected = {}, []
    for k, v in (updates or {}).items():
        if k not in known:
            rejected.append(k)
            continue
        ok, coerced = _coerce_tunable(k, v)
        if not ok:
            rejected.append(k)
            continue
        cfg[k] = coerced
        applied[k] = coerced
    db.execute("UPDATE games SET config_json=? WHERE id=?",
               (json.dumps(cfg, sort_keys=True), game["id"]))
    db.commit()
    return applied, rejected


# ---------------------------------------------------------------------------
# Players, groups, ring views
# ---------------------------------------------------------------------------

def player_by_pid(db, pid):
    return db.one("SELECT * FROM players WHERE pid=?", (pid,))


def player_by_badge_key(db, badge_key):
    row = db.one(
        "SELECT p.* FROM badge_keys b JOIN players p ON p.pid=b.pid "
        "WHERE b.badge_key=? AND b.active=1", (badge_key,))
    return row


def badge_key_retired(db, badge_key):
    row = db.one("SELECT 1 FROM badge_keys WHERE badge_key=? AND active=0",
                 (badge_key,))
    return row is not None


def groups_by_pid(db, game_id):
    rows = db.all(
        "SELECT pg.pid AS pid, pg.gid AS gid FROM player_groups pg "
        "JOIN players p ON p.pid=pg.pid WHERE p.game_id=?", (game_id,))
    out = {}
    for r in rows:
        out.setdefault(int(r["pid"]), set()).add(int(r["gid"]))
    return out


def set_groups(db, pid, groups):
    """Replace a player's group roster (uploaded at enrollment and on change)."""
    cleaned = clean_groups(groups)
    db.execute("DELETE FROM player_groups WHERE pid=?", (pid,))
    db.executemany("INSERT OR IGNORE INTO player_groups(pid, gid, name) VALUES(?,?,?)",
                   [(pid, gid, name) for name, gid in cleaned])
    return cleaned


def start_life(db, pid, life_id, commitment, ts):
    """Open a life with its soul commitment (§3.4). Idempotent.

    The commitment is filled only when the life has none yet (C2): a life's soul
    is binding once set, so a rotation cannot overwrite the proof already held by
    an assassin. Opening a fresh life is an INSERT and unaffected; the post-respawn
    case, where the life was opened with a NULL commitment, is still served.
    """
    db.execute(
        "INSERT INTO lives(pid, life_id, commitment, started_at) VALUES(?,?,?,?) "
        "ON CONFLICT(pid, life_id) DO UPDATE SET commitment=excluded.commitment "
        "WHERE lives.commitment IS NULL",
        (pid, life_id, commitment, ts))


def life_by_commitment(db, pid, commitment_hex):
    """Which of this player's lives does a disclosed soul belong to?"""
    return db.one("SELECT * FROM lives WHERE pid=? AND commitment=?",
                  (pid, (commitment_hex or "").lower()))


def current_life(db, player):
    return db.one("SELECT * FROM lives WHERE pid=? AND life_id=?",
                  (int(player["pid"]), int(player["life_id"])))


def targets_map(db, game_id):
    rows = db.all("SELECT pid, target_pid FROM players WHERE game_id=?", (game_id,))
    return {int(r["pid"]): (int(r["target_pid"]) if r["target_pid"] is not None else None)
            for r in rows}


def huntable_set(db, game, config=None, ts=None):
    """The pids that may be someone's target right now (§9.6): `active` and
    `protected`. Protected players stay in the ring -- protection makes them
    un-attackable for 90 s, it does not remove them from the game."""
    cfg = config or config_for(game)
    ts = clock.now() if ts is None else ts
    out = set()
    for r in db.all("SELECT * FROM players WHERE game_id=? AND base_status='active'",
                    (game["id"],)):
        if state.status_of(r, game, db, ts, cfg) in state.IN_RING_AS_TARGET:
            out.add(int(r["pid"]))
    return out


def apply_target_changes(db, changes):
    for pid, target in changes.items():
        db.execute("UPDATE players SET target_pid=? WHERE pid=?", (target, pid))


def hunters_of(db, pid):
    return [int(r["pid"]) for r in
            db.all("SELECT pid FROM players WHERE target_pid=?", (pid,))]


# ---------------------------------------------------------------------------
# Reconciliation -- act on the derived state
# ---------------------------------------------------------------------------

def reconcile(db, game, config=None, ts=None, rng=None):
    """Bring the ring in line with the derived statuses. Idempotent; safe to call
    on every request; returns a small summary for the dashboard and the tests."""
    cfg = config or config_for(game)
    ts = clock.now() if ts is None else ts
    rng = rng or random
    summary = {"respawned": 0, "spliced_out": 0, "assigned": 0, "conflicts": 0}

    rows = db.all("SELECT * FROM players WHERE game_id=?", (game["id"],))
    gbp = groups_by_pid(db, game["id"])

    # 1. Respawns whose timer has passed -> protected, spliced back in (§3.2).
    #    Respawn timers keep running during a truce (§10.4, "deliberately kind").
    for r in rows:
        if state.respawn_due(r, ts):
            db.execute(
                "UPDATE players SET base_status=?, respawn_at=NULL, protected_until=? "
                "WHERE pid=?",
                (state.ACTIVE, ts + int(cfg["SPAWN_PROTECT_S"]), r["pid"]))
            summary["respawned"] += 1

    # Re-read: statuses changed above.
    rows = db.all("SELECT * FROM players WHERE game_id=?", (game["id"],))
    targets = targets_map(db, game["id"])
    huntable = huntable_set(db, game, cfg, ts)

    # 2. Anyone who is no longer huntable must not be anyone's target.
    for r in rows:
        pid = int(r["pid"])
        if pid in huntable:
            continue
        hs = [h for h in hunters_of(db, pid) if h != pid]
        if not hs:
            continue
        changes = ring.splice_out(targets, huntable, pid)
        if changes:
            apply_target_changes(db, changes)
            targets.update(changes)
            summary["spliced_out"] += 1

    # 3. Anyone who should be hunting but has no valid target gets one.
    #    `stale` players keep hunting (§9.6), so they are included here.
    for r in rows:
        pid = int(r["pid"])
        st = state.status_of(r, game, db, ts, cfg)
        if st not in state.HUNTS:
            continue
        t = targets.get(pid)
        if t is not None and t != pid and t in huntable:
            continue
        pool = huntable - {pid}
        if not pool:
            if t is not None:
                db.execute("UPDATE players SET target_pid=NULL WHERE pid=?", (pid,))
                targets[pid] = None
            continue
        changes = ring.splice_in(targets, huntable, pid, gbp, rng)
        apply_target_changes(db, changes)
        targets.update(changes)
        summary["assigned"] += 1

    summary["conflicts"] = ring_conflicts(db, game["id"], gbp)
    db.commit()
    return summary


def ring_conflicts(db, game_id, gbp=None):
    """Same-group hunter/target pairs currently in the ring (§3.2 step 4, shown
    on the admin page rather than raised as an error)."""
    gbp = gbp if gbp is not None else groups_by_pid(db, game_id)
    n = 0
    for r in db.all("SELECT pid, target_pid FROM players WHERE game_id=? "
                    "AND target_pid IS NOT NULL", (game_id,)):
        if ring.shares_group(gbp, int(r["pid"]), int(r["target_pid"])):
            n += 1
    return n


def build_initial_ring(db, game, config=None, rng=None):
    """Assign targets to everyone from scratch (§3.2 initial assignment).

    Called when the host starts the game. Mid-game joins splice in instead
    (`reconcile`), so this runs once per game and is never the thing that has to
    cope with a player arriving.
    """
    cfg = config or config_for(game)
    ts = clock.now()
    huntable = sorted(huntable_set(db, game, cfg, ts))
    gbp = groups_by_pid(db, game["id"])
    targets, conflicts = ring.build_ring(
        huntable, gbp, int(cfg["MAX_REPAIR_PASSES"]), rng)
    apply_target_changes(db, targets)
    db.commit()
    return {"players": len(huntable), "conflicts": conflicts}


# ---------------------------------------------------------------------------
# Enrollment (§9.2)
# ---------------------------------------------------------------------------

def enroll(db, game, badge_key, display_name, groups, commitment,
           app_version=None, board=None, config=None, ts=None, rng=None):
    """Idempotent on `badge_key`: a returning badge gets the same pid and a fresh
    player_key (§9.2). That is also the `gotcha.json`-wiped recovery path (§10.5)
    -- same badge, same pid, score intact, no admin action needed.

    A *retired* badge_key (tombstoned by /rebind) is refused: the dead badge must
    not be able to re-enroll into the identity it was replaced out of.
    """
    cfg = config or config_for(game)
    ts = clock.now() if ts is None else ts
    if badge_key_retired(db, badge_key):
        return None, "retired_badge_key"

    player_key = crypto.new_player_key()
    existing = player_by_badge_key(db, badge_key)
    if existing is not None:
        pid = int(existing["pid"])
        # Re-enrollment: fresh key, fresh soul commitment (the old life's soul is
        # gone with the wiped gotcha.json), and spawn protection so the recovery
        # is not itself a death sentence.
        db.execute(
            "UPDATE players SET player_key=?, display_name=?, commitment=?, "
            "app_version=COALESCE(?, app_version), board=COALESCE(?, board), "
            "protected_until=?, life_id=life_id+1 WHERE pid=?",
            (player_key, display_name, commitment, app_version, board,
             ts + int(cfg["SPAWN_PROTECT_S"]), pid))
        if existing["base_status"] in (state.OPTED_OUT,):
            db.execute("UPDATE players SET base_status=?, opted_out_at=NULL "
                       "WHERE pid=?", (state.ACTIVE, pid))
        db.execute("UPDATE lives SET ended_at=COALESCE(ended_at, ?) WHERE pid=? "
                   "AND life_id=?", (ts, pid, int(existing["life_id"])))
        start_life(db, pid, int(existing["life_id"]) + 1, commitment, ts)
        set_groups(db, pid, groups)
        db.commit()
        reconcile(db, game, cfg, ts, rng)
        return player_by_pid(db, pid), None

    pid = db.next_pid()
    db.execute(
        "INSERT INTO players(pid, game_id, display_name, player_key, base_status, "
        "commitment, enrolled_at, last_seen_at, app_version, board, protected_until) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (pid, game["id"], display_name, player_key, state.ACTIVE, commitment,
         ts, ts, app_version, board, ts + int(cfg["SPAWN_PROTECT_S"])))
    db.execute(
        "INSERT INTO badge_keys(badge_key, pid, active, bound_at) VALUES(?,?,1,?)",
        (badge_key, pid, ts))
    start_life(db, pid, 0, commitment, ts)
    set_groups(db, pid, groups)
    db.commit()
    # A mid-game join splices in and lands `protected` (§3.2, §5.8).
    reconcile(db, game, cfg, ts, rng)
    return player_by_pid(db, pid), None


def rebind(db, game, pid, new_badge_key, config=None, ts=None):
    """Badge broke, drowned or was lost (§9.4). Score, streak, ring position and
    target survive onto new hardware; the old badge_key is tombstoned; the new
    badge enrolls normally afterwards and lands protected."""
    cfg = config or config_for(game)
    ts = clock.now() if ts is None else ts
    p = player_by_pid(db, pid)
    if p is None:
        return False, "no_such_player"
    if db.one("SELECT 1 FROM badge_keys WHERE badge_key=? AND pid!=?",
              (new_badge_key, pid)) is not None:
        return False, "badge_key_in_use"
    db.execute("UPDATE badge_keys SET active=0, retired_at=? WHERE pid=? AND active=1",
               (ts, pid))
    db.execute(
        "INSERT INTO badge_keys(badge_key, pid, active, bound_at) VALUES(?,?,1,?) "
        "ON CONFLICT(badge_key) DO UPDATE SET active=1, retired_at=NULL, bound_at=?",
        (new_badge_key, pid, ts, ts))
    db.execute("UPDATE players SET protected_until=? WHERE pid=?",
               (ts + int(cfg["SPAWN_PROTECT_S"]), pid))
    db.commit()
    return True, None


# ---------------------------------------------------------------------------
# Sync (§9.2)
# ---------------------------------------------------------------------------

def note_sync(db, pid, ts=None):
    """Record a sync: the badge's liveness, and the camp's aggregate sync volume
    (which is how §10.3's outage detection knows the server was listening)."""
    ts = clock.now() if ts is None else ts
    db.execute("UPDATE players SET last_sync_at=? WHERE pid=?", (ts, pid))
    minute = ts // 60 * 60
    db.execute(
        "INSERT INTO sync_beats(minute_ts, n) VALUES(?, 1) "
        "ON CONFLICT(minute_ts) DO UPDATE SET n = n + 1", (minute,))


def note_return(db, game, player, config=None, ts=None):
    """A badge that has been out of the ring long enough to go `dormant` comes
    back **protected** (§9.6's "Leaves when: any sync -> protected").

    Must be called *before* `note_sync`, because dormancy is derived from
    `last_sync_at` and updating that first would erase the evidence. Without this,
    a badge coming off the charger is spliced back into the ring and immediately
    attackable by whoever happens to be standing next to it -- which is the same
    unfairness §5.8 exists to prevent.
    """
    cfg = config or config_for(game)
    ts = clock.now() if ts is None else ts
    if player["base_status"] != state.ACTIVE:
        return False
    if not state.is_dormant(player, game, db, ts, cfg):
        return False
    db.execute("UPDATE players SET protected_until=? WHERE pid=?",
               (ts + int(cfg["SPAWN_PROTECT_S"]), int(player["pid"])))
    db.commit()
    return True


def note_seen(db, pid, ts=None):
    """Someone was physically near this badge (§10.1). Only ever moves forward."""
    ts = clock.now() if ts is None else ts
    db.execute("UPDATE players SET last_seen_at=MAX(COALESCE(last_seen_at,0), ?) "
               "WHERE pid=?", (ts, pid))


def sync_payload(db, game, player, config=None, ts=None, secret=""):
    """The whole `/v1/sync` response payload (§9.2).

    This is the only thing a badge polls, so everything the badge needs to play
    correctly *offline for the next five minutes* has to be in here.
    """
    cfg = config or config_for(game)
    ts = clock.now() if ts is None else ts
    pid = int(player["pid"])
    status = state.status_of(player, game, db, ts, cfg)
    live_streak = state.derived_streak(player, game, cfg, ts, db)
    rank_total, rank_streak = scoring.ranks_for(db, game["id"], pid)

    target = None
    tp = player["target_pid"]
    if tp is not None and status in state.HUNTS:
        t = player_by_pid(db, tp)
        if t is not None:
            seen = t["last_seen_at"] or t["enrolled_at"] or ts
            target = {
                "pid": int(t["pid"]),
                "name": t["display_name"],
                "commitment": t["commitment"],
                "last_seen_ago_s": max(0, ts - int(seen)),
                # The badge needs this to know why its radar is dark (§10.4):
                # "Otter 42 - slaapt" rather than an unexplained refusal.
                "halted": state.pair_halted(player, t, game, ts, db, cfg),
            }

    dodges = {}
    for r in db.all(
            "SELECT attacker_pid, used FROM dodges WHERE victim_pid=? AND victim_life_id=?",
            (pid, int(player["life_id"]))):
        left = max(0, int(cfg["DODGE_LIMIT"]) - int(r["used"]))
        dodges[str(int(r["attacker_pid"]))] = left

    quiet_from, quiet_to = state.quiet_window(player, game, cfg)
    payload = {
        "server_time": ts,
        "game": {
            "id": int(game["id"]),
            "state": game["state"],
            "truce_active": state.camp_truce_active(game, ts, db),
            "truce_until": state.truce_until(game, ts, db),
            "truce_schedule": {"from": game["truce_from"], "to": game["truce_to"]},
            "modifiers": active_modifiers(db, game["id"], ts),
        },
        "me": {
            "pid": pid,
            "status": status,
            "alive": status not in (state.DEAD,),
            "respawn_at": player["respawn_at"],
            "protected_until": player["protected_until"],
            "streak": live_streak,
            "best_streak": int(player["best_streak"] or 0),
            "total_kills": int(player["total_kills"] or 0),
            "score": int(player["score"] or 0) + int(player["score_adjust"] or 0),
            "deaths": int(player["deaths"] or 0),
            "rank_total": rank_total,
            "rank_streak": rank_streak,
            "dodges": dodges,
            "quiet": {"from": clock.hm_str(*quiet_from), "to": clock.hm_str(*quiet_to)},
            # Rides the sync response so the badge can render the private-card QR
            # (§9.1) without ever transmitting anything replayable.
            "card_token": crypto.card_token(secret, pid, ts + int(cfg["CARD_TOKEN_S"])),
        },
        "target": target,
        "hitlist": scoring.hitlist(db, game, cfg, ts),
        "app": {"min_version": game["min_version"],
                "latest_version": game["latest_version"]},
        "broadcast": game["broadcast"],
        "config": tunables_for_badge(cfg),
    }
    return payload


def active_modifiers(db, game_id, ts):
    rows = db.all(
        "SELECT type, from_ts, to_ts FROM modifiers WHERE game_id=? "
        "AND from_ts <= ? AND to_ts > ?", (game_id, ts, ts))
    return [{"type": r["type"], "until": int(r["to_ts"])} for r in rows]
