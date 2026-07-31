"""Off-device unit tests for ble_proximity.py pure wire-format functions.

Covers every PLAN.md §10 unit-test bullet:
  - AD payload round-trip encode/decode (1 group, several groups)
  - fnv1a_16 hashing (same name -> same hash after normalization; different
    names -> different hash in practice)
  - per-group hashing + dedup/sort determinism
  - group-set intersection matching (overlap -> match; disjoint -> no match)
  - name truncation at the group-count-dependent budget on a UTF-8 boundary
  - version byte round-trips; unknown version rejected
  - MAX_GROUPS overflow keeps the lowest ids
  - malformed/hostile adverts dropped without raising

These import ONLY the pure functions — no bluetooth/fri3d/lvgl needed.
"""
import ble_proximity as bp
from ble_proximity import (
    fnv1a_16, normalize_group, hash_groups, name_budget, truncate_utf8,
    build_payload, parse_payload, intersect, shared_name_for, build_own_table,
    build_game_block, parse_game_block, admit_peer, evict_lru,
    MAGIC, VERSION, ADV_TOTAL, OVERHEAD, MAX_GROUPS, SEEN_CAP,
    BLOCK_GAME, GAME_BLOCK_LEN, GFLAG_ALIVE, GFLAG_BOUNTY,
)


# ---------------------------------------------------------------------------
# fnv1a_16 hashing
# ---------------------------------------------------------------------------
def test_fnv_is_deterministic():
    assert fnv1a_16(b"Makerspace Baasrode") == fnv1a_16(b"Makerspace Baasrode")


def test_fnv_is_16_bits():
    for s in (b"a", b"hello", b"Makerspace Baasrode", b"x" * 200):
        v = fnv1a_16(s)
        assert 0 <= v <= 0xFFFF


def test_fnv_different_inputs_differ():
    # In practice distinct group names should not collide.
    vals = {fnv1a_16(n) for n in (
        b"alpha", b"beta", b"gamma", b"delta", b"epsilon",
        b"Makerspace Baasrode", b"Hack42", b"RevSpace",
    )}
    assert len(vals) == 8


def test_fnv_known_vector():
    # Known FNV-1a-32 of empty string is 0x811c9dc5 -> xor-fold = 0x811c ^ 0x9dc5
    # = 0x1cd9. Pins the implementation to a reference value.
    assert fnv1a_16(b"") == (0x811C9DC5 ^ (0x811C9DC5 >> 16)) & 0xFFFF


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------
def test_normalize_collapses_trivial_differences():
    assert normalize_group("Makerspace Baasrode") == normalize_group(" makerspace baasrode ")
    assert normalize_group("RevSpace") == normalize_group("REVSPACE")
    assert normalize_group("  Hack42 ") == "hack42"


def test_normalize_non_string():
    assert normalize_group(None) == ""
    assert normalize_group(123) == ""
    assert normalize_group("") == ""


# ---------------------------------------------------------------------------
# hash_groups: dedup + sort + cap determinism
# ---------------------------------------------------------------------------
def test_hash_groups_dedup_and_sort():
    ids, dropped = hash_groups(["Beta", "Alpha", "beta", " ALPHA ", "Gamma"])
    # 'Beta'/'beta' and 'Alpha'/' ALPHA ' collapse; 3 distinct ids, sorted.
    assert ids == sorted(ids)
    assert len(ids) == 3
    assert dropped == 0


def test_hash_groups_deterministic():
    a, _ = hash_groups(["X", "Y", "Z"])
    b, _ = hash_groups(["Z", "Y", "X"])
    assert a == b  # order-independent


def test_hash_groups_overflow_keeps_lowest():
    # Force a collision-free set larger than MAX_GROUPS.
    found = []
    i = 0
    while len(found) < MAX_GROUPS + 4:
        h = fnv1a_16(("g%d" % i).encode())
        if h not in found:
            found.append(h)
        i += 1
    names = ["g%d" % j for j in range(i) if fnv1a_16(("g%d" % j).encode()) in found]
    ids, dropped = hash_groups(names)
    assert len(ids) == MAX_GROUPS
    assert dropped == 4
    # The kept ids are the MAX_GROUPS lowest of the full set.
    assert ids == sorted(found)[:MAX_GROUPS]


def test_hash_groups_empty_and_garbage():
    ids, dropped = hash_groups([])
    assert ids == [] and dropped == 0
    ids, dropped = hash_groups(["", "   ", None])
    assert ids == [] and dropped == 0


