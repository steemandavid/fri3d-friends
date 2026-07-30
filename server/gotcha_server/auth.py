"""Request/response signing for the badge path (plan §6.2, §9.1).

There is **no bearer token**. Every badge request carries `X-Pid`, `X-Ts`,
`X-Nonce` and `X-Sig`, and every response body is a signed envelope binding the
request's nonce. Nothing replayable crosses the link; the `player_key` is
transmitted exactly once, over TLS, at enrollment.

Failure mode note: an unauthenticated request gets an **unsigned** error, which
the badge is required to discard (§6.2). That is deliberate -- if we cannot
verify the caller, there is no key with which to say anything trustworthy back,
so saying nothing trustworthy is the correct answer.
"""

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from . import clock, crypto
from .config import DEFAULTS


def signing_path(request):
    """The exact string the badge signed: path plus query string if present.

    The plan writes "METHOD || PATH"; we pin it to the full request target so a
    tampered `?board=` or `?limit=` cannot pass verification. `crypto.py` carries
    the same note -- the badge must sign the string it puts on the request line.
    """
    q = request.url.query
    return request.url.path + (("?" + q) if q else "")


def prune_nonces(db, ts, window):
    db.execute("DELETE FROM nonces WHERE ts < ?", (ts - window - 60,))


async def verify_request(request, db, config=None):
    """Verify a signed badge request. Returns (player_row, nonce, now_ts).

    Raises HTTPException(401) with a short, deliberately uninformative detail:
    the badge acts only on the signed payload and cannot read the status anyway
    (§6.2 -- `DownloadManager` returns the body only), so the detail exists for
    the server log and for `curl`, not for the badge.
    """
    cfg = config or DEFAULTS
    ts = clock.now()
    window = int(cfg.get("SIG_WINDOW_S", DEFAULTS["SIG_WINDOW_S"]))

    pid_raw = request.headers.get("X-Pid")
    ts_raw = request.headers.get("X-Ts")
    nonce = request.headers.get("X-Nonce")
    sig = request.headers.get("X-Sig")
    if not (pid_raw and ts_raw and nonce and sig):
        raise HTTPException(status_code=401, detail="unsigned")
    try:
        pid = int(pid_raw)
        req_ts = int(ts_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="bad_headers")
    if not (4 <= len(nonce) <= 64) or not all(c in "0123456789abcdefABCDEF" for c in nonce):
        raise HTTPException(status_code=401, detail="bad_nonce")

    # Generous ±10 min: badge RTCs drift and are corrected by clock_offset_s.
    if abs(ts - req_ts) > window:
        raise HTTPException(status_code=401, detail="stale_ts")

    player = db.one("SELECT * FROM players WHERE pid=?", (pid,))
    if player is None:
        raise HTTPException(status_code=401, detail="no_such_pid")

    body = await request.body()
    expected = crypto.sign_request(player["player_key"], request.method,
                                   signing_path(request), req_ts, nonce, body)
    if not crypto.sig_ok(expected, sig):
        raise HTTPException(status_code=401, detail="bad_sig")

    # Replay: the nonce cache only has to cover the acceptance window, because
    # anything older is already refused by the timestamp check above.
    prune_nonces(db, ts, window)
    try:
        db.execute("INSERT INTO nonces(pid, nonce, ts) VALUES(?,?,?)",
                   (pid, nonce, ts))
        db.commit()
    except Exception:
        raise HTTPException(status_code=401, detail="replay")

    return player, nonce, ts


def signed(player, nonce, payload, ts=None, status_code=200):
    """A signed response envelope (§6.2). The badge verifies `sig` and that
    `nonce` matches the nonce it just sent, and discards anything else."""
    ts = clock.now() if ts is None else ts
    env = crypto.envelope(player["player_key"], ts, nonce, payload)
    return JSONResponse(env, status_code=status_code)


def enroll_rate_ok(db, ip, badge_key, ts, config=None):
    """Rate-limit enrollment by IP and badge_key (§9.2). Enrollment is the one
    unsigned endpoint, so it is the one that needs a limiter at all."""
    cfg = config or DEFAULTS
    per_ip = int(cfg.get("ENROLL_MAX_PER_IP_HOUR", DEFAULTS["ENROLL_MAX_PER_IP_HOUR"]))
    n_ip = int(db.scalar("SELECT COUNT(*) FROM enroll_attempts WHERE ip=? AND at > ?",
                         (ip, ts - 3600), default=0))
    if n_ip >= per_ip:
        return False
    n_key = int(db.scalar(
        "SELECT COUNT(*) FROM enroll_attempts WHERE badge_key=? AND at > ?",
        (badge_key, ts - 300), default=0))
    return n_key < 5


def note_enroll_attempt(db, ip, badge_key, ts, outcome):
    db.execute("INSERT INTO enroll_attempts(ip, badge_key, at, outcome) "
               "VALUES(?,?,?,?)", (ip, badge_key, ts, outcome))
    db.commit()
