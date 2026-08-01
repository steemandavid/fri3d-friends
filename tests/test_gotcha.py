"""Off-device tests for gotcha.py's PURE half (crypto + soul + versions).

These run on a host with CPython; conftest.py puts the app folder on sys.path so
`import gotcha` works. The HMAC is hand-rolled (MicroPython has no `hmac`), so we
(a) validate it against the RFC 4231 test vectors, and (b) cross-check the whole
signing path against the CPython stdlib `hmac`/`json` -- which proves the badge's
hand-rolled signer produces the exact bytes a stdlib server verifier expects.
"""
import hashlib
import hmac as _stdlib_hmac
import json as _stdlib_json

import gotcha


# ---------------------------------------------------------------------------
# HMAC-SHA256 -- RFC 4231 (HMAC-SHA-256 Test Cases) §4
# ---------------------------------------------------------------------------

def test_rfc4231_case1_short_key():
    key = b"\x0b" * 20
    data = b"Hi There"
    assert (gotcha.hmac_sha256_hex(key, data) ==
            "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7")


def test_rfc4231_case2_string_key():
    key = b"Jefe"
    data = b"what do ya want for nothing?"
    assert (gotcha.hmac_sha256_hex(key, data) ==
            "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843")


def test_rfc4231_case4_long_data():
    key = bytes(range(1, 26))          # 0x01..0x19 (25 bytes)
    data = b"\xcd" * 50
    assert (gotcha.hmac_sha256_hex(key, data) ==
            "82558a389a443c0ea4cc819899f2083a85f0faa3e578f8077a2e3ff46729665b")


def test_rfc4231_case6_key_longer_than_block():
    key = b"\xaa" * 131                 # longer than the 64-byte block -> hashed first
    data = b"Test Using Larger Than Block-Size Key - Hash Key First"
    assert (gotcha.hmac_sha256_hex(key, data) ==
            "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54")


def test_hmac_bytes_form_matches_hex():
    key, msg = b"key", b"The quick brown fox jumps over the lazy dog"
    digest = gotcha.hmac_sha256(key, msg)
    assert len(digest) == 32
    # Independent stdlib cross-check (proves the hex wrapper too).
    assert digest == _stdlib_hmac.new(key, msg, hashlib.sha256).digest()


# ---------------------------------------------------------------------------
# canonical_json -- deterministic, matches stdlib for the types we sign
# ---------------------------------------------------------------------------

def _stdlib_canon(obj):
    return _stdlib_json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_canonical_json_sorts_and_strips_whitespace():
    out = gotcha.canonical_json({"b": 2, "a": 1, "c": [3, 2, 1]})
    assert out == '{"a":1,"b":2,"c":[3,2,1]}'


def test_canonical_json_matches_stdlib_nested_with_unicode():
    payload = {
        "name": "Zoë",                  # accented name -> UTF-8 path
        "pid": 8123,
        "nested": {"z": [1, 2, {"y": True, "x": None}], "a": -5},
        "empty": {},
    }
    assert gotcha.canonical_json(payload) == _stdlib_canon(payload)


def test_canonical_json_is_deterministic():
    payload = {"target": {"pid": 1, "name": "Otter 42"}, "streak": 3, "alive": True}
    a = gotcha.canonical_json(payload)
    b = gotcha.canonical_json(payload)
    assert a == b


def test_canonical_json_escapes_quotes_and_control():
    assert gotcha.canonical_json({"k": 'he said "hi"\n'}) == '{"k":"he said \\"hi\\"\\n"}'


# ---------------------------------------------------------------------------
# Request / response signing -- the badge signer vs a stdlib verifier
# ---------------------------------------------------------------------------

KEY_HEX = "aa" * 32          # 32-byte player_key as hex (plan §8.2)


def test_sign_request_matches_stdlib_over_raw_body():
    body = b'{"events":[{"uuid":"x","type":"kill"}]}'
    sig = gotcha.sign_request(KEY_HEX, "POST", "/v1/events", 1234567890, "abcdef0123456789", body)
    # A stdlib server recomputes over the EXACT received bytes:
    msg = b"POST/v1/events1234567890abcdef0123456789" + body
    assert sig == _stdlib_hmac.new(bytes.fromhex(KEY_HEX), msg, hashlib.sha256).hexdigest()


def test_sign_request_get_has_empty_body():
    sig = gotcha.sign_request(KEY_HEX, "GET", "/v1/sync", 1, "n0", b"")
    msg = b"GET/v1/sync1n0"
    assert sig == _stdlib_hmac.new(bytes.fromhex(KEY_HEX), msg, hashlib.sha256).hexdigest()


def test_response_sig_matches_stdlib_canonical():
    payload = {"b": 2, "a": 1, "name": "Renée", "ok": True, "n": None}
    ts, nonce = 1700000000, "deadbeef"
    sig = gotcha.response_sig(KEY_HEX, ts, nonce, payload)
    msg = str(ts).encode() + nonce.encode() + gotcha.canonical_json(payload).encode()
    assert sig == _stdlib_hmac.new(bytes.fromhex(KEY_HEX), msg, hashlib.sha256).hexdigest()


def test_sig_ok_accepts_correct_signature():
    payload = {"truce_active": False, "streak": 7}
    ts, nonce = 5, "n1"
    sig = gotcha.response_sig(KEY_HEX, ts, nonce, payload)
    assert gotcha.sig_ok(KEY_HEX, ts, nonce, payload, sig) is True


def test_sig_ok_rejects_tamper_and_bad_input():
    ts, nonce = 5, "n1"
    payload = {"a": 1}
    sig = gotcha.response_sig(KEY_HEX, ts, nonce, payload)
    assert gotcha.sig_ok(KEY_HEX, ts, nonce, {"a": 2}, sig) is False   # payload tampered
    assert gotcha.sig_ok(KEY_HEX, ts, "n2", payload, sig) is False     # nonce mismatch
    assert gotcha.sig_ok("bb" * 32, ts, nonce, payload, sig) is False  # wrong key
    assert gotcha.sig_ok(KEY_HEX, ts, nonce, payload, None) is False   # no sig
    assert gotcha.sig_ok(KEY_HEX, ts, nonce, payload, "tampered") is False


