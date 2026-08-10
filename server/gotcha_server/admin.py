"""Admin API and the live dashboard (plan §9.4).

Two things the plan is emphatic about, and they shape this file:

* **"Endpoints are not a screen; this is the screen."** A host at a muddy campsite
  needs to answer "is the game alive?" in one glance, on a phone. So the dashboard
  is one JSON document assembled in one function, and `pages.py` renders it with a
  5 s `setInterval` -- no websockets, no realtime framework (§9.4).
* **"Kills in the last 10 minutes is the single most important number on the
  page"** -- it is the only one that distinguishes "the game is running quietly"
  from "the game has silently stopped working", which §3.3 calls the most likely
  failure mode. It is first in the payload and biggest on the page.

Several volunteers with several phones is how a camp actually gets run, so there
is no server-side session state (signed cookies only), and every action records
*which* host performed it.
"""

import json

from fastapi import APIRouter, Form, HTTPException, Request, Response

from . import clock, crypto, scoring, service, state
from .config import DEFAULTS

router = APIRouter()

COOKIE = "gotcha_admin"


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def require_host(request: Request):
    """The volunteer's name from a valid signed cookie, or 401."""
    app = request.app
    host = crypto.session_host(app.state.secret, request.cookies.get(COOKIE, ""),
                               clock.now())
    if not host:
        raise HTTPException(status_code=401, detail="login_required")
    return host


def log_action(db, host, action, target_pid=None, detail=None):
    db.execute("INSERT INTO admin_log(at, host, action, target_pid, detail_json) "
               "VALUES(?,?,?,?,?)",
               (clock.now(), host, action, target_pid,
                json.dumps(detail or {}, sort_keys=True)[:2000]))
    db.commit()


@router.post("/admin/login")
async def admin_login(request: Request, response: Response,
                      host: str = Form(...), password: str = Form(...)):
    db = request.app.state.db
    pw_hash = db.get_meta("admin_pw_hash")
    salt = db.get_meta("admin_pw_salt")
    host = (host or "").strip()[:32]
    if not host:
        raise HTTPException(status_code=400, detail="host_required")
    if not pw_hash or not salt or not crypto.password_ok(pw_hash, salt, password):
        raise HTTPException(status_code=401, detail="bad_password")
    exp = clock.now() + int(DEFAULTS["ADMIN_SESSION_S"])
    cookie = crypto.session_cookie(request.app.state.secret, host, exp)
    log_action(db, host, "login")
    resp = Response(status_code=303, headers={"Location": "/admin"})
    # `secure` is deliberately not set: the admin page is served over HTTPS in
    # production (D31) but must stay reachable over plain HTTP on the dev LAN.
    resp.set_cookie(COOKIE, cookie, httponly=True, samesite="lax", max_age=
                    int(DEFAULTS["ADMIN_SESSION_S"]), path="/")
    return resp


@router.post("/admin/logout")
async def admin_logout(request: Request):
    resp = Response(status_code=303, headers={"Location": "/admin"})
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ---------------------------------------------------------------------------
# Game control
# ---------------------------------------------------------------------------

@router.post("/v1/admin/game")
async def create_game(request: Request):
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    game = service.create_game(db, str(body.get("name") or "Gotcha")[:64],
                               _int(body.get("start")), _int(body.get("end")),
                               body.get("tunables") or {})
    log_action(db, host, "create_game", None, {"game_id": int(game["id"])})
    return {"game_id": int(game["id"]), "state": game["state"]}


@router.post("/v1/admin/game/{game_id}/state")
async def set_state(game_id: int, request: Request):
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    new_state = str(body.get("state") or "")
    if new_state not in ("lobby", "running", "paused", "ended"):
        raise HTTPException(status_code=400, detail="bad_state")
    game = db.one("SELECT * FROM games WHERE id=?", (game_id,))
    if game is None:
        raise HTTPException(status_code=404, detail="no_such_game")
    was = game["state"]
    db.execute("UPDATE games SET state=? WHERE id=?", (new_state, game_id))
    db.commit()
    built = None
    # Starting the game is what builds the ring (§3.2 initial assignment); every
    # later arrival splices in instead.
    if new_state == "running" and was != "running":
        game = db.one("SELECT * FROM games WHERE id=?", (game_id,))
        built = service.build_initial_ring(db, game)
        if game["start_at"] is None:
            db.execute("UPDATE games SET start_at=? WHERE id=?", (clock.now(), game_id))
            db.commit()
    log_action(db, host, "game_state", None, {"from": was, "to": new_state,
                                              "ring": built})
    return {"state": new_state, "ring": built}


