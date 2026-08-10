"""The ring: target assignment and maintenance (plan §3.2).

A single global ring over the players who can be hunted. The ring is stored as
one `target_pid` pointer per player -- there is no separate ring table, because
the pointer chain *is* the ring and any other representation would let the two
disagree.

Two invariants, in priority order:

1. **A game must always be startable.** If half the camp declares one group the
   no-same-group constraint is genuinely unsatisfiable (§3.2 step 4), so every
   function here degrades to "assign anyway and log" rather than failing. Never
   let the constraint block a game from starting.
2. **No player is their own target, and no player targets a non-huntable
   player.** Violating this strands a hunter, which §3.3 names as the game's
   real failure mode.

`shuffle` is injectable so the tests can pin an ordering.
"""

import random

from . import state

# Statuses that may be *hunted* (hold a slot as someone's target).
HUNTABLE = state.IN_RING_AS_TARGET


def shares_group(groups_by_pid, a, b):
    """Do two players share any group? (§3.2's edge predicate, negated)"""
    ga = groups_by_pid.get(a)
    gb = groups_by_pid.get(b)
    if not ga or not gb:
        return False
    return not ga.isdisjoint(gb)


def build_ring(pids, groups_by_pid, max_passes=20, rng=None):
    """Randomised Hamiltonian cycle avoiding same-group edges (§3.2).

    Returns (targets, conflicts): a {pid: target_pid} map and the number of
    same-group edges that survived repair. At camp scale the constraint graph is
    extremely dense (groups are tens of people out of hundreds), so the
    randomised construction plus local repair converges immediately; the
    conflict count exists for the pathological case, and is surfaced on the
    admin page rather than raised.
    """
    rng = rng or random
    order = list(pids)
    if len(order) < 2:
        return ({order[0]: None} if order else {}), 0
    order = _interleave(order, groups_by_pid, rng)

    n = len(order)

    def conflict_at(i):
        return shares_group(groups_by_pid, order[i], order[(i + 1) % n])

    for _ in range(max_passes):
        bad = [i for i in range(n) if conflict_at(i)]
        if not bad:
            break
        for i in bad:
            if not conflict_at(i):
                continue                        # an earlier swap already fixed it
            # Swap the two players' *successors*: that is the 2-opt move that
            # keeps a single cycle instead of splitting it into two.
            candidates = [j for j in range(n) if j not in (i - 1, i, (i + 1) % n)]
            rng.shuffle(candidates)
            for j in candidates:
                before = _edge_cost(order, groups_by_pid, i, j, n)
                order[(i + 1) % n], order[(j + 1) % n] = (order[(j + 1) % n],
                                                          order[(i + 1) % n])
                if _edge_cost(order, groups_by_pid, i, j, n) < before:
                    break
                order[(i + 1) % n], order[(j + 1) % n] = (order[(j + 1) % n],
                                                          order[(i + 1) % n])

    # Second neighbourhood: swap two players' positions outright. The successor
    # swap above cannot escape every plateau (a ring that is exactly half one
    # group is the tight case), and this move set can, so it is worth one more
    # cheap pass before reporting conflicts to the admin page.
    for _ in range(max_passes):
        bad = [i for i in range(n) if conflict_at(i)]
        if not bad:
            break
        improved = False
        for i in bad:
            p = (i + 1) % n
            for q in rng.sample(range(n), min(n, 24)):
                if q == p:
                    continue
                before = _pos_cost(order, groups_by_pid, p, q, n)
                order[p], order[q] = order[q], order[p]
                if _pos_cost(order, groups_by_pid, p, q, n) < before:
                    improved = True
                    break
                order[p], order[q] = order[q], order[p]
        if not improved:
            break

    targets = {}
    conflicts = 0
    for i in range(n):
        nxt = order[(i + 1) % n]
        targets[order[i]] = nxt
        if shares_group(groups_by_pid, order[i], nxt):
            conflicts += 1
    return targets, conflicts


