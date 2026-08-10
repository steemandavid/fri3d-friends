"""Event ingest (plan §9.3) -- the write path for everything that happens in the
field.

Two principles run through all of it:

* **Never trust badge-side enforcement** (§9.5). The badge enforces truce,
  protection, cooldowns and target validity so that the *offline* experience is
  correct; every one of those rules is re-checked here, because a flashable badge
  at a hacker camp is not a trusted client.
* **The badge is authoritative for exactly one thing: its own death** (§9.6). So a
  `killed_by` is believed. What the server then decides is whether the *kill*
  counted -- an invalid pairing is voided and the victim revived with their streak
  restored (§10.2), because "a stale assassin must never be able to permanently
  cost someone their streak".

Every event is idempotent on `uuid` (§9.2): a badge that flushes its queue twice,
or dies mid-POST and retries, must not double-score.
"""

import json

from . import clock, crypto, ring, scoring, service, state
from .config import DEFAULTS

# Badge clocks drift and queues sit for hours (§10.3). An event's own `at` is
# used for time-of-rule checks (a kill made before the truce began stays legal
# even if it uploads at 23:00), but only if it is plausible: not in the future,
# not older than this.
MAX_EVENT_AGE_S = 48 * 3600

KNOWN_TYPES = ("kill", "killed_by", "dodge", "attack_started", "reveal",
               "revealed", "heartbeat", "optout", "optin")