@router.post("/v1/admin/truce")
async def set_truce(request: Request):
    """Instant camp-wide truce (D7's host button).

    Recorded as an *interval*, not just a flag, because streak decay has to
    subtract it retroactively hours later (§2.2).
    """
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    game = service.current_game(db)
    ts = clock.now()
    active = bool(body.get("active"))
    until = _int(body.get("until"))
    reason = str(body.get("reason") or "")[:120]
    if active:
        db.execute("UPDATE games SET truce_active=1, truce_until=?, truce_reason=? "
                   "WHERE id=?", (until, reason, game["id"]))
        open_row = db.one("SELECT id FROM truce_intervals WHERE game_id=? AND "
                          "to_ts IS NULL ORDER BY id DESC LIMIT 1", (game["id"],))
        if open_row is None:
            db.execute("INSERT INTO truce_intervals(game_id, from_ts, to_ts, reason) "
                       "VALUES(?,?,?,?)", (game["id"], ts, until, reason))
    else:
        db.execute("UPDATE games SET truce_active=0, truce_until=NULL, "
                   "truce_reason=NULL WHERE id=?", (game["id"],))
        db.execute("UPDATE truce_intervals SET to_ts=? WHERE game_id=? AND "
                   "(to_ts IS NULL OR to_ts > ?)", (ts, game["id"], ts))
    db.commit()
    log_action(db, host, "truce", None, {"active": active, "until": until,
                                         "reason": reason})
    return {"truce_active": active, "truce_until": until}


@router.post("/v1/admin/truce_schedule")
async def set_truce_schedule(request: Request):
    """Move the nightly truce window (D7's 22:00-08:00).

    Not in §9.4's endpoint list, but the schedule is pushed to badges in the sync
    payload as `game.truce_schedule` and every other timing constant is
    host-adjustable (§5.4). A camp whose programme runs to 01:00, or a test that
    needs to play a kill at 06:00, otherwise has no way to move it -- and the one
    alternative, editing the database by hand on a laptop in a field, is worse.
    """
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    game = service.current_game(db)
    t_from = clock.hm_str(*clock.parse_hm(body.get("from"),
                                          clock.parse_hm(game["truce_from"], (22, 0))))
    t_to = clock.hm_str(*clock.parse_hm(body.get("to"),
                                        clock.parse_hm(game["truce_to"], (8, 0))))
    db.execute("UPDATE games SET truce_from=?, truce_to=? WHERE id=?",
               (t_from, t_to, game["id"]))
    db.commit()
    log_action(db, host, "truce_schedule", None, {"from": t_from, "to": t_to})
    return {"truce_from": t_from, "truce_to": t_to}


@router.post("/v1/admin/broadcast")
async def set_broadcast(request: Request):
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    text = body.get("text")
    text = None if text in (None, "") else str(text)[:120]
    game = service.current_game(db)
    db.execute("UPDATE games SET broadcast=? WHERE id=?", (text, game["id"]))
    db.commit()
    log_action(db, host, "broadcast", None, {"text": text})
    return {"broadcast": text}


@router.post("/v1/admin/appversion")
async def set_appversion(request: Request):
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    game = service.current_game(db)
    # A key that is ABSENT leaves the stored value alone; a key present but empty
    # CLEARS it. Without the second case a floor could be set and then never
    # lifted -- `if min_v else None` turned "" into None, which COALESCE read as
    # "keep", so the only way back was a DB edit. That is a bad corner to leave in
    # an endpoint whose whole job is a camp-wide kill switch: since §8.10.3 a badge
    # below min_version stops hunting, so a floor typed by mistake takes the camp
    # out of the game with no way back through the UI.
    sets, params = [], []
    for key in ("min_version", "latest_version"):    # literals, never user input
        if key not in body:
            continue                                 # absent -> leave it alone
        v = body.get(key)
        v = str(v).strip()[:16] if v is not None else ""
        sets.append(key + "=?")
        params.append(v or None)                     # "" / null -> clear it
    if sets:
        params.append(game["id"])
        db.execute("UPDATE games SET " + ", ".join(sets) + " WHERE id=?",
                   tuple(params))
    min_v = body.get("min_version")
    latest_v = body.get("latest_version")
    db.commit()
    log_action(db, host, "appversion", None, {"min": min_v, "latest": latest_v})
    game = service.current_game(db)
    return {"min_version": game["min_version"], "latest_version": game["latest_version"]}