def test_make_envelope_round_trips_payload():
    env = gotcha.make_envelope(7, "n3", "dead", {"alive": True})
    assert env == {"ts": 7, "nonce": "n3", "sig": "dead", "payload": {"alive": True}}


# ---------------------------------------------------------------------------
# Kill proof -- the "soul" (plan §3.4)
# ---------------------------------------------------------------------------

def test_make_soul_is_injectable_and_correct_length():
    fixed = bytes(range(16))
    soul = gotcha.make_soul(urandom=lambda n: fixed[:n])
    assert soul == fixed
    assert len(soul) == gotcha.SOUL_LEN == 16


def test_commitment_is_sha256_hex():
    soul = b"0123456789abcdef"
    c = gotcha.commitment(soul)
    assert c == hashlib.sha256(soul).hexdigest()
    assert len(c) == 64


def test_verify_soul_round_trip_and_reject():
    soul = gotcha.make_soul(urandom=lambda n: b"\x01" * n)
    c = gotcha.commitment(soul)
    assert gotcha.verify_soul(soul, c) is True
    assert gotcha.verify_soul(b"\x02" * 16, c) is False          # wrong soul
    assert gotcha.verify_soul(soul, hashlib.sha256(b"\x02" * 16).hexdigest()) is False
    assert gotcha.verify_soul(soul, None) is False               # bad input never raises


def test_two_souls_differ_when_random_differs():
    # Different random sources produce different souls -> different commitments
    # (a fresh soul per life binds each proof to one death, plan §3.4).
    a = gotcha.commitment(gotcha.make_soul(urandom=lambda n: b"\x10" * n))
    b = gotcha.commitment(gotcha.make_soul(urandom=lambda n: b"\x20" * n))
    assert a != b


# ---------------------------------------------------------------------------
# version_lt (plan §8.10)
# ---------------------------------------------------------------------------

def test_version_lt_numeric_not_string():
    assert gotcha.version_lt("0.9.0", "0.10.0") is True      # 9 < 10 numerically
    assert gotcha.version_lt("0.10.0", "0.9.0") is False     # NOT string compare


def test_version_lt_equal_and_higher():
    assert gotcha.version_lt("0.10.0", "0.10.0") is False
    assert gotcha.version_lt("0.11.0", "0.10.0") is False
    assert gotcha.version_lt("1.0.0", "0.99.99") is False
    assert gotcha.version_lt("0.99.99", "1.0.0") is True


def test_version_lt_handles_unequal_length_and_suffix():
    assert gotcha.version_lt("0.9", "0.9.0") is False        # padded equal
    assert gotcha.version_lt("0.9.1-rc1", "0.9.1") is False  # suffix ignored -> equal


# ===========================================================================
# GameConfig.from_sync (§5.4) -- defensive parse of the tunables block
# ===========================================================================

def test_gameconfig_defaults_when_no_sync():
    cfg = gotcha.GameConfig()
    assert cfg.get("KILL_RSSI") == -65
    assert cfg.get("PING_ENABLED") is True
    assert cfg.get("PROX_ALPHA_UP") == 0.60
    assert cfg.get("truce_from") == "22:00"


def test_gameconfig_from_sync_coerces_and_keeps_known_only():
    cfg = gotcha.GameConfig.from_sync(
        {"KILL_RSSI": "-68", "PING_ENABLED": "false", "PROX_ALPHA_UP": "0.5",
         "bogus_key": 99},
        {"truce_schedule": {"from": "23:00", "to": "07:00"}})
    assert cfg.get("KILL_RSSI") == -68            # string -> int
    assert cfg.get("PING_ENABLED") is False       # "false" -> bool
    assert cfg.get("PROX_ALPHA_UP") == 0.5
    assert cfg.get("truce_from") == "23:00"
    assert cfg.get("truce_to") == "07:00"
    assert cfg.get("bogus_key") is None           # unknown key dropped


def test_gameconfig_from_sync_garbage_falls_back():
    cfg = gotcha.GameConfig.from_sync("not a dict", {"truce_schedule": None})
    assert cfg.get("KILL_RSSI") == -65           # untouched -> default
    assert cfg.get("truce_from") == "22:00"
    cfg2 = gotcha.GameConfig.from_sync({"KILL_RSSI": object()})
    assert cfg2.get("KILL_RSSI") == -65          # uncoercible -> default


# ===========================================================================
# Time / truce / quiet hours (§10.4, §10.4a)
# ===========================================================================

def test_time_hm_roundtrip():
    assert gotcha.parse_hm("22:00") == 1320
    assert gotcha.parse_hm("08:00") == 480
    assert gotcha.parse_hm("garbage") is None
    assert gotcha.parse_hm(None) is None
    assert gotcha.hm_str(1320) == "22:00"
    assert gotcha.hm_str(480) == "08:00"


def test_camp_minutes_is_cest():
    # 20:00 UTC == 22:00 CEST (camp-local), i.e. minute 1320.
    assert gotcha.camp_minutes(72000) == 1320
    # 06:00 UTC == 08:00 CEST, minute 480.
    assert gotcha.camp_minutes(21600) == 480


def test_truce_active_camp_window_wraps_midnight():
    cfg = gotcha.GameConfig()                    # truce 22:00-08:00
    assert gotcha.truce_active(72000, cfg, None) == "camp"    # 22:00 start (inclusive)
    assert gotcha.truce_active(21540, cfg, None) == "camp"    # 07:59 still in
    assert gotcha.truce_active(21600, cfg, None) == "none"    # 08:00 boundary out
    assert gotcha.truce_active(64800, cfg, None) == "none"    # 18:00 UTC=20:00 camp, before


def test_truce_active_personal_and_both():
    cfg = gotcha.GameConfig()
    quiet = {"from": "20:30", "to": "08:00"}     # earlier than camp truce
    assert gotcha.truce_active(66600, cfg, quiet) == "personal"  # 20:30 camp, before camp truce
    assert gotcha.truce_active(72000, cfg, quiet) == "both"      # 22:00: both windows


def test_clamp_quiet_valid_passthrough():
    cfg = gotcha.GameConfig()
    assert gotcha.clamp_quiet({"from": "20:30", "to": "07:00"}, cfg) == \
        {"from": "20:30", "to": "07:00"}


