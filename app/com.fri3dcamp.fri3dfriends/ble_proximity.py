# ble_proximity.py — BLE group-aware proximity finder for the Fri3d Camp 2024 badge
# (running MicroPythonOS).
#
# Two cleanly separated halves:
#
#   1. PURE WIRE-FORMAT FUNCTIONS (fnv1a_16, normalize_group, hash_groups,
#      name_budget, truncate_utf8, build_payload, parse_payload, intersect,
#      shared_name_for, parse_groups_field, merge_groups, new_groups_from).
#      These have NO dependency on `bluetooth` / `mpos` /
#      `lvgl` / `asyncio` and are unit-tested off-device (tests/). Importing
#      this module on a host must work.
#
#   2. The BLEProximity radio wrapper (begin/end/scan/advertise + IRQ-driven
#      state machine). It imports `bluetooth` LAZILY inside its methods so the
#      host can still load this module to test the pure functions.
#
# See DESIGN.md for the full protocol rationale (PLAN.md §6 adapted for the
# connected badge, which uses `ble.config("mac")` — public/static — and has no
# `fri3d.application` framework).

# ---------------------------------------------------------------------------
# Constants — protocol
# ---------------------------------------------------------------------------

MAGIC = b"HSNT"                 # "Hackerspace NameTag" — identifies any badge running this app
VERSION = 2                     # wire-format version byte (HSNT v2, plan §4)
COMPANY_ID = b"\xff\xff"        # little-endian placeholder (reserved/testing range)
AD_TYPE_MFG = 0xFF              # Manufacturer Specific Data

MAX_GROUPS = 5                  # cap on advertised group IDs (2 bytes each on the wire)

# HSNT v2 adds a `blocks` byte (always present) after the version, and an
# optional 5-byte game block after the name when bit0 of `blocks` is set
# (plan §4). When no game is running the bit is clear and the beacon is the
# same size as v1, so Gotcha costs nothing when idle.
BLOCK_GAME = 0x01               # bit0 of `blocks`: a game block is appended
GAME_BLOCK_LEN = 5              # pid(3) + gflags(1) + streak(1)

# gflags bits on air (plan §4). Let a nearby badge render bounty/streak/alive
# and the "protected"/"truce" states with no backend round-trip.
GFLAG_ALIVE = 0x01
GFLAG_UNDER_ATTACK = 0x02
GFLAG_BOUNTY = 0x04
GFLAG_TRUCE = 0x08
GFLAG_PROTECTED = 0x10
GFLAG_SEEKING_TRAINING = 0x20

# 31-byte adv budget, no Flags AD emitted (non-connectable beacon):
#   2 (AD len+type) + 2 (company) + 4 (magic) + 1 (version) + 1 (blocks)
#   + 1 (group count) + 2*G (groups) + 1 (name len)  =  12 + 2*G  of overhead,
#   name gets the rest; +5 more when a game block is present.
ADV_TOTAL = 31
OVERHEAD = 2 + 2 + 4 + 1 + 1 + 1 + 1   # +1 vs v1 for the `blocks` byte

# Tuning (radio wrapper)
ADV_MS = 250                    # advertise interval (ms)
EVICT_MS = 30000                # peer gone if not seen for this long (ms)
SEEN_CAP = 64                   # LRU cap on the peer table (plan §4)
# Scanning: a CONTINUOUS, dense scan with an explicit interval/window. This is
# critical — MicroPython's gap_scan() with DEFAULT args enables NimBLE's
# duplicate filter, so each peer is reported only ~once and presence flaps as
# peers age out. Passing explicit interval_us/window_us disables that filter,
# so every advertisement is reported and last_seen stays fresh (age <1 s) even
# amid collisions from several co-located badges. 50% duty (window 60 ms,
# interval 120 ms) holds peers rock-solid for a fraction of the RX power of
# 100% duty. gap_scan(0, ...) runs indefinitely; we re-arm every SCAN_REARM_MS
# as insurance in case the stack ever stops it.
SCAN_WINDOW_US = 60000          # 60 ms listen window
SCAN_INTERVAL_US = 120000       # 120 ms scan interval  -> 50% duty, dense
SCAN_REARM_MS = 30000           # restart the continuous scan this often
RSSI_FLOOR_DEFAULT = -120       # disabled (ESP32-S3 sensitivity ~-97 dBm)


