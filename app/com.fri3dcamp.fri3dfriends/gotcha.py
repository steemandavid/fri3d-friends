# gotcha.py -- the "Gotcha" (Assassin) game for !Fri3d Friends.
#
# Two cleanly separated halves (same convention as ble_proximity.py /
# contact_exchange.py), so the PURE half imports on a host and is unit-tested
# off-device with pytest:
#
#   1. PURE LOGIC (no `bluetooth` / `mpos` / `lvgl` / `asyncio`):
#        - crypto:        hmac_sha256, canonical_json, sign_request / response_sig
#                         / sig_ok  (the signed-plain-HTTP scheme, plan §6.2)
#        - kill proof:    make_soul / commitment / verify_soul  (the "soul", §3.4)
#        - versions:      version_lt  (per-component numeric compare, §8.10)
#      (The remaining pure helpers -- GameConfig, truce_active, DuelState,
#      EventQueue, DodgeLedger, hunt_bar, rssi_trend, hunt_ping, TrainingSession
#      -- arrive with Phases 1-2; this file grows then.)
#
#   2. The radio wrappers (GotchaResponder / GotchaHunter / GotchaSync) arrive
#      with Phases 2-4. They import `bluetooth`/`mpos` lazily, as the other radio
#      wrappers do, so this module still loads on a host.
#
# Transport decision (plan D21): plain HTTP with HMAC-SHA256-signed requests AND
# responses, except ONE HTTPS call at enrollment that bootstraps player_key.
# Authenticity is the property that matters on the camp network; secrecy is not
# (kill proofs are self-authenticating, scores are published). MicroPython has no
# `hmac` module, so HMAC-SHA256 is implemented by hand over hashlib.sha256
# (RFC 2104) and verified against the RFC 4231 test vectors in tests/test_gotcha.py.

import hashlib

# ---------------------------------------------------------------------------
# 1a. CRYPTO -- HMAC-SHA256 and canonical JSON (plan §6.2)
# ---------------------------------------------------------------------------

_SHA256_BLOCK = 64            # SHA-256 block size in bytes (RFC 2104)


def _sha256(b):
    return hashlib.sha256(b).digest()


def hmac_sha256(key, msg):
    """RFC-2104 HMAC-SHA256. `key` and `msg` are bytes; returns 32 bytes.

    Implemented by hand because MicroPython ships no `hmac` module. Keys longer
    than the 64-byte block are hashed first; shorter keys are zero-padded.
    """
    if len(key) > _SHA256_BLOCK:
        key = _sha256(key)
    key = key + b"\x00" * (_SHA256_BLOCK - len(key))
    i_pad = bytes(b ^ 0x36 for b in key)
    o_pad = bytes(b ^ 0x5c for b in key)
    return _sha256(o_pad + _sha256(i_pad + msg))


def hmac_sha256_hex(key, msg):
    """Hex-digest HMAC-SHA256 (what rides in X-Sig / the response `sig`)."""
    h = hmac_sha256(key, msg)
    return "".join("%02x" % b for b in h)


def _cj_str(s):
    """JSON string with minimal, deterministic escaping (matches CPython)."""
    out = ['"']
    for ch in s:
        c = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif c < 0x20:
            out.append('\\u%04x' % c)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _cj_float(f):
    # Deterministic enough for the integer/string payloads this game signs; a
    # float in a signed payload would be a bug, so render it and move on.
    if f == int(f) and not (f == 0 and str(f) == "-0.0"):
        return str(int(f))
    return repr(f)


def _cj(o, out):
    if o is None:
        out.append("null")
    elif o is True:
        out.append("true")
    elif o is False:
        out.append("false")
    elif isinstance(o, str):
        out.append(_cj_str(o))
    elif isinstance(o, int):
        out.append(str(o))
    elif isinstance(o, float):
        out.append(_cj_float(o))
    elif isinstance(o, dict):
        out.append("{")
        first = True
        for k in sorted(o.keys()):
            if not first:
                out.append(",")
            first = False
            out.append(_cj_str(str(k)))
            out.append(":")
            _cj(o[k], out)
        out.append("}")
    elif isinstance(o, (list, tuple)):
        out.append("[")
        first = True
        for v in o:
            if not first:
                out.append(",")
            first = False
            _cj(v, out)
        out.append("]")
    else:
        out.append(_cj_str(str(o)))