def test_clamp_quiet_snaps_daytime_bound_into_night_band():
    cfg = gotcha.GameConfig()                    # band 20:00-10:00
    # Start 18:00 is daytime (before 20:00) -> snapped up to the band edge.
    out = gotcha.clamp_quiet({"from": "18:00", "to": "08:00"}, cfg)
    assert out is not None
    assert gotcha.parse_hm(out["from"]) >= gotcha.parse_hm("20:00")


def test_clamp_quiet_rejects_inverted_and_garbage():
    cfg = gotcha.GameConfig()
    assert gotcha.clamp_quiet({"from": "23:00", "to": "20:00"}, cfg) is None  # inverted
    assert gotcha.clamp_quiet({"from": "oops", "to": "08:00"}, cfg) is None
    assert gotcha.clamp_quiet(None, cfg) is None


# ===========================================================================
# Proximity filter + fraction (§8.8.2)
# ===========================================================================

def test_prox_filter_first_sample_and_asymmetry():
    cfg = gotcha.GameConfig()
    assert gotcha.prox_filter(None, -70, cfg) == -70.0           # first sample
    # Fast attack: a stronger sample jumps most of the way.
    up = gotcha.prox_filter(-80.0, -60, cfg)                     # a_up 0.60
    assert up == (1.0 - 0.60) * -80.0 + 0.60 * -60
    # Slow decay: a weaker sample barely moves it.
    dn = gotcha.prox_filter(-60.0, -80, cfg)                     # a_down 0.08
    assert dn == (1.0 - 0.08) * -60.0 + 0.08 * -80
    assert abs(up - -60) < abs(dn - -80)                         # attack faster than decay


def test_prox_fraction_band_and_clamp():
    cfg = gotcha.GameConfig()
    assert gotcha.prox_fraction(None, cfg) == 0.0
    assert gotcha.prox_fraction(-90, cfg) == 0.0                 # floor
    assert gotcha.prox_fraction(-55, cfg) == 1.0                 # ceil
    assert gotcha.prox_fraction(-100, cfg) == 0.0                # below floor
    assert gotcha.prox_fraction(-40, cfg) == 1.0                 # above ceil
    assert 0.0 < gotcha.prox_fraction(-72, cfg) < 1.0


# ===========================================================================
# LED radar bar (§8.8.2 / §8.8.3)
# ===========================================================================

def test_breathe_period_endpoints_and_monotonic():
    assert gotcha.breathe_period_ms(1, 5) == 3800                # far
    assert gotcha.breathe_period_ms(4, 5) == 700                 # near (n-1)
    assert gotcha.breathe_period_ms(5, 5) is None                # kill range steady
    periods = [gotcha.breathe_period_ms(l, 5) for l in range(1, 5)]
    assert all(periods[i] >= periods[i + 1] for i in range(len(periods) - 1))


def test_hunt_segments_matches_table_n5():
    cfg = gotcha.GameConfig()                    # KILL=-65, REVEAL=-80
    assert gotcha.hunt_segments(None, cfg, 5) is None           # no target
    assert gotcha.hunt_segments(-95, cfg, 5) is None           # below floor
    assert gotcha.hunt_segments(-90, cfg, 5) == (1, "blue", 0.20)
    assert gotcha.hunt_segments(-80, cfg, 5) == (4, "amber", 0.45)   # reveal -> n-1
    assert gotcha.hunt_segments(-70, cfg, 5) == (4, "amber", 0.45)
    assert gotcha.hunt_segments(-65, cfg, 5) == (5, "red", 0.55)     # kill -> all n


def test_hunt_segments_n4_and_kill_only_led():
    cfg = gotcha.GameConfig()
    assert gotcha.hunt_segments(-80, cfg, 4) == (3, "amber", 0.45)   # n-1
    assert gotcha.hunt_segments(-65, cfg, 4) == (4, "red", 0.55)
    # Single-LED board never shows kill red unless in range.
    assert gotcha.hunt_segments(-80, cfg, 1) == (1, "blue", 0.20)


def test_hunt_bar_dark_and_red_states():
    cfg = gotcha.GameConfig()
    assert gotcha.hunt_bar(None, 0, cfg, 5) == [(0, 0, 0)] * 5
    assert gotcha.hunt_bar(-70, 0, cfg, 5, halted=True) == [(0, 0, 0)] * 5  # truce -> dark
    red = gotcha.hunt_bar(-65, 0, cfg, 5)                       # kill range, steady
    assert len(red) == 5
    assert all(c == red[0] for c in red)
    assert red[0] == gotcha._scale_colour("red", 0.55)


def test_hunt_bar_is_pure_cacheable():
    cfg = gotcha.GameConfig()
    a = gotcha.hunt_bar(-72, 1234, cfg, 5)
    b = gotcha.hunt_bar(-72, 1234, cfg, 5)
    assert a == b                                               # identical in -> identical out


def test_solid_frame_dead_pulse_and_protected():
    dead = gotcha.solid_frame("red", 5, 0.20, now_ms=0, pulse_period_ms=2000)
    assert len(dead) == 5 and all(c == dead[0] for c in dead)
    prot = gotcha.solid_frame("white", 5, 0.30)
    assert prot[0] == gotcha._scale_colour("white", 0.30)


# ===========================================================================
# Hunt ping (§8.8.6)
# ===========================================================================

def test_hunt_ping_silent_below_floor_and_disabled():
    cfg = gotcha.GameConfig()                    # PING_FROM_SEG=3 -> thr 0.6 -> -69 dBm
    assert gotcha.hunt_ping(-80, 0, None, cfg) is None         # far below floor
    assert gotcha.hunt_ping(-60, 0, None, cfg, enabled=False) is None
    assert gotcha.hunt_ping(-60, 0, None, cfg, sound_on=False) is None


def test_hunt_ping_kill_range_is_double_tap():
    cfg = gotcha.GameConfig()
    res = gotcha.hunt_ping(-60, 0, None, cfg)                  # >= KILL_RSSI
    assert res == (2400, 40, 350, 2)                           # near freq, near interval, 2 taps


def test_hunt_ping_single_tap_at_threshold_and_not_due():
    cfg = gotcha.GameConfig()
    res = gotcha.hunt_ping(-69, 0, None, cfg)                  # f ~= thr -> far pitch
    assert res is not None
    assert res[3] == 1
    assert res[0] == 1400                                      # PING_FREQ_FAR
    # Not due within the interval -> dropped (§8.8.6: drop, never queue).
    interval = res[2]
    assert gotcha.hunt_ping(-69, interval - 1, 0, cfg) is None
    assert gotcha.hunt_ping(-69, interval, 0, cfg) is not None