@router.post("/v1/admin/modifier")
async def add_modifier(request: Request):
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    game = service.current_game(db)
    mtype = str(body.get("type") or "")
    if mtype not in ("double_points", "amnesty"):
        raise HTTPException(status_code=400, detail="bad_type")
    from_ts = _int(body.get("from")) or clock.now()
    to_ts = _int(body.get("to")) or (from_ts + 3600)
    db.execute("INSERT INTO modifiers(game_id, type, from_ts, to_ts) VALUES(?,?,?,?)",
               (game["id"], mtype, from_ts, to_ts))
    db.commit()
    log_action(db, host, "modifier", None, {"type": mtype, "from": from_ts, "to": to_ts})
    return {"type": mtype, "from": from_ts, "to": to_ts}


@router.post("/v1/admin/tunables")
async def set_tunables(request: Request):
    """Live retuning (§5.4). Worth a lot: "RSSI at a real camp will not behave
    like RSSI on a bench, and you will want to adjust on Friday afternoon without
    reflashing 700 badges."""
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    game = service.current_game(db)
    applied, rejected = service.set_tunables(db, game, body.get("config") or body)
    log_action(db, host, "tunables", None, {"applied": applied, "rejected": rejected})
    return {"applied": applied, "rejected": rejected}


# ---------------------------------------------------------------------------
# Player actions
# ---------------------------------------------------------------------------

@router.post("/v1/admin/player/{pid}")
async def player_action(pid: int, request: Request):
    """kick | revive | void_kill | adjust | reassign | protect (§9.4).

    "The host can void kills, revive victims, adjust scores and kick. This is the
    correct posture for a hacker camp: make cheating possible, visible and
    socially expensive rather than pretending an open flashable badge is
    tamper-proof."
    """
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    game = service.current_game(db)
    cfg = service.config_for(game)
    ts = clock.now()
    action = str(body.get("action") or "")
    p = service.player_by_pid(db, pid)
    if p is None:
        raise HTTPException(status_code=404, detail="no_such_player")

    result = {}
    if action == "kick":
        db.execute("UPDATE players SET base_status=?, kicked_at=?, target_pid=NULL "
                   "WHERE pid=?", (state.KICKED, ts, pid))
        db.commit()
    elif action == "unkick":
        db.execute("UPDATE players SET base_status=?, kicked_at=NULL, protected_until=? "
                   "WHERE pid=?", (state.ACTIVE, ts + int(cfg["SPAWN_PROTECT_S"]), pid))
        db.commit()
    elif action == "revive":
        scoring.revive(db, p, restore_streak=_int(body.get("streak")),
                       protected_until=ts + int(cfg["SPAWN_PROTECT_S"]))
        db.commit()
    elif action == "void_kill":
        kill_id = _int(body.get("kill_id"))
        if kill_id is None:
            raise HTTPException(status_code=400, detail="kill_id_required")
        result = _void_kill(db, kill_id, str(body.get("reason") or "host")[:120])
    elif action == "adjust":
        delta = _int(body.get("delta")) or 0
        db.execute("UPDATE players SET score_adjust=score_adjust+? WHERE pid=?",
                   (delta, pid))
        db.commit()
        result = {"delta": delta}
    elif action == "reassign":
        new_target = _int(body.get("target_pid"))
        if new_target is None:
            db.execute("UPDATE players SET target_pid=NULL WHERE pid=?", (pid,))
            db.commit()
        else:
            if service.player_by_pid(db, new_target) is None:
                raise HTTPException(status_code=404, detail="no_such_target")
            db.execute("UPDATE players SET target_pid=? WHERE pid=?", (new_target, pid))
            db.commit()
        result = {"target_pid": new_target}
    elif action == "protect":
        secs = _int(body.get("seconds"))
        if secs is None:
            secs = int(cfg["SPAWN_PROTECT_S"])
        # `seconds: 0` means *clear* protection, not "protect for the default 90 s"
        # -- a host who wants somebody attackable right now (or a smoke test that
        # cannot wait 90 s) needs a way to say so, and NULL is unambiguous however
        # far in the past an incoming event's timestamp is.
        until = None if secs <= 0 else ts + secs
        db.execute("UPDATE players SET protected_until=? WHERE pid=?", (until, pid))
        db.commit()
        result = {"protected_until": until}
    elif action == "rename":
        name = str(body.get("display_name") or "").strip()[:32]
        if not name:
            raise HTTPException(status_code=400, detail="name_required")
        db.execute("UPDATE players SET display_name=? WHERE pid=?", (name, pid))
        db.commit()
        result = {"display_name": name}
    else:
        raise HTTPException(status_code=400, detail="bad_action")

    service.reconcile(db, game, cfg, ts)
    log_action(db, host, action, pid, {k: v for k, v in body.items() if k != "action"})
    return {"ok": True, "action": action, **result}