# ---------------------------------------------------------------------------
# build/parse round-trip
# ---------------------------------------------------------------------------
def test_roundtrip_one_group():
    ids, _ = hash_groups(["Makerspace Baasrode"])
    adv = build_payload(ids, "Alex")
    assert len(adv) <= ADV_TOTAL
    info = parse_payload(adv)
    assert info is not None
    assert info["version"] == VERSION
    assert info["group_ids"] == ids
    assert info["name"] == "Alex"


def test_roundtrip_several_groups():
    ids, _ = hash_groups(["Hack42", "RevSpace", "Makerspace Baasrode"])
    adv = build_payload(ids, "Alice ON4XYZ")
    info = parse_payload(adv)
    assert info is not None
    assert info["group_ids"] == ids
    assert info["name"] == "Alice ON4XYZ"


def test_payload_has_magic_and_version_and_company():
    ids, _ = hash_groups(["X"])
    adv = build_payload(ids, "n")
    # AD header
    assert adv[1] == 0xFF
    body = adv[2:]
    assert body[0:2] == b"\xff\xff"          # company id (LE placeholder)
    assert body[2:2 + len(MAGIC)] == MAGIC   # magic
    assert body[2 + len(MAGIC)] == VERSION   # version byte


def test_payload_within_budget():
    ids, _ = hash_groups(["A", "B", "C", "D", "E"])  # max groups
    adv = build_payload(ids, "A" * 200)              # over-long name
    assert len(adv) <= ADV_TOTAL


# ---------------------------------------------------------------------------
# name truncation on a UTF-8 boundary
# ---------------------------------------------------------------------------
def test_truncate_ascii_boundary():
    assert truncate_utf8("Alex", 3) == "Ale"
    assert truncate_utf8("Alex", 100) == "Alex"
    assert truncate_utf8("Alex", 0) == ""


def test_truncate_never_splits_codepoint():
    # 'é' is 2 bytes in UTF-8 (0xC3 0xA9). Cutting at byte 1 must drop it.
    s = "ééé"            # 6 bytes
    t = truncate_utf8(s, 1)
    assert t.encode("utf-8") == b""           # no partial codepoint
    t = truncate_utf8(s, 2)
    assert t == "é"
    t = truncate_utf8(s, 3)
    assert t == "é"                            # the second 'é' would be split
    t = truncate_utf8(s, 4)
    assert t == "éé"


def test_truncate_multibyte_emoji():
    # '🚀' is 4 bytes in UTF-8.
    s = "a🚀b"
    assert truncate_utf8(s, 1) == "a"
    assert truncate_utf8(s, 2) == "a"          # can't include emoji (needs 4)
    assert truncate_utf8(s, 5) == "a🚀"        # 'a'(1) + '🚀'(4) = 5
    assert truncate_utf8(s, 6) == "a🚀b"


def test_name_truncated_in_payload_roundtrips_cleanly():
    ids, _ = hash_groups(["A", "B", "C"])
    nb = name_budget(len(ids))
    name = "Müller Märchen 🚀" * 5             # lots of multibyte
    adv = build_payload(ids, name)
    info = parse_payload(adv)
    assert info is not None
    # Decoded name fits the budget and never has a dangling partial char.
    assert len(info["name"].encode("utf-8")) <= nb
    info["name"].encode("utf-8")               # must be re-encodable (valid UTF-8)


# ---------------------------------------------------------------------------
# version handling
# ---------------------------------------------------------------------------
def test_unknown_version_rejected():
    ids, _ = hash_groups(["X"])
    adv = bytearray(build_payload(ids, "n"))
    # version byte sits at: AD(2) + company(2) + magic(4) = offset 8
    assert adv[8] == VERSION
    adv[8] = 0x09                              # a future version
    assert parse_payload(bytes(adv)) is None


# ---------------------------------------------------------------------------
# HSNT v2 game block (plan §4)
# ---------------------------------------------------------------------------
def test_v2_no_game_costs_one_byte_vs_v1_name():
    # The blocks byte is the only v2 overhead when idle; the name shrinks by 1.
    ids, _ = hash_groups(["A"])
    adv = build_payload(ids, "n")
    info = parse_payload(adv)
    assert info is not None
    assert info["version"] == VERSION
    assert info["game"] is None                # no game block -> game None
    assert adv[9] == 0x00                      # blocks byte clear


def test_game_block_roundtrip():
    ids, _ = hash_groups(["A"])
    g = {"pid": 0x123456, "gflags": GFLAG_ALIVE | GFLAG_BOUNTY, "streak": 7}
    adv = build_payload(ids, "Otter 42", game=g)
    assert len(adv) <= ADV_TOTAL
    info = parse_payload(adv)
    assert info is not None
    assert info["game"] == {"pid": 0x123456,
                            "gflags": GFLAG_ALIVE | GFLAG_BOUNTY, "streak": 7}


