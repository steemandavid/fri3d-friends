#!/usr/bin/env python3
"""analyze_rssi.py -- score the RSSI-trend ("warmer/colder") promise + scan health.

Replays one or more raw advert logs (produced by probes/rssi_log.py) through a
grid of (alpha_fast, alpha_slow, deadband) triples and scores them against the
plan §8.8.2a success criteria:

  * approach / retreat : trend_db sign correct in >= 80 % of 2 s windows
  * stand still 30 s    : no sign flips outside the deadband (trend stays steady)
  * lateral / obstacle  : reported, not gating

It also prints per-file scan-health (adverts/s, max gap, duplicate-filter guess)
for the WiFi-coexistence (spike #1) and scan-duty (spike #4) tests, then gives a
single GO / NO-GO: is there one (af, as, deadband) triple that meets the approach
+ retreat >= 80 % bar in EVERY supplied condition file?

Usage:
  python3 tools/analyze_rssi.py probes/logs/open.csv probes/logs/tent.csv \
            probes/logs/bodies.csv probes/logs/pocket.csv \
            [--phases "0-30:up,30-60:flat,60-90:down,90-110:lat,110-130:obs"]

The phase spec is `start-end:kind` comma-separated, where kind is one of
up/down/flat/lat/obs and the times are seconds from the start of each run. The
default matches the standard walk protocol in the probe header comment. Pass a
SHORT target name on the advertiser badge (<= ~12 chars) so it fits the beacon.
"""
import argparse
import sys
from statistics import mean

# Candidate sweeps (plan defaults anchor the centres).
AF_GRID = [0.20, 0.25, 0.30, 0.35, 0.40]
AS_GRID = [0.04, 0.05, 0.06, 0.08, 0.10]
DB_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
BAR = 0.80
WIN_S = 2.0

DEFAULT_PHASES = "0-30:up,30-60:flat,60-90:down,90-110:lat,110-130:obs"


def load_csv(path):
    t, r = [], []
    header = ""
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                header = line
                continue
            try:
                a, b = line.split(",")
                t.append(int(a) / 1000.0)
                r.append(int(b))
            except ValueError:
                continue
    return t, r, header


def parse_phases(spec):
    phases = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        rng, kind = part.split(":")
        a, b = rng.split("-")
        phases.append((float(a), float(b), kind.strip().lower()))
    return phases


def ewma(r, af, as_):
    fast = [0.0] * len(r)
    slow = [0.0] * len(r)
    if not r:
        return fast, slow
    fast[0] = slow[0] = float(r[0])
    for i in range(1, len(r)):
        fast[i] = (1 - af) * fast[i - 1] + af * r[i]
        slow[i] = (1 - as_) * slow[i - 1] + as_ * r[i]
    return fast, slow


def score_phases(t, fast, slow, phases, db):
    """For each phase, score its 2 s windows. up/down/flat return the fraction of
    windows whose mean trend sign matches; lat/obs return the mean trend (dB) and
    a steadiness fraction (windows inside the deadband) for documentation.
    Returns {kind: {"frac": float, "mean": float, "n": int}}."""
    if not t:
        return {}
    trend = [f - s for f, s in zip(fast, slow)]
    out = {}
    for lo, hi, kind in phases:
        wins = []
        w = lo
        while w + WIN_S <= hi + 1e-9:
            # samples in [w, w+WIN_S) intersect [lo,hi]
            vals = [trend[i] for i in range(len(t)) if w <= t[i] < w + WIN_S and lo <= t[i] <= hi]
            if vals:
                wins.append(mean(vals))
            w += WIN_S
        if not wins:
            continue
        m = mean(wins)
        if kind == "up":
            frac = sum(1 for v in wins if v > db) / len(wins)
        elif kind == "down":
            frac = sum(1 for v in wins if v < -db) / len(wins)
        elif kind == "flat":
            frac = sum(1 for v in wins if abs(v) <= db) / len(wins)
        else:  # lat / obs : document the mean trend + how often it held steady
            frac = sum(1 for v in wins if abs(v) <= db) / len(wins)
        out[kind] = {"frac": frac, "mean": m, "n": len(wins)}
    return out


