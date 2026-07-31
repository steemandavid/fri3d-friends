"""Server side of the signed-plain-HTTP scheme (plan §6.2, D21).

The badge signs with a hand-rolled HMAC-SHA256 over a hand-rolled canonical JSON
(MicroPython has no `hmac`); the server uses the stdlib. Both must produce the
*same bytes*, so:

  - `canonical_json` here is `json.dumps(sort_keys=True, separators=(",", ":"))`,
    which `tests/test_gotcha.py` already cross-checks against the badge's
    `gotcha.canonical_json`, and `tests/test_server_parity.py` re-checks against
    this module for the exact payload shapes the API returns.
  - the message layouts (`METHOD || PATH || ts || nonce || body` for requests,
    `ts || nonce || canonical_json(payload)` for responses) are copied from
    `gotcha.py`, not re-derived.

PATH means the **full request target including the query string** (e.g.
`/v1/leaderboard?board=total&limit=50`). The plan writes "METHOD || PATH"; this
module pins the ambiguity to the stricter reading, so a tampered `?board=` or
`?limit=` cannot pass. The badge must sign the same string it puts on the
request line.
"""

import hashlib
import hmac
import json
import os
import secrets


def _normalize_floats(obj):
    """Render an integral-valued float the way the badge does (D11).

    The badge's hand-rolled `canonical_json` emits `2500.0` and `1.0` as `2500`
    and `1` (see `gotcha._cj_float`); stdlib `json.dumps` emits `2500.0`/`1.0`.
    Because both sides HMAC over `canonical_json(payload)`, that one-character
    disagreement silently breaks *every* response signature the moment an admin
    stores an integral-valued tunable (e.g. `PROX_ALPHA_UP: 1.0`). Collapsing
    integral floats to ints here makes the two implementations agree for all
    values, whatever the wire JSON happens to look like.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        # Mirror the badge's _cj_float exactly, including its -0.0 guard: an
        # integral float collapses to its int form, EXCEPT negative zero, which
        # the badge renders as "-0.0".
        try:
            if obj == int(obj) and not (obj == 0.0 and str(obj) == "-0.0"):
                return int(obj)
        except (ValueError, OverflowError):
            pass
        return obj
    if isinstance(obj, dict):
        return {k: _normalize_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_floats(v) for v in obj]
    return obj


def canonical_json(obj):
    """Keys sorted, no whitespace (plan §6.2)."""
    return json.dumps(_normalize_floats(obj), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)


def hmac_hex(key, msg):
    """HMAC-SHA256 hex. `key` is bytes, `msg` is bytes."""
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def key_bytes(key_hex):
    return bytes.fromhex(key_hex)


def request_message(method, path, ts, nonce, body):
    """METHOD || PATH || ts || nonce || BODY -- the bytes a badge signs.

    `body` is the EXACT bytes received; never re-serialise before hashing, or a
    semantically identical but differently formatted body will fail to verify.
    """
    msg = method.encode("utf-8") + path.encode("utf-8")
    msg += str(ts).encode("utf-8") + str(nonce).encode("utf-8")
    return msg + (body or b"")


def sign_request(key_hex, method, path, ts, nonce, body=b""):
    """X-Sig for a request (used by the badge simulator and the smoke tool)."""
    return hmac_hex(key_bytes(key_hex), request_message(method, path, ts, nonce, body))


def response_sig(key_hex, ts, nonce, payload):
    """`sig` for a response envelope: HMAC(key, ts || nonce || cjson(payload))."""
    msg = str(ts).encode("utf-8") + str(nonce).encode("utf-8")
    msg += canonical_json(payload).encode("utf-8")
    return hmac_hex(key_bytes(key_hex), msg)


def envelope(key_hex, ts, nonce, payload):
    """The signed response body: {ts, nonce, sig, payload} (plan §6.2).

    `nonce` is the *request's* nonce, so a response cannot be lifted from one
    request and replayed against another.
    """
    return {
        "ts": ts,
        "nonce": nonce,
        "sig": response_sig(key_hex, ts, nonce, payload),
        "payload": payload,
    }


def sig_ok(expected_hex, given_hex):
    """Constant-time signature compare."""
    if not isinstance(given_hex, str) or len(given_hex) != len(expected_hex):
        return False
    return hmac.compare_digest(expected_hex, given_hex)


def new_player_key():
    """A fresh 32-byte player_key as hex (issued once, over HTTPS, at enroll)."""
    return secrets.token_hex(32)


def new_server_secret():
    """Server-side secret for admin sessions and card read tokens."""
    return secrets.token_hex(32)


def sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def verify_soul(soul_hex, commitment_hex):
    """The kill proof (§3.4): accept iff sha256(soul) == the victim's current
    commitment. `soul_hex` is the 16-byte soul, hex-encoded, as the assassin
    reports it. Bad input is a failed proof, never an exception."""
    try:
        soul = bytes.fromhex(str(soul_hex))
    except Exception:
        return False
    if len(soul) != 16:
        return False
    if not isinstance(commitment_hex, str) or not commitment_hex:
        return False
    return hmac.compare_digest(sha256_hex(soul), commitment_hex.lower())


# ---------------------------------------------------------------------------
# Card read tokens (§9.1) -- stateless, so nothing to store or expire-sweep.
# ---------------------------------------------------------------------------

def card_token(server_secret, pid, exp):
    """Short-lived read token for the private player card, rendered into the QR
    on the badge. Stateless: `<exp>.<mac>`, verified without a DB round trip."""
    mac = hmac_hex(server_secret.encode("utf-8"), b"card:%d:%d" % (int(pid), int(exp)))
    return "%d.%s" % (int(exp), mac[:32])


def card_token_ok(server_secret, pid, token, now_ts):
    try:
        exp_s, mac = str(token).split(".", 1)
        exp = int(exp_s)
    except Exception:
        return False
    if now_ts > exp:
        return False
    return sig_ok(card_token(server_secret, pid, exp).split(".", 1)[1], mac)


# ---------------------------------------------------------------------------
# Admin session cookies (§9.4) -- signed, so no server-side session table.
# ---------------------------------------------------------------------------

def session_cookie(server_secret, host_name, exp):
    payload = "%s|%d" % (host_name, int(exp))
    mac = hmac_hex(server_secret.encode("utf-8"), b"admin:" + payload.encode("utf-8"))
    return "%s|%s" % (payload, mac)


def session_host(server_secret, cookie, now_ts):
    """Returns the host (volunteer) name from a valid cookie, else None.

    Admin actions are attributed to this name in the audit log -- plan §9.4
    ("Admin actions are logged with which host performed them")."""
    try:
        host_name, exp_s, mac = str(cookie).rsplit("|", 2)
        exp = int(exp_s)
    except Exception:
        return None
    if now_ts > exp:
        return None
    expected = session_cookie(server_secret, host_name, exp).rsplit("|", 1)[1]
    return host_name if sig_ok(expected, mac) else None


def password_ok(stored_hash, salt, given):
    """PBKDF2 check for the admin password (one shared password, several hosts;
    the host *name* is typed at login and is not a credential)."""
    if not stored_hash:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", given.encode("utf-8"),
                             bytes.fromhex(salt), 120_000)
    return hmac.compare_digest(dk.hex(), stored_hash)


def password_hash(password):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return dk.hex(), salt.hex()