# ---------------------------------------------------------------------------
# 1. PURE WIRE-FORMAT FUNCTIONS
# ---------------------------------------------------------------------------

def fnv1a_16(data):
    """FNV-1a 32-bit of `data` (bytes), folded to 16 bits via xor-folding.

    Collision-tolerant group identifier, NOT a security mechanism. Same bytes
    always produce the same 16-bit id; different group names practically differ.
    """
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 0xFFFF


def normalize_group(name):
    """Normalize a group name before hashing: strip + lower.

    Trivial formatting differences between two members typing the same group
    ('Makerspace Baasrode ' vs 'makerspace baasrode') still hash identically.
    Non-string / None -> '' (so they hash to a consistent, ignorable value).
    """
    if not isinstance(name, str):
        return ""
    return name.strip().lower()


def hash_groups(groups, max_groups=MAX_GROUPS):
    """Hash a list of group names into a deduplicated, sorted, capped list of
    16-bit ids.

    Returns (ids, dropped) where `ids` is sorted ascending and `dropped` is the
    number of distinct ids beyond max_groups that were discarded (we keep the
    lowest `max_groups`, deterministically — both ends agree).
    """
    seen = set()
    for g in groups or []:
        n = normalize_group(g)
        if not n:
            continue
        seen.add(fnv1a_16(n.encode("utf-8")))
    ids = sorted(seen)
    if len(ids) > max_groups:
        dropped = len(ids) - max_groups
        ids = ids[:max_groups]
    else:
        dropped = 0
    return ids, dropped


FLAG_AD_LEN = 3  # a connectable advert carries a Flags AD (len+type+flags)


def name_budget(num_groups, total=ADV_TOTAL, overhead=OVERHEAD, game=False, connectable=False):
    """Bytes available for the name field given `num_groups` advertised ids.

    `game` True reserves the 5-byte game block too (the v2 `blocks` byte is
    already counted in OVERHEAD). `connectable` True reserves the 3-byte Flags AD
    a connectable advert must carry -- without it central stacks (BlueZ/hcitool,
    verified on the 2026 badge) do not treat the advert as connectable and the
    connection hangs indefinitely (plan §5.7 probe finding, 2026-08-01)."""
    extra = GAME_BLOCK_LEN if game else 0
    flag = FLAG_AD_LEN if connectable else 0
    nb = total - overhead - extra - flag - 2 * num_groups
    return nb if nb > 0 else 0


def build_game_block(pid, gflags=0, streak=0):
    """The 5-byte v2 game block: pid(3 LE) + gflags(1) + streak(1) (plan §4)."""
    pid = int(pid or 0) & 0xFFFFFF
    return bytes([pid & 0xFF, (pid >> 8) & 0xFF, (pid >> 16) & 0xFF,
                  int(gflags) & 0xFF, int(streak) & 0xFF])


def parse_game_block(b):
    """Inverse of build_game_block. Bad input -> None, never raises."""
    if not isinstance(b, (bytes, bytearray)) or len(b) < GAME_BLOCK_LEN:
        return None
    return {"pid": b[0] | (b[1] << 8) | (b[2] << 16),
            "gflags": b[3], "streak": b[4]}


def truncate_utf8(s, max_bytes):
    """Truncate string `s` so its UTF-8 encoding fits in `max_bytes`, cutting
    only on a character (codepoint) boundary — never mid-codepoint."""
    if max_bytes <= 0:
        return ""
    enc = s.encode("utf-8")
    if len(enc) <= max_bytes:
        return s
    # Walk back to a UTF-8 boundary. A continuation byte has top bits 10xxxxxx.
    cut = max_bytes
    while cut > 0 and (enc[cut] & 0xC0) == 0x80:
        cut -= 1
    return enc[:cut].decode("utf-8", "ignore")


