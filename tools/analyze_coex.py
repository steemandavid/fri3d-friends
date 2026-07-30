#!/usr/bin/env python3
"""analyze_coex.py -- score the Phase 0 coexistence / scan-duty spike (#1, #3, #4).

Reads probes/logs/coex_<label>.json (the badge's own per-condition summary) and,
independently, recomputes rate and worst presence gap straight from
probes/logs/coex_<label>.csv, so the verdict does not rest on on-badge maths.

  python3 tools/analyze_coex.py [logdir]

Bars (plan §11 items 1 and 4, §4 EVICT_MS):
  * coexistence: WiFi-on detection rate within 25 % of WiFi-off, and no peer's
    worst gap crossing EVICT_MS (30 s) -- crossing it means presence flaps.
  * scan duty:   12.5 % duty must keep the duplicate filter OFF (steady stream,
    not a collapse after ~3 s) and keep worst gap under EVICT_MS.
"""
import json
import os
import sys
from collections import defaultdict

EVICT_S = 30.0
TOL = 0.25
ORDER = ["off_60_120", "idle_60_120", "busy_60_120",
         "off_30_240", "idle_30_240", "busy_30_240"]


def load_csv(path):
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                p = line.split(",")
                if len(p) < 3:
                    continue
                rows.append((int(p[0]) / 1000.0, int(p[1]), p[2]))
    except OSError:
        pass
    return rows


