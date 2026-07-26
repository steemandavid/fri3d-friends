# identity.py — auto-generated badge nickname.
#
# PURE module: no `machine` / `bluetooth` / `mpos` / `lvgl` imports, so the host
# tests can import it directly (tests/test_identity.py). The caller supplies the
# raw id bytes (on-device: `machine.unique_id()`).
#
# Why not the Bluetooth `Fri3d-XXXX` id? That comes from the BLE MAC, which is
# only readable once the radio is active — and a fresh badge with no groups never
# brings the radio up. `machine.unique_id()` is the fused base MAC and works with
# no radio at all, but it differs from the BLE MAC by a small fixed offset. Two
# near-identical ids that disagree reads as a bug, so the auto-nickname is
# deliberately a DIFFERENT KIND of name: nobody expects "Otter 42" to match
# "Fri3d-A3F2". See DESIGN.md "Auto-nickname".

# 64 short, kid-friendly, unambiguous animal names. Kept ASCII and <= 8 chars so
# the 42px name font renders them on one line without scrolling on both boards.
ANIMALS = (
    "Otter", "Badger", "Fox", "Heron", "Lynx", "Marten", "Falcon", "Ibex",
    "Puffin", "Raven", "Stoat", "Weasel", "Beaver", "Osprey", "Shrew", "Vole",
    "Adder", "Newt", "Toad", "Gecko", "Skink", "Turtle", "Cobra", "Iguana",
    "Panda", "Koala", "Tapir", "Okapi", "Lemur", "Sloth", "Gibbon", "Macaw",
    "Puma", "Ocelot", "Jaguar", "Caracal", "Serval", "Dingo", "Coyote", "Jackal",
    "Walrus", "Narwhal", "Orca", "Manta", "Marlin", "Tarpon", "Wrasse", "Blenny",
    "Hornet", "Cicada", "Mantis", "Weevil", "Cricket", "Firefly", "Moth", "Beetle",
    "Bison", "Tahr", "Saiga", "Kudu", "Oryx", "Eland", "Gaur", "Yak",
)

NICK_NUMBERS = 100          # numeric suffix range: 0..99


def _fold(uid):
    """Fold arbitrary id bytes into a 32-bit integer, deterministically.

    FNV-1a (same construction as ble_proximity.fnv1a_16, kept local so this
    module stays dependency-free). Any bytes-like input works; a non-bytes or
    empty input folds to the FNV offset basis, which still yields a valid — if
    not unique — nickname rather than raising.
    """
    h = 0x811C9DC5
    try:
        data = bytes(uid)
    except Exception:
        data = b""
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def auto_nickname(uid):
    """Derive a stable, friendly nickname from raw id bytes -> e.g. "Otter 42".

    Deterministic: the same badge always yields the same name, so the nickname
    is stable across reboots WITHOUT ever being written to flash. That matters —
    it means the auto-name can never fight a phone-side save, and wiping
    config.json restores the same nickname.

    64 animals x 100 numbers = 6400 combinations. Collisions across a large camp
    are possible and harmless: the nickname is a display name, not an identity,
    and matching is done on group hashes.
    """
    h = _fold(uid)
    animal = ANIMALS[h % len(ANIMALS)]
    number = (h // len(ANIMALS)) % NICK_NUMBERS
    return "%s %d" % (animal, number)
