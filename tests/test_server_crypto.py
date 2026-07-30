"""Badge <-> server crypto parity (plan §6.2).

The badge signs with a hand-rolled HMAC over a hand-rolled canonical JSON because
MicroPython ships neither; the server uses the stdlib. If those two ever disagree
by one byte, every badge in the camp silently stops being able to sync -- and it
would look like a network problem, not a crypto problem. So this file pins them
together in both directions.
"""
import json

import gotcha
from gotcha_server import crypto
from gotcha_server.groups import clean_groups, fnv1a_16, group_id, normalize_group

import ble_proximity


PAYLOADS = [
    {},
    {"a": 1},
    {"b": "x", "a": 2},
    {"nested": {"z": 1, "a": [1, 2, {"c": 3}]}, "t": True, "f": False, "n": None},
    {"server_time": 1786694400, "hitlist": [{"pid": 1001, "name": "Otter 1",
                                             "streak": 3}]},
    {"config": {"KILL_RSSI": -65, "PROX_ALPHA_UP": 0.6, "PING_ENABLED": True}},
    {"quote": 'he said "hi"\n\ttab', "backslash": "a\\b"},
    {"empty_list": [], "empty_obj": {}},
]


def test_canonical_json_matches_badge():
    for p in PAYLOADS:
        assert crypto.canonical_json(p) == gotcha.canonical_json(p), p


def test_canonical_json_is_sorted_and_tight():
    s = crypto.canonical_json({"b": 1, "a": 2})
    assert s == '{"a":2,"b":1}'
    # and it is real JSON, not just a lookalike
    assert json.loads(s) == {"a": 2, "b": 1}


def test_request_signature_round_trip():
    """A badge-signed request verifies with the server's verifier, byte for byte,
    including a non-empty body and a query string."""
    key = "00112233445566778899aabbccddeeff" * 2
    body = json.dumps({"events": [{"uuid": "u1", "type": "heartbeat"}]}).encode()
    for method, path, b in [("GET", "/v1/sync", b""),
                            ("POST", "/v1/events", body),
                            ("GET", "/v1/leaderboard?board=total&limit=50", b"")]:
        badge_sig = gotcha.sign_request(key, method, path, 1786694400, "deadbeef", b)
        server_sig = crypto.sign_request(key, method, path, 1786694400, "deadbeef", b)
        assert badge_sig == server_sig


def test_response_signature_round_trip():
    """The server signs an envelope; the badge's verifier accepts it, and rejects
    a tampered payload, a swapped nonce and a truncated signature."""
    key = "ab" * 32
    payload = {"me": {"pid": 1001, "streak": 2}, "target": None}
    env = crypto.envelope(key, 1786694400, "cafebabe", payload)
    assert gotcha.sig_ok(key, env["ts"], env["nonce"], env["payload"], env["sig"])

    tampered = json.loads(json.dumps(payload))
    tampered["me"]["streak"] = 99
    assert not gotcha.sig_ok(key, env["ts"], env["nonce"], tampered, env["sig"])
    assert not gotcha.sig_ok(key, env["ts"], "0000beef", env["payload"], env["sig"])
    assert not gotcha.sig_ok(key, env["ts"], env["nonce"], env["payload"],
                             env["sig"][:-2])


def test_response_signature_binds_the_nonce():
    """§6.2's reason for putting the nonce in the signature: a response lifted
    from one request must not verify against another."""
    key = "cd" * 32
    p = {"x": 1}
    a = crypto.envelope(key, 1786694400, "1111aaaa", p)
    b = crypto.envelope(key, 1786694400, "2222bbbb", p)
    assert a["sig"] != b["sig"]


def test_soul_verification():
    soul = gotcha.make_soul()
    c = gotcha.commitment(soul)
    assert crypto.verify_soul(soul.hex(), c)
    assert not crypto.verify_soul(gotcha.make_soul().hex(), c)
    # Garbage is a failed proof, never an exception.
    for bad in (None, "", "zz", "ab", 42, "00" * 15, "00" * 17):
        assert not crypto.verify_soul(bad, c)
    assert not crypto.verify_soul(soul.hex(), None)


def test_card_token_expires_and_binds_pid():
    secret = "s3cret"
    tok = crypto.card_token(secret, 1001, 2000)
    assert crypto.card_token_ok(secret, 1001, tok, 1999)
    assert not crypto.card_token_ok(secret, 1001, tok, 2001)      # expired
    assert not crypto.card_token_ok(secret, 1002, tok, 1999)      # other player
    assert not crypto.card_token_ok("other", 1001, tok, 1999)     # other server
    assert not crypto.card_token_ok(secret, 1001, "garbage", 1999)


def test_admin_session_cookie():
    secret = "s3cret"
    c = crypto.session_cookie(secret, "Ward", 2000)
    assert crypto.session_host(secret, c, 1999) == "Ward"
    assert crypto.session_host(secret, c, 2001) is None
    assert crypto.session_host("other", c, 1999) is None
    assert crypto.session_host(secret, "Ward|2000|deadbeef", 1999) is None
    # A host name containing the separator must not let anyone forge a session.
    assert crypto.session_host(secret, "Ward|9999999999|" + c.rsplit("|", 1)[1],
                               1999) is None


def test_password_hash_round_trip():
    h, salt = crypto.password_hash("hunter2")
    assert crypto.password_ok(h, salt, "hunter2")
    assert not crypto.password_ok(h, salt, "hunter3")


def test_group_ids_match_the_badge():
    """§2.3: the group boards use the same ids the badge already puts on air. If
    these ever diverge, one group silently becomes two on the leaderboard."""
    names = ["Makerspace Baasrode", "makerspace baasrode ", "  MAKERSPACE BAASRODE",
             "Chiro", "chiro", "hackerspace gent", "Otters", "", "  ", "e" * 40,
             "groep-met-streepje", "1234"]
    for n in names:
        assert normalize_group(n) == ble_proximity.normalize_group(n)
        assert group_id(n) == ble_proximity.fnv1a_16(
            ble_proximity.normalize_group(n).encode("utf-8"))
    assert fnv1a_16(b"chiro") == ble_proximity.fnv1a_16(b"chiro")


def test_clean_groups_dedupes_and_caps():
    got = clean_groups(["Chiro", "chiro ", "Otters", "", None, "a", "b", "c", "d"])
    names = [n for n, _ in got]
    assert names[:2] == ["chiro", "otters"]
    assert len(got) == 5                      # MAX_GROUPS
    assert len(set(g for _, g in got)) == 5