def build_payload(group_ids, name, game=None, connectable=False):
    """Build the v2 advertising payload (one manufacturer AD structure).

    `group_ids` must already be deduped/sorted/capped (use hash_groups()).
    `name` is truncated to the available budget on a UTF-8 boundary. `game`, if
    a dict with a `pid`, appends the 5-byte game block (plan §4) and sets the
    blocks bit so the name is budgeted for it. `connectable` prepends a Flags AD
    (LE General Discoverable + BR/EDR Not Supported) so central stacks honour the
    advert as connectable (plan §5.7 probe finding); parse_payload skips it.
    Returns bytes of length <= ADV_TOTAL.
    """
    gids = sorted(set(int(g) & 0xFFFF for g in group_ids))[:MAX_GROUPS]
    has_game = isinstance(game, dict) and game.get("pid") is not None
    nb = name_budget(len(gids), game=has_game, connectable=connectable)
    disp = truncate_utf8(name or "", nb)
    name_b = disp.encode("utf-8")

    body = (
        COMPANY_ID +
        MAGIC +
        bytes([VERSION, BLOCK_GAME if has_game else 0x00, len(gids)]) +
        b"".join(_u16_le(g) for g in gids) +
        bytes([len(name_b)]) +
        name_b
    )
    if has_game:
        body += build_game_block(game.get("pid"), game.get("gflags", 0),
                                 game.get("streak", 0))
    # AD structure: [length-of-following, type, body...]
    mfg = bytes([len(body) + 1, AD_TYPE_MFG]) + body
    if connectable:
        # Flags AD first: type 0x01, value 0x06 (LE gen discoverable, no BR/EDR).
        return bytes([0x02, 0x01, 0x06]) + mfg
    return mfg


def parse_payload(adv):
    """Defensively parse an advertising payload and extract our beacon if present.

    `adv` is the raw advertisement bytes (one or more AD structures). Returns a
    dict {version, group_ids, name, game} on a valid HSNT v1/v2 beacon, or None
    for anything malformed, wrong magic/company, unknown version, reserved blocks
    bits, or length fields that overrun the buffer. `game` is None unless a v2
    game block is present and well-formed. Never raises.
    """
    if not isinstance(adv, (bytes, bytearray)):
        return None
    i = 0
    n = len(adv)
    while i + 1 < n:
        slen = adv[i]
        if slen == 0:
            i += 1
            continue
        ad_type = adv[i + 1]
        field = adv[i + 2:i + 2 + slen - 1]
        i += 1 + slen
        if ad_type != AD_TYPE_MFG:
            continue
        # Need: company(2) + magic(4) = 6 bytes minimum to even check.
        if len(field) < 2 + len(MAGIC):
            continue
        if field[:2] != COMPANY_ID:
            continue            # not our (placeholder) company id
        if field[2:2 + len(MAGIC)] != MAGIC:
            continue
        rest = field[2 + len(MAGIC):]
        if len(rest) < 1:
            continue
        version = rest[0]
        if version == 1:
            # v1: ver gcount gids namelen name (no blocks byte, no game block)
            blocks = 0
            if len(rest) < 2:
                continue
            gcount = rest[1]
            p = 2
        elif version == 2:
            # v2: ver blocks gcount gids namelen name [game block]
            if len(rest) < 3:
                continue
            blocks = rest[1]
            if blocks & ~BLOCK_GAME:        # reserved bits set -> drop (forward-compat)
                continue
            gcount = rest[2]
            p = 3
        else:
            continue                        # unknown version -> drop
        gid_end = p + 2 * gcount
        if len(rest) < gid_end + 1:
            continue                        # truncated
        gids = []
        for k in range(gcount):
            lo = rest[p + 2 * k]
            hi = rest[p + 2 * k + 1]
            gids.append(lo | (hi << 8))
        namelen = rest[gid_end]
        name_start = gid_end + 1
        if len(rest) < name_start + namelen:
            continue                        # truncated
        name_b = rest[name_start:name_start + namelen]
        try:
            name = name_b.decode("utf-8", "replace")
        except Exception:
            name = ""
        game = None
        if version == 2 and (blocks & BLOCK_GAME):
            gb = rest[name_start + namelen:name_start + namelen + GAME_BLOCK_LEN]
            game = parse_game_block(gb)     # None if truncated/short
        return {"version": version, "group_ids": gids, "name": name, "game": game}
    return None


