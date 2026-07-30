#!/usr/bin/env python3
"""analyze_shadow.py -- body-shadow headroom for the absolute kill thresholds.

Two jobs, both about the §11 item 5 residual (the Phase 0 walks put the advertiser
on a PEDESTAL; the real game wears both badges, so there are two bodies in the
path, not one):

  1. MEASURE the one-body shadow penalty from the existing walks. Within a walk,
     the approach has the badge facing the target and the retreat has the walker's
     own body in the path. Slicing both phases by fraction and pairing slice k of
     the approach with slice N-1-k of the retreat matches them by distance, so the
     median difference is a one-body shadow measurement.

     Caveat, and it is why the worn-on-worn walk is still required: this uses
     TIME as a distance proxy, so it assumes a roughly constant walking pace.

  2. PROJECT the kill mechanic forward. Apply a uniform extra penalty to every
     sample and re-score: what fraction of the time at 1 m is the badge armed,
     what is the worst walk's longest continuous arm window (must clear
     KILL_HOLD_MS), and what does a threshold change cost in false arming at 5 m?
     Produces the pre-committed KILL_RSSI lookup table in §11 item 5.

  python3 tools/analyze_shadow.py [logdir]
"""
import statistics as st
import sys
import os

LBL = ["open", "open2", "walk_1", "walk_2", "walk_3"]
KILL_HOLD_S = 5.0
HOLD_BAR = 2 * KILL_HOLD_S      # want 2x the required hold in the WORST walk
FA_BAR = 0.15                   # tolerable false-arm fraction at 5 m+
KILLS = (-65, -68, -71, -74, -77, -80)
PENALTIES = (0, 4, 8, 12, 16)
N_SLICES = 5


def load(p):
    t, r = [], []
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        a, b = line.split(",")
        t.append(int(a) / 1000.0)
        r.append(int(b))
    return t, r


def marks(p):
    m = {}
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        a, b = line.split(",")
        m[b.strip()] = int(a) / 1000.0
    return m


def asym(rs, up=0.60, dn=0.08):
    """The §8.8.2 rssi_prox filter: fast attack, slow decay."""
    out, v = [], None
    for x in rs:
        a = up if (v is None or x > v) else dn
        v = float(x) if v is None else (1 - a) * v + a * x
        out.append(v)
    return out


def ewma(rs, a=0.3):
    out, v = [], None
    for x in rs:
        v = float(x) if v is None else (1 - a) * v + a * x
        out.append(v)
    return out


def measure_shadow(d):
    deltas, rates = [], []
    rows = []
    for lbl in LBL:
        t, r = load(os.path.join(d, lbl + ".csv"))
        m = marks(os.path.join(d, lbl + "_markers.csv"))
        a0, a1 = m["start"], m["approach_end"]
        r0, r1 = m["stand_end"], m["retreat_end"]
        for k in range(N_SLICES):
            aa = a0 + (a1 - a0) * k / N_SLICES
            ab = a0 + (a1 - a0) * (k + 1) / N_SLICES
            j = N_SLICES - 1 - k
            ra = r0 + (r1 - r0) * j / N_SLICES
            rb = r0 + (r1 - r0) * (j + 1) / N_SLICES
            A = [x for tt, x in zip(t, r) if aa <= tt < ab]
            R = [x for tt, x in zip(t, r) if ra <= tt < rb]
            if len(A) < 3 or len(R) < 3:
                continue
            dlt = st.median(R) - st.median(A)
            deltas.append(dlt)
            rates.append((len(A) / (ab - aa), len(R) / (rb - ra)))
            rows.append((lbl, 40 - 39 * k / N_SLICES, 40 - 39 * (k + 1) / N_SLICES,
                         st.median(A), st.median(R), dlt))
    return rows, deltas, rates