def recompute(rows, dur_hint=None):
    """-> (dur_s, rate, n_peers, worst_gap_s, {name: (n, rate, gap)})"""
    if not rows:
        return 0.0, 0.0, 0, None, {}
    dur = dur_hint or max(r[0] for r in rows)
    by = defaultdict(list)
    for t, _rssi, nm in rows:
        by[nm].append(t)
    out, worst = {}, 0.0
    for nm, ts in by.items():
        ts.sort()
        gaps = [ts[0]] + [ts[i] - ts[i - 1] for i in range(1, len(ts))] + [dur - ts[-1]]
        g = max(gaps)
        worst = max(worst, g)
        out[nm] = (len(ts), len(ts) / max(dur, 1e-9), g)
    return dur, len(rows) / max(dur, 1e-9), len(by), worst, out


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "probes/logs"

    print("=" * 74)
    print("SPIKE 3 -- three GATT services in ONE gatts_register_services call")
    print("=" * 74)
    try:
        g = json.load(open(os.path.join(d, "coex_gatt.json")))
        print("  attempted : %s" % ", ".join(g.get("services", [])))
        print("  RESULT    : %s" % ("GO" if g.get("ok") else "NO-GO: %s" % g.get("err")))
        if g.get("ok"):
            print("  handle groups returned : %s (one per service)" % g.get("handle_groups"))
            for nm, h in zip(g.get("services", []), g.get("handles", [])):
                print("    %-9s %d char handles %s" % (nm, len(h), h))
            print("  512-byte gatts_set_buffer on SPOILS : %s" % g.get("buffer_512_ok"))
    except Exception as e:
        print("  no result (%s)" % e)

    print()
    print("=" * 74)
    print("SPIKES 1 + 4 -- per condition (recomputed from the raw advert log)")
    print("=" * 74)
    print("%-13s %6s %6s %6s %8s %10s  %s" % (
        "cond", "duty%", "wifi", "peers", "adv/s", "worst gap", "note"))
    summ = {}
    for label in ORDER:
        jp = os.path.join(d, "coex_%s.json" % label)
        cp = os.path.join(d, "coex_%s.csv" % label)
        meta = {}
        try:
            meta = json.load(open(jp))
        except Exception:
            pass
        rows = load_csv(cp)
        if not rows and not meta:
            continue
        dur, rate, npeers, worst, per = recompute(rows, meta.get("dur_s"))
        summ[label] = (rate, worst, per, meta)
        wf = meta.get("wifi_connected_frac")
        print("%-13s %6s %6s %6d %8.2f %9.1fs  %s" % (
            label, meta.get("duty_pct", "?"),
            ("-" if wf is None else ("%.0f%%" % (wf * 100))),
            npeers, rate, worst if worst is not None else -1,
            "" if (worst or 0) < EVICT_S else "GAP > EVICT_MS"))
        for nm, (n, r, gp) in sorted(per.items()):
            print("               peer %-16s n=%-4d %5.2f/s  worst gap %5.1fs%s" % (
                nm, n, r, gp, "   <-- exceeds EVICT_MS" if gp > EVICT_S else ""))

    print()
    print("=" * 74)
    print("VERDICT")
    print("=" * 74)

    def rate_of(c):
        return summ.get(c, (0.0,))[0]

    def gap_of(c):
        return summ.get(c, (0.0, None))[1]

    print("\nSPIKE 1 -- WiFi + BLE coexistence")
    any_bad = False
    for duty, off, idle, busy in (("50 %", "off_60_120", "idle_60_120", "busy_60_120"),
                                  ("12.5 %", "off_30_240", "idle_30_240", "busy_30_240")):
        b = rate_of(off)
        if not b:
            continue
        print("  at %s duty (baseline WiFi-off %.2f adv/s):" % (duty, b))
        for lbl, c in (("wifi idle", idle), ("wifi busy", busy)):
            r = rate_of(c)
            if not r:
                print("    %-10s no data" % lbl)
                continue
            keep = r / b
            ok = keep >= (1 - TOL)
            any_bad = any_bad or not ok
            print("    %-10s %5.2f adv/s = %3.0f %% of baseline   %s" % (
                lbl, r, keep * 100, "OK" if ok else "DEGRADED"))
    gaps = [gap_of(c) for c in ORDER if gap_of(c) is not None]
    if gaps:
        print("  worst presence gap over all conditions: %.1fs (EVICT_MS %.0fs) -> %s" % (
            max(gaps), EVICT_S,
            "presence stable" if max(gaps) < EVICT_S else "PRESENCE WOULD FLAP"))
    # The bar that decides "revisit the architecture" is idle association, not a
    # transfer: the link is up ~all the time, transfers are ~1.7 % of it (§8.7).
    idle_ok = all(rate_of(i) >= (1 - TOL) * rate_of(o)
                  for o, i in (("off_60_120", "idle_60_120"),
                               ("off_30_240", "idle_30_240"))
                  if rate_of(o) and rate_of(i))
    presence_ok = (not gaps) or max(gaps) < EVICT_S
    if idle_ok and presence_ok:
        print("  => GO, WITH A SCHEDULING RULE. Idle association is cheap and presence")
        print("     never flaps, so the architecture stands. But a transfer costs")
        print("     ~58 % of the detection rate, so do NOT sync while the hunt bar is")
        print("     lit (§5.4 HUNT_SYNC_DEFER).")
    elif not presence_ok:
        print("  => NO-GO: a peer exceeded EVICT_MS, so presence itself flaps.")
    else:
        print("  => DEGRADED even when idle - revisit the architecture.")

    print("\nSPIKE 4 -- scan duty 50 % -> 12.5 %")
    r50, r12 = rate_of("off_60_120"), rate_of("off_30_240")
    if r50 and r12:
        print("  WiFi-off detection rate: %.2f -> %.2f adv/s (%.0f %% kept)" % (
            r50, r12, 100.0 * r12 / r50))
        g12 = gap_of("off_30_240")
        collapsed = r12 < 0.3
        print("  duplicate filter at 12.5 %%: %s" % (
            "SUSPECT - rate collapsed, filter likely ON" if collapsed
            else "OFF - steady stream, explicit interval/window still disables it"))
        if g12 is not None:
            print("  worst gap at 12.5 %%: %.1fs -> %s" % (
                g12, "OK" if g12 < EVICT_S else "EXCEEDS EVICT_MS"))
        ok4 = (not collapsed) and (g12 is not None and g12 < EVICT_S)
        # Per-PEER rate is what the kill needs, and it is what disqualifies 12.5 %
        # for the hunt: KILL_HOLD_MS is 5 s, and the field is ~4x slower than a desk.
        per12 = summ.get("off_30_240", (0, 0, {}))[2]
        worst_peer = min((v[1] for v in per12.values()), default=0.0)
        field_est = worst_peer / 4.0          # walks: 0.7-1.0/s per peer at 50 % vs ~1.8 here
        print("  slowest peer at 12.5 %%: %.2f adv/s on a desk -> ~%.2f/s in a field" % (
            worst_peer, field_est))
        print("  KILL_HOLD_MS is 5000 ms, i.e. ~%.1f field samples per hold window" % (
            field_est * 5.0))
        if not ok4:
            print("  => NO-GO - keep 50 % duty")
        elif field_est * 5.0 < 2.0:
            print("  => GO MECHANICALLY (filter stays off, presence stable), but NOT for")
            print("     the hunt path: fewer than 2 samples per KILL_HOLD_MS window in a")
            print("     field. Use 12.5 % for the non-hunting background state only.")
        else:
            print("  => GO - ~37 mA available for a slower radar")
    else:
        print("  insufficient data")


if __name__ == "__main__":
    main()