def test_game_block_name_is_shorter():
    ids, _ = hash_groups(["A"])
    plain = name_budget(len(ids))
    with_game = name_budget(len(ids), game=True)
    assert with_game == plain - GAME_BLOCK_LEN


def test_game_block_truncated_parses_name_game_none():
    ids, _ = hash_groups(["A"])
    g = {"pid": 1, "gflags": GFLAG_ALIVE, "streak": 0}
    adv = bytearray(build_payload(ids, "n", game=g))
    # The 5-byte game block sits at the very end; chop the last byte.
    info = parse_payload(bytes(adv[:-1]))
    assert info is not None
    assert info["name"] == "n"
    assert info["game"] is None                # block short -> None, never raises


def test_reserved_blocks_bit_dropped():
    ids, _ = hash_groups(["A"])
    adv = bytearray(build_payload(ids, "n"))
    assert adv[9] == 0x00                      # blocks byte
    adv[9] = 0x80                              # a reserved bit set
    assert parse_payload(bytes(adv)) is None


def test_roundtrip_preserves_version():
    ids, _ = hash_groups(["X"])
    info = parse_payload(build_payload(ids, "n"))
    assert info["version"] == VERSION


# ---------------------------------------------------------------------------
# malformed / hostile adverts never raise
# ---------------------------------------------------------------------------
def test_parse_bad_magic_returns_none():
    ids, _ = hash_groups(["X"])
    adv = bytearray(build_payload(ids, "n"))
    adv[4:8] = b"XXXX"                         # corrupt magic
    assert parse_payload(bytes(adv)) is None


def test_parse_truncated_returns_none():
    ids, _ = hash_groups(["X"])
    adv = build_payload(ids, "n")
    for cut in range(0, len(adv)):
        assert parse_payload(adv[:cut]) is None  # never raises, never half-parses


def test_parse_oversized_length_field_returns_none():
    # Hand-craft a structure whose name length overruns the buffer.
    adv = bytes([0x09, 0xFF]) + b"\xff\xff" + MAGIC + bytes([VERSION, 1, 0x01, 0x00, 99]) + b"ab"
    assert parse_payload(adv) is None


def test_parse_empty_and_garbage():
    assert parse_payload(b"") is None
    assert parse_payload(b"\x00\x00\x00") is None
    assert parse_payload(bytes(range(31))) is None


def test_parse_multiple_ad_structures_finds_ours():
    ids, _ = hash_groups(["X"])
    ours = build_payload(ids, "Bob")
    # Prefix with an unrelated AD structure (e.g. a fake TX-power).
    other = bytes([2, 0x0A, 0x00])
    info = parse_payload(other + ours)
    assert info is not None
    assert info["name"] == "Bob"


# ---------------------------------------------------------------------------
# intersection matching
# ---------------------------------------------------------------------------
def test_intersect_overlap_matches():
    own = hash_groups(["Hack42", "RevSpace"])[0]
    peer = hash_groups(["RevSpace", "FooBar"])[0]
    assert intersect(own, peer)                # shared 'RevSpace'


def test_intersect_disjoint_no_match():
    own = hash_groups(["Hack42"])[0]
    peer = hash_groups(["RevSpace"])[0]
    assert not intersect(own, peer)


def test_intersect_multi_any_one_matches():
    own = hash_groups(["A", "B", "C"])[0]
    peer = hash_groups(["C", "Z"])[0]
    assert intersect(own, peer)


def test_shared_name_uses_lowest_id():
    table = build_own_table(["Zeta", "Alpha", "Mu"])    # ids unknown until hashed
    table.sort(key=lambda t: t[1])                       # by id
    lowest_id = table[0][1]
    # Peer shares all three -> signature is the lowest id.
    sid, sname = shared_name_for(table, [t[1] for t in table])
    assert sid == lowest_id
    assert sname == table[0][0]


def test_shared_name_none_when_disjoint():
    table = build_own_table(["Alpha"])
    sid, sname = shared_name_for(table, [0x1234])
    assert sid is None and sname is None


# ---------------------------------------------------------------------------
# v0.9.0 — adopting a group from a friend after a Y-swap
# ---------------------------------------------------------------------------

def test_parse_groups_field_splits_and_trims():
    assert bp.parse_groups_field("Alpha, Beta,  Gamma ") == ["Alpha", "Beta", "Gamma"]


def test_parse_groups_field_drops_empties_and_junk():
    assert bp.parse_groups_field("Alpha,,  , Beta,") == ["Alpha", "Beta"]
    assert bp.parse_groups_field("") == []
    for junk in (None, 42, ["Alpha"], {"a": 1}):
        assert bp.parse_groups_field(junk) == []