class Rejected(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def rule_time(ev_at, server_at):
    """The timestamp a rule check should use: the badge's own, when believable."""
    if ev_at is None:
        return server_at
    at = int(ev_at)
    if at > server_at + 600 or at < server_at - MAX_EVENT_AGE_S:
        return server_at
    return at


def ingest_batch(db, game, reporter, events, config=None, ts=None, rng=None):
    """Ingest a POST /v1/events batch. Returns (accepted_uuids, rejected).

    One event's failure never fails the batch: the badge would retry the whole
    queue forever and the one bad event would block every good one behind it.
    """
    cfg = config or service.config_for(game)
    ts = clock.now() if ts is None else ts
    accepted, rejected = [], []
    reporter_pid = int(reporter["pid"])
    # A mutable, request-entry snapshot of the reporter. Handlers see this rather
    # than a per-event DB re-read, so `reconcile` below (which repairs the ring for
    # *other* players and may reassign this reporter's target once its victim goes
    # dormant) cannot retroactively invalidate a kill the badge already committed
    # to offline. Intra-batch target inheritance is folded back in explicitly after
    # each accepted event (D12), so a table sweep still works.
    reporter = dict(reporter)

    service.reconcile(db, game, cfg, ts, rng)

    for ev in events or []:
        uuid = (ev or {}).get("uuid")
        if not uuid or not isinstance(uuid, str):
            rejected.append({"uuid": uuid, "reason": "no_uuid"})
            continue
        prior = db.one("SELECT accepted, reason FROM events WHERE uuid=?", (uuid,))
        if prior is not None:
            # Idempotent replay: report the original outcome, do nothing again.
            if prior["accepted"]:
                accepted.append(uuid)
            else:
                rejected.append({"uuid": uuid, "reason": prior["reason"] or "duplicate"})
            continue
        try:
            _handle(db, game, reporter, ev, cfg, ts, rng)
        except Rejected as r:
            db.rollback()                             # discard any partial write
            _record(db, reporter, ev, ts, False, r.reason)
            rejected.append({"uuid": uuid, "reason": r.reason})
            db.commit()
            continue
        except Exception as exc:                      # a bug must not eat the batch
            db.rollback()                             # C4: never commit a half kill
            _record(db, reporter, ev, ts, False, "error")
            rejected.append({"uuid": uuid, "reason": "error"})
            db.execute("UPDATE events SET payload_json=? WHERE uuid=?",
                       (json.dumps({"exc": repr(exc)[:200]}), uuid))
            db.commit()
            continue
        _record(db, reporter, ev, ts, True, None)
        accepted.append(uuid)
        db.commit()
        # D12: a kill in this same batch may have moved the reporter's target via
        # ring inheritance; fold it in so a table sweep's next kill is not refused
        # `not_your_target`. Refreshed only after an accepted event -- rejects and
        # errors rolled back, so nothing changed.
        fresh = service.player_by_pid(db, reporter_pid)
        if fresh is not None:
            reporter = dict(fresh)

    db.execute("UPDATE players SET last_event_at=? WHERE pid=?", (ts, reporter_pid))
    db.commit()
    return accepted, rejected


def _record(db, reporter, ev, ts, ok, reason):
    db.execute(
        "INSERT OR REPLACE INTO events(uuid, pid, type, at, server_at, ticks, "
        "payload_json, accepted, reason) VALUES(?,?,?,?,?,?,?,?,?)",
        (ev.get("uuid"), int(reporter["pid"]), str(ev.get("type"))[:32],
         _int_or_none(ev.get("at")), ts, _int_or_none(ev.get("ticks")),
         json.dumps(_payload_of(ev), sort_keys=True)[:4000], 1 if ok else 0, reason))


def _payload_of(ev):
    return {k: v for k, v in (ev or {}).items()
            if k not in ("uuid", "type", "at", "ticks", "pid")}


def _int_or_none(v):
    try:
        return int(v)
    except Exception:
        return None


def _handle(db, game, reporter, ev, cfg, ts, rng):
    etype = ev.get("type")
    if etype not in KNOWN_TYPES:
        raise Rejected("unknown_type")
    handler = _HANDLERS[etype]
    return handler(db, game, reporter, ev, cfg, ts, rng)


# ---------------------------------------------------------------------------
# kill / killed_by -- the two halves of one death
# ---------------------------------------------------------------------------

def _h_kill(db, game, assassin, ev, cfg, ts, rng):
    """The assassin's report: victim_pid + the disclosed soul (§3.4).

    (`witnesses` is tolerated and ignored -- D30 dropped it for v1 but kept the
    parser accepting the key so an app update can revive it.)
    """
    victim_pid = _int_or_none(ev.get("victim_pid"))
    if victim_pid is None:
        raise Rejected("no_victim")
    if victim_pid == int(assassin["pid"]):
        raise Rejected("self_kill")
    victim = service.player_by_pid(db, victim_pid)
    if victim is None:
        raise Rejected("no_such_victim")

    at = rule_time(ev.get("at"), ts)

    # The soul is the only thing that cannot be talked around: no soul, no kill.
    # Matching it against the victim's *life history* rather than only their
    # current commitment is what lets a proof that spent two hours in an offline
    # queue still land after the victim respawned and rotated their soul.
    life = _life_for_soul(db, victim, ev.get("soul"))
    if life is None:
        raise Rejected("bad_soul")

    # C3: a *voided* row (e.g. a `killed_by` that landed during spawn protection)
    # must not occupy the life's kill slot -- otherwise every later genuine kill on
    # this same live life is refused `already_dead` forever, and since the victim
    # never dies, life_id never advances. A voided row spares the victim; it must
    # not immunise them.
    dup = db.one("SELECT * FROM kills WHERE victim_pid=? AND victim_life_id=? "
                 "AND voided=0", (int(victim["pid"]), int(life["life_id"])))
    if dup is not None:
        # The victim's own report already landed: one death, two reports (§10.3).
        if int(dup["assassin_pid"]) == int(assassin["pid"]):
            db.execute("UPDATE kills SET reported_by='both', rssi=COALESCE(rssi, ?) "
                       "WHERE id=?", (_int_or_none(ev.get("rssi")), dup["id"]))
            return {"kill_id": dup["id"], "deduped": True}
        raise Rejected("already_dead")

    if int(life["life_id"]) != int(victim["life_id"]):
        # A proof for a life that has already ended some other way (a re-enroll,
        # say). The soul is genuine but there is nothing left to kill.
        raise Rejected("life_over")

    _check_kill_legal(db, game, assassin, victim, cfg, at)

    return _apply_kill(db, game, assassin, victim, cfg, ts, at, rng,
                       reported_by="assassin", rssi=_int_or_none(ev.get("rssi")),
                       life_id=int(life["life_id"]))


def _life_for_soul(db, victim, soul_hex):
    """The life a disclosed soul proves the death of, or None (§3.4)."""
    try:
        soul = bytes.fromhex(str(soul_hex))
    except Exception:
        return None
    if len(soul) != 16:
        return None
    return service.life_by_commitment(db, int(victim["pid"]),
                                      crypto.sha256_hex(soul))


def _h_killed_by(db, game, victim, ev, cfg, ts, rng):
    """The victim's report. Believed (§9.6) -- and it rotates the commitment,
    because the soul that has just been disclosed is burned either way."""
    attacker_pid = _int_or_none(ev.get("attacker_pid"))
    new_commitment = ev.get("new_commitment")
    at = rule_time(ev.get("at"), ts)

    if new_commitment and isinstance(new_commitment, str) and len(new_commitment) == 64:
        pending_commitment = new_commitment.lower()
    else:
        pending_commitment = None

    if attacker_pid is None or attacker_pid == int(victim["pid"]):
        raise Rejected("no_attacker")
    attacker = service.player_by_pid(db, attacker_pid)
    if attacker is None:
        raise Rejected("no_such_attacker")

    # Which life is this report about? Resolve it from the `lives` history by the
    # time the death happened, NOT from players.life_id (C3): a killed_by that sat
    # in an offline queue across the victim's own respawn is about the life that
    # was live at `at`, which may be several lives back. Keying it to the current
    # life instead parks a voided row on the live life and makes the victim
    # permanently unkillable. Falls back to the dead-shift heuristic if no life
    # window contains `at`.
    # `ended_at >= at` (inclusive) and the earliest matching life: a death lands
    # exactly on the life boundary (apply_death sets the old life's ended_at and
    # the new life's started_at to the same instant), and the report is about the
    # life that *ended* there -- so at a tie prefer the lower life_id.
    lrow = db.one(
        "SELECT life_id FROM lives WHERE pid=? AND started_at <= ? "
        "AND (ended_at IS NULL OR ended_at >= ?) ORDER BY life_id ASC LIMIT 1",
        (int(victim["pid"]), at, at))
    if lrow is not None:
        reported_life = int(lrow["life_id"])
    else:
        reported_life = int(victim["life_id"])
        if victim["base_status"] == state.DEAD and reported_life > 0:
            reported_life -= 1

    existing = db.one(
        "SELECT * FROM kills WHERE victim_pid=? AND victim_life_id=?",
        (int(victim["pid"]), reported_life))
    if existing is not None:
        # The assassin's copy already landed: same death, dedupe onto it (§10.3).
        db.execute("UPDATE kills SET reported_by='both' WHERE id=?", (existing["id"],))
        _rotate_commitment(db, victim, pending_commitment, ts)
        return {"kill_id": existing["id"], "deduped": True}

    try:
        _check_kill_legal(db, game, attacker, victim, cfg, at)
    except Rejected as r:
        # §10.2: the victim's badge is the authority for its own death, but an
        # invalid pairing is voided and the victim is NOT killed -- their streak
        # survives. The disclosed soul is burned regardless.
        kill_id = _insert_kill(db, game, attacker, victim, at, ts, 0, "target",
                               None, "victim", voided=1, void_reason=r.reason,
                               life_id=reported_life)
        _rotate_commitment(db, victim, pending_commitment, ts)
        db.commit()
        return {"kill_id": kill_id, "voided": r.reason}

    return _apply_kill(db, game, attacker, victim, cfg, ts, at, rng,
                       reported_by="victim", rssi=None,
                       new_commitment=pending_commitment)


def _check_kill_legal(db, game, assassin, victim, cfg, at):
    """Every server-side rule a kill has to clear (§9.5). Raises Rejected."""
    if game["state"] != "running":
        raise Rejected("game_not_running")

    # Truce and quiet hours, evaluated at the time of the kill, not of the upload.
    if state.camp_truce_active(game, at, db):
        raise Rejected("truce")
    if state.in_quiet(victim, game, at, cfg):
        raise Rejected("victim_quiet")
    if state.in_quiet(assassin, game, at, cfg):
        # Symmetry is what stops quiet hours being an invulnerability exploit.
        raise Rejected("attacker_quiet")

    a_status = state.status_of(assassin, game, db, at, cfg)
    if a_status in (state.KICKED, state.RETIRED, state.OPTED_OUT):
        raise Rejected("attacker_" + a_status)
    if assassin["base_status"] == state.DEAD:
        raise Rejected("attacker_dead")

    if victim["base_status"] == state.DEAD:
        raise Rejected("already_dead")
    if victim["base_status"] in (state.OPTED_OUT, state.KICKED, state.RETIRED):
        raise Rejected("victim_" + victim["base_status"])
    if state.is_protected(victim, at):
        raise Rejected("protected")

    # Target validity: your assigned target, or anyone carrying a bounty (rule 10).
    is_target = (assassin["target_pid"] is not None
                 and int(assassin["target_pid"]) == int(victim["pid"]))
    if not is_target and not state.has_bounty(victim, game, cfg, at, db):
        raise Rejected("not_your_target")
    return is_target


def _apply_kill(db, game, assassin, victim, cfg, ts, at, rng,
                reported_by, rssi=None, new_commitment=None, life_id=None):
    """Score it, kill the victim, inherit the target. One transaction."""
    is_target = (assassin["target_pid"] is not None
                 and int(assassin["target_pid"]) == int(victim["pid"]))
    repeated = scoring.repeat_kill_window(db, int(assassin["pid"]),
                                          int(victim["pid"]), ts, cfg)
    kind, points = scoring.classify_kill(
        assassin, victim, is_target,
        state.has_bounty(victim, game, cfg, at, db), repeated)
    if scoring.double_points_active(db, game["id"], at):
        points *= 2

    # Ring first, while the victim still holds the pointer we inherit (D10).
    targets = service.targets_map(db, game["id"])
    huntable = service.huntable_set(db, game, cfg, ts) - {int(victim["pid"])}
    gbp = service.groups_by_pid(db, game["id"])
    if is_target:
        # Classic inheritance (§3.2): the assassin was hunting the victim, so it
        # takes over the victim's target.
        changes, conflicted = ring.inherit(targets, huntable, int(assassin["pid"]),
                                           int(victim["pid"]), gbp, rng)
    else:
        # D8: a bounty kill -- the assassin is NOT the victim's hunter. Inheriting
        # would hand the assassin the victim's target and orphan the victim's real
        # hunter, who is then un-hunted for the rest of camp (§3.2 rule 10, §3.3).
        # Splice the victim out so *their* hunter inherits, and leave the assassin's
        # own pointer alone.
        changes = ring.splice_out(targets, huntable, int(victim["pid"]))
        conflicted = False

    kill_id = _insert_kill(db, game, assassin, victim, at, ts, points, kind,
                           rssi, reported_by, life_id=life_id)
    scoring.snapshot_kill_groups(db, kill_id, int(assassin["pid"]))
    scoring.apply_kill_to_assassin(db, assassin, points, at, game, cfg, ts)
    scoring.apply_death(db, victim, ts + int(cfg["RESPAWN_S"]), new_commitment, at=ts)
    service.apply_target_changes(db, changes)
    # A kill proves both badges were metres apart: both are demonstrably alive
    # and in the field, which is exactly what §10.1's staleness clock wants.
    service.note_seen(db, int(assassin["pid"]), ts)
    service.note_seen(db, int(victim["pid"]), ts)

    _flag_if_farming(db, kill_id, assassin, cfg, ts)
    db.commit()
    return {"kill_id": kill_id, "points": points, "kind": kind,
            "ring_conflict": conflicted}


def _insert_kill(db, game, assassin, victim, at, server_at, points, kind, rssi,
                 reported_by, voided=0, void_reason=None, life_id=None):
    life = int(victim["life_id"]) if life_id is None else int(life_id)
    if not voided:
        # C3: a prior voided marker on this same life (e.g. a killed_by rejected
        # `protected`) would collide with UNIQUE(victim_pid, victim_life_id) and
        # this genuine kill would be lost. Voided rows carry no score and no
        # kill_groups, and the event stays in `events` for audit, so clearing the
        # marker before the real death lands is safe.
        db.execute("DELETE FROM kills WHERE victim_pid=? AND victim_life_id=? "
                   "AND voided=1", (int(victim["pid"]), life))
    cur = db.execute(
        "INSERT INTO kills(game_id, assassin_pid, victim_pid, victim_life_id, at, "
        "server_at, points, kind, rssi, reported_by, voided, void_reason) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (game["id"], int(assassin["pid"]), int(victim["pid"]), life,
         at, server_at, points, kind, rssi, reported_by, voided, void_reason))
    return int(cur.lastrowid)