def _void_kill(db, kill_id, reason):
    """Undo a kill's score. The victim is revived only if this was the death that
    is still standing -- voiding an old kill must not resurrect someone who has
    since died again."""
    k = db.one("SELECT * FROM kills WHERE id=?", (kill_id,))
    if k is None:
        raise HTTPException(status_code=404, detail="no_such_kill")
    if k["voided"]:
        return {"already_voided": True}
    db.execute("UPDATE kills SET voided=1, void_reason=? WHERE id=?", (reason, kill_id))
    if k["points"]:
        db.execute("UPDATE players SET score=MAX(0, score-?), "
                   "total_kills=MAX(0, total_kills-1) WHERE pid=?",
                   (int(k["points"]), int(k["assassin_pid"])))
    victim = db.one("SELECT * FROM players WHERE pid=?", (int(k["victim_pid"]),))
    revived = False
    if victim is not None and victim["base_status"] == state.DEAD \
            and int(victim["life_id"]) == int(k["victim_life_id"]) + 1:
        scoring.revive(db, victim)
        revived = True
    db.commit()
    return {"voided": kill_id, "revived": revived}


@router.post("/v1/admin/player/{pid}/rebind")
async def player_rebind(pid: int, request: Request):
    """Badge broke, got lost or went in a puddle (§9.4). "You have lost 11 kills
    and your streak" is not an acceptable answer at a camp."""
    host = require_host(request)
    db = request.app.state.db
    body = await _json(request)
    new_key = str(body.get("new_badge_key") or "").strip().lower()
    if not new_key:
        raise HTTPException(status_code=400, detail="new_badge_key_required")
    game = service.current_game(db)
    ok, err = service.rebind(db, game, pid, new_key)
    if not ok:
        raise HTTPException(status_code=409, detail=err)
    log_action(db, host, "rebind", pid, {"new_badge_key": new_key})
    return {"ok": True, "pid": pid, "new_badge_key": new_key}


# ---------------------------------------------------------------------------
# Dashboard, audit, export
# ---------------------------------------------------------------------------

@router.get("/v1/admin/dashboard")
async def dashboard(request: Request):
    require_host(request)
    return build_dashboard(request.app.state.db)


