"""Scoring and leaderboards (plan §2).

**One interpretation decision, flagged rather than hidden.** §2.1 ranks board 1 by
`total_kills`, while §2's "Points per kill" table awards 1 for your target and 2
for a bounty player. Those are two different numbers, so this server stores both:

  * `players.total_kills` -- the count of kills that scored (a repeat kill inside
    6 h scores 0 and is not counted; it is still recorded in `kills` and still
    kills the victim).
  * `players.score` -- the sum of points, which is what the "total" board ranks
    by, since otherwise the bounty rule's "2" would never show up anywhere.

Both are returned by the API, so the page can show "14 kills · 19 points" and the
plan's wording stays honest either way.

Group boards (§2.3) read `kill_groups`, the membership snapshot taken at kill
time, never the current roster -- except the per-member *denominator*, which is
deliberately the current roster so that a group inflating its membership dilutes
its own average.
"""

from . import state
from .config import DEFAULTS

TARGET = "target"
BOUNTY = "bounty"
REPEAT = "repeat"

POINTS = {TARGET: 1, BOUNTY: 2, REPEAT: 0}


def classify_kill(assassin, victim, is_assigned_target, victim_has_bounty,
                  repeated_within_window):
    """(kind, points) for one kill (§2's table).

    Order matters: a repeat kill of the same victim within 6 h scores 0 *even if*
    they are your assigned target or carry a bounty. That is the anti-farming
    rule and it has to dominate.
    """
    if repeated_within_window:
        return REPEAT, 0
    if is_assigned_target:
        return TARGET, POINTS[TARGET]
    if victim_has_bounty:
        return BOUNTY, POINTS[BOUNTY]
    # Not your target and no bounty: not a legal kill (§1). Callers reject before
    # reaching here; this keeps the function total.
    return TARGET, 0


def double_points_active(db, game_id, ts):
    row = db.one(
        "SELECT 1 FROM modifiers WHERE game_id=? AND type='double_points' "
        "AND from_ts <= ? AND to_ts > ?", (game_id, ts, ts))
    return row is not None


def repeat_kill_window(db, assassin_pid, victim_pid, ts, config=None):
    """Did this assassin already kill this victim inside REPEAT_KILL_S (6 h)?"""
    cfg = config or DEFAULTS
    window = int(cfg.get("REPEAT_KILL_S", DEFAULTS["REPEAT_KILL_S"]))
    row = db.one(
        "SELECT 1 FROM kills WHERE assassin_pid=? AND victim_pid=? "
        "AND voided=0 AND server_at > ?",
        (assassin_pid, victim_pid, ts - window))
    return row is not None


def apply_kill_to_assassin(db, assassin, points, at, game, config=None, ts=None):
    """Bank a kill: streak +1 from the *decayed* streak, best_streak high-water.

    Reading the decayed streak first is what makes decay real -- a player whose
    streak has decayed from 5 to 2 continues from 3, not from 6 (§2.2: decay
    lowers `streak` only; it never touches `best_streak` or `total_kills`).
    """
    cfg = config or DEFAULTS
    live = state.derived_streak(assassin, game, cfg, ts, db)
    new_streak = live + 1
    best = max(int(assassin["best_streak"] or 0), new_streak)
    scoring = 1 if points > 0 else 0
    db.execute(
        "UPDATE players SET total_kills=total_kills+?, score=score+?, "
        "streak_at_last_kill=?, last_kill_at=?, best_streak=? WHERE pid=?",
        (scoring, points, new_streak, at, best, assassin["pid"]))
    return new_streak


def apply_death(db, victim, respawn_at, new_commitment=None, at=None):
    """Mark a death: status dead, respawn timer, life_id +1, streak reset.

    The streak reset is expressed as `streak_at_last_kill = 0` with
    `last_kill_at` left alone, because the derived streak is
    `streak_at_last_kill - decay` and zero decays to zero.

    The old life is closed and a new one opened. The new life's commitment is
    whatever the victim disclosed in its `killed_by` report; until it reports one
    the player has **no** verifiable soul, which is the safe direction -- nobody
    can be killed with a stale proof (§3.4).
    """
    pid = int(victim["pid"])
    life = int(victim["life_id"])
    at = respawn_at if at is None else at
    db.execute(
        "UPDATE players SET base_status=?, respawn_at=?, deaths=deaths+1, "
        "life_id=life_id+1, streak_at_last_kill=0, protected_until=NULL, "
        "commitment=? WHERE pid=?",
        (state.DEAD, respawn_at, new_commitment, pid))
    db.execute("UPDATE lives SET ended_at=COALESCE(ended_at, ?) WHERE pid=? AND life_id=?",
               (at, pid, life))
    db.execute(
        "INSERT INTO lives(pid, life_id, commitment, started_at) VALUES(?,?,?,?) "
        "ON CONFLICT(pid, life_id) DO UPDATE SET commitment=excluded.commitment",
        (pid, life + 1, new_commitment, at))


def revive(db, victim, restore_streak=None, protected_until=None):
    """Undo a death (§10.2's reconciliation, and the host's /revive action).

    "A stale assassin must never be able to permanently cost someone their
    streak", so the streak is restored, not just the life.
    """
    if restore_streak is None:
        db.execute(
            "UPDATE players SET base_status=?, respawn_at=NULL, "
            "deaths=MAX(0, deaths-1), protected_until=? WHERE pid=?",
            (state.ACTIVE, protected_until, victim["pid"]))
    else:
        db.execute(
            "UPDATE players SET base_status=?, respawn_at=NULL, "
            "deaths=MAX(0, deaths-1), streak_at_last_kill=?, protected_until=? "
            "WHERE pid=?",
            (state.ACTIVE, int(restore_streak), protected_until, victim["pid"]))


