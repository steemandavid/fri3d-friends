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