def test_hunt_ping_pitch_rises_with_proximity():
    cfg = gotcha.GameConfig()
    near_thr = gotcha.hunt_ping(-69, 0, None, cfg)[0]
    closer = gotcha.hunt_ping(-67, 0, None, cfg)[0]
    assert closer >= near_thr                                   # monotonic up


# ===========================================================================
# Score preview (§2)
# ===========================================================================

def test_score_preview_target_bounty_repeat():
    # total_kills is a *count* (one per kill); points is separate (1 or 2).
    assert gotcha.score_preview(5, 2, 4, "target") == (6, 3, 4, 1)
    assert gotcha.score_preview(5, 2, 4, "bounty") == (6, 3, 4, 2)
    # A repeat scores 0 and does not advance streak/total in the optimistic UI.
    assert gotcha.score_preview(5, 2, 4, "repeat") == (5, 2, 4, 0)


def test_score_preview_best_streak_rises():
    assert gotcha.score_preview(0, 4, 4, "target") == (1, 5, 5, 1)   # new best


# ===========================================================================
# EventQueue (§8.2 / §9.3) -- bounded, dedup, never drops a kill
# ===========================================================================

def test_eventqueue_dedup_and_bounded():
    q = gotcha.EventQueue()
    assert q.add({"uuid": "a", "type": "heartbeat"})
    assert not q.add({"uuid": "a", "type": "heartbeat"})      # dup dropped
    assert len(q) == 1
    for i in range(gotcha.MAX_QUEUE + 5):                     # overflow
        q.add({"uuid": "u%d" % i, "type": "heartbeat"})
    assert len(q) == gotcha.MAX_QUEUE


def test_eventqueue_never_drops_kill_when_full_of_kills():
    q = gotcha.EventQueue()
    for i in range(gotcha.MAX_QUEUE):
        q.add({"uuid": "k%d" % i, "type": "kill"})
    assert len(q) == gotcha.MAX_QUEUE
    assert not q.add({"uuid": "kNEW", "type": "kill"})        # refused, none to drop
    assert len(q) == gotcha.MAX_QUEUE


def test_eventqueue_drops_oldest_nonkill_to_save_kill():
    q = gotcha.EventQueue()
    q.add({"uuid": "h1", "type": "heartbeat"})
    q.add({"uuid": "h2", "type": "heartbeat"})
    for i in range(gotcha.MAX_QUEUE - 1):
        q.add({"uuid": "k%d" % i, "type": "kill"})
    assert len(q) == gotcha.MAX_QUEUE
    assert q.add({"uuid": "h3", "type": "heartbeat"})         # makes room by dropping h1
    assert len(q) == gotcha.MAX_QUEUE
    assert "h1" not in [e["uuid"] for e in q.peek_batch(100)]
    assert all(e["uuid"] != "h1" for e in q.peek_batch(100))


def test_eventqueue_remove_and_uuid_mint():
    q = gotcha.EventQueue([{"uuid": "a", "type": "kill"},
                           {"uuid": "b", "type": "dodge"}])
    assert len(q) == 2
    q.remove(["a"])
    assert len(q) == 1
    q2 = gotcha.EventQueue()
    assert q2.add({"type": "reveal"})                         # uuid minted
    e = q2.peek_batch()[0]
    assert isinstance(e["uuid"], str) and len(e["uuid"]) >= 8


# ===========================================================================
# GotchaState persistence + sync merge (§8.2, §8.3)
# ===========================================================================

def _fake_fs():
    store = {}

    def reader():
        return store.get("gotcha.json")

    def writer(tmp, data):
        store[tmp] = data

    def renamer(tmp, path):
        store[path] = store.pop(tmp, None)

    return store, reader, writer, renamer


def test_gotcha_state_save_load_roundtrip():
    _, r, w, rn = _fake_fs()
    gs = gotcha.GotchaState("gotcha.json", reader=r, writer=w, renamer=rn)
    gs.enroll(4711, "deadbeef", 1, soul=bytes(range(16)), commitment_hex="a" * 64)
    gs.d["state"]["streak"] = 3
    gs.queue.add({"uuid": "x", "type": "kill"})
    assert gs.save() is True

    gs2 = gotcha.GotchaState("gotcha.json", reader=r, writer=w, renamer=rn)
    gs2.load()
    assert gs2.is_enrolled()
    assert gs2.d["pid"] == 4711
    assert gs2.d["player_key"] == "deadbeef"
    assert gs2.d["state"]["streak"] == 3
    assert len(gs2.queue) == 1


def test_gotcha_state_load_corrupt_degrades_to_blank():
    store = {"gotcha.json": "{not json"}
    gs = gotcha.GotchaState("gotcha.json",
                            reader=lambda: store.get("gotcha.json"),
                            writer=lambda *a: None, renamer=lambda *a: None)
    gs.load()
    assert not gs.is_enrolled()
    assert gs.d["pid"] is None


def test_gotcha_state_apply_sync_merges_everything():
    _, r, w, rn = _fake_fs()
    gs = gotcha.GotchaState(reader=r, writer=w, renamer=rn)
    gs.enroll(100, "keyhex", 1)
    payload = {
        "server_time": 1000000,
        "me": {"pid": 100, "alive": True, "status": "active", "streak": 2,
               "best_streak": 5, "total_kills": 11, "score": 13, "deaths": 1,
               "respawn_at": None, "protected_until": None, "dodges": {"7": 1},
               "quiet": {"from": "22:00", "to": "08:00"}, "card_token": "TOK"},
        "target": {"pid": 200, "name": "Otter 42", "commitment": "dead",
                   "last_seen_ago_s": 240, "halted": False},
        "hitlist": [{"pid": 3, "name": "Fox", "streak": 4}],
        "broadcast": "hello",
        "app": {"min_version": "0.11.0", "latest_version": "0.11.2"},
    }
    gs.apply_sync(payload, local_time_s=999990)
    assert gs.d["clock_offset_s"] == 1000000 - 999990
    assert gs.d["synced_at"] == 1000000
    assert gs.d["state"]["streak"] == 2
    assert gs.d["state"]["total"] == 11
    assert gs.d["state"]["score"] == 13
    assert gs.d["target"]["name"] == "Otter 42"
    assert gs.d["target"]["seen_ago_s"] == 240
    assert gs.d["dodges"] == {"7": 1}
    assert gs.d["quiet"] == {"from": "22:00", "to": "08:00"}
    assert gs.d["broadcast"] == "hello"
    assert gs.d["app"]["latest_version"] == "0.11.2"
    assert gs.effective_now(999990) == 1000000