def scan_health(t):
    if not t:
        return {"n": 0, "rate": 0.0, "maxgap": 0.0, "dup_guess": "?"}
    dur = max(1e-9, t[-1] - t[0])
    gaps = [t[i] - t[i - 1] for i in range(1, len(t))]
    maxgap = max(gaps) if gaps else 0.0
    # If adverts basically stop after the first few seconds, NimBLE's duplicate
    # filter is probably on (each peer reported ~once) -- the #4 signal.
    early = [g for ti, g in zip(t[1:], gaps) if ti < 3.0]
    later = [g for ti, g in zip(t[1:], gaps) if ti >= 5.0]
    later_rate = (len(later) / max(1e-9, dur - 5.0)) if dur > 5.0 else len(later)
    dup = "ON? (rate collapses after ~3s)" if later_rate < 0.5 and len(t) > 10 else "off (steady)"
    return {"n": len(t), "rate": len(t) / dur, "maxgap": maxgap, "dup_guess": dup}


def best_triple(t, r, phases):
    """Sweep the grid; return (best (af,as,db), score dict). Score = mean of the
    approach and retreat window fractions (flat is reported but not weighted)."""
    best = None
    best_key = -1.0
    best_scores = {}
    for af in AF_GRID:
        for as_ in AS_GRID:
            fast, slow = ewma(r, af, as_)
            for db in DB_GRID:
                sc = score_phases(t, fast, slow, phases, db)
                up = sc.get("up", {"frac": 0.0})["frac"]
                down = sc.get("down", {"frac": 0.0})["frac"]
                flat = sc.get("flat", {"frac": 0.0})["frac"]
                # Require both approach and retreat present to score a triple.
                if "up" not in sc or "down" not in sc:
                    continue
                key = 0.5 * up + 0.5 * down + 0.1 * flat  # flat is a tiebreaker
                if key > best_key:
                    best_key = key
                    best = (af, as_, db)
                    best_scores = sc
    return best, best_scores


def _print_scores(sc):
    for kind, v in sc.items():
        if kind in ("up", "down", "flat"):
            print("     %-6s %2.0f%%  (%d windows, mean trend %+.1f dB)" % (
                kind, v["frac"] * 100, v["n"], v["mean"]))
        else:  # lat / obs : document the trend behaviour
            print("     %-6s mean trend %+.1f dB, held steady %2.0f%%  (%d windows)" % (
                kind, v["mean"], v["frac"] * 100, v["n"]))


# ---- marker-driven phase windows (from the prompted walk app) ----
MARKER_ORDER = ["start", "approach_end", "stand_end", "retreat_end",
                "lateral_end", "obstacle_end"]
MARKER_KIND = {"approach_end": "up", "stand_end": "flat", "retreat_end": "down",
               "lateral_end": "lat", "obstacle_end": "obs"}


def load_markers(path):
    """Parse a <label>_markers.csv (t_ms,kind) -> {kind: seconds}; None if absent."""
    m = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    a, b = line.split(",")
                    m[b.strip()] = int(a) / 1000.0
                except ValueError:
                    continue
    except OSError:
        return None
    return m or None


def markers_to_phases(m):
    """(lo,hi,kind) intervals from consecutive present markers."""
    out = []
    for i in range(len(MARKER_ORDER) - 1):
        a, b = MARKER_ORDER[i], MARKER_ORDER[i + 1]
        if a in m and b in m:
            out.append((m[a], m[b], MARKER_KIND.get(b, "any")))
    return out


