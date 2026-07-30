"""Parity between the plan's §5.4 tunables table and what the server pushes.

§5.4 says *every* tunable is server-pushed — "Retuning KILL_RSSI and KILL_HOLD_MS
live from the admin page is worth a lot... you will want to adjust on Friday
afternoon without reflashing 700 badges". A tunable that exists in the plan but not
in `TUNABLE_DEFAULTS` silently breaks that promise: the badge falls back to its
compiled-in default and the admin page cannot reach it.

This test reads the plan and fails when the two drift. It exists because they
*did* drift: `HUNT_SYNC_DEFER` and `HUNT_SYNC_DEFER_MAX_S` were added to §5.4 on
2026-07-30, an hour after `config.py` was written, and nothing would have noticed.
The plan is the specification, so it is the plan that this test trusts.

Struck-through rows (`~~NAME~~`) are retractions -- currently the four RSSI-trend
tunables killed by the §8.8.2a no-go -- and must be *absent* from the config, which
is asserted too: a retracted tunable quietly coming back is the same class of bug.
"""
import os
import re

from gotcha_server.config import SERVER_DEFAULTS, TUNABLE_DEFAULTS, tunables_for_badge

PLAN = os.path.join(os.path.dirname(__file__), "..",
                    "Implementation_Plan_Gotcha_20260726.md")

# §8.10.1 feature kill switches and the two ping frequencies are pushed to badges
# but are not single-name rows in the §5.4 table (the frequencies share one row).
NOT_TABLE_ROWS = {"PING_FREQ_FAR", "PING_FREQ_NEAR",
                  "reveal_enabled", "bounty_enabled", "training_enabled",
                  "alarm_enabled"}


def _parse_section():
    with open(PLAN, encoding="utf-8") as f:
        txt = f.read()
    sec = txt.split("### 5.4 Tunables")[1].split("### 5.5")[0]
    live, retracted = {}, set()
    for line in sec.splitlines():
        m = re.match(r"^\|\s*(~~)?`([A-Za-z_]+)`(~~)?\s*\|\s*([^|]*?)\s*\|", line)
        if not m:
            continue
        name = m.group(2)
        if m.group(1) or m.group(3):
            retracted.add(name)
        else:
            live[name] = m.group(4).strip()
    return live, retracted


def test_the_plan_section_is_still_parseable():
    """If §5.4 is restructured this test must fail loudly rather than pass by
    finding nothing -- a vacuous parity check is worse than none."""
    live, retracted = _parse_section()
    assert len(live) >= 25, "parsed only %d tunables from §5.4" % len(live)
    assert retracted, "expected the retracted RSSI-trend tunables to still be listed"


def test_every_plan_tunable_is_pushed_to_badges():
    live, _ = _parse_section()
    missing = sorted(k for k in live if k not in TUNABLE_DEFAULTS)
    assert not missing, (
        "§5.4 lists tunables the server does not push: %s. Every tunable must be "
        "server-pushed (§5.4), so add them to TUNABLE_DEFAULTS." % missing)


def test_retracted_tunables_are_not_pushed():
    _, retracted = _parse_section()
    revived = sorted(k for k in retracted if k in TUNABLE_DEFAULTS)
    assert not revived, (
        "these tunables were struck through in §5.4 and must not be pushed: %s"
        % revived)


def test_pushed_tunables_are_all_in_the_plan():
    """The reverse direction: no invented tunables. A badge acting on a constant
    that is not in the plan is a constant nobody has agreed to."""
    live, _ = _parse_section()
    unknown = sorted(k for k in TUNABLE_DEFAULTS
                     if k not in live and k not in NOT_TABLE_ROWS)
    assert not unknown, "pushed but not documented in §5.4: %s" % unknown