def _pos_cost(order, groups_by_pid, p, q, n):
    """Same-group edges among those a swap of positions p and q can change."""
    idx = {(p - 1) % n, p % n, (q - 1) % n, q % n}
    return sum(1 for k in idx
               if shares_group(groups_by_pid, order[k], order[(k + 1) % n]))


def _interleave(pids, groups_by_pid, rng):
    """Randomised group-aware deal, used as the starting order for the repair.

    §3.2 specifies "a randomised construction with local repair". A plain shuffle
    is a legitimate reading of that, but it has a nasty local minimum: with two
    large groups of roughly equal size -- say Chiro and a makerspace, which is a
    perfectly plausible camp -- a shuffled ring lands on four or five same-group
    edges and *no single successor-swap improves it*, so the hill-climbing repair
    stalls and the admin page reports conflicts for a ring that has a perfect
    solution.

    Dealing instead from the group with the most players left, skipping anyone who
    shares a group with the previous pick, starts the repair at or very near zero
    for every realistic shape. The randomness stays: the tie-break is random, so
    two runs give different rings.
    """
    remaining = list(pids)
    rng.shuffle(remaining)
    out = []
    while remaining:
        prev = out[-1] if out else None
        pool = [p for p in remaining
                if prev is None or not shares_group(groups_by_pid, prev, p)]
        if not pool:                        # genuinely unsatisfiable from here
            pool = remaining
        counts = {}
        for p in remaining:
            for g in groups_by_pid.get(p, ()):
                counts[g] = counts.get(g, 0) + 1
        # Deal the crowded groups first, or they pile up at the end of the ring.
        pick = max(pool, key=lambda p: (max((counts[g] for g in
                                             groups_by_pid.get(p, ())), default=0),
                                        rng.random()))
        out.append(pick)
        remaining.remove(pick)
    return out


def _edge_cost(order, groups_by_pid, i, j, n):
    """Same-group edges among those a swap of positions i+1 and j+1 can change.

    Swapping the two successors touches the edges leaving i, i+1, j and j+1 --
    getting this index set wrong makes the repair loop evaluate edges it did not
    move, and it stops converging on exactly the case that matters (two large
    groups, where a perfect alternating ring exists).
    """
    idx = {i % n, (i + 1) % n, j % n, (j + 1) % n}
    return sum(1 for k in idx
               if shares_group(groups_by_pid, order[k], order[(k + 1) % n]))


# ---------------------------------------------------------------------------
# Maintenance. These operate on a live {pid: target_pid} view plus the set of
# huntable pids, and return the pointer changes to apply.
# ---------------------------------------------------------------------------

def hunter_of(targets, pid):
    """Who is hunting `pid`? (the ring's reverse pointer, computed on demand --
    at 700 players this is a dict scan, not a problem)"""
    for h, t in targets.items():
        if t == pid:
            return h
    return None


def splice_in(targets, huntable, pid, groups_by_pid, rng=None, tries=10):
    """New enrollment or respawn (§3.2): pick a random huntable P, then
    `new.target = P.target; P.target = new`.

    Retries up to `tries` times for a P that creates no group conflict; accepts a
    conflict rather than leaving the player out of the ring.
    """
    rng = rng or random
    pool = [p for p in huntable if p != pid and targets.get(p) is not None]
    changes = {}
    if not pool:
        # Ring of one (or of one-plus-this): pair them up if we can.
        other = [p for p in huntable if p != pid]
        if other:
            changes[pid] = other[0]
            changes[other[0]] = pid
        else:
            changes[pid] = None
        return changes

    best = None
    for _ in range(tries):
        p = rng.choice(pool)
        t = targets.get(p)
        if t is None or t == pid:
            continue
        ok = (not shares_group(groups_by_pid, p, pid)
              and not shares_group(groups_by_pid, pid, t))
        if ok:
            best = p
            break
        if best is None:
            best = p                              # fallback: accept a conflict
    if best is None:
        best = pool[0]
    t = targets.get(best)
    if t is None or t == pid:
        # Every candidate in the pool already hunts us, so inheriting their
        # target would hand us OURSELVES (§10.5: "inheritance yields yourself ->
        # walk forward"). Worse, it is a stable fixed point: the next reconcile
        # sees target == pid, re-enters here, and re-derives the same self-target
        # forever, leaving a player who can never score. Resolve it the way the
        # ring-of-two branch above does -- a mutual pair.
        changes[pid] = best
        changes[best] = pid
        return changes
    changes[pid] = t
    changes[best] = pid
    return changes


