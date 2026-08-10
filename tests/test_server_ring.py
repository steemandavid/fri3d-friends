"""The ring (plan §3.2).

The invariant that matters more than group avoidance: **the game must always be
startable and nobody may be stranded**. So most of these tests are about the
degenerate cases -- one group holding half the camp, a ring of two, a ring of one
-- rather than about the happy path.
"""
import random

from gotcha_server import ring


def _groups(spec):
    """{pid: {gid, ...}} from {pid: [gid, ...]}."""
    return {p: set(g) for p, g in spec.items()}


def _is_single_cycle(targets):
    """Every player has exactly one hunter and the pointers form ONE cycle."""
    pids = [p for p, t in targets.items() if t is not None]
    if not pids:
        return True
    seen, cur, start = set(), pids[0], pids[0]
    while True:
        seen.add(cur)
        cur = targets[cur]
        if cur is None or cur == start:
            break
        if cur in seen:
            return False
    return len(seen) == len(pids)


def test_build_ring_is_one_cycle_and_avoids_groups():
    rng = random.Random(7)
    pids = list(range(1001, 1041))
    # Four groups of ten -- the realistic shape (§3.3: groups are tens out of
    # hundreds), where the constraint is easily satisfiable.
    gbp = _groups({p: [(p - 1001) // 10] for p in pids})
    targets, conflicts = ring.build_ring(pids, gbp, 20, rng)
    assert set(targets) == set(pids)
    assert _is_single_cycle(targets)
    assert conflicts == 0
    for p, t in targets.items():
        assert p != t
        assert gbp[p].isdisjoint(gbp[t])


def test_build_ring_starts_the_game_even_when_the_constraint_is_impossible():
    """§3.2 step 4: "if half the camp declares one group the constraint is
    genuinely unsatisfiable and the game must still start. Never let the
    constraint block a game from starting." """
    rng = random.Random(3)
    pids = list(range(1001, 1021))
    gbp = _groups({p: [0] for p in pids})       # everyone in one group
    targets, conflicts = ring.build_ring(pids, gbp, 20, rng)
    assert _is_single_cycle(targets)
    assert len(targets) == 20
    assert conflicts == 20                      # all of them, honestly reported


def test_ring_of_two_and_of_one():
    assert ring.build_ring([1001], {}, 20)[0] == {1001: None}
    targets, _ = ring.build_ring([1001, 1002], {}, 20, random.Random(1))
    assert targets == {1001: 1002, 1002: 1001}


def test_splice_in_keeps_one_cycle():
    rng = random.Random(11)
    pids = list(range(1001, 1011))
    targets, _ = ring.build_ring(pids, {}, 20, rng)
    huntable = set(pids)
    newcomer = 1099
    changes = ring.splice_in(targets, huntable, newcomer, {}, rng)
    targets.update(changes)
    assert _is_single_cycle(targets)
    assert newcomer in targets.values()         # somebody hunts them now
    assert targets[newcomer] is not None


def test_splice_in_prefers_a_non_conflicting_neighbour():
    rng = random.Random(5)
    # 1001 -> 1002 -> 1003 -> 1001, with 1001 and 1002 sharing a group.
    targets = {1001: 1002, 1002: 1003, 1003: 1001}
    gbp = _groups({1001: [1], 1002: [2], 1003: [3], 1099: [2]})
    changes = ring.splice_in(targets, {1001, 1002, 1003}, 1099, gbp, rng)
    targets.update(changes)
    # The newcomer is in group 2, so they must not end up hunting or hunted by
    # 1002 when an alternative exists.
    assert targets[1099] != 1002
    assert _is_single_cycle(targets)


def test_splice_in_never_assigns_a_self_target():
    """§10.5: "inheritance yields yourself -> walk forward". Reproduces a live
    ring seen on the dev backend (2026-08-10): every other huntable player
    already targets `pid`, so every candidate is skipped by the `t == pid`
    guard, `best` falls back to pool[0], and inheriting ITS target hands `pid`
    itself. That is also a stable fixed point -- the next reconcile re-derives
    the same self-target forever, so the player can never score."""
    rng = random.Random(3)
    targets = {1003: 1004, 1004: 1004, 1007: 1004}
    changes = ring.splice_in(targets, {1003, 1004, 1007}, 1004, {}, rng)
    targets.update(changes)
    assert targets[1004] != 1004
    assert targets[1004] in (1003, 1007)
    # ...and it is reciprocal, so 1004 is hunted too rather than orphaned.
    assert targets[targets[1004]] == 1004

    # Idempotent: running it again on the repaired ring leaves it valid.
    changes = ring.splice_in(targets, {1003, 1004, 1007}, 1004, {}, rng)
    targets.update(changes)
    assert targets[1004] != 1004


def test_splice_in_two_player_pool_all_pointing_at_us():
    # The minimal case: one other huntable player, already hunting us.
    targets = {1: 2, 2: 1}
    changes = ring.splice_in(targets, {1, 2}, 2, {}, random.Random(0))
    targets.update(changes)
    assert targets[2] == 1 and targets[1] == 2


def test_splice_out_hands_the_target_to_the_hunter():
    targets = {1: 2, 2: 3, 3: 1}
    huntable = {1, 3}                           # 2 has just died
    changes = ring.splice_out(targets, huntable, 2)
    assert changes == {1: 3}


def test_splice_out_walks_past_the_dead():
    targets = {1: 2, 2: 3, 3: 4, 4: 1}
    huntable = {1, 4}                           # 2 and 3 both gone
    changes = ring.splice_out(targets, huntable, 2)
    assert changes == {1: 4}


def test_inheritance_is_classic_and_never_yields_yourself():
    """D10/§3.2: assassin.target = victim.target. If that is the assassin, walk
    forward (§10.5)."""
    targets = {1: 2, 2: 1}                      # a ring of two
    changes, _ = ring.inherit(targets, {1}, 1, 2, {})
    # Nobody else is huntable, so there is nothing to inherit but themselves --
    # which must not happen; None is the honest answer ("waiting for players").
    assert changes[1] in (None,)

    targets = {1: 2, 2: 3, 3: 1}
    changes, conflicted = ring.inherit(targets, {1, 3}, 1, 2, {})
    assert changes == {1: 3}
    assert not conflicted


def test_inheritance_resplices_once_on_a_group_conflict():
    """§10.5: "Inheritance creates a group conflict -> one re-splice attempt, then
    accept and log." """
    rng = random.Random(2)
    targets = {1: 2, 2: 3, 3: 4, 4: 1}
    gbp = _groups({1: [7], 2: [1], 3: [7], 4: [2]})   # 1 and 3 share group 7
    huntable = {1, 3, 4}
    changes, conflicted = ring.inherit(targets, huntable, 1, 2, gbp, rng)
    assert not conflicted
    assert changes[1] != 3                      # the conflict was avoided
    merged = dict(targets)
    merged.update(changes)
    assert _is_single_cycle({p: t for p, t in merged.items() if p != 2})


def test_inheritance_accepts_a_conflict_rather_than_stranding_the_hunter():
    targets = {1: 2, 2: 3, 3: 1}
    gbp = _groups({1: [7], 2: [1], 3: [7]})     # only 3 is left, and it conflicts
    changes, conflicted = ring.inherit(targets, {1, 3}, 1, 2, gbp, random.Random(1))
    assert changes == {1: 3}
    assert conflicted                           # accepted, and reported


def test_walk_forward_falls_back_to_any_huntable_player():
    """A fresh ring where pointers have not been set yet must still give a hunter
    somebody to hunt."""
    assert ring.walk_forward({}, {5, 6}, 1, exclude=(1,)) in (5, 6)
    assert ring.walk_forward({}, {1}, 1, exclude=(1,)) is None