def _rotate_commitment(db, victim, commitment, ts):
    """Install a soul commitment for the victim's *current* life (§3.4) -- but only
    if that life has none yet.

    C2: `lives` keeps history *across* lives, but a commitment must also be binding
    *within* a life. If it is not, a victim being chased can heartbeat a fresh
    commitment, overwrite in place the soul the assassin already holds, and every
    queued genuine kill is then refused `bad_soul` -- the victim becomes unkillable
    at will. A respawn opens the new life with a NULL commitment (`apply_death`),
    so the legitimate post-respawn publish still lands; a second rotation within
    the same life is silently ignored.
    """
    if not commitment:
        return
    pid = int(victim["pid"])
    row = db.one("SELECT life_id FROM players WHERE pid=?", (pid,))
    life = int(row["life_id"]) if row else int(victim["life_id"])
    cur = db.one("SELECT commitment FROM lives WHERE pid=? AND life_id=?", (pid, life))
    if cur is not None and cur["commitment"]:
        return                       # already committed this life; do not overwrite
    db.execute("UPDATE players SET commitment=? WHERE pid=?", (commitment, pid))
    service.start_life(db, pid, life, commitment, ts)


def _flag_if_farming(db, kill_id, assassin, cfg, ts):
    """§9.5: MAX_KILLS_PER_HOUR marks kills for review, it does not refuse them.
    A legitimate table sweep is explicitly legal (D16) and refusing one would
    break the best moment in the game."""
    limit = int(cfg.get("MAX_KILLS_PER_HOUR", DEFAULTS["MAX_KILLS_PER_HOUR"]))
    n = int(db.scalar("SELECT COUNT(*) FROM kills WHERE assassin_pid=? AND "
                      "server_at > ? AND voided=0",
                      (int(assassin["pid"]), ts - 3600), default=0))
    if n > limit:
        db.execute("UPDATE kills SET flagged=1, flag_reason=? WHERE id=?",
                   ("rate:%d/h" % n, kill_id))