def test_gotcha_state_target_none_when_no_target():
    gs = gotcha.GotchaState()
    gs.apply_sync({"server_time": 50, "me": {"pid": 1}, "target": None},
                  local_time_s=50)
    assert gs.d["target"] is None
    assert gs.target_pid() is None


def test_gotcha_state_opt_out_round_trip():
    gs = gotcha.GotchaState()
    gs.enroll(1, "k", 1)
    assert gs.is_enrolled()
    gs.opt_out()
    assert not gs.is_enrolled()                  # opted out reads as not playing
    gs.opt_in()
    assert gs.is_enrolled()


# ===========================================================================
# Signed-HTTP request/response shaping (§6.2, §9.1)
# ===========================================================================
_KEY = "a" * 64        # 32-byte player_key as hex


def test_new_nonce_is_hex():
    n = gotcha.new_nonce()
    assert len(n) == 16
    assert all(c in "0123456789abcdef" for c in n)


def test_signed_get_headers_and_signature():
    url, headers = gotcha.signed_get(4711, _KEY, "http://h:8080/", "/v1/sync",
                                     ts=123, nonce="abcd")
    assert url == "http://h:8080/v1/sync"
    assert headers["X-Pid"] == "4711"
    assert headers["X-Ts"] == "123"
    assert headers["X-Nonce"] == "abcd"
    # The signature is over GET || "/v1/sync" || ts || nonce || "" (no body).
    assert headers["X-Sig"] == gotcha.sign_request(_KEY, "GET", "/v1/sync",
                                                   123, "abcd", b"")


def test_signed_get_signs_full_target_with_query():
    url, headers = gotcha.signed_get(1, _KEY, "http://h", "/v1/leaderboard",
                                     ts=5, nonce="n",
                                     query={"limit": 50, "board": "total"})
    # query is sorted into the signed target, matching the server's signing_path.
    assert url == "http://h/v1/leaderboard?board=total&limit=50"
    assert headers["X-Sig"] == gotcha.sign_request(
        _KEY, "GET", "/v1/leaderboard?board=total&limit=50", 5, "n", b"")


def test_signed_post_body_signed_byte_for_byte():
    obj = {"events": [{"uuid": "x", "type": "kill"}]}
    url, headers, body = gotcha.signed_post(1, _KEY, "http://h", "/v1/events",
                                            obj, ts=7, nonce="n")
    assert url == "http://h/v1/events"
    assert body == gotcha.canonical_json(obj).encode("utf-8")
    assert headers["X-Sig"] == gotcha.sign_request(_KEY, "POST", "/v1/events",
                                                   7, "n", body)


def test_verify_response_accepts_valid_envelope():
    payload = {"server_time": 100, "me": {"pid": 1}}
    env = gotcha.make_envelope(100, "n1",
                               gotcha.response_sig(_KEY, 100, "n1", payload), payload)
    assert gotcha.verify_response(_KEY, "n1", env) == payload


def test_verify_response_rejects_tamper_and_mismatch():
    payload = {"server_time": 100}
    good = gotcha.make_envelope(100, "n1",
                                gotcha.response_sig(_KEY, 100, "n1", payload), payload)
    assert gotcha.verify_response(_KEY, "OTHER", good) is None     # wrong nonce
    bad_sig = dict(good); bad_sig["sig"] = "00" * 32
    assert gotcha.verify_response(_KEY, "n1", bad_sig) is None     # bad sig
    tampered = dict(good); tampered["payload"] = {"server_time": 999}
    assert gotcha.verify_response(_KEY, "n1", tampered) is None    # payload re-signed
    assert gotcha.verify_response(_KEY, "n1", "nope") is None      # not a dict


def test_enroll_body_shape():
    b = gotcha.enroll_body("abcd1234", "Otter 42", ["Hack42"], "c" * 64,
                           "0.11.0", "2026")
    assert b == {"badge_key": "abcd1234", "display_name": "Otter 42",
                 "groups": ["Hack42"], "commitment": "c" * 64,
                 "app_version": "0.11.0", "board": "2026"}


def test_from_sync_malformed_truce_schedule_fails_closed():
    """D25: a host typing "22.00" instead of "22:00" must NOT disable the camp
    night truce -- a malformed schedule keeps the DEFAULTS 22:00-08:00 window
    (fail closed), the §10.4 "screaming badge in a tent of sleeping kids" case."""
    cfg = gotcha.GameConfig.from_sync(
        None, {"truce_schedule": {"from": "22.00", "to": "08:00"}})
    assert cfg.get("truce_from") == "22:00"       # default kept, not "22.00"
    assert cfg.get("truce_to") == "08:00"
    # 23:00 camp-local (21:00 UTC) is inside the default night truce.
    assert gotcha.truce_active(75600, cfg, None) == "camp"
    # A well-formed schedule is still adopted.
    ok = gotcha.GameConfig.from_sync(
        None, {"truce_schedule": {"from": "23:00", "to": "07:00"}})
    assert ok.get("truce_from") == "23:00" and ok.get("truce_to") == "07:00"


def test_gotcha_state_load_valid_json_wrong_types_degrades_safely():
    """D27: a structurally-corrupt but JSON-valid file ({"state": "broken"}) must
    not copy a wrong-typed value into state, where apply_sync would then do
    s["alive"]=... on a str and die on every sync forever."""
    import json as _json
    bad = _json.dumps({"enrolled": True, "pid": 1001, "state": "broken",
                       "queue": "not-a-list", "clock_offset_s": "nope"})
    store = {"gotcha.json": bad}
    gs = gotcha.GotchaState("gotcha.json",
                            reader=lambda: store.get("gotcha.json"),
                            writer=lambda *a: None, renamer=lambda *a: None)
    gs.load()
    assert isinstance(gs.d["state"], dict)        # wrong-typed value rejected
    assert isinstance(gs.d["queue"], list)
    assert gs.d["clock_offset_s"] == 0
    # apply_sync no longer explodes on the poisoned state.
    gs.apply_sync({"server_time": 1000,
                   "me": {"pid": 1001, "alive": True, "status": "active"}}, 900)
    assert gs.d["state"]["alive"] is True


