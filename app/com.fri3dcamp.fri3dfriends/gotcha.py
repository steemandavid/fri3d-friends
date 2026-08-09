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


def _hex(b):
    """bytes -> lowercase hex. Manual because MicroPython's hashlib sha256 has
    .digest() but NO .hexdigest() (unlike CPython) -- so commitment()/verify_soul()
    must not use .hexdigest(). Identical output to CPython's hexdigest()."""
    return "".join("%02x" % x for x in b)


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
    return _hex(hashlib.sha256(soul).digest())


def verify_soul(soul, commitment_hex):
    """True iff sha256(soul) == the victim's current-life commitment."""
    try:
        return _hex(hashlib.sha256(soul).digest()) == commitment_hex
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


# ---------------------------------------------------------------------------
# 1d. GAME CONFIG -- defensive parse of the server-pushed tunables (plan §5.4)
# ---------------------------------------------------------------------------
#
# /v1/sync returns a `config` block of live-tunable constants (the server's
# TUNABLE_DEFAULTS, server/gotcha_server/config.py) and a `game` block carrying
# the camp truce schedule. GameConfig.from_sync() parses both defensively: it
# never raises, coerces every value to the type of its default, ignores unknown
# keys (so a tampered signed payload cannot smuggle in a knob), and falls back
# to the badge defaults below so the game is playable before the first sync and
# survives a malformed block. Every value here is overwritten on first sync.

# These mirror server/gotcha_server/config.py TUNABLE_DEFAULTS exactly; keeping
# a copy on the badge means a never-synced badge still plays a sane game and the
# unit tests have something to assert against.
DEFAULTS = {
    "KILL_RSSI": -65, "KILL_HOLD_MS": 5000, "FLEE_RSSI": -78, "FLEE_MS": 1500,
    "REVEAL_RSSI": -80, "REVEAL_COOLDOWN_S": 120, "REVEAL_FLASH_MS": 2500,
    "PING_ENABLED": True, "PING_FROM_SEG": 3, "PING_MS": 40,
    "PING_FREQ_FAR": 1400, "PING_FREQ_NEAR": 2400, "PING_INTERVAL_NEAR": 350,
    "PROX_ALPHA_UP": 0.60, "PROX_ALPHA_DOWN": 0.08,
    "DODGE_LIMIT": 1, "DODGE_DECAY_MS": 3600000, "INSTANT_KILL_MS": 1000,
    "ATTACK_COOLDOWN_MS": 60000, "RESPAWN_S": 1800, "SPAWN_PROTECT_S": 90,
    "BOUNTY_STREAK": 3, "STREAK_GRACE_S": 10800, "STREAK_DECAY_S": 7200,
    "QUIET_EARLIEST": "20:00", "QUIET_LATEST": "10:00",
    "TRAINING_WINDOW_S": 10, "TRAINING_SESSION_S": 300, "TRAINING_REENTRY_S": 600,
    "SYNC_S": 300, "HUNT_SYNC_DEFER": True, "HUNT_SYNC_DEFER_MAX_S": 900,
    "reveal_enabled": True, "bounty_enabled": True,
    "training_enabled": False, "alarm_enabled": True,
    # Camp truce schedule (camp-local HH:MM), cached from the sync `game` block.
    # Default is the camp-wide 22:00-08:00 night truce (D7).
    "truce_from": "22:00", "truce_to": "08:00",
}


def _coerce(val, default):
    """Coerce `val` to the type of `default`; bad input -> `default`."""
    try:
        if isinstance(default, bool):
            if isinstance(val, str):
                return val.strip().lower() in ("1", "true", "yes", "on")
            return bool(val)
        if isinstance(default, int):
            return int(val)
        if isinstance(default, float):
            return float(val)
        return str(val)
    except Exception:
        return default


class GameConfig(object):
    """Typed, read-only view of the server-pushed tunables + truce schedule.

    Access values with cfg.get("KILL_RSSI") (returns the default if unset). Built
    via from_sync(); the bare constructor gives the badge defaults.
    """

    def __init__(self):
        self.d = dict(DEFAULTS)

    @classmethod
    def from_sync(cls, config_block=None, game_block=None):
        """Parse the sync response's `config` (tunables) and `game` (schedule).

        Never raises. Only known keys are kept; unknown ones are dropped."""
        cfg = cls()
        c = config_block if isinstance(config_block, dict) else {}
        for k in DEFAULTS:
            if k in c:
                cfg.d[k] = _coerce(c[k], DEFAULTS[k])
        g = game_block if isinstance(game_block, dict) else {}
        sched = g.get("truce_schedule")
        if isinstance(sched, dict):
            # Fail CLOSED (D25): only adopt a schedule whose BOTH ends parse as
            # HH:MM. A host typing "22.00" instead of "22:00" must not silently
            # disable the camp night truce on every badge -- the §10.4 failure mode
            # is a screaming badge in a tent of sleeping children. A malformed
            # value keeps the DEFAULTS 22:00-08:00 window.
            tf = parse_hm(sched.get("from"))
            tt = parse_hm(sched.get("to"))
            if tf is not None and tt is not None:
                cfg.d["truce_from"] = str(sched["from"])
                cfg.d["truce_to"] = str(sched["to"])
        return cfg

    def get(self, key, fallback=None):
        v = self.d.get(key, DEFAULTS.get(key))
        if v is None:
            return fallback
        return v

    def __getitem__(self, key):
        return self.get(key)


# ---------------------------------------------------------------------------
# 1e. TIME -- truce and personal quiet hours, server-clock corrected (§10.4)
# ---------------------------------------------------------------------------
#
# Server times are true UTC unix seconds (server/gotcha_server/clock.py). The
# badge is NTP-synced to UTC, so effective_now = time.time() + clock_offset_s
# (the small drift to server time). The truce schedule is camp-local HH:MM; the
# camp is 14-16 Aug 2026, entirely inside CEST (UTC+2), so camp-local minutes are
# (effective_now_min + 120) % 1440. Fixed offset, not tzdata: matches the server
# and cannot fail on a freshly imaged laptop (same reasoning as clock.py).

CAMP_UTC_OFFSET_M = 120          # minutes: CEST = UTC+2


