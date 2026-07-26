"""Host tests for identity.auto_nickname (the v0.9.0 auto-generated badge name)."""

from identity import ANIMALS, NICK_NUMBERS, auto_nickname


def test_shape():
    nick = auto_nickname(b"\x01\x02\x03\x04\x05\x06")
    animal, number = nick.rsplit(" ", 1)
    assert animal in ANIMALS
    assert 0 <= int(number) < NICK_NUMBERS


def test_deterministic():
    # The whole design rests on this: the nickname is never written to flash, so
    # stability across reboots comes purely from the derivation being pure.
    uid = b"\x34\x85\x18\xac\xfa\xb8"
    assert auto_nickname(uid) == auto_nickname(uid)


def test_different_badges_differ():
    # Not a uniqueness guarantee (6400 combos), just a smoke test that nearby
    # MACs — which real badges have — don't collapse onto one name.
    uids = [bytes([0x34, 0x85, 0x18, 0xAC, 0xFA, n]) for n in range(32)]
    assert len(set(auto_nickname(u) for u in uids)) > 24


def test_accepts_bytearray_and_memoryview():
    uid = b"\xde\xad\xbe\xef"
    assert auto_nickname(bytearray(uid)) == auto_nickname(uid)
    assert auto_nickname(memoryview(uid)) == auto_nickname(uid)


def test_never_raises_on_junk():
    # A badge that somehow can't read its unique_id still gets a usable name
    # rather than crashing the app at config-load time.
    for junk in (None, "", 42, object(), b""):
        nick = auto_nickname(junk)
        assert nick.rsplit(" ", 1)[0] in ANIMALS


def test_animals_are_render_safe():
    # Rendered in the 42px name font on a 296px-wide screen; keep them short and
    # ASCII so they never scroll or fall back to a tofu glyph.
    for a in ANIMALS:
        assert a.isascii() and a.isalpha() and len(a) <= 8
    assert len(set(ANIMALS)) == len(ANIMALS)