# ---------------------------------------------------------------------------
# REVEAL (plan §5.7) -- payload, A-action ladder, cooldown, validation, spotted
# ---------------------------------------------------------------------------

def test_reveal_payload_roundtrip():
    raw = gotcha.build_reveal_payload(7, 1003, 1004, "abc123")
    assert raw == '{"g":7,"h":1003,"n":"abc123","t":1004}'   # compact, sorted
    assert gotcha.parse_reveal_payload(raw) == {"g": 7, "h": 1003, "t": 1004, "n": "abc123"}


def test_reveal_payload_parse_defensive():
    assert gotcha.parse_reveal_payload(b'{"g":1,"h":2,"t":3,"n":"x"}') == \
        {"g": 1, "h": 2, "t": 3, "n": "x"}                  # bytes accepted
    assert gotcha.parse_reveal_payload("not json") is None
    assert gotcha.parse_reveal_payload(b"\x00\x01") is None
    assert gotcha.parse_reveal_payload("[1,2,3]") is None    # not an object
    p = gotcha.parse_reveal_payload('{"t": 1004}')           # missing fields ok
    assert p["t"] == 1004 and p["h"] is None


def test_reveal_ready_cooldown_boundary():
    cfg = gotcha.GameConfig()                                # REVEAL_COOLDOWN_S = 120
    assert gotcha.reveal_ready(0, 1000, cfg) is True         # never revealed
    assert gotcha.reveal_ready(None, 1000, cfg) is True
    assert gotcha.reveal_ready(1000, 1119, cfg) is False     # 119 s < 120 -> cooling
    assert gotcha.reveal_ready(1000, 1120, cfg) is True      # exactly 120 -> ready
    assert gotcha.reveal_ready(1000, 1100, cfg) is False     # still cooling


def test_decide_strip_action_ladder():
    cfg = gotcha.GameConfig()                                # KILL -65, REVEAL -80
    now = 100000
    assert gotcha.decide_strip_action(None, 0, now, cfg) == "none"           # not detected
    assert gotcha.decide_strip_action(-100, 0, now, cfg, halted=True) == "none"
    assert gotcha.decide_strip_action(-80, 0, now, cfg) == "reveal"         # reveal range
    assert gotcha.decide_strip_action(-70, 0, now, cfg) == "reveal"
    assert gotcha.decide_strip_action(-70, now - 10, now, cfg) == "radar"   # cooling
    assert gotcha.decide_strip_action(-60, 0, now, cfg) == "reveal"         # kill range, 3a fallthrough
    assert gotcha.decide_strip_action(-60, 0, now, cfg, kill_enabled=True) == "attack"
    assert gotcha.decide_strip_action(-60, 0, now, cfg,
                                      attack_in_progress=True) == "abort"
    assert gotcha.decide_strip_action(-85, 0, now, cfg) == "none"           # below reveal


def test_decide_strip_action_respects_kill_switch():
    cfg = gotcha.GameConfig()
    cfg.d["reveal_enabled"] = False
    # reveal disabled -> within reveal range shows radar detail, not reveal
    assert gotcha.decide_strip_action(-70, 0, 100000, cfg) == "radar"


def test_validate_reveal_branches():
    p = {"g": 7, "h": 1003, "t": 1004, "n": "x"}
    assert gotcha.validate_reveal(p, 1004, True, "none", True) == "ok"
    assert gotcha.validate_reveal(p, 1004, True, "none", True,
                                  radio_busy=True) == "busy"                 # precedence
    assert gotcha.validate_reveal(p, 1004, True, "none", False) == "no_game"
    assert gotcha.validate_reveal(p, 1004, True, "camp", True) == "truce"    # §5.7 both sides
    assert gotcha.validate_reveal(p, 1004, True, "both", True) == "truce"
    assert gotcha.validate_reveal(p, 1004, False, "none", True) == "dead"
    assert gotcha.validate_reveal(p, 9999, True, "none", True) == "wrong_target"
    assert gotcha.validate_reveal(None, 1004, True, "none", True) == "wrong_target"


def test_validate_reveal_has_no_protection_or_cooldown_check():
    # §5.8/§5.7 design invariant: the responder never refuses on protection or
    # cooldown. There is no such parameter, and an alive, in-game target is 'ok'
    # regardless of any protected/cooldown state the caller might hold.
    import inspect
    params = inspect.signature(gotcha.validate_reveal).parameters
    assert "protected" not in params
    assert "cooldown" not in params
    p = {"g": 7, "h": 1003, "t": 1004, "n": "x"}
    assert gotcha.validate_reveal(p, 1004, True, "none", True) == "ok"


def test_spotted_active_window():
    assert gotcha.spotted_active(0, 1000) is False
    assert gotcha.spotted_active(None, 1000) is False
    assert gotcha.spotted_active(3500, 1000) is True          # before deadline
    assert gotcha.spotted_active(3500, 3500) is False         # at deadline
    assert gotcha.spotted_active(3500, 4000) is False         # after deadline


def test_reveal_events_shape_and_droppable():
    assert gotcha.reveal_event(1004, rssi=-75) == \
        {"type": "reveal", "target_pid": 1004, "rssi": -75}
    assert gotcha.revealed_event(1003) == {"type": "revealed", "hunter_pid": 1003}
    assert gotcha.reveal_event(1004, at=123) == \
        {"type": "reveal", "target_pid": 1004, "at": 123}     # at stamped when given
    # NOT keep-types: a reveal/revealed is droppable on overflow (a kill never is)
    assert "reveal" not in gotcha.EventQueue.KEEP_TYPES
    assert "revealed" not in gotcha.EventQueue.KEEP_TYPES
    q = gotcha.EventQueue()
    for i in range(gotcha.MAX_QUEUE):                         # fill with kills
        assert q.add({"type": "kill", "victim_pid": i, "soul": "s%d" % i,
                      "as": "target", "rssi": -60})
    assert q.add(gotcha.reveal_event(1004)) is False          # full of kills -> refused