def camp_minutes(now_s):
    """Camp-local minutes-of-day (0..1439) for `now_s` effective UTC seconds."""
    return (int(now_s) // 60 + CAMP_UTC_OFFSET_M) % 1440


def parse_hm(s):
    """"22:00" -> 22*60+0 = 1320 minutes since midnight. Bad input -> None."""
    try:
        parts = str(s).split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except Exception:
        pass
    return None


def hm_str(minutes):
    """Inverse of parse_hm: 1320 -> "22:00"."""
    minutes = int(minutes) % 1440
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def _in_window(minutes, frm, to):
    """True if `minutes` (0..1439) is inside [frm, to), which may wrap midnight."""
    if frm is None or to is None or frm == to:
        return False
    if frm < to:
        return frm <= minutes < to
    return minutes >= frm or minutes < to      # wraps past midnight


def truce_active(now_s, cfg, quiet):
    """Which quiet applies at `now_s` (effective UTC seconds)?

    Returns one of "none", "camp", "personal", "both". Both suppress attacks,
    reveal, the hunt ping and the radar (§10.4); ONLY the camp truce pauses
    streak decay (§2.2 -- a personal window is a form of hiding and must cost
    the crown). `cfg` carries the camp truce schedule; `quiet` is the player's
    personal window {from,to} (camp-local HH:MM) or None."""
    m = camp_minutes(now_s)
    camp = _in_window(m, parse_hm(cfg.get("truce_from")), parse_hm(cfg.get("truce_to")))
    pers = False
    if isinstance(quiet, dict):
        pers = _in_window(m, parse_hm(quiet.get("from")), parse_hm(quiet.get("to")))
    if camp and pers:
        return "both"
    if camp:
        return "camp"
    if pers:
        return "personal"
    return "none"


def clamp_quiet(window, cfg):
    """Clamp/validate a personal quiet window to [QUIET_EARLIEST, QUIET_LATEST].

    Returns {from,to} in HH:MM, or None if it cannot be made sane (the caller
    then falls back to the camp truce). The allowed band wraps midnight
    (20:00->10:00) and contains the camp truce. Never raises (§8.2, §10.4a)."""
    if not isinstance(window, dict):
        return None
    earliest = parse_hm(cfg.get("QUIET_EARLIEST"))
    latest = parse_hm(cfg.get("QUIET_LATEST"))
    if earliest is None or latest is None:
        return None
    span = (latest - earliest) % 1440        # length of the allowed night band
    if span == 0:
        return None

    def off(b):                               # minutes offset from `earliest`
        return (b - earliest) % 1440

    frm = parse_hm(window.get("from"))
    to = parse_hm(window.get("to"))
    if frm is None or to is None:
        return None
    fo = off(frm)
    to_ = off(to)
    # Snap any daytime bound (outside the night band) to the nearest band edge.
    if fo >= span:
        fo = span - 1 if (fo - span) < (1440 - fo) else 0
    if to_ >= span:
        to_ = span - 1 if (to_ - span) < (1440 - to_) else 0
    if fo >= to_:                             # empty / inverted -> unusable
        return None
    return {"from": hm_str((earliest + fo) % 1440),
            "to": hm_str((earliest + to_) % 1440)}


# ---------------------------------------------------------------------------
# 1f. PROXIMITY -- the asymmetric filter, the fraction, the radar bar (§8.8.2)
# ---------------------------------------------------------------------------
#
# Two mappings of a smoothed rssi_prox (dBm):
#   * prox_fraction : the canonical 0..1 used by the on-screen 5-segment bar and
#     the PING_FROM_SEG silent floor. It is independent of LED count, so the ping
#     means the same proximity on the 4-LED 2024 and the 5-LED 2026 (§8.8.6).
#   * hunt_segments : the LED bar's (lit, colour, brightness). It keys off the
#     live KILL_RSSI/REVEAL_RSSI so the affordance "all red = kill range" holds by
#     construction even after the host retunes those thresholds at camp (§5.4).
# Both are monotonic in rssi_prox, so the screen bar, the ping and the LEDs agree
# directionally; only the LED count at an exact dBm is a display nicety.

# Fixed display-calibration band for prox_fraction (§8.8.2: -90..-55 dBm is the
# only band that carries information; spreading it wider wastes the bar).
RSSI_FLOOR_DBM = -90
RSSI_CEIL_DBM = -55


def prox_filter(prev, rssi, cfg):
    """Asymmetric EWMA over rssi_prox: fast attack, slow decay (§8.8.2).

    `prev` is the previous rssi_prox (or None for the first sample). A_UP rises
    fast toward a stronger sample; A_DOWN falls slowly so a one-sided body-shadow
    fade does not empty the bar while the target stands in front of you. This is
    NOT the friends-list rssi_ewma (that stays symmetric) -- it is the single
    place raw RSSI becomes a hunt input."""
    if prev is None:
        return float(rssi)
    a_up = float(cfg.get("PROX_ALPHA_UP"))
    a_dn = float(cfg.get("PROX_ALPHA_DOWN"))
    a = a_up if rssi > prev else a_dn
    return (1.0 - a) * prev + a * rssi


def prox_fraction(prox, cfg):
    """0..1 across the calibrated band [-90, -55] dBm. None/below floor -> 0."""
    if prox is None:
        return 0.0
    span = RSSI_CEIL_DBM - RSSI_FLOOR_DBM
    if span <= 0:
        return 0.0
    f = (prox - RSSI_FLOOR_DBM) / span
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


# RGB at full brightness; the bar scales these by the per-state brightness.
COL_BLUE = (0, 0, 255)
COL_AMBER = (255, 150, 0)
COL_RED = (255, 0, 0)
COL_WHITE = (255, 255, 255)
_COLMAP = {"blue": COL_BLUE, "amber": COL_AMBER, "red": COL_RED, "white": COL_WHITE}

_BREATHE_SLOW_MS = 3800        # §8.8.2 breathe periods: far ... near
_BREATHE_FAST_MS = 700


def breathe_period_ms(lit, n):
    """Breathe period for `lit` of `n` LEDs. None = steady (kill range, §8.8.4).

    Geometric ramp 3800 -> 700 across lit [1, n-1] (approximates the §8.8.2
    table; exact endpoints, monotonic). Shared by the LED bar and the hunt ping
    so the two ride the same clock (§8.8.6)."""
    if lit >= n or n <= 1:
        return None
    if lit < 1:
        return _BREATHE_SLOW_MS
    if n <= 2:
        return _BREATHE_SLOW_MS                   # only one breathing level
    t = (lit - 1) / (n - 2)                       # 0 at first LED, 1 at n-1
    ratio = _BREATHE_FAST_MS / _BREATHE_SLOW_MS
    return int(_BREATHE_SLOW_MS * (ratio ** t) + 0.5)


def _breathe_env(now_ms, period_ms):
    """Triangle envelope in [0,1] once per period; period<=0 -> 1.0 (steady)."""
    if period_ms is None or period_ms <= 0:
        return 1.0
    phase = (now_ms % period_ms) / period_ms
    return 1.0 - abs(2.0 * phase - 1.0)


def hunt_segments(prox, cfg, n):
    """The LED radar decision: (lit, colour_key, base_brightness) or None (dark).

    Agrees with the action thresholds by construction: all-n red at KILL_RSSI,
    (n-1) amber at REVEAL_RSSI, and the lower segments fill [floor, reveal)
    (blue then amber). See §8.8.2. `n` is 4 on the 2024, 5 on the 2026."""
    if prox is None or n < 1:
        return None
    kill = cfg.get("KILL_RSSI")
    reveal = cfg.get("REVEAL_RSSI")
    if prox >= kill:
        return (n, "red", 0.55)
    if n == 1:
        return (1, "blue", 0.20)
    if prox >= reveal:
        return (n - 1, "amber", 0.45)
    if prox < RSSI_FLOOR_DBM:
        return None
    if reveal <= RSSI_FLOOR_DBM:
        return (1, "blue", 0.20)
    frac = (prox - RSSI_FLOOR_DBM) / (reveal - RSSI_FLOOR_DBM)
    if frac < 0.0:
        frac = 0.0
    elif frac > 1.0:
        frac = 1.0
    lit = 1 + int(frac * (n - 2) + 0.5)          # 1 .. n-2
    if lit < 1:
        lit = 1
    if lit > n - 2:
        lit = n - 2
    if lit <= 2:
        return (lit, "blue", 0.20 if lit == 1 else 0.25)
    return (lit, "amber", 0.35)


def _scale_colour(key, eff):
    r, g, b = _COLMAP.get(key, COL_BLUE)
    def clip(v):
        x = int(v * eff + 0.5)
        return 255 if x > 255 else (0 if x < 0 else x)
    return (clip(r), clip(g), clip(b))


def hunt_bar(prox, now_ms, cfg, n, halted=False):
    """The full LED frame: [(r,g,b)] * n with brightness+breathe applied.

    `halted` (truce/quiet) or no target -> all dark (§8.8.3). Identical inputs
    give identical output, so the caller can cache the whole frame and skip
    lights.write() when it is unchanged (§8.8.4: dark and steady-red cost zero)."""
    dark = [(0, 0, 0)] * n
    if halted:
        return dark
    seg = hunt_segments(prox, cfg, n)
    if seg is None:
        return dark
    lit, key, base = seg
    period = breathe_period_ms(lit, n)
    env = _breathe_env(now_ms, period)
    eff = base * (0.25 + 0.75 * env)             # breathe 25%..100% of base
    col = _scale_colour(key, eff)
    return [col if i < lit else (0, 0, 0) for i in range(n)]


def solid_frame(colour_key, n, brightness, now_ms=0, pulse_period_ms=None):
    """A whole-strip frame for the §8.8.3 steady/pulse states (dead, protected,
    battery-low, kill/dodge flash, reveal gold). `pulse_period_ms` pulses; None
    is steady. Same shape as hunt_bar so the caller swaps one for the other."""
    env = _breathe_env(now_ms, pulse_period_ms)
    eff = brightness * (0.25 + 0.75 * env) if pulse_period_ms else brightness
    return [_scale_colour(colour_key, eff)] * n


# ---------------------------------------------------------------------------
# 1g. HUNT PING -- sound on the same clock as the bar (§8.8.6)
# ---------------------------------------------------------------------------

def hunt_ping(prox, now_ms, last_ping_ms, cfg, *, enabled=True, sound_on=True):
    """The hunt ping due this tick, or None (silent).

    Returns (freq_hz, burst_ms, interval_ms, taps). Rate is the cue, rising with
    proximity; pitch is redundant. Silent below PING_FROM_SEG (the silent floor
    -- "they are here, now, close"), when disabled/muted, or not yet due. At kill
    range it becomes a double-tap at PING_INTERVAL_NEAR. `last_ping_ms` makes the
    "drop, don't queue" rule (§8.8.6) pure: a ping that is not due is dropped."""
    if not enabled or not sound_on:
        return None
    if prox is None or prox < RSSI_FLOOR_DBM:
        return None
    pfs = cfg.get("PING_FROM_SEG")
    thr = (pfs / 5.0) if pfs else 0.6           # PING_FROM_SEG is in screen-bar
    f = prox_fraction(prox, cfg)                # segments, so /5 makes it n-indp.
    if f < thr:                                 # below the silent floor -> dark
        return None
    kill = cfg.get("KILL_RSSI")
    near = cfg.get("PING_FREQ_NEAR")
    far = cfg.get("PING_FREQ_FAR")
    burst = cfg.get("PING_MS")
    interval_near = cfg.get("PING_INTERVAL_NEAR")
    if prox >= kill:                            # kill range: double-tap (§8.8.6)
        res = (near, burst, interval_near, 2)
    else:
        t = (f - thr) / (1.0 - thr) if thr < 1.0 else 1.0
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        freq = int(far + (near - far) * t + 0.5)
        interval = int(interval_near * 4 + (interval_near - interval_near * 4) * t + 0.5)
        res = (freq, burst, interval, 1)
    if last_ping_ms is not None and (now_ms - last_ping_ms) < res[2]:
        return None                             # not due; drop, never queue
    return res


# ---------------------------------------------------------------------------
# 1h. SCORE PREVIEW -- optimistic UI for a kill, before the server confirms (§2)
# ---------------------------------------------------------------------------

def score_preview(total_kills, streak, best_streak, kill_type):
    """Optimistic UI update for a kill (§2.1, §8.1).

    `kill_type` in {"target","bounty","repeat"} -> (new_total, new_streak,
    new_best, points). target=1, bounty=2, repeat=0. A repeat is a no-op for the
    killer's preview (the server still records the victim's death)."""
    if kill_type == "target":
        pts = 1
    elif kill_type == "bounty":
        pts = 2
    else:
        pts = 0
    new_streak = streak + 1 if pts > 0 else streak
    new_best = best_streak if new_streak <= best_streak else new_streak
    new_total = total_kills + (1 if pts > 0 else 0)
    return (new_total, new_streak, new_best, pts)


# ---------------------------------------------------------------------------
# 1i. REVEAL -- the last ten metres (plan §5.7)
# ---------------------------------------------------------------------------
#
# Reveal is the disambiguator: once rssi_prox has brought you to "within a few
# metres" but cannot say WHICH badge in a crowd, a Reveal makes your target's
# badge flash gold + chirp + show SPOTTED. It is the shortest GATT interaction
# (hunter writes REVEAL -> target acks -> disconnect -> flash), so it is built
# first (Phase 3a) to prove the connect path the duel (§5.3) will share.
#
# All of this is pure and host-tested: the GATT payload, the escalating A-action
# ladder (§5.7 D29), the hunter cooldown, the responder validation, the spotted
# window, and the log-only event shapes. The on-badge connect/IRQ wiring lives in
# gotcha_gatt.py / gotcha_app.py.

def build_reveal_payload(group_id, hunter_pid, target_pid, nonce):
    """The REVEAL GATT write body (hunter -> target, plan §5.7): compact JSON.

    {g, h, t, n} = group id, hunter pid, target pid, nonce. Unauthenticated --
    consistent with the sniffing-accepted posture (§3.4/§13): anyone on the link
    can read who revealed whom, which the public audit trail shows anyway. The
    nonce lets the hunter match the write to its ack; it carries no security."""
    return canonical_json({"g": group_id, "h": hunter_pid, "t": target_pid, "n": nonce})


def parse_reveal_payload(raw):
    """Parse a REVEAL write body. Defensive and never raising -> dict or None.

    Returns {g, h, t, n} (any value may be None/missing). None means 'not JSON /
    not an object'; the responder treats that as a dropped write."""
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return {"g": obj.get("g"), "h": obj.get("h"), "t": obj.get("t"), "n": obj.get("n")}


def reveal_ready(last_reveal_at_s, now_s, cfg):
    """Has the hunter's per-hunter REVEAL_COOLDOWN_S elapsed (§5.7)?

    Cooldown is hunter-side ONLY -- the responder never checks it (a target must
    always answer). `last_reveal_at_s`/`now_s` are effective server seconds
    (stable across reboots, unlike ticks_ms); 0/None means 'never'."""
    cd = int(cfg.get("REVEAL_COOLDOWN_S") or 0)
    if cd <= 0 or not last_reveal_at_s:
        return True
    return (int(now_s) - int(last_reveal_at_s)) >= cd


def decide_strip_action(target_prox, last_reveal_at_s, now_s, cfg, *,
                        attack_in_progress=False, kill_enabled=False, halted=False):
    """The escalating A-action on the hunt strip (plan §5.7 D29).

    Returns one of 'attack'|'reveal'|'radar'|'abort'|'none'. The ladder is
    monotonic in proximity, so a single press does the strongest legal thing:
      own attack live        -> 'abort'  (a real tactical choice, §10.2)
      truce / no target      -> 'none'   (radar detail / the Gotcha screen)
      within KILL_RSSI       -> 'attack' (Phase 3b; gated off until kill_enabled)
      within REVEAL_RSSI     -> 'reveal' if cooldown clear, else 'radar' (cooldown)
      farther / not detected -> 'none'
    With kill_enabled=False (Phase 3a) kill range falls through to 'reveal', so a
    press right next to the target still does something useful."""
    if attack_in_progress:
        return "abort"
    if halted or target_prox is None:
        return "none"
    in_kill = target_prox >= cfg.get("KILL_RSSI")
    in_reveal = target_prox >= cfg.get("REVEAL_RSSI")
    if in_kill and kill_enabled:
        return "attack"
    if in_reveal:
        if cfg.get("reveal_enabled", True) and reveal_ready(last_reveal_at_s, now_s, cfg):
            return "reveal"
        return "radar"
    return "none"


def validate_reveal(parsed, my_pid, alive, truce_now, game_running, radio_busy=False):
    """Responder-side verdict on an incoming REVEAL write (plan §5.7).

    Returns 'ok'|'busy'|'no_game'|'truce'|'dead'|'wrong_target'. Deliberately NO
    protection check (§5.8: reveal is allowed on protected players -- knowing
    where someone is does them no harm) and NO cooldown check (cooldown is
    hunter-side). 'busy' covers the §5.5 radio-arbitration states (a live GATT
    connection / single slot taken) which the handler knows and passes in.
    `truce_now` is a truce_active() result ('none'/'camp'/'personal'/'both')."""
    if radio_busy:
        return "busy"
    if not game_running:
        return "no_game"
    if truce_now != "none":
        return "truce"
    if not alive:
        return "dead"
    t = parsed.get("t") if isinstance(parsed, dict) else None
    if t != my_pid:
        return "wrong_target"
    return "ok"


def spotted_active(spotted_until_ms, now_ms):
    """Is the target's gold reveal flash still showing (§5.7 REVEAL_FLASH_MS)?

    `spotted_until_ms` is an absolute ticks_ms deadline (0/None = not spotted).
    Raw compare is fine: the window is ~2.5 s, far inside the ticks wrap range."""
    return bool(spotted_until_ms) and now_ms < spotted_until_ms


def reveal_event(target_pid, rssi=None, at=None):
    """A hunter's 'reveal' event (plan §9.3): log-only, feeds the audit page.
    Not in EventQueue.KEEP_TYPES -- droppable on overflow (a kill is never dropped,
    a reveal is). rssi/at optional; the controller stamps `at` when it has a clock."""
    e = {"type": "reveal", "target_pid": target_pid}
    if rssi is not None:
        e["rssi"] = int(rssi)
    if at is not None:
        e["at"] = int(at)
    return e


def revealed_event(hunter_pid, at=None):
    """A target's 'revealed' event (plan §9.3): log-only + a liveness signal --
    being revealed proves physical proximity, so the server refreshes last_seen."""
    e = {"type": "revealed", "hunter_pid": hunter_pid}
    if at is not None:
        e["at"] = int(at)
    return e


# ---------------------------------------------------------------------------
# 1j. THE DUEL -- attack handshake, victim state machine, spawn protection
#     (plan §5.3, §5.8). All pure and host-tested; the on-badge GATT/IRQ wiring
#     lives in gotcha_gatt.py / gotcha_app.py. DuelState is the victim-only
#     responder reused by beacon_service.py in Phase 4 (§5.6), so it carries NO
#     lvgl / Activity / radio dependency -- effects ride injected callbacks.
# ---------------------------------------------------------------------------
#
# ESCAPE MECHANIC (deviation from §5.3 -- see Phase 3b plan). `gap_conn_rssi` is
# absent on this MicroPython build, so §5.3's "rssi < FLEE_RSSI for FLEE_MS"
# escape is not implementable. Escape is LINK-DROP: the victim leaving BLE range
# drops the GATT connection before the hold elapses -> DODGED. §5.3 already lists
# "link drops before hold elapses" as an escape, so FLEE_RSSI/FLEE_MS go unused
# and the BLE link supervision-timeout replaces them (same posture as the Phase-0
# RSSI-trend retraction). Instant-kill (dodges_left == 0) uses a very short hold
# (INSTANT_KILL_MS) rather than disabling escape in code: a link that drops always
# ends a duel without a kill regardless, so the short window -- not a code flag --
# is what makes the last attempt land in practice.

# DUEL notify states (victim -> attacker over the DUEL characteristic, §5.2).
DUEL_ENGAGED = "engaged"
DUEL_DODGED = "dodged"
DUEL_KILLED = "killed"
DUEL_REFUSED = "refused"          # carries the validate_attack verdict as reason

# ATTACK "as" modes (§5.2).
ATTACK_TARGET = "target"
ATTACK_BOUNTY = "bounty"


def build_attack_payload(group_id, attacker_pid, victim_pid, mode, nonce):
    """The ATTACK GATT write body (attacker -> victim, §5.2/§5.3): compact JSON
    {a, as, g, n, v} = attacker pid, mode, group id, nonce, victim pid.
    Unauthenticated like REVEAL (§3.4/§13 sniffing-accepted posture)."""
    return canonical_json({"g": group_id, "a": attacker_pid, "v": victim_pid,
                           "as": mode, "n": nonce})


def parse_attack_payload(raw):
    """Parse an ATTACK write body. Defensive, never raises -> dict or None
    ('not JSON / not an object' -> None, a dropped write)."""
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return {"g": obj.get("g"), "a": obj.get("a"), "v": obj.get("v"),
            "as": obj.get("as"), "n": obj.get("n")}


def build_duel_payload(status, hold_ms=None, dodges_left=None, reason=None):
    """A DUEL notify body (victim -> attacker): {s, h?, d?, r?}. ENGAGED carries
    hold_ms (h) and dodges_left (d); REFUSED carries the verdict (r); DODGED/
    KILLED carry only the state."""
    d = {"s": status}
    if hold_ms is not None:
        d["h"] = int(hold_ms)
    if dodges_left is not None:
        d["d"] = int(dodges_left)
    if reason is not None:
        d["r"] = reason
    return canonical_json(d)


def parse_duel_payload(raw):
    """Parse a DUEL notify body -> {s, h, d, r} or None."""
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return {"s": obj.get("s"), "h": obj.get("h"),
            "d": obj.get("d"), "r": obj.get("r")}


def build_spoils_payload(soul_hex, target):
    """The SPOILS read value (victim -> attacker, §5.2 D10): {soul, tgt}. The
    inherited target rides the kill so inheritance works fully offline. `target`
    is the victim's own target dict (pid/name/commitment) or None (the victim had
    no live target -- the assassin then keeps hunting and re-syncs for a new one)."""
    tgt = None
    if isinstance(target, dict):
        tgt = {"pid": target.get("pid"),
               "name": str(target.get("name") or ""),
               "commitment": target.get("commitment")}
    return canonical_json({"soul": _hex(soul_hex), "tgt": tgt})


def parse_spoils_payload(raw):
    """Parse a SPOILS read value -> {soul, tgt} or None."""
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    tgt = obj.get("tgt")
    if not isinstance(tgt, dict):
        tgt = None
    return {"soul": obj.get("soul"), "tgt": tgt}


def validate_attack(parsed, my_pid, my_streak, alive, truce_now, game_running, cfg,
                    *, protected=False, on_cooldown=False, in_duel=False,
                    radio_busy=False):
    """Responder-side verdict on an incoming ATTACK write (§5.3, §5.8).

    Returns 'ok'|'busy'|'no_game'|'truce'|'dead'|'wrong_target'|'protected'|
    'on_cooldown'|'bounty'. The victim validates only what it can know locally;
    the server re-checks true kill legality (ring/inheritance) on ingest (§10.2):
      busy         -> radio slot taken or we are mid-duel ("no attack while
                      attacking / a link is up", §5.5).
      protected    -> we are spawn/join protected (§5.8); the attacker pays no
                      cooldown for a refused attempt.
      on_cooldown  -> this attacker attacked us inside ATTACK_COOLDOWN_MS.
      bounty       -> attacker declared 'bounty' but we are not a bounty (our
                      streak < BOUNTY_STREAK): the one lie the victim CAN catch.
    `truce_now` is a truce_active() result ('none'/'camp'/'personal'/'both')."""
    if radio_busy or in_duel:
        return "busy"
    if not game_running:
        return "no_game"
    if truce_now != "none":
        return "truce"
    if not alive:
        return "dead"
    v = parsed.get("v") if isinstance(parsed, dict) else None
    if v != my_pid:
        return "wrong_target"
    if protected:
        return "protected"
    if on_cooldown:
        return "on_cooldown"
    mode = parsed.get("as") if isinstance(parsed, dict) else None
    if mode == ATTACK_BOUNTY and cfg.get("bounty_enabled", True):
        # The one lie the victim CAN catch (§5.3): a 'bounty' attack on a player
        # whose streak is below BOUNTY_STREAK. Honours the bounty_enabled kill
        # switch (§8.10.1): when bounties are off the badge never sends this mode
        # and a stray bounty write just validates as a plain target attack.
        if int(my_streak or 0) < int(cfg.get("BOUNTY_STREAK")):
            return "bounty"
    return "ok"


def protection_active(protected_until_s, now_s):
    """Is spawn/join protection (§5.8) still in force? `protected_until_s` is an
    absolute server-seconds deadline (None/0 = not protected). Server-seconds,
    not ticks_ms, so it survives reboots and is not paused by a truce."""
    try:
        return bool(protected_until_s) and int(now_s) < int(protected_until_s)
    except Exception:
        return False


def protection_left_s(protected_until_s, now_s):
    """Whole seconds of protection left (for the countdown chip, §5.8), or 0."""
    try:
        if not protected_until_s:
            return 0
        d = int(protected_until_s) - int(now_s)
        return d if d > 0 else 0
    except Exception:
        return 0


def cooldown_ready(last_at_ms, now_ms, cooldown_ms):
    """Has `cooldown_ms` elapsed since `last_at_ms` (ATTACK_COOLDOWN_MS, §5.4)?
    0/None = never -> ready. Used by the ATTACKER for its own per-victim cooldown
    (ticks_ms); the cooldown is <=60 s, inside the wrap range (cf. spotted_active)."""
    if not last_at_ms:
        return True
    try:
        return (now_ms - int(last_at_ms)) >= int(cooldown_ms)
    except Exception:
        return True


class DodgeLedger(object):
    """Per-attacker dodge + cooldown bookkeeping for the victim's current life
    (§5.4). Bridges the server-synced `me.dodges` map (str(pid) -> dodges_LEFT
    int) with locally-tracked offline duels: a local record upgrades an entry to
    a {used, last} dict carrying the last-attack time for the DODGE_DECAY_MS reset
    and the ATTACK_COOLDOWN_MS gate. On the next sync apply_sync overwrites the
    whole map with the server's authoritative ints, discarding the local dicts.
    Operates in server-seconds (stable across reboots, unlike ticks_ms)."""

    def __init__(self, data=None, limit=1):
        self._d = data if isinstance(data, dict) else {}
        self.limit = int(limit)

    def _used_of(self, e):
        if isinstance(e, dict):
            return int(e.get("used", 0))
        if isinstance(e, int) and not isinstance(e, bool):
            return max(0, self.limit - e)             # server 'left' int -> used
        return 0

    def dodges_left(self, attacker_pid, now_s, decay_s):
        """Dodges this attacker still has against us this life. A DODGE_DECAY_MS
        gap since their last attack resets it to the full DODGE_LIMIT (§5.4)."""
        e = self._d.get(str(attacker_pid))
        if e is None:
            return self.limit
        if isinstance(e, dict):
            last = e.get("last")
            if last is not None and (int(now_s) - int(last)) > int(decay_s):
                return self.limit                     # decayed -> full reprieve
            return max(0, self.limit - int(e.get("used", 0)))
        try:
            return max(0, min(self.limit, int(e)))    # server 'left' int
        except Exception:
            return self.limit

    def last_attack_s(self, attacker_pid):
        """When this attacker last attacked us (server-seconds), or None."""
        e = self._d.get(str(attacker_pid))
        if isinstance(e, dict) and e.get("last") is not None:
            return int(e["last"])
        return None

    def note_attack(self, attacker_pid, now_s):
        """Stamp an attack attempt's time (feeds cooldown + decay); used unchanged."""
        k = str(attacker_pid)
        self._d[k] = {"used": self._used_of(self._d.get(k)), "last": int(now_s)}

    def note_dodge(self, attacker_pid, now_s):
        """Record a granted dodge: used += 1 (capped at the limit) + stamp time."""
        k = str(attacker_pid)
        used = min(self._used_of(self._d.get(k)) + 1, self.limit)
        self._d[k] = {"used": used, "last": int(now_s)}

    def to_dict(self):
        return self._d


class DuelState(object):
    """The victim's lvgl-free duel state machine (§5.3, §5.6). Reused by both
    fri3d_friends.py (foreground) and beacon_service.py (background, Phase 4);
    effects (alarm, screens, LEDs) ride injected callbacks so this class touches
    no lvgl / Activity / radio. Ticks on a monotonic ms clock (time.ticks_ms
    on-device, plain ints in tests)."""

    def __init__(self, on_engaged=None, on_dodge=None, on_kill=None):
        self.on_engaged = on_engaged     # (duel) -> fired when a duel begins
        self.on_dodge = on_dodge         # (duel) -> fired on escape (link drop)
        self.on_kill = on_kill           # (duel) -> fired when the hold completes
        self.phase = "idle"              # idle -> hold -> killed|dodged
        self.attacker_pid = None
        self.hold_ms = 0
        self.dodges_left = 0
        self._deadline = 0

    def active(self):
        """A duel is live (holding) -> the single connection slot is committed."""
        return self.phase == "hold"

    def begin_attack(self, attacker_pid, hold_ms, dodges_left, now_ms):
        """Start the hold. Idempotent while already holding (single slot, §5.5):
        a second ATTACK during a live duel is ignored. Returns True if started."""
        if self.phase == "hold":
            return False
        self.attacker_pid = attacker_pid
        self.hold_ms = int(hold_ms)
        self.dodges_left = int(dodges_left)
        self._deadline = now_ms + int(hold_ms)
        self.phase = "hold"
        self._fire(self.on_engaged)
        return True

    def tick(self, now_ms, link_up):
        """Advance the machine -> 'idle'|'hold'|'killed'|'dodged'. link_up False
        (the central dropped) is the escape (see the LINK-DROP note above) ->
        'dodged'; otherwise the hold completing -> 'killed'. Raw ms compare: the
        hold is <=5 s, well inside the ticks_ms wrap (cf. spotted_active)."""
        if self.phase != "hold":
            return self.phase
        if not link_up:
            self.phase = "dodged"
            self._fire(self.on_dodge)
            return "dodged"
        if now_ms >= self._deadline:
            self.phase = "killed"
            self._fire(self.on_kill)
            return "killed"
        return "hold"

    def hold_fraction(self, now_ms):
        """0..1 progress of the hold bar (for the under-attack + attacker UI)."""
        if self.hold_ms <= 0:
            return 1.0
        done = (now_ms - (self._deadline - self.hold_ms)) / float(self.hold_ms)
        if done < 0.0:
            return 0.0
        return 1.0 if done > 1.0 else done

    def reset(self):
        self.phase = "idle"
        self.attacker_pid = None
        self.hold_ms = 0
        self.dodges_left = 0
        self._deadline = 0

    def _fire(self, cb):
        if cb is not None:
            try:
                cb(self)
            except Exception:
                pass


# -- duel event builders (§5.3, §9.3) ---------------------------------------

def attack_started_event(victim_pid, at=None):
    """The attacker's 'attack_started' event (§5.3, §9.3): cooldown bookkeeping +
    the §5.8 rule that sending an ATTACK ends the attacker's OWN protection.
    Log/accounting-only -> droppable on overflow."""
    e = {"type": "attack_started", "victim_pid": victim_pid}
    if at is not None:
        e["at"] = int(at)
    return e


def kill_event(victim_pid, soul_hex, rssi=None, at=None):
    """The assassin's 'kill' report (§3.4, §5.3): victim_pid + the disclosed soul.
    A KEEP_TYPE -- never dropped on overflow (a kid's kills survive a power-off)."""
    e = {"type": "kill", "victim_pid": victim_pid, "soul": _hex(soul_hex)}
    if rssi is not None:
        e["rssi"] = int(rssi)
    if at is not None:
        e["at"] = int(at)
    return e


def killed_by_event(attacker_pid, new_commitment, at=None):
    """The victim's 'killed_by' report (§5.3, §9.6): names the attacker and
    publishes the NEW commitment for the freshly-rotated soul. A KEEP_TYPE."""
    e = {"type": "killed_by", "attacker_pid": attacker_pid}
    if new_commitment is not None:
        e["new_commitment"] = new_commitment
    if at is not None:
        e["at"] = int(at)
    return e


def dodge_event(attacker_pid=None, victim_pid=None, counterpart_pid=None, at=None):
    """A 'dodge' event (§5.4). The victim names `attacker_pid`; the assassin names
    `victim_pid`; either half lands on the same server row. Droppable on overflow."""
    e = {"type": "dodge"}
    if attacker_pid is not None:
        e["attacker_pid"] = attacker_pid
    if victim_pid is not None:
        e["victim_pid"] = victim_pid
    if counterpart_pid is not None:
        e["counterpart_pid"] = counterpart_pid
    if at is not None:
        e["at"] = int(at)
    return e


def heartbeat_event(battery=None, peers_seen=None, target_seen_ago_s=None,
                    groups=None, background=False, app_version="", at=None):
    """A 'heartbeat' event (§9.3, §8.10.3): one per SYNC_S, queued immediately
    before the flush. It proves the badge is awake, refreshes the server's
    app_version (so the admin version-histogram + update nudge stay honest), and
    carries the liveness signals the dormancy/stale logic needs (battery,
    peers_seen, target_seen_ago_s). Droppable on overflow -- it is retried whole
    on the next flush and a heartbeat is only ever the latest truth.

    `background` is True when emitted by the headless beacon_service (app closed);
    the foreground app passes False. Matches BadgeSim.heartbeat's shape exactly."""
    e = {"type": "heartbeat", "alive": True, "background": bool(background)}
    if battery is not None:
        e["battery"] = int(battery)
    if peers_seen is not None:
        e["peers_seen"] = int(peers_seen)
    if target_seen_ago_s is not None:
        e["target_seen_ago_s"] = int(target_seen_ago_s)
    if isinstance(groups, list):
        e["groups"] = list(groups)
    if isinstance(app_version, str) and app_version:
        e["app_version"] = app_version[:16]      # server caps at 16 (C1)
    if at is not None:
        e["at"] = int(at)
    return e


# ---------------------------------------------------------------------------
# 2. EVENT QUEUE -- bounded, dedup-by-uuid offline store (§8.2, §9.3)
# ---------------------------------------------------------------------------
#
# Events are queued while offline and flushed with POST /v1/events, which is
# idempotent on uuid. The queue is capped at MAX_QUEUE: on overflow the OLDEST
# NON-KILL event is dropped first -- a kill/killed_by is never dropped (a kid's
# kills survive a power-off). The queue is persisted inside gotcha.json.

import json

MAX_QUEUE = 40


def _new_uuid():
    """A short hex uuid for an event (injectable os.urandom on-device)."""
    try:
        import os
        return "".join("%02x" % x for x in os.urandom(8))
    except Exception:
        import hashlib
        try:
            import time
            return _hex(hashlib.sha256(b"ev%d" % time.ticks_ms()).digest())[:16]
        except Exception:
            return "0000000000000000"


def _hex(b):
    """bytes -> hex; hex str -> unchanged; else None."""
    if isinstance(b, str):
        return b
    if isinstance(b, (bytes, bytearray)):
        return "".join("%02x" % x for x in b)
    return None


class EventQueue(object):
    """Bounded, dedup-by-uuid event queue. Host-testable (no FS)."""

    KEEP_TYPES = ("kill", "killed_by")     # never dropped on overflow

    def __init__(self, events=None):
        self._ev = []
        self._seen = set()
        if isinstance(events, list):
            for e in events:
                if isinstance(e, dict):
                    u = e.get("uuid")
                    if isinstance(u, str) and u:
                        self._index(e)

    def _index(self, e):
        u = e.get("uuid")
        if isinstance(u, str) and u and u not in self._seen:
            self._seen.add(u)
            self._ev.append(e)
            return True
        return False

    def add(self, event):
        """Add an event (a fresh uuid is minted if it lacks one). Returns True
        if accepted, False on dup or when the queue is full of kills."""
        if not isinstance(event, dict):
            return False
        ev = dict(event)
        u = ev.get("uuid")
        if not isinstance(u, str) or not u:
            u = _new_uuid()
            ev["uuid"] = u
        if u in self._seen:
            return False
        if len(self._ev) >= MAX_QUEUE:
            if not self._drop_oldest_dropable():
                return False                # full of kills; refuse, never drop one
        self._ev.append(ev)
        self._seen.add(u)
        return True

    def _drop_oldest_dropable(self):
        for i in range(len(self._ev)):
            if self._ev[i].get("type") not in self.KEEP_TYPES:
                removed = self._ev.pop(i)
                self._seen.discard(removed.get("uuid"))
                return True
        return False

    def peek_batch(self, limit=MAX_QUEUE):
        """A copy of up to `limit` events, oldest first, for a flush attempt."""
        return [dict(e) for e in self._ev[:limit]]

    def remove(self, uuids):
        """Drop the given uuids (the server's `accepted` list)."""
        drop = set(uuids or [])
        keep = []
        for e in self._ev:
            if e.get("uuid") in drop:
                self._seen.discard(e.get("uuid"))
            else:
                keep.append(e)
        self._ev = keep

    def __len__(self):
        return len(self._ev)

    def to_list(self):
        return [dict(e) for e in self._ev]


# ---------------------------------------------------------------------------
# 3. GOTCHA STATE -- atomically-persisted badge game state (plan §8.2)
# ---------------------------------------------------------------------------
#
# gotcha.json in the app dir, written temp + os.rename (like contacts.json,
# DESIGN.md §9) so a power-off mid-write loses at most the in-flight event.
# reader/writer/renamer are injectable so this class is host-testable without a
# filesystem; the Activity passes the real FS helpers (or None for the built-in
# open/os.rename defaults).

def _blank_state():
    return {
        "enrolled": False, "pid": None, "player_key": None, "game_id": None,
        "soul": None, "commitment": None,
        "target": None,
        "state": {"alive": True, "status": "active", "streak": 0, "best_streak": 0,
                  "total": 0, "score": 0, "deaths": 0,
                  "respawn_at": None, "protected_until": None},
        "dodges": {}, "last_reveal_at": 0, "clock_offset_s": 0, "quiet": None,
        "opted_out": False, "queue": [], "hitlist": [], "broadcast": None,
        "card_token": None,
        "app": {"min_version": None, "latest_version": None},
        "synced_at": None,
    }


def _parse_target(t):
    if not isinstance(t, dict):
        return None
    return {
        "pid": t.get("pid"),
        "name": str(t.get("name") or ""),
        "commitment": t.get("commitment"),
        "seen_ago_s": int(t.get("last_seen_ago_s") or 0),
        "halted": bool(t.get("halted", False)),
    }


class GotchaState(object):
    """In-memory + atomically-persisted badge game state."""

    def __init__(self, path="gotcha.json", reader=None, writer=None, renamer=None,
                 on_save=None):
        self.path = path
        self._reader = reader          # () -> file str, or None
        self._writer = writer          # (tmp_path, data_str) -> None
        self._renamer = renamer        # (tmp_path, path) -> None
        self._on_save = on_save        # () -> None, §8.10.4 mirror hook
        self.reset()

    def reset(self):
        self.d = _blank_state()
        self.queue = EventQueue()

    # -- persistence ---------------------------------------------------------

    def _read_raw(self):
        if self._reader is not None:
            try:
                return self._reader()
            except Exception:
                return None
        try:
            import os
            if not os.path.exists(self.path):
                return None
            f = open(self.path, "r")
            data = f.read()
            f.close()
            return data
        except Exception:
            return None

    def load(self):
        """Load gotcha.json, merging onto the blank schema so new fields get
        defaults and a corrupt/truncated file degrades to a fresh state."""
        raw = self._read_raw()
        if not raw:
            self.reset()
            return
        try:
            obj = json.loads(raw)
        except Exception:
            self.reset()
            return
        if not isinstance(obj, dict):
            self.reset()
            return
        b = _blank_state()
        for k in b:
            if k not in obj:
                continue
            v = obj[k]
            dv = b[k]
            # Type-guard per key (D27): a structurally-corrupt but JSON-valid file
            # (e.g. {"state": "broken"}) must not copy a wrong-typed value into
            # state, where apply_sync would then do `s["alive"]=...` on a str and
            # die on every sync forever. A key whose blank default is None has no
            # type to enforce and is taken as-is.
            if dv is None:
                b[k] = v
            elif isinstance(dv, bool):
                if isinstance(v, bool):
                    b[k] = v
            elif isinstance(dv, dict):
                if isinstance(v, dict):
                    b[k] = v
            elif isinstance(dv, list):
                if isinstance(v, list):
                    b[k] = v
            elif isinstance(dv, (int, float)):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    b[k] = v
            elif isinstance(dv, str):
                if isinstance(v, str):
                    b[k] = v
        # Never trust a persisted queue that lost its dedup index.
        b["queue"] = [e for e in (obj.get("queue") or [])
                      if isinstance(e, dict) and isinstance(e.get("uuid"), str)]
        self.d = b
        self.queue = EventQueue(b["queue"])

    def save(self):
        """Atomic write: temp file + rename. Returns True, never raises."""
        out = dict(self.d)
        out["queue"] = self.queue.to_list()
        data = json.dumps(out)
        tmp = self.path + ".tmp"
        try:
            if self._writer is not None and self._renamer is not None:
                self._writer(tmp, data)
                self._renamer(tmp, self.path)
            else:
                f = open(tmp, "w")
                f.write(data)
                f.close()
                import os
                os.rename(tmp, self.path)
            # §8.10.4: mirror gotcha.json to the update-survival backup so a
            # wipe can never lose enrollment/queue. Best-effort; the on-device
            # hook swallows its own errors, and tests pass None.
            if self._on_save is not None:
                try:
                    self._on_save()
                except Exception:
                    pass
            return True
        except Exception:
            return False

    # -- mutations -----------------------------------------------------------

    def enroll(self, pid, player_key, game_id, soul=None, commitment_hex=None):
        self.d["enrolled"] = True
        self.d["pid"] = pid
        self.d["player_key"] = player_key
        self.d["game_id"] = game_id
        if soul is not None:
            self.d["soul"] = _hex(soul)
        if commitment_hex is not None:
            self.d["commitment"] = commitment_hex
        self.d["opted_out"] = False

    def apply_sync(self, payload, local_time_s):
        """Merge a verified /v1/sync payload into cached state. `local_time_s`
        is the badge's time.time() at the moment of the sync; the server_time in
        the payload sets clock_offset_s (§8.3)."""
        if not isinstance(payload, dict):
            return
        st = payload.get("server_time")
        if isinstance(st, (int, float)):
            self.d["clock_offset_s"] = int(st) - int(local_time_s)
            self.d["synced_at"] = int(st)
        me = payload.get("me")
        if isinstance(me, dict):
            self.d["pid"] = me.get("pid", self.d.get("pid"))
            s = self.d.setdefault("state", {})
            s["alive"] = bool(me.get("alive", True))
            s["status"] = me.get("status", s.get("status", "active"))
            s["streak"] = int(me.get("streak") or 0)
            s["best_streak"] = int(me.get("best_streak") or 0)
            s["total"] = int(me.get("total_kills") or 0)
            s["score"] = int(me.get("score") or 0)
            s["deaths"] = int(me.get("deaths") or 0)
            s["respawn_at"] = me.get("respawn_at")
            s["protected_until"] = me.get("protected_until")
            dd = me.get("dodges")
            self.d["dodges"] = dd if isinstance(dd, dict) else {}
            q = me.get("quiet")
            self.d["quiet"] = q if isinstance(q, dict) else None
            self.d["card_token"] = me.get("card_token")
        self.d["target"] = _parse_target(payload.get("target"))
        hl = payload.get("hitlist")
        self.d["hitlist"] = hl if isinstance(hl, list) else []
        self.d["broadcast"] = payload.get("broadcast")
        app = payload.get("app")
        if isinstance(app, dict):
            a = self.d.setdefault("app", {})
            a["min_version"] = app.get("min_version")
            a["latest_version"] = app.get("latest_version")

    def opt_out(self):
        self.d["opted_out"] = True

    def opt_in(self):
        self.d["opted_out"] = False

    # -- queries -------------------------------------------------------------

    def is_enrolled(self):
        return bool(self.d.get("enrolled")) and not self.d.get("opted_out")

    def effective_now(self, local_time_s):
        """Server-time (UTC seconds) for truce/decay checks (§8.3)."""
        return int(local_time_s) + int(self.d.get("clock_offset_s") or 0)

    def target_pid(self):
        t = self.d.get("target")
        return t.get("pid") if isinstance(t, dict) else None


# ---------------------------------------------------------------------------
# 4. SIGNED-HTTP REQUEST/RESPONSE SHAPING (plan §6.2, §9.1) -- pure, host-tested
# ---------------------------------------------------------------------------
#
# The wire scheme: GET /v1/sync and POST /v1/events carry X-Pid/X-Ts/X-Nonce/
# X-Sig (HMAC over METHOD || full-target || ts || nonce || body); every response
# is a {ts, nonce, sig, payload} envelope the badge verifies (sig + nonce match).
# These helpers build requests and verify responses with no I/O, so they unit-
# test on a host. The on-badge urequests calls live in GotchaSync below.

def new_nonce():
    """16 random hex chars for X-Nonce (server accepts 4-64 hex)."""
    try:
        import os
        return "".join("%02x" % x for x in os.urandom(8))
    except Exception:
        return "0123456789abcdef"


def _full_path(path, query=None):
    """path plus a sorted, urlencoded-free query string (query values are simple
    tokens in this API: board=total, limit=50). This is the EXACT string signed
    and put on the request line, so it must match what the server sees."""
    p = path or "/"
    if query:
        parts = []
        for k in sorted(query):
            parts.append("%s=%s" % (k, query[k]))
        if parts:
            p = p + "?" + "&".join(parts)
    return p


def _signed_headers(pid, player_key, method, full_path, ts, nonce, body=b""):
    sig = sign_request(player_key, method, full_path, ts, nonce, body)
    return {"X-Pid": str(pid), "X-Ts": str(ts),
            "X-Nonce": nonce, "X-Sig": sig}


def signed_get(pid, player_key, base, path, ts, nonce, query=None):
    """Build a signed GET. Returns (url, headers). `base` is e.g.
    'http://192.168.1.57:8080'; the full request target (path + query) is what
    gets signed, matching server auth.signing_path()."""
    fp = _full_path(path, query)
    url = base.rstrip("/") + fp
    return url, _signed_headers(pid, player_key, "GET", fp, ts, nonce, b"")


def signed_post(pid, player_key, base, path, body_obj, ts, nonce):
    """Build a signed POST. Returns (url, headers, body_bytes). The body is
    canonical JSON (deterministic bytes) and is signed byte-for-byte, so it
    matches the server's raw-body verification exactly."""
    body = canonical_json(body_obj).encode("utf-8")
    url = base.rstrip("/") + (path or "/")
    return url, _signed_headers(pid, player_key, "POST", path or "/", ts, nonce, body), body


def enroll_body(badge_key, display_name, groups, commitment, app_version="", board=""):
    """The UNSIGNED /v1/enroll request body (§9.2). The badge has no key yet."""
    return {
        "badge_key": badge_key,
        "display_name": display_name,
        "groups": list(groups or []),
        "commitment": commitment,
        "app_version": app_version,
        "board": board,
    }


def verify_response(player_key, nonce_sent, envelope):
    """Verify a signed response envelope; return its payload dict, or None.

    Checks the envelope shape, that `nonce` equals the nonce we just sent (replay
    defence), and that `sig` is valid over ts+nonce+canonical_json(payload). Bad
    input -> None, never raises (§6.2: discard anything unsigned/mis-signed)."""
    if not isinstance(envelope, dict):
        return None
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None
    if envelope.get("nonce") != nonce_sent:
        return None
    if not sig_ok(player_key, envelope.get("ts"), nonce_sent, payload,
                  envelope.get("sig")):
        return None
    return payload


# ---------------------------------------------------------------------------
# 5. GOTCHA SYNC -- the on-badge signed-HTTP client (plan §8.3, §9.2)
# ---------------------------------------------------------------------------
#
# urequests, not DownloadManager: the on-badge probe (2026-07-30) found
# DownloadManager.post_url absent on this firmware (only download_url), and the
# §11 1000-sync soak already proved urequests does GET sync / POST enroll / POST
# events cleanly. Each call is a blocking urequests round trip run inside an
# asyncio task (never from the main tick), closed in `finally` (never leak a
# socket), with a short `sleep_ms` yield afterwards to let the OS loop / lwIP
# drain. If a real sync ever stalls BLE noticeably, run the request in a
# `_thread` like _ntp_blocking -- but the soak showed the brief block is fine.
#
# NOT host-tested (urequests is MicroPython-only); the request/response SHAPING
# it relies on is fully covered by the §4 tests above.

class GotchaSync(object):
    """Signed-HTTP client bound to a GotchaState. Methods are coroutines: the
    Activity runs each under TaskManager.create_task (and may bound it with
    TaskManager.wait_for(..., timeout), which exists on this firmware)."""

    def __init__(self, state):
        self.state = state

    # -- low-level I/O (blocking urequests, kept tiny and finally-safe) --------
    def _patch_tls_no_verify(self):
        # External backends (e.g. a Tailscale Funnel URL) are https-only, but the
        # ESP32 ships no root-CA store so urequests' default verification fails
        # (MBEDTLS_ERR_SSL_CA_CHAIN_REQUIRED). Every request is HMAC-signed (D21),
        # so integrity does not depend on the TLS cert -- disable verification for
        # the one blocking urequests call, then restore. Returns the original
        # ssl.wrap_socket (to restore) or None if it can't be patched (caller no-ops).
        try:
            import ssl
            orig = ssl.wrap_socket
        except Exception:
            return None
        def _wrap(sock, *a, **kw):
            kw["cert_reqs"] = ssl.CERT_NONE
            kw.pop("ca_certs", None)
            return orig(sock, *a, **kw)
        ssl.wrap_socket = _wrap
        return orig

    def _get(self, url, headers, timeout=10):
        import urequests
        _orig = self._patch_tls_no_verify() if url[:5] == "https" else None
        try:
            r = urequests.get(url, headers=headers or {}, timeout=timeout)
            try:
                sc = r.status_code
                try:
                    env = r.json()
                except Exception:
                    env = None
            finally:
                r.close()                   # never leak a socket across syncs
        finally:
            if _orig is not None:
                import ssl
                ssl.wrap_socket = _orig
        return sc, env

    def _post(self, url, body, headers=None, timeout=10):
        import urequests, json
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body)
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        _orig = self._patch_tls_no_verify() if url[:5] == "https" else None
        try:
            r = urequests.post(url, data=data, headers=h, timeout=timeout)
            try:
                sc = r.status_code
                try:
                    obj = r.json()
                except Exception:
                    obj = None
            finally:
                r.close()
        finally:
            if _orig is not None:
                import ssl
                ssl.wrap_socket = _orig
        return sc, obj

    async def _yield(self):
        import asyncio
        await asyncio.sleep_ms(80)          # let the loop/WDT run + lwIP drain

    def _now(self):
        import time
        return int(time.time())

    async def _bootstrap_clock(self, base):
        """The badge RTC is ~30 yr off until synced (no SNTP yet), so the first
        signed request's X-Ts would be refused as stale. Pull server_time from
        /healthz (unsigned) and seed clock_offset_s before the first sync."""
        try:
            _, env = self._get(base.rstrip("/") + "/healthz", {}, timeout=8)
            await self._yield()
            if isinstance(env, dict) and isinstance(env.get("server_time"), int):
                self.state.d["clock_offset_s"] = int(env["server_time"]) - self._now()
        except Exception:
            pass

    # -- public API -----------------------------------------------------------
    async def enroll(self, base, badge_key, name, groups, app_version, board):
        """POST /v1/enroll (unsigned bootstrap, §6.2). On success, persists pid,
        player_key, game_id and a fresh soul/commitment. Returns True/False."""
        st = self.state
        soul = make_soul()
        comm = commitment(soul)
        body = enroll_body(badge_key, name, groups, comm, app_version, board)
        try:
            sc, d = self._post(base.rstrip("/") + "/v1/enroll", body)
            await self._yield()
        except Exception:
            return False
        if sc != 200 or not isinstance(d, dict) or "player_key" not in d:
            return False
        st.enroll(int(d["pid"]), d["player_key"], int(d.get("game_id") or 0),
                  soul, comm)
        await self._bootstrap_clock(base)    # seed the clock for the first sync
        st.save()
        return True

    async def sync(self, base):
        """GET /v1/sync (signed). Verifies the response, merges it into state,
        persists, and returns the payload (or None on any failure)."""
        st = self.state
        if not st.is_enrolled():
            return None
        if st.d.get("synced_at") is None:
            await self._bootstrap_clock(base)
        ts = st.effective_now(self._now())
        nonce = new_nonce()
        url, headers = signed_get(st.d["pid"], st.d["player_key"], base,
                                  "/v1/sync", ts, nonce)
        try:
            _, env = self._get(url, headers)
            await self._yield()
        except Exception:
            return None
        payload = verify_response(st.d["player_key"], nonce, env)
        if payload is None:
            return None                      # unsigned/mis-signed/stale -> ignore
        st.apply_sync(payload, self._now())
        st.save()
        return payload

    async def flush_events(self, base, limit=200):
        """POST the queued events (signed). Removes the server's accepted uuids.
        Returns the response payload, or None. Idempotent: a failed/lost POST is
        retried whole on the next flush (server dedups by uuid)."""
        st = self.state
        if not st.is_enrolled() or len(st.queue) == 0:
            return None
        batch = st.queue.peek_batch(limit)
        ts = st.effective_now(self._now())
        nonce = new_nonce()
        url, headers, body = signed_post(st.d["pid"], st.d["player_key"], base,
                                         "/v1/events", {"events": batch}, ts, nonce)
        try:
            _, env = self._post(url, body, headers=headers)
            await self._yield()
        except Exception:
            return None
        payload = verify_response(st.d["player_key"], nonce, env)
        if payload is None:
            return None
        st.queue.remove(payload.get("accepted") or [])
        st.save()
        return payload