def build_dashboard(db, ts=None):
    """The one document behind the screen (§9.4's table)."""
    ts = clock.now() if ts is None else ts
    game = service.current_game(db)
    cfg = service.config_for(game)

    rows = db.all("SELECT * FROM players WHERE game_id=?", (game["id"],))
    pop = {"enrolled": 0, "alive": 0, "dead": 0, "protected": 0, "opted_out": 0,
           "dormant": 0, "stale": 0, "kicked": 0}
    batt_hist = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0,
                 "unknown": 0}
    low_batt = 0
    versions = {}
    bg_split = {"app": 0, "background": 0}
    synced_15m = 0
    unseen_1h = 0
    for r in rows:
        if r["base_status"] == state.RETIRED:
            continue
        pop["enrolled"] += 1
        st = state.status_of(r, game, db, ts, cfg)
        if st == state.DEAD:
            pop["dead"] += 1
        elif st == state.PROTECTED:
            pop["protected"] += 1
            pop["alive"] += 1
        elif st == state.OPTED_OUT:
            pop["opted_out"] += 1
        elif st == state.DORMANT:
            pop["dormant"] += 1
        elif st == state.STALE:
            pop["stale"] += 1
            pop["alive"] += 1
        elif st == state.KICKED:
            pop["kicked"] += 1
        else:
            pop["alive"] += 1

        b = r["battery"]
        if b is None:
            batt_hist["unknown"] += 1
        else:
            b = int(b)
            if b < 20:
                batt_hist["0-20"] += 1
                low_batt += 1
            elif b < 40:
                batt_hist["20-40"] += 1
            elif b < 60:
                batt_hist["40-60"] += 1
            elif b < 80:
                batt_hist["60-80"] += 1
            else:
                batt_hist["80-100"] += 1
        v = r["app_version"] or "unknown"
        versions[v] = versions.get(v, 0) + 1
        bg_split["background" if r["bg_service"] else "app"] += 1
        if r["last_sync_at"] and ts - int(r["last_sync_at"]) <= 900:
            synced_15m += 1
        seen = r["last_seen_at"] or r["enrolled_at"]
        if seen is None or ts - int(seen) > 3600:
            unseen_1h += 1

    def kills_since(seconds):
        return int(db.scalar(
            "SELECT COUNT(*) FROM kills WHERE game_id=? AND voided=0 AND server_at > ?",
            (game["id"], ts - seconds), default=0))

    reveals_10m = int(db.scalar(
        "SELECT COUNT(*) FROM events WHERE type='reveal' AND accepted=1 AND server_at > ?",
        (ts - 600,), default=0))
    backlog = int(db.scalar(
        "SELECT COUNT(*) FROM events WHERE accepted=0 AND server_at > ?",
        (ts - 3600,), default=0))

    return {
        # First, and biggest on the page (§9.4).
        "kills_10m": kills_since(600),
        "kills_1h": kills_since(3600),
        "kills_total": kills_since(10 ** 9),
        "reveals_10m": reveals_10m,
        "population": pop,
        "health": {"synced_15m": synced_15m, "unseen_1h": unseen_1h,
                   "rejected_events_1h": backlog,
                   "ring_conflicts": service.ring_conflicts(db, game["id"]),
                   "flagged_kills": int(db.scalar(
                       "SELECT COUNT(*) FROM kills WHERE game_id=? AND flagged=1",
                       (game["id"],), default=0))},
        "fleet": {"battery": batt_hist, "below_20": low_batt,
                  "versions": versions, "split": bg_split},
        "game": {"id": int(game["id"]), "name": game["name"], "state": game["state"],
                 "truce_active": state.camp_truce_active(game, ts, db),
                 "truce_until": state.truce_until(game, ts, db),
                 "broadcast": game["broadcast"],
                 "min_version": game["min_version"],
                 "latest_version": game["latest_version"]},
        "leaders": {"total": scoring.board_total(db, game["id"], 5),
                    "streak": scoring.board_streak(db, game["id"], 5),
                    "group_total": scoring.board_group(db, game["id"], False, 3),
                    "group_per_member": scoring.board_group(db, game["id"], True, 3),
                    "hitlist": scoring.hitlist(db, game, cfg, ts)},
        "server_time": ts,
    }