def test_parse_groups_field_single_group():
    assert bp.parse_groups_field("Makerspace Baasrode") == ["Makerspace Baasrode"]


def test_new_groups_from_skips_already_joined():
    # Dedup is by normalize_group, so the peer's casing/spacing doesn't matter:
    # a typo'd group hashes differently and silently never matches, which is
    # exactly what adoption exists to prevent.
    existing = ["Makerspace Baasrode"]
    incoming = ["  makerspace baasrode ", "Fri3d Volunteers"]
    assert bp.new_groups_from(existing, incoming) == ["Fri3d Volunteers"]


def test_new_groups_from_dedups_within_incoming():
    assert bp.new_groups_from([], ["A", "a", " A "]) == ["A"]


def test_new_groups_from_empty_when_nothing_new():
    assert bp.new_groups_from(["A", "B"], ["b", "a"]) == []
    assert bp.new_groups_from(["A"], []) == []


def test_new_groups_from_caps_at_max_groups():
    incoming = ["G%d" % i for i in range(MAX_GROUPS + 3)]
    assert len(bp.new_groups_from([], incoming)) == MAX_GROUPS


def test_merge_groups_appends_new_only():
    merged, dropped = bp.merge_groups(["Alpha"], ["Beta", " alpha "])
    assert merged == ["Alpha", "Beta"]     # existing spelling preserved
    assert dropped == 0


def test_merge_groups_multi_select_from_one_peer():
    # A friend in several groups: the user ticks two of them at once.
    merged, dropped = bp.merge_groups(["Mine"], ["Alpha", "Beta"])
    assert merged == ["Mine", "Alpha", "Beta"]
    assert dropped == 0


def test_merge_groups_caps_and_reports_dropped():
    existing = ["G%d" % i for i in range(MAX_GROUPS - 1)]
    merged, dropped = bp.merge_groups(existing, ["New1", "New2", "New3"])
    assert len(merged) == MAX_GROUPS
    assert merged[-1] == "New1"            # first ticked wins the last slot
    assert dropped == 2                    # caller must surface this, not swallow it


def test_merge_groups_full_existing_drops_everything():
    existing = ["G%d" % i for i in range(MAX_GROUPS)]
    merged, dropped = bp.merge_groups(existing, ["New"])
    assert merged == existing
    assert dropped == 1


def test_merge_groups_trims_and_survives_junk():
    merged, dropped = bp.merge_groups(["A"], ["  B  ", "", "   ", None, 42])
    assert merged == ["A", "B"]
    assert dropped == 0


def test_merge_groups_result_still_hashes():
    # The whole point: the merged list must drive the beacon.
    merged, _ = bp.merge_groups(["Alpha"], ["Beta"])
    ids, _ = hash_groups(merged)
    assert ids == hash_groups(["Alpha", "Beta"])[0]


# ===========================================================================
# Peer-table admission + LRU (plan §4)
# ===========================================================================
def test_admit_peer_friend_match_and_game_rules():
    own = hash_groups(["X"])[0]
    assert admit_peer(own, {"group_ids": own, "name": "a", "game": None}) is True
    assert admit_peer(own, {"group_ids": [999], "name": "b", "game": None}) is False

    target = {"group_ids": [999], "name": "t",
              "game": {"pid": 42, "gflags": GFLAG_ALIVE, "streak": 0}}
    assert admit_peer(own, target, admit_pids={42}, game_live=True) is True
    assert admit_peer(own, target, admit_pids={42}, game_live=False) is False

    bounty = {"group_ids": [999], "name": "B",
              "game": {"pid": 7, "gflags": GFLAG_BOUNTY, "streak": 5}}
    assert admit_peer(own, bounty, game_live=True) is True

    stranger = {"group_ids": [999], "name": "r",
                "game": {"pid": 8, "gflags": GFLAG_ALIVE, "streak": 0}}
    assert admit_peer(own, stranger, game_live=True) is False


def test_evict_lru_drops_oldest_nonpinned():
    seen = {("a", 1): {"last_seen_ms": 10},
            ("a", 2): {"last_seen_ms": 30},
            ("a", 3): {"last_seen_ms": 20}}
    evicted = evict_lru(seen, cap=2)
    assert evicted == [("a", 1)]
    assert ("a", 1) not in seen and len(seen) == 2