# ---------------------------------------------------------------------------
# dodge / attack_started
# ---------------------------------------------------------------------------

def _h_dodge(db, game, reporter, ev, cfg, ts, rng):
    """One reprieve per (attacker, victim) pair per life (§5.4 DODGE_LIMIT).

    Either side may report it: the victim's report names `attacker_pid`, the
    assassin's names `victim_pid`. Both land on the same row, so the pair's
    counter is right whichever half arrives (or if both do).
    """
    attacker_pid = _int_or_none(ev.get("attacker_pid"))
    victim_pid = _int_or_none(ev.get("victim_pid"))
    if attacker_pid is None and victim_pid is None:
        counterpart = _int_or_none(ev.get("counterpart_pid"))
        if counterpart is None:
            raise Rejected("no_counterpart")
        # Disambiguate by the ring: if the reporter hunts the counterpart, the
        # reporter is the attacker.
        if reporter["target_pid"] is not None and int(reporter["target_pid"]) == counterpart:
            attacker_pid, victim_pid = int(reporter["pid"]), counterpart
        else:
            attacker_pid, victim_pid = counterpart, int(reporter["pid"])
    elif attacker_pid is None:
        attacker_pid = int(reporter["pid"])
    elif victim_pid is None:
        victim_pid = int(reporter["pid"])

    victim = service.player_by_pid(db, victim_pid)
    attacker = service.player_by_pid(db, attacker_pid)
    if victim is None or attacker is None:
        raise Rejected("no_such_player")

    life = int(victim["life_id"])
    row = db.one("SELECT used, last_attack_at FROM dodges WHERE attacker_pid=? "
                 "AND victim_pid=? AND victim_life_id=?",
                 (attacker_pid, victim_pid, life))
    decay_s = int(cfg.get("DODGE_DECAY_MS", DEFAULTS["DODGE_DECAY_MS"])) // 1000
    used = 0 if row is None else int(row["used"])
    if row is not None and row["last_attack_at"] is not None \
            and ts - int(row["last_attack_at"]) > decay_s:
        used = 0                                   # DODGE_DECAY_MS reset (§5.4)
    used = min(used + 1, int(cfg["DODGE_LIMIT"]))
    db.execute(
        "INSERT INTO dodges(attacker_pid, victim_pid, victim_life_id, used, "
        "last_attack_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(attacker_pid, victim_pid, victim_life_id) DO UPDATE SET "
        "used=excluded.used, last_attack_at=excluded.last_attack_at",
        (attacker_pid, victim_pid, life, used, ts))
    # A dodge is a physical encounter: both were in range (§10.1).
    service.note_seen(db, attacker_pid, ts)
    service.note_seen(db, victim_pid, ts)
    return {"used": used}