def canonical_json(obj):
    """Deterministic JSON: keys sorted, no whitespace (plan §6.2).

    Hand-rolled rather than json.dumps(sort_keys=...) so byte output is identical
    on MicroPython and CPython -- required because both the badge signer and the
    server verifier hash this exact string.
    """
    out = []
    _cj(obj, out)
    return "".join(out)


def _req_message(method, path, ts, nonce, body):
    """The byte string a badge signs for a request:
    METHOD || PATH || ts || nonce || body  (plan §6.2)."""
    msg = method.encode("utf-8") + path.encode("utf-8")
    msg += str(ts).encode("utf-8") + str(nonce).encode("utf-8")
    msg += body or b""
    return msg


def sign_request(key_hex, method, path, ts, nonce, body=b""):
    """X-Sig for an outgoing request. `key_hex` is the 32-byte player_key as hex;
    `body` is the EXACT bytes sent (b'' for GET). Server verifies over the raw
    received body, so never re-serialise on the server -- hash what arrived."""
    return hmac_sha256_hex(bytes.fromhex(key_hex), _req_message(method, path, ts, nonce, body))


def response_sig(key_hex, ts, nonce, payload):
    """The `sig` field of a signed response envelope:
    HMAC(player_key, ts || nonce || canonical_json(payload))  (plan §6.2)."""
    key = bytes.fromhex(key_hex)
    msg = str(ts).encode("utf-8") + str(nonce).encode("utf-8") + canonical_json(payload).encode("utf-8")
    return hmac_sha256_hex(key, msg)


def _ct_eq(a, b):
    """Constant-time-ish string compare (the server may forge over plain HTTP,
    so prefer this over `==` for signature checks)."""
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a, b):
        r |= ord(x) ^ ord(y)
    return r == 0


def sig_ok(key_hex, ts, nonce, payload, sig_hex):
    """Verify a response envelope's signature. Bad input -> False, never raises."""
    try:
        return _ct_eq(response_sig(key_hex, ts, nonce, payload), sig_hex or "")
    except Exception:
        return False


def make_envelope(ts, nonce, sig_hex, payload):
    """Build the {ts, nonce, sig, payload} body envelope (plan §6.2).

    Pure helper used by the server signer; the badge parses this exact shape and
    re-checks sig + nonce match."""
    return {"ts": ts, "nonce": nonce, "sig": sig_hex, "payload": payload}


# ---------------------------------------------------------------------------
# 1b. KILL PROOF -- the "soul" (commitment / disclosure, plan §3.4)
# ---------------------------------------------------------------------------

SOUL_LEN = 16


def make_soul(urandom=None):
    """A fresh 16-byte random secret (a 'soul'). `urandom(os.urandom by default)
    is injectable for deterministic tests. Only the sha256 commitment is ever
    uploaded; the backend never learns the soul."""
    if urandom is not None:
        return urandom(SOUL_LEN)
    try:
        import os
        return os.urandom(SOUL_LEN)
    except Exception:                                  # host fallback only
        return _sha256(b"gotcha-soul")[:SOUL_LEN]


def commitment(soul):
    """sha256(soul) as hex -- the value uploaded at enroll/respawn."""
    return hashlib.sha256(soul).hexdigest()


def verify_soul(soul, commitment_hex):
    """True iff sha256(soul) == the victim's current-life commitment."""
    try:
        return hashlib.sha256(soul).hexdigest() == commitment_hex
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 1c. VERSION COMPARE (plan §8.10 -- "0.10.0" < "0.9.0" is False)
# ---------------------------------------------------------------------------

def _ver_parts(s):
    out = []
    for part in str(s).split("."):
        num = ""
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        out.append(int(num) if num else 0)
    return out


def version_lt(a, b):
    """Per-component numeric compare: True iff version a is strictly older than b.
    Never compares as strings (so 0.10.0 > 0.9.0)."""
    pa, pb = _ver_parts(a), _ver_parts(b)
    n = max(len(pa), len(pb))
    pa = pa + [0] * (n - len(pa))
    pb = pb + [0] * (n - len(pb))
    return pa < pb