@router.get("/v1/admin/audit")
async def audit(request: Request):
    """Suspicious-pattern report (§9.5). Detection, not prevention: Sybil farming
    is the real hole and D16 removed the natural rate limiter, so this page is
    what carries it."""
    require_host(request)
    db = request.app.state.db
    ts = clock.now()
    game = service.current_game(db)
    cfg = service.config_for(game)

    flagged = [dict(r) for r in db.all(
        "SELECT k.*, a.display_name AS assassin_name, v.display_name AS victim_name "
        "FROM kills k JOIN players a ON a.pid=k.assassin_pid "
        "JOIN players v ON v.pid=k.victim_pid "
        "WHERE k.game_id=? AND k.flagged=1 ORDER BY k.server_at DESC LIMIT 100",
        (game["id"],))]

    # Mutual-only pairs: players who only ever kill each other (§9.5 graph shape).
    pairs = {}
    for r in db.all("SELECT assassin_pid, victim_pid, COUNT(*) AS n FROM kills "
                    "WHERE game_id=? AND voided=0 GROUP BY assassin_pid, victim_pid",
                    (game["id"],)):
        pairs[(int(r["assassin_pid"]), int(r["victim_pid"]))] = int(r["n"])
    partners = {}
    for (a, v), n in pairs.items():
        partners.setdefault(a, set()).add(v)
    mutual = []
    for (a, v), n in sorted(pairs.items()):
        if a < v and (v, a) in pairs:
            if partners.get(a) == {v} and partners.get(v) == {a}:
                mutual.append({"a": a, "b": v, "a_kills_b": n, "b_kills_a": pairs[(v, a)]})

    # Kills with the assassin reporting almost no peers around: a farm in a tent
    # sees nobody (§9.5).
    lonely = [dict(r) for r in db.all(
        "SELECT k.id, k.assassin_pid, k.victim_pid, k.server_at, p.peers_seen "
        "FROM kills k JOIN players p ON p.pid=k.assassin_pid "
        "WHERE k.game_id=? AND k.voided=0 AND COALESCE(p.peers_seen, 99) <= 1 "
        "ORDER BY k.server_at DESC LIMIT 50", (game["id"],))]

    # Enrollments clustered in time from one IP.
    clusters = [dict(r) for r in db.all(
        "SELECT ip, COUNT(*) AS n, MIN(at) AS first_at, MAX(at) AS last_at "
        "FROM enroll_attempts WHERE outcome='ok' GROUP BY ip HAVING n >= 5 "
        "ORDER BY n DESC LIMIT 20")]

    rate = [dict(r) for r in db.all(
        "SELECT assassin_pid, COUNT(*) AS n FROM kills WHERE game_id=? AND voided=0 "
        "AND server_at > ? GROUP BY assassin_pid HAVING n > ? ORDER BY n DESC",
        (game["id"], ts - 3600, int(cfg["MAX_KILLS_PER_HOUR"])))]

    return {"flagged_kills": flagged, "mutual_only_pairs": mutual,
            "kills_with_no_peers": lonely, "enroll_clusters": clusters,
            "over_rate_limit": rate,
            "admin_log": [dict(r) for r in db.all(
                "SELECT * FROM admin_log ORDER BY id DESC LIMIT 50")]}


@router.get("/v1/admin/export")
async def export(request: Request, fmt: str = "json"):
    """Full dump (§9.4). `player_key` is never exported -- it is a credential, and
    a CSV on a volunteer's phone is not where it belongs."""
    require_host(request)
    db = request.app.state.db
    game = service.current_game(db)
    players = [{k: r[k] for k in r.keys() if k != "player_key"}
               for r in db.all("SELECT * FROM players WHERE game_id=?", (game["id"],))]
    kills = [dict(r) for r in db.all("SELECT * FROM kills WHERE game_id=?",
                                     (game["id"],))]
    if fmt == "csv":
        return Response(_csv(players), media_type="text/csv",
                        headers={"Content-Disposition":
                                 "attachment; filename=gotcha_players.csv"})
    return {"game": dict(game), "players": players, "kills": kills,
            "groups": [dict(r) for r in db.all("SELECT * FROM player_groups")],
            "admin_log": [dict(r) for r in db.all("SELECT * FROM admin_log")]}


def _csv(rows):
    if not rows:
        return ""
    cols = list(rows[0].keys())
    out = [",".join(cols)]
    for r in rows:
        out.append(",".join(_csv_cell(r.get(c)) for c in cols))
    return "\n".join(out) + "\n"


def _csv_cell(v):
    if v is None:
        return ""
    s = str(v)
    if any(c in s for c in ',"\n'):
        return '"' + s.replace('"', '""') + '"'
    return s


async def _json(request):
    try:
        raw = await request.body()
        return json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(status_code=400, detail="bad_json")


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