# ---------------------------------------------------------------------------
# THE DUEL (plan §5.3, §5.8) -- payloads, validate, DodgeLedger, DuelState
# ---------------------------------------------------------------------------

def test_attack_payload_roundtrip():
    raw = gotcha.build_attack_payload(7, 1003, 1004, "target", "n1")
    # compact, keys sorted (a, as, g, n, v)
    assert raw == '{"a":1003,"as":"target","g":7,"n":"n1","v":1004}'
    assert gotcha.parse_attack_payload(raw) == {
        "g": 7, "a": 1003, "v": 1004, "as": "target", "n": "n1"}


def test_attack_payload_parse_defensive():
    assert gotcha.parse_attack_payload(b'{"a":1,"v":2,"as":"bounty","g":3,"n":"x"}') == {
        "g": 3, "a": 1, "v": 2, "as": "bounty", "n": "x"}     # bytes accepted
    assert gotcha.parse_attack_payload("not json") is None
    assert gotcha.parse_attack_payload("[1,2]") is None       # not an object
    p = gotcha.parse_attack_payload('{"v": 1004}')            # missing fields ok
    assert p["v"] == 1004 and p["a"] is None


def test_duel_payload_states():
    eng = gotcha.build_duel_payload(gotcha.DUEL_ENGAGED, hold_ms=5000, dodges_left=1)
    assert gotcha.parse_duel_payload(eng) == {"s": "engaged", "h": 5000, "d": 1, "r": None}
    killed = gotcha.build_duel_payload(gotcha.DUEL_KILLED)
    assert gotcha.parse_duel_payload(killed)["s"] == "killed"
    ref = gotcha.build_duel_payload(gotcha.DUEL_REFUSED, reason="protected")
    assert gotcha.parse_duel_payload(ref) == {"s": "refused", "h": None, "d": None,
                                              "r": "protected"}
    assert gotcha.parse_duel_payload("garbage") is None


def test_spoils_payload_carries_soul_and_inherited_target():
    tgt = {"pid": 2001, "name": "Otter 42", "commitment": "ab" * 32, "extra": "drop"}
    raw = gotcha.build_spoils_payload("ff" * 16, tgt)
    p = gotcha.parse_spoils_payload(raw)
    assert p["soul"] == "ff" * 16
    assert p["tgt"] == {"pid": 2001, "name": "Otter 42", "commitment": "ab" * 32}
    # a victim with no target still produces a valid SPOILS (tgt None)
    p2 = gotcha.parse_spoils_payload(gotcha.build_spoils_payload("00" * 16, None))
    assert p2["soul"] == "00" * 16 and p2["tgt"] is None
    assert gotcha.parse_spoils_payload("nope") is None


def test_spoils_soul_verifies_against_commitment():
    # end-to-end: the soul disclosed in SPOILS proves the kill (§3.4).
    soul = bytes(range(16))
    comm = gotcha.commitment(soul)
    raw = gotcha.build_spoils_payload(soul, {"pid": 1, "name": "x", "commitment": "c"})
    disclosed = gotcha.parse_spoils_payload(raw)["soul"]
    assert gotcha.verify_soul(bytes.fromhex(disclosed), comm) is True
    assert gotcha.verify_soul(bytes.fromhex(disclosed), "00" * 32) is False


def test_validate_attack_branches():
    cfg = gotcha.GameConfig()                                # BOUNTY_STREAK = 3
    p = {"g": 7, "a": 1003, "v": 1004, "as": "target", "n": "x"}
    ok = gotcha.validate_attack(p, 1004, 0, True, "none", True, cfg)
    assert ok == "ok"
    # precedence: busy first (radio slot / mid-duel)
    assert gotcha.validate_attack(p, 1004, 0, True, "none", True, cfg,
                                  radio_busy=True) == "busy"
    assert gotcha.validate_attack(p, 1004, 0, True, "none", True, cfg,
                                  in_duel=True) == "busy"
    assert gotcha.validate_attack(p, 1004, 0, True, "none", False, cfg) == "no_game"
    assert gotcha.validate_attack(p, 1004, 0, True, "camp", True, cfg) == "truce"
    assert gotcha.validate_attack(p, 1004, 0, True, "both", True, cfg) == "truce"
    assert gotcha.validate_attack(p, 1004, 0, False, "none", True, cfg) == "dead"
    assert gotcha.validate_attack(p, 9999, 0, True, "none", True, cfg) == "wrong_target"
    assert gotcha.validate_attack(None, 1004, 0, True, "none", True, cfg) == "wrong_target"
    assert gotcha.validate_attack(p, 1004, 0, True, "none", True, cfg,
                                  protected=True) == "protected"
    assert gotcha.validate_attack(p, 1004, 0, True, "none", True, cfg,
                                  on_cooldown=True) == "on_cooldown"


def test_validate_attack_bounty_lie_caught_locally():
    cfg = gotcha.GameConfig()                                # BOUNTY_STREAK = 3
    b = {"g": 7, "a": 1003, "v": 1004, "as": "bounty", "n": "x"}
    # attacker claims bounty but victim's streak < BOUNTY_STREAK -> caught
    assert gotcha.validate_attack(b, 1004, 2, True, "none", True, cfg) == "bounty"
    # victim IS a bounty (streak >= 3) -> a bounty attack is legal
    assert gotcha.validate_attack(b, 1004, 3, True, "none", True, cfg) == "ok"
    # a plain 'target' attack never triggers the bounty check
    t = dict(b); t["as"] = "target"
    assert gotcha.validate_attack(t, 1004, 0, True, "none", True, cfg) == "ok"


def test_validate_attack_protection_not_paused_by_being_alive():
    # §5.8: protection refuses the attack even though everything else is legal.
    cfg = gotcha.GameConfig()
    p = {"g": 7, "a": 1003, "v": 1004, "as": "target", "n": "x"}
    assert gotcha.validate_attack(p, 1004, 0, True, "none", True, cfg,
                                  protected=True) == "protected"


def test_protection_active_and_left():
    assert gotcha.protection_active(None, 1000) is False
    assert gotcha.protection_active(0, 1000) is False
    assert gotcha.protection_active(1090, 1000) is True       # 90 s to go
    assert gotcha.protection_active(1000, 1000) is False      # at deadline
    assert gotcha.protection_left_s(1090, 1000) == 90
    assert gotcha.protection_left_s(1000, 1050) == 0          # already expired
    assert gotcha.protection_left_s(None, 1000) == 0