def score(d, pen, kill, filt=asym):
    near, far, holds = [], [], []
    for lbl in LBL:
        t, r = load(os.path.join(d, lbl + ".csv"))
        m = marks(os.path.join(d, lbl + "_markers.csv"))
        v = filt([x - pen for x in r])
        best, cur = 0.0, None
        for tt, vv in zip(t, v):
            if m["approach_end"] <= tt <= m["stand_end"]:
                near.append(vv >= kill)
                if vv >= kill:
                    if cur is None:
                        cur = tt
                    best = max(best, tt - cur)
                else:
                    cur = None
            elif m["retreat_end"] <= tt <= m["lateral_end"]:
                far.append(vv >= kill)
        holds.append(best)
    frac = lambda L: (sum(L) / len(L)) if L else 0.0
    return frac(near), frac(far), min(holds)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "probes/logs"

    print("=" * 78)
    print("1. ONE-BODY SHADOW, measured from the existing pedestal walks")
    print("=" * 78)
    print("   approach slice = badge faces target; matched retreat slice = body in path")
    rows, deltas, rates = measure_shadow(d)
    print("\n%-8s %12s %9s %9s %9s" % ("walk", "dist band", "facing", "shadowed", "delta dB"))
    for lbl, d0, d1, a, r, dl in rows:
        print("%-8s %11s %9.0f %9.0f %+9.0f" % (lbl, "%.0f-%.0fm" % (d0, d1), a, r, dl))
    ar = [x[0] for x in rates]
    rr = [x[1] for x in rates]
    print("\n   POOLED penalty: median %+.1f dB, mean %+.1f dB, range %+.0f..%+.0f (n=%d)" % (
        st.median(deltas), st.mean(deltas), min(deltas), max(deltas), len(deltas)))
    print("   POOLED advert rate: %.2f/s facing vs %.2f/s shadowed = %.0f %% kept" % (
        st.median(ar), st.median(rr), 100 * st.median(rr) / st.median(ar)))
    print("   NOTE: time is the distance proxy here -- assumes a steady pace. The")
    print("   worn-on-worn walk is still required; this only predicts its outcome.")

    print()
    print("=" * 78)
    print("2. WHY THE FILTER MUST BE ASYMMETRIC (§8.8.2), at KILL_RSSI = -65")
    print("=" * 78)
    print("%8s %8s %10s %14s" % ("penalty", "filter", "armed@1m", "worst hold"))
    for pen in PENALTIES:
        for nm, f in (("asym", asym), ("ewma", ewma)):
            n, fa, h = score(d, pen, -65, f)
            flag = "  KILL FAILS" if h < KILL_HOLD_S else ""
            print("%+8d %8s %9.0f%% %13.1fs%s" % (-pen, nm, n * 100, h, flag))

    print()
    print("=" * 78)
    print("3. PRE-COMMITTED KILL_RSSI TABLE (asymmetric filter)")
    print("=" * 78)
    print("   bar: worst walk's longest continuous arm window >= %.0fs (2x KILL_HOLD_MS)" % HOLD_BAR)
    print("        and false-arm at 5 m+ <= %.0f %%\n" % (FA_BAR * 100))
    print("%8s | %s" % ("penalty", " ".join("%7d" % k for k in KILLS)))
    for pen in PENALTIES:
        hs, fs = [], []
        for kill in KILLS:
            n, fa, h = score(d, pen, kill)
            hs.append(h)
            fs.append(fa)
        print("%+8d | %s   hold s" % (-pen, " ".join("%7.1f" % h for h in hs)))
        print("%8s | %s   false-arm %%" % ("", " ".join("%7.0f" % (f * 100) for f in fs)))
        rec = None
        for kill in KILLS:
            n, fa, h = score(d, pen, kill)
            if h >= HOLD_BAR and fa <= FA_BAR:
                rec = (kill, h, fa)
                break
        print("%8s -> %s\n" % ("", ("KILL_RSSI = %d  (worst hold %.1fs, false-arm %.0f %%)"
                                    % (rec[0], rec[1], rec[2] * 100)) if rec else
                               "NO threshold clears the bar -- cut KILL_HOLD_MS instead"))


if __name__ == "__main__":
    main()