def _h_attack_started(db, game, attacker, ev, cfg, ts, rng):
    """Cooldown bookkeeping and abuse detection (§9.3), plus the one rule that
    has real teeth here: **protection ends the moment an ATTACK is sent** (§5.8).
    It is a breath, not a bunker, and it must never become a free first strike."""
    victim_pid = _int_or_none(ev.get("victim_pid"))
    if victim_pid is None:
        raise Rejected("no_victim")
    at = rule_time(ev.get("at"), ts)
    db.execute("INSERT INTO attacks(attacker_pid, victim_pid, server_at) VALUES(?,?,?)",
               (int(attacker["pid"]), victim_pid, ts))
    if state.is_protected(attacker, at):
        db.execute("UPDATE players SET protected_until=NULL WHERE pid=?",
                   (int(attacker["pid"]),))
    service.note_seen(db, int(attacker["pid"]), ts)
    service.note_seen(db, victim_pid, ts)
    return {"ok": True}


# ---------------------------------------------------------------------------
# reveal / revealed -- log only, but they carry liveness (§9.3)
# ---------------------------------------------------------------------------

def _h_reveal(db, game, hunter, ev, cfg, ts, rng):
    target_pid = _int_or_none(ev.get("target_pid"))
    if target_pid is None:
        raise Rejected("no_target")
    service.note_seen(db, int(hunter["pid"]), ts)
    service.note_seen(db, target_pid, ts)
    return {"ok": True}


