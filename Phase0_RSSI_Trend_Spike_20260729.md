# Phase 0 spike result — RSSI trend ("warmer/colder"): NO-GO

**Date:** 2026-07-29 · **Plan ref:** §8.8.2a, §8.8.6, §"Finding them" · **Decision:** the
trend promise is **retracted**; fall back to the absolute proximity bar. Raw data
preserved in `probes/logs/` (`open.csv`, `open2.csv`, `walk_1..3.csv` + their
`*_markers.csv`). Tools: `probes/rssi_walk_pkg/walk.py` (prompted multi-walk app),
`tools/analyze_rssi.py`, `tools/pull_walks.sh`.

## What was tested

The single most load-bearing untested assumption in the design (plan §8.8.2a):
that a hunter can steer on the **derivative** of BLE RSSI — "warmer or colder" —
shown as a pitch bend on the hunt ping and a trend arrow, computed as
`fast_ewma − slow_ewma` over the received adverts.

**Setup.** Two Fri3d badges (both ESP32-S3): one the **advertiser** (its HSNT
beacon, on a ~1.2 m pedestal, fixed in the wear orientation), one the **logger**
(`walk.py`, empty groups so its own beacon is silent). Open field. The logger
scanned at the app's load-bearing 50 % duty (60 ms / 120 ms window/interval —
explicit, to keep NimBLE's duplicate filter off) and logged every received
advert `(t_ms, rssi)`. The prompted app recorded a timestamped marker per
button press (`start, approach_end, stand_end, retreat_end, lateral_end,
obstacle_end`) so phase windows are exact. Walks followed the §8.8.2a protocol
(approach 40 m→1 m · stand still · retreat · cross laterally · step behind an
obstacle).

**Estimators tried.** (1) the spec'd `fast − slow` EWMA across the tuning grid
`af ∈ {0.04…0.40}`, `as ∈ {0.01…0.10}`, deadband `1…16 dB`; (2) a windowed
least-squares **linear-regression slope** over a trailing 8 s window (the robust
estimator — no EWMA settling lag). Scored as the plan prescribes: fraction of
2 s windows whose sign matches the phase (approach = +, retreat = −, stand =
within deadband), bar **≥ 80 %**.

## Data (5 open-field walks; 4 with the advertiser on the pedestal)

| walk | cond. | rate | max gap | stand RSSI @1 m (stationary) | EWMA best approach | **regression approach / stand / retreat** |
|---|---|---|---|---|---|---|
| `open`   | open field (1st)   | 1.05/s | 15.1 s | −100…−49 (**51 dB**) | 32 % | **58 % / 0 % / 50 %** |
| `open2`  | pedestal           | 0.92/s | 18.9 s | −82…−53 (29 dB)      | 100 %* | **52 % / 0 % / 66 %** |
| `walk_1` | pedestal           | 0.73/s | 11.0 s | −81…−51 (30 dB)      | 55 % | **61 % / 0 % / 80 %** |
| `walk_2` | pedestal           | 0.72/s | 10.4 s | −97…−54 (43 dB)      | 23 % | **61 % / 5 % / 71 %** |
| `walk_3` | pedestal           | 0.79/s | 13.0 s | −81…−51 (30 dB)      | 58 % | **56 % / 0 % / 73 %** |

`*` false positive — see below.

## Conclusions

1. **Reproducible NO-GO.** The robust estimator (regression) is *consistent*
   across all five walks: **approach ≈ 52–61 %** (bar 80 %), **stand ≈ 0–5 %**,
   **retreat ≈ 66–80 %**. None pass approach; none pass stand. Five samples,
   same answer every time.
2. **The EWMA is the unreliable one, not the walks.** The spec'd `fast − slow`
   EWMA's approach score bounced **23 % → 100 %** across walks. Its occasional
   "passes" (e.g. `open2` 100 %) were **false positives** — the regression shows
   the real approach slope there was only ~+0.1 dB/s. The first walk (`open`) was
   *not* botched: its regression approach (58 %) matches the others.
3. **Root cause — signal-to-noise, not tuning.** Two independent halves, both
   measured:

   **(a) The approach is not a ramp.** Median RSSI per fifth of the 40 m→1 m
   approach: `−93 → −88 → −88 → −85 → −74`. From 40 m to roughly 5–10 m there is
   **no usable signal at all** — the whole gain arrives in the last few metres.
   A derivative cue over the part of the walk where a hunter actually needs
   steering is estimating a slope that is not there.

   **(b) The noise is deep and one-sided, not Gaussian.** At a fixed 1 m the
   distribution is a *tight mode* — IQR **4–22 dB**, p90 within ~5 dB of the
   median — punctuated by body-shadow/multipath fades that put **12–28 % of
   samples 15 dB or more below the median**. (An earlier draft of this report
   quoted "±15–25 dB noise" from the stand-phase min–max spread of 29–51 dB;
   that is outlier-driven and mischaracterises the distribution. The correction
   matters, because asymmetric noise calls for an asymmetric filter — see §5.)

   Against that, whole-phase regression slopes are **+0.50…+0.78 dB/s**
   (approach) and **−0.50…−1.38 dB/s** (retreat), sampled at **0.7–1.0
   advert/s** (the 50 % scan ceilings at ~2/s). A trailing-window regression
   only clears the 80 % bar at a **20–30 s window** (pooled across all five
   walks: 8 s → 70 % approach / 21 % stand; 20 s → 89 % / 47 %; 30 s → 100 % /
   89 %) — far too laggy to steer on. No estimator or retuning fixes this; it is
   fundamental to a 2.4 GHz badge worn/held on a person.