def phases_for(csv_path, fixed):
    """Per-file phases: marker-driven if a sibling <stem>_markers.csv exists,
    else the fixed --phases spec. Returns (phases, used_markers)."""
    stem = csv_path[:-4] if csv_path.endswith(".csv") else csv_path
    m = load_markers(stem + "_markers.csv")
    if m:
        mp = markers_to_phases(m)
        if mp:
            return mp, True
    return fixed, False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+", help="raw advert logs from probes/rssi_log.py")
    ap.add_argument("--phases", default=DEFAULT_PHASES, help="phase spec (see module docstring)")
    ap.add_argument("--af", type=float, help="single alpha_fast (skip the grid)")
    ap.add_argument("--as", dest="as_", type=float, help="single alpha_slow (skip the grid)")
    ap.add_argument("--db", type=float, help="single deadband dB (skip the grid)")
    ap.add_argument("--plot", action="store_true", help="plot rssi/fast/slow/trend (needs matplotlib)")
    args = ap.parse_args()

    fixed_phases = parse_phases(args.phases)
    file_phases = {}
    per_file_best = []  # (path, best triple) for the cross-condition verdict
    for path in args.csv:
        t, r, header = load_csv(path)
        print("\n=== %s ===" % path)
        if header:
            print("  " + header.lstrip("# ").strip())
        phases, used_mk = phases_for(path, fixed_phases)
        file_phases[path] = phases
        print("  phases: %s" % ("markers (<label>_markers.csv)" if used_mk else
                                 "fixed 30s -- pass <label>_markers.csv for exact windows"))
        h = scan_health(t)
        print("  adverts=%d  rate=%.1f/s  max_gap=%.1fs  dup_filter=%s" % (
            h["n"], h["rate"], h["maxgap"], h["dup_guess"]))
        if len(t) < 20:
            print("  (too few adverts to score -- check the advertiser is on + near)")
            per_file_best.append((path, None))
            continue

        if args.af and args.as_ and args.db:
            fast, slow = ewma(r, args.af, args.as_)
            sc = score_phases(t, fast, slow, phases, args.db)
            print("  single triple (af=%.2f as=%.2f db=%.1f):" % (args.af, args.as_, args.db))
            _print_scores(sc)
            per_file_best.append((path, (args.af, args.as_, args.db)))
        else:
            triple, sc = best_triple(t, r, phases)
            print("  best triple: af=%.2f  as=%.2f  deadband=%.1f dB" % triple)
            _print_scores(sc)
            per_file_best.append((path, triple))

        if args.plot:
            try:
                import matplotlib.pyplot as plt
            except ImportError:
                print("  (matplotlib not installed; skipping plot)")
                continue
            af, as_, db = per_file_best[-1][1] or (0.30, 0.06, 1.5)
            fast, slow = ewma(r, af, as_)
            trend = [f - s for f, s in zip(fast, slow)]
            fig, (a0, a1) = plt.subplots(2, 1, sharex=True, num=path)
            a0.plot(t, r, ".", ms=2, label="rssi")
            a0.plot(t, fast, label="fast (a=%.2f)" % af)
            a0.plot(t, slow, label="slow (a=%.2f)" % as_)
            a0.set_ylabel("dBm"); a0.legend(fontsize=8); a0.set_title(path)
            a1.plot(t, trend, label="trend=fast-slow")
            a1.axhline(db, color="r", ls=":", label="+/-deadband")
            a1.axhline(-db, color="r", ls=":")
            for lo, hi, kind in phases:
                a1.axvspan(lo, hi, color={"up": "g", "down": "r", "flat": "b"}.get(kind, "grey"), alpha=0.08)
            a1.set_ylabel("trend dB"); a1.legend(fontsize=8); a1.set_xlabel("time (s)")
            fig.tight_layout()

    # ---- cross-condition GO / NO-GO ----
    print("\n==================== VERDICT ====================")
    good = [(p, tr) for p, tr in per_file_best if tr is not None]
    if len(good) < 2:
        print("Need >=2 scored conditions to judge a shared triple; scored %d." % len(good))
    else:
        # Does any triple appear (or a near-neighbour) across all conditions?
        from collections import Counter
        c = Counter(tr for _, tr in good)
        common = c.most_common(1)[0]
        # Re-score that single triple in every file against the bar.
        tr = common[0]
        print("Most-common best triple across conditions: af=%.2f as=%.2f db=%.1f" % tr)
        all_ok = True
        for path in args.csv:
            t, r, _ = load_csv(path)
            if len(t) < 20:
                continue
            fast, slow = ewma(r, *tr[:2])
            sc = score_phases(t, fast, slow, file_phases.get(path, fixed_phases), tr[2])
            up = sc.get("up", {"frac": 0.0})["frac"]
            down = sc.get("down", {"frac": 0.0})["frac"]
            ok = up >= BAR and down >= BAR
            all_ok = all_ok and ok
            print("  %-28s up=%2.0f%% down=%2.0f%%  %s" % (
                path.split("/")[-1], up * 100, down * 100, "OK" if ok else "below 80%"))
        print("\n  >> %s: a single (af,as,deadband) triple meets the >=80%% bar in every "
              "condition." % ("GO" if all_ok else "NO-GO"))
        if not all_ok:
            print("     Fallback: ship the ABSOLUTE bar alone (no warmer/colder), and rewrite")
            print("     the 'Finding them' narrative so it stops promising trend.")

    if args.plot:
        try:
            import matplotlib.pyplot as plt
            plt.show()
        except Exception:
            pass


if __name__ == "__main__":
    main()