def test_cooldown_ready_boundary():
    ms = gotcha.DEFAULTS["ATTACK_COOLDOWN_MS"]                # 60000
    assert gotcha.cooldown_ready(0, 100000, ms) is True       # never attacked
    assert gotcha.cooldown_ready(None, 100000, ms) is True
    assert gotcha.cooldown_ready(100000, 100000 + 59999, ms) is False
    assert gotcha.cooldown_ready(100000, 100000 + 60000, ms) is True


def test_dodge_ledger_from_server_left_ints():
    # apply_sync stores {str(pid): dodges_LEFT}; the ledger reads that directly.
    led = gotcha.DodgeLedger({"1003": 1, "1005": 0}, limit=1)
    assert led.dodges_left(1003, now_s=1000, decay_s=3600) == 1
    assert led.dodges_left(1005, now_s=1000, decay_s=3600) == 0
    assert led.dodges_left(9999, now_s=1000, decay_s=3600) == 1   # never dodged -> full
    assert led.last_attack_s(1003) is None                        # server int -> no local time


def test_dodge_ledger_local_record_and_decay():
    led = gotcha.DodgeLedger({}, limit=1)
    assert led.dodges_left(1003, now_s=1000, decay_s=3600) == 1
    led.note_dodge(1003, now_s=1000)                              # used one dodge
    assert led.dodges_left(1003, now_s=1000, decay_s=3600) == 0
    assert led.last_attack_s(1003) == 1000
    # within DODGE_DECAY_MS window -> still spent
    assert led.dodges_left(1003, now_s=1000 + 3600, decay_s=3600) == 0
    # after the decay window -> resets to the full limit (§5.4)
    assert led.dodges_left(1003, now_s=1000 + 3601, decay_s=3600) == 1


def test_dodge_ledger_note_attack_stamps_time_without_spending():
    led = gotcha.DodgeLedger({}, limit=1)
    led.note_attack(1003, now_s=500)
    assert led.last_attack_s(1003) == 500
    assert led.dodges_left(1003, now_s=500, decay_s=3600) == 1     # attack != dodge
    # note_attack on a server-left int converts it, preserving used
    led2 = gotcha.DodgeLedger({"1003": 0}, limit=1)                # 0 left = 1 used
    led2.note_attack(1003, now_s=500)
    assert led2.dodges_left(1003, now_s=500, decay_s=3600) == 0    # still spent


def test_duel_state_hold_completes_to_kill():
    log = []
    d = gotcha.DuelState(on_engaged=lambda s: log.append("engaged"),
                         on_kill=lambda s: log.append("kill"),
                         on_dodge=lambda s: log.append("dodge"))
    assert d.begin_attack(1003, hold_ms=5000, dodges_left=1, now_ms=0) is True
    assert d.active() is True
    assert d.tick(2000, link_up=True) == "hold"
    assert 0.3 < d.hold_fraction(2000) < 0.5
    assert d.tick(4999, link_up=True) == "hold"
    assert d.tick(5000, link_up=True) == "killed"              # deadline reached
    assert d.tick(5100, link_up=True) == "killed"              # terminal, stays
    assert log == ["engaged", "kill"]


def test_duel_state_link_drop_is_a_dodge():
    log = []
    d = gotcha.DuelState(on_dodge=lambda s: log.append("dodge"))
    d.begin_attack(1003, hold_ms=5000, dodges_left=1, now_ms=0)
    assert d.tick(2000, link_up=False) == "dodged"             # ran out of range
    assert d.tick(2100, link_up=True) == "dodged"              # terminal
    assert log == ["dodge"]


def test_duel_state_single_slot_second_attack_ignored():
    d = gotcha.DuelState()
    assert d.begin_attack(1003, 5000, 1, now_ms=0) is True
    assert d.begin_attack(1007, 5000, 1, now_ms=100) is False  # already holding
    assert d.attacker_pid == 1003                              # first attacker kept


def test_duel_state_instant_kill_short_hold():
    # dodges_left == 0 -> the caller passes INSTANT_KILL_MS; the machine just runs
    # the short timer (link-drop still ends it, per the LINK-DROP note).
    d = gotcha.DuelState()
    d.begin_attack(1003, hold_ms=1000, dodges_left=0, now_ms=0)
    assert d.tick(999, link_up=True) == "hold"
    assert d.tick(1000, link_up=True) == "killed"


def test_duel_state_reset_returns_to_idle():
    d = gotcha.DuelState()
    d.begin_attack(1003, 5000, 1, now_ms=0)
    d.tick(5000, link_up=True)
    d.reset()
    assert d.phase == "idle" and d.active() is False
    assert d.tick(9999, link_up=True) == "idle"


def test_duel_event_builders_shapes_and_keep_types():
    assert gotcha.attack_started_event(1004, at=10) == {
        "type": "attack_started", "victim_pid": 1004, "at": 10}
    assert gotcha.kill_event(1004, "ab" * 16, rssi=-60, at=5) == {
        "type": "kill", "victim_pid": 1004, "soul": "ab" * 16, "rssi": -60, "at": 5}
    assert gotcha.kill_event(1004, bytes(range(16)))["soul"] == \
        "".join("%02x" % b for b in range(16))                # bytes -> hex
    assert gotcha.killed_by_event(1003, "cd" * 32, at=7) == {
        "type": "killed_by", "attacker_pid": 1003, "new_commitment": "cd" * 32, "at": 7}
    assert gotcha.dodge_event(attacker_pid=1003) == {
        "type": "dodge", "attacker_pid": 1003}                # victim half
    assert gotcha.dodge_event(victim_pid=1004) == {
        "type": "dodge", "victim_pid": 1004}                  # assassin half
    # kill/killed_by survive an overflow full of kills; dodge/attack_started do not
    assert "kill" in gotcha.EventQueue.KEEP_TYPES
    assert "killed_by" in gotcha.EventQueue.KEEP_TYPES
    assert "dodge" not in gotcha.EventQueue.KEEP_TYPES
    assert "attack_started" not in gotcha.EventQueue.KEEP_TYPES