def test_documented_defaults_match():
    """Numeric and boolean defaults must match the plan's table.

    Only rows whose default parses unambiguously are compared -- several are prose
    ("20:00", "1400 / 2400 Hz"), and this test is a drift alarm, not a parser.
    """
    live, _ = _parse_section()
    mismatches = []
    for name, raw in live.items():
        if name not in TUNABLE_DEFAULTS:
            continue
        # Strip markdown emphasis and any trailing commentary.
        val = raw.replace("**", "").strip()
        val = val.split()[0] if val else ""
        val = val.replace("−", "-").rstrip("%")     # unicode minus, percent
        want = None
        if val.lower() in ("true", "false"):
            want = val.lower() == "true"
        else:
            try:
                want = int(val)
            except ValueError:
                try:
                    want = float(val)
                except ValueError:
                    continue                             # prose default: skip
        mine = TUNABLE_DEFAULTS[name]
        if isinstance(want, bool) != isinstance(mine, bool) or want != mine:
            mismatches.append((name, want, mine))
    assert not mismatches, "plan/config default mismatch: %s" % mismatches


def test_hunt_sync_defer_cannot_outlast_the_outage_window():
    """A badge deferring its sync mid-chase must not look like the server being
    down. `HUNT_SYNC_DEFER_MAX_S` therefore has to stay below the silence that
    `state.outage_intervals` reads as an outage (§10.3), or a long hunt would pause
    dormancy accounting for the whole camp -- which at 2 dev badges, or 4 players in
    the endgame, is not theoretical: every badge really can be deferring at once."""
    from gotcha_server.state import OUTAGE_GAP_MIN
    assert TUNABLE_DEFAULTS["HUNT_SYNC_DEFER_MAX_S"] < OUTAGE_GAP_MIN * 60


def test_deferral_is_never_reported_as_an_outage_at_any_bucket_phase():
    """The constant ordering above is necessary but not sufficient.

    `outage_intervals()` works on 60 s buckets, so there is rounding on top of the
    comparison, and the interesting question is which way it runs. Measured, rather
    than argued: a silence starts at `bucket_of(prev_sync) + 60` and ends at
    `bucket_of(next_sync)`, so the *measured* gap is always **shorter** than the
    true one -- at most `true - 1`. The rounding therefore adds margin against a
    false outage rather than eating it, and the worst case over all 60 possible
    phases of a maximal 900 s deferral is reported as no outage at all.

    (The cost is on the other side: a real outage of up to `OUTAGE_GAP_MIN + 59` s
    can be missed. That is the right trade -- under-declaring an outage costs a
    little dormancy accuracy, whereas over-declaring one pauses dormancy for the
    whole camp.)
    """
    from gotcha_server.db import Database
    from gotcha_server.state import OUTAGE_GAP_MIN, outage_intervals

    span = OUTAGE_GAP_MIN * 60
    defer = TUNABLE_DEFAULTS["HUNT_SYNC_DEFER_MAX_S"]

    def measured(phase, silence):
        db = Database(":memory:")
        prev, nxt = 6000 + phase, 6000 + phase + silence
        for t in (prev, nxt):
            db.execute("INSERT OR REPLACE INTO sync_beats(minute_ts, n) "
                       "VALUES(?, 1)", (t // 60 * 60,))
        db.commit()
        iv = outage_intervals(db, prev, nxt + 60)
        db.close()
        return max((b - a for a, b in iv), default=0)

    for phase in range(60):
        assert measured(phase, defer) < span, (
            "a maximal deferral at bucket phase %d measures as a %d s outage"
            % (phase, measured(phase, defer)))
    # The boundary itself, pinned so a future change to the bucketing is visible:
    # nothing below the threshold is ever declared, i.e. measured <= true.
    assert all(measured(p, span - 1) < span for p in range(60))
    assert any(measured(p, span + 1) >= span for p in range(60))


def test_server_only_rules_are_not_pushed():
    """The badge cannot act on DORMANT_H or MAX_KILLS_PER_HOUR, and every byte
    rides 700 badges twelve times an hour."""
    pushed = tunables_for_badge(dict(TUNABLE_DEFAULTS, **SERVER_DEFAULTS))
    for k in SERVER_DEFAULTS:
        assert k not in pushed, k
