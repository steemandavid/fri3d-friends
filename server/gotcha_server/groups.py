"""Group normalisation and hashing -- byte-identical to the badge.

The badge already normalises and hashes group names in `ble_proximity.py`
(`normalize_group` + `fnv1a_16`) for the nametag pills and proximity matching,
and plan §2.3 says the group scoreboard uses *the same* ids. These functions are
therefore a deliberate duplicate of the badge's, not a re-invention:
`tests/test_server_parity.py` asserts they agree with `ble_proximity.py` for a
corpus of names, so a change on either side fails a test rather than silently
splitting one group into two on the leaderboard.
"""

MAX_GROUPS = 5          # plan §2.3 / ble_proximity.MAX_GROUPS


def normalize_group(name):
    """Strip + lower; non-string -> ''. (ble_proximity.normalize_group)"""
    if not isinstance(name, str):
        return ""
    return name.strip().lower()


def fnv1a_16(data):
    """FNV-1a 32-bit xor-folded to 16 bits. (ble_proximity.fnv1a_16)"""
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 0xFFFF


def group_id(name):
    """The 16-bit id a normalised group name hashes to."""
    return fnv1a_16(normalize_group(name).encode("utf-8"))


def clean_groups(groups, max_groups=MAX_GROUPS):
    """Normalise an incoming groups[] list: drop blanks, de-duplicate by
    normalised name, keep declaration order, cap at MAX_GROUPS.

    Returns [(normalised_name, gid), ...]. The normalised name is what the
    leaderboard displays -- unverified by design (§2.3), so it is stored as the
    player typed it modulo case and whitespace.
    """
    out = []
    seen = set()
    if not isinstance(groups, (list, tuple)):
        return out
    for raw in groups:
        name = normalize_group(raw)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append((name, group_id(name)))
        if len(out) >= max_groups:
            break
    return out