def intersect(own_ids, peer_ids):
    """Return the set of group ids present in BOTH lists (the match test)."""
    a = set(own_ids)
    return a.intersection(peer_ids)


def shared_name_for(own_groups, peer_ids):
    """Map the (sorted ascending) shared group ids back to the lowest-sorted
    shared group's display name, using this badge's own name->hash table.

    own_groups: list of (name, id) pairs (display name + its hash).
    peer_ids: the peer's advertised group ids.
    Returns (shared_id_lowest, shared_name) or (None, None) if no overlap.
    The lowest-sorted shared id is the deterministic 'signature' both badges
    agree on for colour/tone.
    """
    pid = set(peer_ids)
    id_to_name = {}
    for name, gid in own_groups:
        if gid in pid:
            id_to_name.setdefault(gid, name)   # first (original order) name wins per id
    if not id_to_name:
        return None, None
    low = min(id_to_name)
    return low, id_to_name[low]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _u16_le(v):
    return bytes([v & 0xFF, (v >> 8) & 0xFF])


def build_own_table(groups):
    """Return [(display_name, id), ...] for the configured groups (dedup by id,
    preserving first-seen display name). Used by shared_name_for()."""
    out = []
    seen = set()
    for g in groups or []:
        n = normalize_group(g)
        if not n:
            continue
        gid = fnv1a_16(n.encode("utf-8"))
        if gid in seen:
            continue
        seen.add(gid)
        out.append((g, gid))
    return out


def parse_groups_field(value):
    """Parse the cleartext "Groups" contact field from a Y-swap -> [name, ...].

    `contact_exchange` ships the sender's group NAMES (not the hashed ids) as a
    comma-joined string in the contact envelope, so a receiving badge can offer
    to join them (zero typing — a typo'd group hashes differently and silently
    never matches, which is the worst failure mode this app has).

    Defensive: non-str input -> []. Empty/whitespace entries are dropped.
    """
    if not isinstance(value, str):
        return []
    return [g.strip() for g in value.split(",") if g.strip()]


def merge_groups(existing, incoming, max_groups=MAX_GROUPS):
    """Append `incoming` group names to `existing`, skipping duplicates.

    Returns `(merged, dropped)`. Duplicate detection uses normalize_group(), so
    "Makerspace Baasrode" is recognised as already-joined even when the peer
    typed " makerspace baasrode ". `existing` is never reordered or rewritten —
    the user's own spelling of a group they already have wins.

    The result is capped at `max_groups` (the beacon can only advertise
    MAX_GROUPS ids); `dropped` counts the incoming names that did not fit, so
    the caller can say so instead of silently discarding them.

    Pure — no clock, no radio. Unit-tested off-device.
    """
    merged = list(existing or [])
    seen = set()
    for g in merged:
        n = normalize_group(g)
        if n:
            seen.add(n)
    dropped = 0
    for g in incoming or []:
        n = normalize_group(g)
        if not n or n in seen:
            continue
        if len(merged) >= max_groups:
            dropped += 1
            continue
        seen.add(n)
        merged.append(g.strip() if isinstance(g, str) else g)
    return merged, dropped


def new_groups_from(existing, incoming, max_groups=MAX_GROUPS):
    """The subset of `incoming` that is not already in `existing`.

    Used to decide whether a post-swap "join a group?" prompt is worth showing
    at all, and to populate its rows. Dedups within `incoming` too, so a peer
    listing the same group twice offers it once. Order is preserved.
    """
    seen = set()
    for g in existing or []:
        n = normalize_group(g)
        if n:
            seen.add(n)
    out = []
    for g in incoming or []:
        n = normalize_group(g)
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(g.strip() if isinstance(g, str) else g)
        if len(out) >= max_groups:
            break
    return out


# ---------------------------------------------------------------------------
# 2b. PEER-TABLE ADMISSION + LRU (pure; plan §4 pre-existing weakness)
# ---------------------------------------------------------------------------
#
# Today _process_result() drops any advert sharing no group, which keeps _seen
# small by accident. Once game-block peers are admitted (a Gotcha target is by
# design almost never in your group, D9), 700 badges mean unbounded growth. So
# admission widens during a live game (target pid / bounty / alive-dead display)
# AND the table is capped with an LRU that pins the current target + bounty
# peers so a dense crowd can never evict the one peer the game is about.