def _h_revealed(db, game, revealed, ev, cfg, ts, rng):
    """"Being revealed proves you were physically near someone, so it refreshes
    last_seen" (§9.3) -- which is what keeps a player who is out in the field but
    not hunting anyone from being declared stale."""
    hunter_pid = _int_or_none(ev.get("hunter_pid"))
    service.note_seen(db, int(revealed["pid"]), ts)
    if hunter_pid is not None:
        service.note_seen(db, hunter_pid, ts)
    return {"ok": True}


# ---------------------------------------------------------------------------
# heartbeat -- one per sync (§9.3)
# ---------------------------------------------------------------------------

def _h_heartbeat(db, game, player, ev, cfg, ts, rng):
    pid = int(player["pid"])
    battery = _int_or_none(ev.get("battery"))
    peers = _int_or_none(ev.get("peers_seen"))
    bg = 1 if ev.get("background") else 0
    # Cap like enrollment does (C1): the admin dashboard interpolates this into
    # innerHTML, and the heartbeat is the one write path that otherwise stored it
    # with no length bound at all.
    app_version = ev.get("app_version")
    if isinstance(app_version, str):
        app_version = app_version[:16]
    db.execute(
        "UPDATE players SET battery=COALESCE(?, battery), "
        "peers_seen=COALESCE(?, peers_seen), bg_service=?, "
        "app_version=COALESCE(?, app_version) WHERE pid=?",
        (battery, peers, bg, app_version if isinstance(app_version, str) else None, pid))

    # The group snapshot rides the heartbeat, so a player who edits their groups
    # mid-camp moves the per-member denominator without any extra endpoint.
    if isinstance(ev.get("groups"), list):
        service.set_groups(db, pid, ev["groups"])

    # A badge that respawned while offline has generated a fresh soul (§3.4: "on
    # enrollment and on every respawn") and has no other way to publish the new
    # commitment if its `killed_by` never reached us -- for instance if the
    # battery was pulled mid-duel. Accepting it here is what stops a player
    # coming back from the dead permanently unkillable.
    c = ev.get("commitment")
    if isinstance(c, str) and len(c) == 64:
        _rotate_commitment(db, player, c.lower(), ts)

    # Personal quiet hours (§10.4a): re-checked server-side on ingest, and
    # clamped to QUIET_EARLIEST/QUIET_LATEST here so a badge cannot declare
    # itself quiet from 12:00 to 19:00 and become unkillable all afternoon.
    q = ev.get("quiet")
    if isinstance(q, dict):
        q_from, q_to = state.clamp_quiet(
            clock.parse_hm(q.get("from"), clock.parse_hm(game["truce_from"], (22, 0))),
            clock.parse_hm(q.get("to"), clock.parse_hm(game["truce_to"], (8, 0))),
            clock.parse_hm(game["truce_from"], (22, 0)),
            clock.parse_hm(game["truce_to"], (8, 0)),
            cfg.get("QUIET_EARLIEST", "20:00"), cfg.get("QUIET_LATEST", "10:00"))
        db.execute("UPDATE players SET quiet_from=?, quiet_to=? WHERE pid=?",
                   (clock.hm_str(*q_from), clock.hm_str(*q_to), pid))

    # A heartbeat proves this badge is awake, and its `target_seen_ago_s` is the
    # only evidence anyone has that the *target* is awake (§10.1).
    ago = _int_or_none(ev.get("target_seen_ago_s"))
    if ago is not None and ago >= 0 and player["target_pid"] is not None:
        service.note_seen(db, int(player["target_pid"]), ts - min(ago, MAX_EVENT_AGE_S))
    # A badge reporting peers is standing in a populated place, and BLE detection
    # is near-symmetric at these ranges, so its peers almost certainly see it
    # too. Counting that as a sighting closes an otherwise nasty false-positive:
    # a player out in the field whose *hunter's* badge is switched off has nobody
    # reporting `target_seen_ago_s` for them, and would drift into `stale`
    # despite being visibly present all afternoon.
    if peers:
        service.note_seen(db, pid, ts)
    return {"ok": True}