def test_evict_lru_respects_pins():
    seen = {("a", 1): {"last_seen_ms": 10},
            ("a", 2): {"last_seen_ms": 30},
            ("a", 3): {"last_seen_ms": 20}}
    evict_lru(seen, cap=2, pinned_keys={("a", 1)})
    assert ("a", 1) in seen            # pinned -> never evicted
    assert len(seen) == 2


# ----- BLEProximity._process_result is host-testable (no bluetooth needed) ----
def _scanner(own_group):
    b = bp.BLEProximity()
    b._own_ids = hash_groups([own_group])[0]
    b._own_table = build_own_table([own_group])
    b._rssi_floor = -120
    return b


def test_process_result_friend_admitted_with_arrival():
    b = _scanner("Makerspace Baasrode")
    adv = build_payload(b._own_ids, "Otter 42")
    b._process_result(0, b"\x01\x02\x03", adv, -70, 1000)
    assert len(b._seen) == 1
    e = list(b._seen.values())[0]
    assert e["name"] == "Otter 42" and e["rssi_prox"] == -70.0
    assert len(b.take_arrivals()) == 1


def test_process_result_game_target_admitted_no_arrival():
    b = _scanner("MyGroup")
    b.set_game_context(admit_pids={4242}, pin_pids={4242})
    tgt_ids = hash_groups(["OtherGroup"])[0]      # no friend match
    adv = build_payload(tgt_ids, "Target",
                        game={"pid": 4242, "gflags": GFLAG_ALIVE, "streak": 0})
    b._process_result(0, b"\x09\x09", adv, -70, 1000)
    assert b.peer_by_pid(4242) is not None
    assert b.take_arrivals() == []                # game-only admit -> no friend arrival


def test_process_result_lru_caps_and_pins_target():
    b = _scanner("G")
    b._seen_cap = 3
    b.set_game_context(admit_pids={999}, pin_pids={999})
    tgt = build_payload(hash_groups(["Z"])[0], "T",
                        game={"pid": 999, "gflags": GFLAG_ALIVE, "streak": 0})
    b._process_result(0, b"\x01", tgt, -60, 5000)     # target, oldest, pinned
    for i in range(5):                                 # flood with friends
        b._process_result(0, bytes([i + 10]), build_payload(b._own_ids, "f%d" % i),
                          -70, 5000 + i)
    assert len(b._seen) <= b._seen_cap
    assert b.peer_by_pid(999) is not None              # survived despite being oldest


def test_process_result_rssi_prox_is_asymmetric():
    b = _scanner("G")
    b.set_prox_filter(0.6, 0.08)                       # fast attack, slow decay
    addr = b"\xaa"
    adv = build_payload(b._own_ids, "p")
    b._process_result(0, addr, adv, -80, 1000)
    b._process_result(0, addr, adv, -60, 2000)         # jump up -> fast attack
    up = b._seen[(0, addr)]["rssi_prox"]
    b._process_result(0, addr, adv, -90, 3000)         # drop -> slow decay
    dn = b._seen[(0, addr)]["rssi_prox"]
    assert up > -75 and dn > -80                       # attacked fast, decayed slowly


def test_current_peers_and_has_peers_exclude_game_admitted(monkeypatch):
    """C5/D32: a game-admitted peer (the Gotcha target) carries shared_id=None and
    must NOT surface in the friends UI. current_peers() feeds detail rows whose
    colour path crashes on a None gid, and has_peers() gates the backlight dim and
    the nearby-friends count. The hunt still reads the target via peer_by_pid()."""
    import time as _time
    monkeypatch.setattr(_time, "ticks_ms", lambda: 10_000, raising=False)
    monkeypatch.setattr(_time, "ticks_diff", lambda a, b: a - b, raising=False)
    b = _scanner("MyGroup")
    b.set_game_context(admit_pids={4242}, pin_pids={4242})
    # A real friend: shares a group -> shared_id is set.
    b._process_result(0, b"\x01", build_payload(b._own_ids, "Otter 42"), -60, 1000)
    # The Gotcha target: no shared group -> admitted only because it is the target.
    tgt = build_payload(hash_groups(["OtherGroup"])[0], "Target",
                        game={"pid": 4242, "gflags": GFLAG_ALIVE, "streak": 0})
    b._process_result(0, b"\x09", tgt, -55, 1000)

    assert b.peer_by_pid(4242) is not None              # still tracked for the hunt
    peers = b.current_peers()
    assert [p[0] for p in peers] == ["Otter 42"]        # the target is filtered out
    assert all(p[2] is not None for p in peers)         # never a None gid (C5)
    assert b.has_peers() is True                         # the friend counts

    # With only the game peer left, it is not a "nearby friend".
    del b._seen[(0, b"\x01")]
    assert b.current_peers() == []
    assert b.has_peers() is False