def admit_peer(own_ids, info, admit_pids=None, game_live=False):
    """Should this parsed advert enter the peer table?

    Admit if it shares a group (the friend finder), OR -- during a live game --
    it carries a v2 game block and is the current target / a wanted bounty
    player. Defensive; never raises."""
    if not isinstance(info, dict):
        return False
    if intersect(own_ids, info.get("group_ids") or []):
        return True
    if game_live:
        g = info.get("game")
        if isinstance(g, dict):
            pid = g.get("pid")
            if admit_pids and pid in admit_pids:
                return True
            if g.get("gflags", 0) & GFLAG_BOUNTY:
                return True
    return False


def evict_lru(seen, cap, pinned_keys=None):
    """If len(seen) > cap, drop the lowest-last_seen NON-pinned entries until it
    fits. `seen` is mutated in place; returns the evicted keys. If every entry is
    pinned, stops (the table may briefly exceed the cap rather than lose a pin)."""
    pinned = pinned_keys or set()
    evicted = []
    while len(seen) > cap:
        victim = None
        victim_t = None
        for k, e in seen.items():
            if k in pinned:
                continue
            t = e.get("last_seen_ms", 0)
            if victim is None or t < victim_t:
                victim, victim_t = k, t
        if victim is None:
            break
        del seen[victim]
        evicted.append(victim)
    return evicted


# ---------------------------------------------------------------------------
# 3. RADIO WRAPPER  (lazy `import bluetooth`)
# ---------------------------------------------------------------------------