# ---------------------------------------------------------------------------
# optout / optin (rule 15, §3.2)
# ---------------------------------------------------------------------------

def _h_optout(db, game, player, ev, cfg, ts, rng):
    db.execute("UPDATE players SET base_status=?, opted_out_at=?, target_pid=NULL "
               "WHERE pid=?", (state.OPTED_OUT, ts, int(player["pid"])))
    db.commit()
    service.reconcile(db, game, cfg, ts, rng)
    return {"ok": True}


def _h_optin(db, game, player, ev, cfg, ts, rng):
    """Opts back in -> `protected` (§9.6), so rejoining is not a death sentence."""
    db.execute("UPDATE players SET base_status=?, opted_out_at=NULL, "
               "protected_until=? WHERE pid=?",
               (state.ACTIVE, ts + int(cfg["SPAWN_PROTECT_S"]), int(player["pid"])))
    db.commit()
    service.reconcile(db, game, cfg, ts, rng)
    return {"ok": True}


_HANDLERS = {
    "kill": _h_kill,
    "killed_by": _h_killed_by,
    "dodge": _h_dodge,
    "attack_started": _h_attack_started,
    "reveal": _h_reveal,
    "revealed": _h_revealed,
    "heartbeat": _h_heartbeat,
    "optout": _h_optout,
    "optin": _h_optin,
}
