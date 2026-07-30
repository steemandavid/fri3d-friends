"""FastAPI application: the player-facing API (plan §9.2).

The routes are thin. Every rule lives in `service.py`, `events.py`, `scoring.py`
or `state.py`, so the game is testable without HTTP and there is exactly one
place each rule is written down.

Two faces, one process (§6.2, D31): HTTPS on :443 for `/v1/enroll` and the web
pages, plain signed HTTP on :80 for everything a badge calls afterwards. Nothing
in this file knows which port it was reached on -- the split is a deployment
concern, and the signature scheme means the plain-HTTP face is not the weaker one.
"""

import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import admin as admin_mod
from . import auth, clock, crypto, events, pages, scoring, service, state
from .config import DEFAULTS, Settings
from .db import Database

# Player-facing status names are Dutch (D26), ASCII only.
STATUS_NL = {
    "active": "in het spel",
    "protected": "beschermd",
    "dead": "uitgeschakeld",
    "opted_out": "uitgeschreven",
    "dormant": "badge slaapt",
    "stale": "niet gezien",
    "kicked": "verwijderd",
    "retired": "oude badge",
}


def create_app(settings=None, db=None, clock_impl=None):
    settings = settings or Settings()
    if clock_impl is not None:
        clock.set_clock(clock_impl)
    database = db or Database(settings.db_path)

    # The server secret signs admin sessions and player-card tokens. Generated on
    # first boot and stored, so restarting the service does not log every host out
    # or invalidate every QR code a badge has already rendered.
    secret = settings.secret or database.get_meta("server_secret")
    if not secret:
        secret = crypto.new_server_secret()
        database.set_meta("server_secret", secret)
    if settings.admin_password:
        h, salt = crypto.password_hash(settings.admin_password)
        database.set_meta("admin_pw_hash", h)
        database.set_meta("admin_pw_salt", salt)

    app = FastAPI(title="Fri3d Gotcha backend", version="0.11.0-phase1",
                  docs_url="/api-docs", redoc_url=None)
    app.state.db = database
    app.state.settings = settings
    app.state.secret = secret
    service.ensure_game(database)

    # -----------------------------------------------------------------------
    # POST /v1/enroll -- the only HTTPS call, and the only unsigned one (§6.2)
    # -----------------------------------------------------------------------
    @app.post("/v1/enroll")
    async def enroll(request: Request):
        db = app.state.db
        ts = clock.now()
        ip = request.client.host if request.client else "?"
        try:
            body = json.loads(await request.body() or b"{}")
        except Exception:
            raise HTTPException(status_code=400, detail="bad_json")

        badge_key = str(body.get("badge_key") or "").strip().lower()
        display_name = str(body.get("display_name") or "").strip()[:32]
        commitment = str(body.get("commitment") or "").strip().lower()
        groups = body.get("groups") or []
        if not badge_key or len(badge_key) > 32:
            raise HTTPException(status_code=400, detail="bad_badge_key")
        if len(commitment) != 64:
            raise HTTPException(status_code=400, detail="bad_commitment")
        if not display_name:
            display_name = "Badge %s" % badge_key[-4:]

        game = service.current_game(db)
        cfg = service.config_for(game)
        if not auth.enroll_rate_ok(db, ip, badge_key, ts, cfg):
            auth.note_enroll_attempt(db, ip, badge_key, ts, "rate_limited")
            raise HTTPException(status_code=429, detail="slow_down")

        player, err = service.enroll(
            db, game, badge_key, display_name, groups, commitment,
            app_version=str(body.get("app_version") or "")[:16] or None,
            board=str(body.get("board") or "")[:16] or None, config=cfg, ts=ts)
        auth.note_enroll_attempt(db, ip, badge_key, ts, err or "ok")
        if err:
            raise HTTPException(status_code=409, detail=err)
        return {"pid": int(player["pid"]), "player_key": player["player_key"],
                "game_id": int(game["id"])}

    # -----------------------------------------------------------------------
    # GET /v1/sync -- the only thing the badge polls (§9.2, D13)
    # -----------------------------------------------------------------------
    @app.get("/v1/sync")
    async def sync(request: Request):
        db = app.state.db
        game = service.current_game(db)
        cfg = service.config_for(game)
        player, nonce, ts = await auth.verify_request(request, db, cfg)
        service.note_return(db, game, player, cfg, ts)
        service.note_sync(db, int(player["pid"]), ts)
        db.commit()
        service.reconcile(db, game, cfg, ts)
        player = service.player_by_pid(db, int(player["pid"]))
        payload = service.sync_payload(db, game, player, cfg, ts, app.state.secret)
        return auth.signed(player, nonce, payload, ts)

    # -----------------------------------------------------------------------
    # POST /v1/events -- the offline queue's flush target (§9.2, §9.3)
    # -----------------------------------------------------------------------
    @app.post("/v1/events")
    async def post_events(request: Request):
        db = app.state.db
        game = service.current_game(db)
        cfg = service.config_for(game)
        player, nonce, ts = await auth.verify_request(request, db, cfg)
        service.note_return(db, game, player, cfg, ts)
        try:
            body = json.loads(await request.body() or b"{}")
        except Exception:
            return auth.signed(player, nonce, {"accepted": [], "rejected": [],
                                               "error": "bad_json"}, ts)
        evs = body.get("events") or []
        if not isinstance(evs, list):
            return auth.signed(player, nonce, {"accepted": [], "rejected": [],
                                               "error": "bad_events"}, ts)
        cap = int(cfg.get("MAX_EVENTS_PER_POST", DEFAULTS["MAX_EVENTS_PER_POST"]))
        overflow = [{"uuid": (e or {}).get("uuid"), "reason": "too_many"}
                    for e in evs[cap:]]
        accepted, rejected = events.ingest_batch(db, game, player, evs[:cap], cfg, ts)
        return auth.signed(player, nonce,
                           {"accepted": accepted, "rejected": rejected + overflow}, ts)

    # -----------------------------------------------------------------------
    # GET /v1/leaderboard -- signed like everything else on the badge path
    # -----------------------------------------------------------------------
    @app.get("/v1/leaderboard")
    async def leaderboard(request: Request, board: str = "total", limit: int = 50):
        db = app.state.db
        game = service.current_game(db)
        cfg = service.config_for(game)
        player, nonce, ts = await auth.verify_request(request, db, cfg)
        limit = max(1, min(int(limit), 200))
        payload = {"board": board, "entries": board_entries(db, game, board, limit, cfg, ts)}
        return auth.signed(player, nonce, payload, ts)

    # Public, unsigned copy for the web pages (same origin, D31). Read-only
    # public data only -- exactly what the leaderboard page publishes anyway.
    @app.get("/v1/public/leaderboard")
    async def public_leaderboard(board: str = "total", limit: int = 50):
        db = app.state.db
        game = service.current_game(db)
        cfg = service.config_for(game)
        limit = max(1, min(int(limit), 200))
        return {"board": board,
                "entries": board_entries(db, game, board, limit, cfg, clock.now())}

    # -----------------------------------------------------------------------
    # Public read-only views for the web pages (same origin, D31).
    # -----------------------------------------------------------------------
    @app.get("/v1/public/player/{pid}")
    async def public_player(pid: int, t: str = ""):
        """Public player card. The *private* half -- your current target -- needs
        the short-lived read token the badge puts in its QR (§9.1)."""
        db = app.state.db
        game = service.current_game(db)
        cfg = service.config_for(game)
        ts = clock.now()
        p = service.player_by_pid(db, pid)
        if p is None or p["game_id"] != game["id"]:
            raise HTTPException(status_code=404, detail="no_such_player")
        status = state.status_of(p, game, db, ts, cfg)
        rank_total, rank_streak = scoring.ranks_for(db, game["id"], pid)
        out = {
            "pid": pid,
            "name": p["display_name"],
            "status": status,
            "status_nl": STATUS_NL.get(status, status),
            "score": int(p["score"] or 0) + int(p["score_adjust"] or 0),
            "kills": int(p["total_kills"] or 0),
            "deaths": int(p["deaths"] or 0),
            "streak": state.derived_streak(p, game, cfg, ts, db),
            "best_streak": int(p["best_streak"] or 0),
            "rank_total": rank_total,
            "rank_streak": rank_streak,
            "groups": [r["name"] for r in
                       db.all("SELECT name FROM player_groups WHERE pid=?", (pid,))],
        }
        if t and crypto.card_token_ok(app.state.secret, pid, t, ts) \
                and p["target_pid"] is not None and status in state.HUNTS:
            tgt = service.player_by_pid(db, int(p["target_pid"]))
            if tgt is not None:
                seen = tgt["last_seen_at"] or tgt["enrolled_at"] or ts
                out["target"] = {"pid": int(tgt["pid"]), "name": tgt["display_name"],
                                 "last_seen_ago_s": max(0, ts - int(seen))}
        return out

    @app.get("/v1/public/hitlist")
    async def public_hitlist():
        db = app.state.db
        game = service.current_game(db)
        cfg = service.config_for(game)
        return {"hitlist": scoring.hitlist(db, game, cfg, clock.now())}

    @app.get("/healthz")
    async def healthz():
        db = app.state.db
        game = service.current_game(db)
        return {"ok": True, "game_state": game["state"] if game else None,
                "players": int(db.scalar("SELECT COUNT(*) FROM players", default=0)),
                "server_time": clock.now()}

    app.include_router(admin_mod.router)
    app.include_router(pages.router)

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app


def board_entries(db, game, board, limit, cfg, ts):
    if board == "streak":
        return scoring.board_streak(db, game["id"], limit)
    if board == "group_total":
        return scoring.board_group(db, game["id"], per_member=False, limit=limit)
    if board == "group_per_member":
        return scoring.board_group(db, game["id"], per_member=True, limit=limit)
    return scoring.board_total(db, game["id"], limit)