def splice_out(targets, huntable, pid):
    """Remove `pid` as a target: their hunter inherits their target (§3.2).

    Used for opt-out, dormancy, staleness, kick and death. The player keeps their
    own target pointer -- `stale` players still hunt (§9.6), and a dead player's
    pointer is what their killer inherits (D10).
    """
    changes = {}
    h = hunter_of(targets, pid)
    if h is None:
        return changes
    nxt = walk_forward(targets, huntable, pid, exclude=(h, pid))
    changes[h] = nxt
    return changes


def walk_forward(targets, huntable, start, exclude=()):
    """From `start`, follow target pointers to the first huntable player that is
    not excluded (§10.5: "inheritance yields yourself / a dead player -> walk
    forward"). Returns None if the ring holds nobody else."""
    seen = set()
    cur = targets.get(start)
    while cur is not None and cur not in seen:
        seen.add(cur)
        if cur in huntable and cur not in exclude:
            return cur
        cur = targets.get(cur)
    # The pointer chain dead-ended (a fresh ring, or everyone excluded): fall
    # back to any huntable player, which is still better than stranding a hunter.
    for p in sorted(huntable):
        if p not in exclude:
            return p
    return None


def swap_positions(targets, u, v):
    """Exchange two players' *positions* in the ring, returning the pointer diff.

    This is the only safe way to move somebody in a cycle: naively handing one
    player's target to somebody else splits the cycle in two, or -- worse -- makes
    a player their own target. The three cases are u immediately before v, v
    immediately before u, and disjoint.
    """
    if u == v:
        return {}
    h_u, h_v = hunter_of(targets, u), hunter_of(targets, v)
    t_u, t_v = targets.get(u), targets.get(v)
    if h_u is None or h_v is None or t_u is None or t_v is None:
        return {}
    if t_u == v:                                  # ... h_u -> u -> v ...
        return {h_u: v, v: u, u: t_v}
    if t_v == u:                                  # ... h_v -> v -> u ...
        return {h_v: u, u: v, v: t_u}
    return {h_u: v, v: t_u, h_v: u, u: t_v}


def inherit(targets, huntable, assassin, victim, groups_by_pid, rng=None):
    """Kill (§3.2): `assassin.target = victim.target`, classic inheritance.

    If that yields the assassin themselves or a non-huntable player, walk
    forward. If it creates a group conflict, try **one** re-splice; otherwise
    accept it and log (§10.5).
    """
    rng = rng or random
    nxt = targets.get(victim)
    if nxt is None or nxt == assassin or nxt not in huntable:
        nxt = walk_forward(targets, huntable, victim, exclude=(assassin, victim))
    if nxt is None:
        return {assassin: None}, False

    conflicted = shares_group(groups_by_pid, assassin, nxt)
    if conflicted:
        alt = [p for p in huntable
               if p not in (assassin, victim, nxt)
               and not shares_group(groups_by_pid, assassin, p)]
        if alt:
            other = rng.choice(alt)
            # The provisional ring: victim gone, inheritance applied. Swapping
            # `nxt` and `other` inside it hands the assassin a non-conflicting
            # target while keeping one cycle.
            prov = {p: t for p, t in targets.items() if p != victim}
            prov[assassin] = nxt
            swap = swap_positions(prov, nxt, other)
            if swap:
                changes = {assassin: nxt}
                changes.update(swap)
                changes = {p: t for p, t in changes.items() if p != victim}
                if changes.get(assassin) == other:
                    return changes, False
    return {assassin: nxt}, conflicted