def snapshot_kill_groups(db, kill_id, assassin_pid):
    """Freeze the assassin's current groups onto the kill (§2.3)."""
    rows = db.all("SELECT gid, name FROM player_groups WHERE pid=?", (assassin_pid,))
    db.executemany(
        "INSERT OR IGNORE INTO kill_groups(kill_id, gid, name) VALUES(?,?,?)",
        [(kill_id, r["gid"], r["name"]) for r in rows])


# ---------------------------------------------------------------------------
# Leaderboards (§9.2 GET /v1/leaderboard)
# ---------------------------------------------------------------------------

GROUP_MIN_MEMBERS = 3          # §2.3: per-member board needs >= 3 members


def board_total(db, game_id, limit=50):
    rows = db.all(
        "SELECT pid, display_name, total_kills, score, score_adjust, deaths "
        "FROM players WHERE game_id=? AND base_status NOT IN ('retired') "
        "ORDER BY (score + score_adjust) DESC, total_kills DESC, pid ASC LIMIT ?",
        (game_id, limit))
    return [{"pid": r["pid"], "name": r["display_name"],
             "score": r["score"] + r["score_adjust"],
             "kills": r["total_kills"], "deaths": r["deaths"]} for r in rows]


def board_streak(db, game_id, limit=50):
    """Ranks `best_streak`, the high-water mark, which never decays (§2.1)."""
    rows = db.all(
        "SELECT pid, display_name, best_streak, total_kills FROM players "
        "WHERE game_id=? AND base_status NOT IN ('retired') "
        "ORDER BY best_streak DESC, total_kills DESC, pid ASC LIMIT ?",
        (game_id, limit))
    return [{"pid": r["pid"], "name": r["display_name"],
             "best_streak": r["best_streak"], "kills": r["total_kills"]}
            for r in rows]


def _group_scores(db, game_id):
    rows = db.all(
        "SELECT kg.gid AS gid, kg.name AS name, "
        "       SUM(k.points) AS points, COUNT(*) AS kills "
        "FROM kill_groups kg JOIN kills k ON k.id = kg.kill_id "
        "WHERE k.game_id=? AND k.voided=0 GROUP BY kg.gid, kg.name",
        (game_id,))
    out = {}
    for r in rows:
        g = out.setdefault(int(r["gid"]), {"gid": int(r["gid"]), "name": r["name"],
                                           "points": 0, "kills": 0})
        g["points"] += int(r["points"] or 0)
        g["kills"] += int(r["kills"] or 0)
    return out


def _group_members(db, game_id):
    rows = db.all(
        "SELECT pg.gid AS gid, pg.name AS name, COUNT(*) AS members "
        "FROM player_groups pg JOIN players p ON p.pid = pg.pid "
        "WHERE p.game_id=? AND p.base_status NOT IN ('retired','kicked') "
        "GROUP BY pg.gid, pg.name", (game_id,))
    return {int(r["gid"]): {"name": r["name"], "members": int(r["members"])}
            for r in rows}


def board_group(db, game_id, per_member=False, limit=50):
    scores = _group_scores(db, game_id)
    members = _group_members(db, game_id)
    out = []
    for gid, m in members.items():
        s = scores.get(gid, {"points": 0, "kills": 0})
        entry = {"gid": gid, "name": m["name"], "members": m["members"],
                 "points": s["points"], "kills": s["kills"]}
        if per_member:
            if m["members"] < GROUP_MIN_MEMBERS:
                continue
            entry["per_member"] = round(s["points"] / m["members"], 2)
        out.append(entry)
    key = (lambda e: (-e["per_member"], -e["points"], e["name"])) if per_member \
        else (lambda e: (-e["points"], -e["kills"], e["name"]))
    out.sort(key=key)
    return out[:limit]


def hitlist(db, game, config=None, ts=None, limit=None):
    """Players whose *live* (decayed) streak carries a bounty (rule 10, §9.2).

    Computed from the derived streak, not a stored one, so a leader who has gone
    quiet for five hours drops off the list without anything having to run.
    """
    cfg = config or DEFAULTS
    if not cfg.get("bounty_enabled", True):
        return []
    limit = limit or int(cfg.get("HITLIST_MAX", DEFAULTS["HITLIST_MAX"]))
    threshold = int(cfg.get("BOUNTY_STREAK", DEFAULTS["BOUNTY_STREAK"]))
    rows = db.all(
        "SELECT * FROM players WHERE game_id=? AND base_status='active' "
        "AND streak_at_last_kill >= ?", (game["id"], threshold))
    out = []
    for r in rows:
        live = state.derived_streak(r, game, cfg, ts, db)
        if live >= threshold:
            out.append({"pid": r["pid"], "name": r["display_name"], "streak": live})
    out.sort(key=lambda e: (-e["streak"], e["pid"]))
    return out[:limit]


def ranks_for(db, game_id, pid):
    """(rank_total, rank_streak) -- 1-based, ties share the better rank."""
    row = db.one("SELECT score + score_adjust AS s, best_streak FROM players "
                 "WHERE pid=?", (pid,))
    if row is None:
        return None, None
    rank_total = 1 + int(db.scalar(
        "SELECT COUNT(*) FROM players WHERE game_id=? AND "
        "(score + score_adjust) > ? AND base_status != 'retired'",
        (game_id, row["s"]), default=0))
    rank_streak = 1 + int(db.scalar(
        "SELECT COUNT(*) FROM players WHERE game_id=? AND best_streak > ? "
        "AND base_status != 'retired'",
        (game_id, row["best_streak"]), default=0))
    return rank_total, rank_streak