## Decision (confirmed 2026-07-29): apply the §8.8.2a fallback

The plan anticipated this outcome. Applied:

- **Drop:** the trend EWMAs (`TREND_ALPHA_FAST/SLOW`), `TREND_DEADBAND_DB`,
  `rssi_trend()`, and the **pitch bend** on the hunt ping (`PING_BEND_PCT`).
- **Keep (all still work — they are absolute proximity):** the LED radar bar,
  the on-screen radar bar, and the hunt ping's **rate** (quickens as you close).
- **Rewrite** the "Finding them" narrative: the radar shows *how close right
  now*, not *getting warmer/colder*. The kill/Reveal/inheritance loop is
  unaffected — it keys off absolute `KILL_RSSI`/`REVEAL_RSSI` thresholds, which
  the data supports fine.

The game stays fully playable: bar fills → ping quickens → LEDs go amber→red as
you near the target. What is lost is the directional warmer/colder cue, which
the badge cannot deliver reliably on-body.

## 5. The fallback, checked against the same data (added 2026-07-29)

The trend result only matters if the thing it falls back to actually works. It
was re-scored from the same five walks rather than assumed:

**Absolute separation is strong and reproducible.** Target at 1 m: median
**−57 dBm**. Same target at 5 m+: median **−83…−86 dBm**. Consistent in all five
walks. A single absolute threshold at −65 dBm separates near from far with
**81 % detection at 1 m and 2.8 % false alarm at 5 m+** on *raw* samples, before
any smoothing. The absolute bar is well-founded.

**But the smoothing has to be asymmetric.** Because the noise is a tight mode plus
one-sided fades (§3b), a symmetric EWMA treats fades as signal:

| smoothing | armed at 1 m (≥ −65) | false-arm at 5 m+ | longest continuous arm-window at 1 m |
|---|---|---|---|
| symmetric EWMA `a = 0.3` (today's) | 74 % | 0 % | **5.6** – 17.3 s |
| asymmetric 0.60 up / 0.08 down | **100 %** | 3 % | **24.5 – 34.5 s** |

The symmetric filter's worst walk holds above `KILL_RSSI` for only 5.6 s against
`KILL_HOLD_MS = 5000` — a 12 % margin, i.e. a kill that fails for no reason the
player can see. Applied to the plan as `rssi_prox` / `PROX_ALPHA_UP` /
`PROX_ALPHA_DOWN` (§8.8.2, §5.4).

**And the bar needs calibrating to −90…−55 dBm** (§8.8.2), because outside that
band the radio separates nothing — see §3a.

## 6. Known limit of this spike

Every walk had the **advertiser on a pedestal** and only the logger worn. In the
real game both badges are worn, so there are **two** bodies in the path. This
makes the trend NO-GO *conservative* — worn-on-worn is strictly noisier, so the
result would not reverse. It does **not** transfer the other way: the absolute
thresholds in §5 above (`KILL_RSSI`, `REVEAL_RSSI`, `FLEE_RSSI`, the bar band)
are validated only in the easier configuration, and they now carry the whole hunt.
**One worn-on-worn walk pair is required before Phase 2 builds the radar**
(§11.1, §12). The tooling already exists — it is one field session.

**But the penalty can be estimated from this same data, and it is small.** Within
each walk the approach has the badge *facing* the target while the retreat has the
walker's own body *in the path*; pairing distance-matched slices of the two measures
one body's shadow directly. Result: **median −4.0 dB, mean −3.1 dB, range −14…+12
(n = 14)**, with **77 %** of the advert rate kept. A second body should therefore cost
a few dB, not the 15–25 dB the raw noise figures might suggest. (Time is the distance
proxy, so this assumes a steady pace — it predicts the walk's outcome, it does not
replace it.) Re-scoring the kill mechanic against a uniform extra penalty
(`tools/analyze_shadow.py`) gives §11.1's pre-committed `KILL_RSSI` table, and turns
up one thing worth stating here:

> At the **expected −4 dB**, the symmetric `a = 0.3` EWMA's worst-walk arm window
> collapses to **1.8 s against a `KILL_HOLD_MS` of 5000 — the kill becomes
> unwinnable** — while the §8.8.2 asymmetric filter still holds **18.6 s**. The
> asymmetric filter is therefore a correctness requirement on the hunt path, not a
> refinement. `REVEAL_RSSI` by contrast is untroubled: still 100 % at 1 m even at
> −16 dB.

## What this does / does not affect

- **Does not affect:** scoring, the backend, the data-survival work (§8.10.4,
  confirmed needed by the A5 wipe test), or the other Phase 0 spikes (WiFi/BLE
  coexistence, scan-duty, 3rd GATT service, 2024 screen blanking).
- **Does affect:** §8.8.2a (retracted), §8.8.6 (drop pitch bend), §8.1
  (`rssi_trend` removed; `prox_filter`/`prox_fraction` added), §5.4 (`TREND_*` /
  `PING_BEND_PCT` removed; `PROX_ALPHA_UP`/`PROX_ALPHA_DOWN` added), §8.8.2 (bar
  band calibration + asymmetric smoothing), the "Finding them" narrative
  (rewritten, not annotated), §11 Phase 0 item 5 (resolved → no-go, with a
  worn-on-worn residual), §12 (RSSI-trend risk resolved; a new pedestal-calibration
  risk row added).
- **Newly load-bearing:** the absolute radar bar/ping and the kill handshake all
  worked before *alongside* the trend; with the trend gone they are the only
  proximity cue, so their thresholds carry more weight than when they were
  written — hence §5 and §6 above.