class BLEProximity:
    """Advertise this badge's groups/name and scan for matching peers.

    Cooperative: the UI loop calls tick() every frame to run eviction and
    duty-cycled scanning. New arrivals are queued in _arrivals; drain with
    take_arrivals(). current_peers() returns the in-range set for display.
    """

    def __init__(self):
        self._ble = None
        self._active = False
        self._own_ids = []
        self._own_table = []          # [(name, id), ...]
        self._rssi_floor = RSSI_FLOOR_DEFAULT
        self._seen = {}               # key (addr_type, addr_bytes) -> dict
        self._seen_cap = SEEN_CAP     # LRU cap on the peer table (plan §4)
        self._arrivals = []           # queued new-arrival events for UI
        self._pending = []            # raw scan results captured in the IRQ, drained in tick()
        self._adv = None              # current adv payload
        self._next_rearm_ms = 0       # ticks_ms deadline to restart the continuous scan
        self._irq_scan_result = 5     # bluetooth._IRQ_SCAN_RESULT (seeded in begin)
        self._name = ""
        self._suspended = False       # True while the contact-exchange window owns the radio
        # Gotcha game context (plan §4, §8.8.2). Defaults make rssi_prox behave
        # like the symmetric friends EWMA until Gotcha supplies the asymmetric
        # hunt alphas; admission/pinning stay friend-only until a game is live.
        self._prox_alpha_up = 0.3
        self._prox_alpha_down = 0.3
        self._admit_pids = set()      # extra pids to admit during a live game
        self._pin_pids = set()        # pids never evicted by the LRU (target/bounty)
        self._game = None             # current v2 game block on air (plan §4)
        self._connectable = False     # non-connectable beacon until a Gotcha game is live (§5.1)
        self._gatt_dispatch = None    # optional IRQ forwarder for the Gotcha GATT server (§5.6)

    # ---- lifecycle ----
    def begin(self, groups, name, rssi_floor=RSSI_FLOOR_DEFAULT, game=None):
        import bluetooth
        from bluetooth import BLE
        self._own_ids, _ = hash_groups(groups)
        self._own_table = build_own_table(groups)
        # Coerce the name to str so a non-string config value degrades instead of
        # crashing begin() in build_payload/truncate_utf8.
        self._name = name if isinstance(name, str) else ""
        self._rssi_floor = self._validate_floor(rssi_floor)
        self._irq_scan_result = getattr(bluetooth, "_IRQ_SCAN_RESULT", 5)
        self._game = game

        self._adv = build_payload(self._own_ids, self._name, game=self._game,
                                  connectable=self._connectable)

        self._ble = BLE()
        # Only activate if not already active: active(True) on an ALREADY-active
        # radio re-inits NimBLE and WIPES the gatts registration on this build
        # (verified: a registered handle EINVALs right after a redundant
        # active(True)). Since services are registered before begin() advertises
        # (fri3d_friends onResume), a blind active(True) here would silently
        # destroy the whole GATT server -- the Phase-3b "victim serves no service"
        # bug. gap_advertise itself preserves the registration; only active(True)
        # on an active radio does not.
        if not self._ble.active():
            self._ble.active(True)
        # Stable public address is the default on this build (verified
        # ble.config("mac") -> (0, ...)); no addr_mode change needed.
        self._ble.irq(self._irq)
        adv_ok = True
        try:
            self._ble.gap_advertise(ADV_MS * 1000, adv_data=self._adv,
                                    connectable=self._connectable)
        except Exception:
            adv_ok = False        # scanning-but-invisible; report it to the caller
        self._next_rearm_ms = 0       # start the continuous scan on the first tick()
        self._active = True
        return adv_ok

    def set_game(self, game):
        """Update the v2 game block on air (pid/gflags/streak change after a
        sync). Rebuilds the adv payload and re-advertises; a None game drops the
        block (idle beacon). Safe to call before begin() (just stores it)."""
        self._game = game
        self._adv = build_payload(self._own_ids, self._name, game=self._game,
                                  connectable=self._connectable)
        if self._ble and self._active and not self._suspended:
            try:
                self._ble.gap_advertise(ADV_MS * 1000, adv_data=self._adv,
                                        connectable=self._connectable)
            except Exception:
                pass

    def set_connectable(self, on):
        """Switch the beacon between non-connectable (friends-only) and connectable
        (a live Gotcha game: the target must be reachable for a REVEAL/ATTACK,
        plan §5.1). Re-advertises immediately on a real flip; no-op before begin()."""
        on = bool(on)
        if on == self._connectable:
            return
        self._connectable = on
        # Rebuild the payload: a connectable advert must carry the Flags AD, so the
        # name budget + AD set change when the flag flips.
        self._adv = build_payload(self._own_ids, self._name, game=self._game,
                                  connectable=self._connectable)
        if self._ble and self._active and not self._suspended and self._adv is not None:
            try:
                self._ble.gap_advertise(ADV_MS * 1000, adv_data=self._adv,
                                        connectable=self._connectable)
            except Exception:
                pass

    def end(self):
        if not self._ble:
            return
        self._active = False
        try:
            self._ble.gap_scan(None)
        except Exception:
            pass
        try:
            self._ble.gap_advertise(None)
        except Exception:
            pass
        try:
            self._ble.active(False)
        except Exception:
            pass
        self._ble = None
        self._seen = {}
        self._arrivals = []
        self._pending = []

    # ---- hand the radio to / take it back from the contact-exchange window ----
    def suspend(self):
        """Stop advertising + scanning (but keep BLE active) so the contact
        exchange can take over the single adv set / IRQ handler. Idempotent."""
        if not self._ble:
            self._suspended = True
            return
        self._suspended = True
        for fn in (lambda: self._ble.gap_scan(None),
                   lambda: self._ble.gap_advertise(None)):
            try:
                fn()
            except Exception:
                pass

    def resume(self):
        """Reinstall the proximity IRQ + non-connectable beacon and re-arm the
        dense scan after a contact-exchange window returns the radio."""
        self._suspended = False
        if not self._ble:
            return
        try:
            self._ble.irq(self._irq)
        except Exception:
            pass
        if self._adv is not None:
            try:
                self._ble.gap_advertise(ADV_MS * 1000, adv_data=self._adv,
                                        connectable=self._connectable)
            except Exception:
                pass
        self._next_rearm_ms = 0        # re-arm the continuous scan on the next tick()

    # ---- continuous dense scan (called from UI loop each frame) ----
    def tick(self, now_ms, dt_ms):
        if not self._active or not self._ble or self._suspended:
            return
        from time import ticks_diff, ticks_add
        # Drain scan results captured by the IRQ and update the peer table on
        # THIS (loop) thread, so _seen is never mutated mid-iteration by the IRQ.
        self._process_pending(now_ms)
        # Evict stale peers every frame (cheap).
        self._evict(now_ms)
        # Re-arm the continuous dense scan periodically (starts it on the first
        # tick, and restarts it every SCAN_REARM_MS as insurance). ticks_diff is
        # wrap-safe (PLAN §6.3) — never compare raw ticks_ms values.
        if ticks_diff(now_ms, self._next_rearm_ms) >= 0:
            try:
                self._ble.gap_scan(0, SCAN_INTERVAL_US, SCAN_WINDOW_US)
            except Exception:
                pass
            self._next_rearm_ms = ticks_add(now_ms, SCAN_REARM_MS)

    # ---- IRQ: capture only (no parsing / no _seen mutation here) ----
    def _irq(self, event, data):
        if event == self._irq_scan_result:
            try:
                # On MicroPython NimBLE, _IRQ_SCAN_RESULT data layout:
                #   (addr_type, addr, adv_type, rssi, adv_data)
                addr_type, addr, adv_type, rssi, adv_data = data
                # Copy the transient buffers (only valid during this callback) and
                # queue for processing in tick(). Bound the queue so a stalled loop
                # can't grow it without limit.
                if len(self._pending) < 256:
                    self._pending.append((addr_type, bytes(addr), bytes(adv_data), rssi))
            except Exception:
                pass              # never let an IRQ raise
            return
        # Any other event is GATT-server activity while we own the radio (a central
        # connected/disconnected, or a write to a Gotcha characteristic). Forward
        # it to the Gotcha responder (plan §5.6) so an inbound REVEAL is answered
        # without this scanner knowing anything about GATT. No-op if none attached.
        dispatch = self._gatt_dispatch
        if dispatch is not None:
            try:
                dispatch(event, data)
            except Exception:
                pass              # an IRQ must never crash the scan path

    # ---- deferred processing (runs in tick(), on the loop thread) ----
    def _process_pending(self, now):
        if not self._pending:
            return
        pending = self._pending
        self._pending = []            # atomic rebind; a concurrent IRQ append is safe
        for addr_type, addr, adv_data, rssi in pending:
            self._process_result(addr_type, addr, adv_data, rssi, now)

    def _process_result(self, addr_type, addr, adv_data, rssi, now):
        info = parse_payload(adv_data)
        if info is None:
            return
        game_live = bool(self._admit_pids) or bool(self._pin_pids)
        if not admit_peer(self._own_ids, info, self._admit_pids, game_live):
            return                  # not a friend, and not a game-admitted peer
        if rssi < self._rssi_floor:
            return                  # below noise floor
        key = (addr_type, addr)
        entry = self._seen.get(key)
        shared_id, shared_name = shared_name_for(self._own_table, info["group_ids"])
        game = info.get("game")
        pid = game.get("pid") if isinstance(game, dict) else None
        is_new = entry is None
        if is_new:
            entry = {
                "name": info["name"],
                "shared_id": shared_id,
                "shared_name": shared_name,
                "addr_type": addr_type,
                "addr": addr,
                "pid": pid,
                "gflags": game.get("gflags", 0) if isinstance(game, dict) else 0,
                "rssi": rssi,
                "rssi_ewma": float(rssi),
                "rssi_prox": float(rssi),
                "last_seen_ms": now,
            }
            self._seen[key] = entry
            # A friend-arrival is announced only for group-sharing peers, never
            # for a game-only admit (the target is rarely a group-mate, D9).
            if shared_id is not None:
                self._arrivals.append({
                    "name": info["name"],
                    "shared_id": shared_id,
                    "shared_name": shared_name,
                    "rssi": rssi,
                })
            self._enforce_cap()
        else:
            entry["last_seen_ms"] = now
            a = 0.3
            entry["rssi_ewma"] = (1 - a) * entry["rssi_ewma"] + a * rssi
            entry["rssi_prox"] = self._filter_prox(entry["rssi_prox"], rssi)
            entry["rssi"] = rssi
            entry["name"] = info["name"]     # refresh (peer may have been renamed)
            entry["shared_name"] = shared_name
            entry["shared_id"] = shared_id
            entry["pid"] = pid
            if isinstance(game, dict):
                entry["gflags"] = game.get("gflags", 0)

    # ---- Gotcha game context (admission widening + LRU pinning + hunt filter) ----
    def set_game_context(self, admit_pids=None, pin_pids=None):
        """Tell the scanner which extra peers to admit (target pid, alive-dead
        display) and which to pin against LRU eviction (target + bounty), during
        a live game. Pass empty/None to return to friend-only admission."""
        self._admit_pids = set(admit_pids or [])
        self._pin_pids = set(pin_pids or [])

    def set_prox_filter(self, alpha_up=None, alpha_down=None):
        """Set the asymmetric hunt-path rssi_prox coefficients (plan §8.8.2).
        Defaults 0.3/0.3 mirror the friends EWMA; Gotcha passes the live
        PROX_ALPHA_UP/DOWN tunables so rssi_prox attacks fast and decays slow."""
        if alpha_up is not None:
            self._prox_alpha_up = alpha_up
        if alpha_down is not None:
            self._prox_alpha_down = alpha_down

    def _filter_prox(self, prev, rssi):
        a = self._prox_alpha_up if rssi > prev else self._prox_alpha_down
        return (1.0 - a) * prev + a * rssi

    def _enforce_cap(self):
        if len(self._seen) <= self._seen_cap:
            return
        pinned = set()
        if self._pin_pids:
            for k, e in self._seen.items():
                if e.get("pid") in self._pin_pids:
                    pinned.add(k)
        evict_lru(self._seen, self._seen_cap, pinned)

    def peer_by_pid(self, pid):
        """The _seen entry for the peer advertising this game pid, or None.
        The hunt reads the target's rssi_prox from here (§8.8.2)."""
        for e in self._seen.values():
            if e.get("pid") == pid:
                return e
        return None

    def addr_for_pid(self, pid):
        """(addr_type, addr_bytes) for the peer advertising this pid, or None.

        The hunter needs the address to gap_connect() to its target (plan §5.1).
        The address is kept in the entry (not just the _seen key) precisely so it
        is reachable from a pid lookup."""
        e = self.peer_by_pid(pid)
        if e is None:
            return None
        return (e.get("addr_type"), e.get("addr"))

    def set_gatt_dispatch(self, fn):
        """Install the Gotcha GATT-server IRQ forwarder (plan §5.6). While we own
        the radio, _irq() routes non-scan events (central connect/disconnect,
        GATT writes) to `fn(event, data)`. Pass None to detach."""
        self._gatt_dispatch = fn

    # ---- eviction ----
    def _evict(self, now_ms):
        from time import ticks_diff
        stale = []
        for key, e in self._seen.items():
            if ticks_diff(now_ms, e["last_seen_ms"]) > EVICT_MS:
                stale.append(key)
        for k in stale:
            del self._seen[k]

    # ---- UI accessors ----
    def take_arrivals(self):
        a = self._arrivals
        self._arrivals = []
        return a

    def current_peers(self):
        # list of (name, shared_name, shared_id, rssi_ewma, age_ms) sorted by name.
        # Friends only: a game-admitted peer (the Gotcha target, D9) carries
        # shared_id=None and must NOT surface in the friends UI -- it is not a
        # friend, its group is unknown, and a None gid crashes the detail-row
        # colour path (C5/D32). The hunt reads the target via peer_by_pid().
        from time import ticks_diff, ticks_ms
        now = ticks_ms()
        out = []
        for e in self._seen.values():
            if e["shared_id"] is None:
                continue
            out.append((
                e["name"],
                e["shared_name"],
                e["shared_id"],
                int(e["rssi_ewma"]),
                ticks_diff(now, e["last_seen_ms"]),
            ))
        out.sort(key=lambda x: x[0].lower())
        return out

    def has_peers(self):
        # Friends only (see current_peers): a game-only admit must not count as a
        # nearby friend, or it suppresses the backlight dim and inflates the count.
        for e in self._seen.values():
            if e["shared_id"] is not None:
                return True
        return False

    # ---- validation ----
    @staticmethod
    def _validate_floor(v):
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return RSSI_FLOOR_DEFAULT
        if iv < -120 or iv > 0:
            return RSSI_FLOOR_DEFAULT
        return iv
