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
3. **Root cause — signal-to-noise, not tuning.** Real approach slope is
   **~0.1–0.5 dB/s**; sample-to-sample multipath/body-shadow noise is
   **±15–25 dB**, and it is present **even standing still at 1 m** (stand-phase
   swings of 29–51 dB). Detecting a 0.5 dB/s slope in ±20 dB noise requires
   averaging over ~30–40 s — far too laggy for a real-time cue. The stand phase
   is not actually stationary (RSSI drifts while "still"), so "no sign flips
   while standing" is unachievable, not a tuning issue. The advert rate
   (**0.7–1.0/s**; the 50 % scan ceilings at ~2/s) further limits per-second
   averaging. No estimator or retuning fixes this; it is fundamental to a
   2.4 GHz badge worn/held on a person.

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

## What this does / does not affect

- **Does not affect:** the absolute radar bar/ping (proximity-level, works),
  the kill handshake, Reveal, scoring, the backend, the data-survival work
  (§8.10.4, confirmed needed by the A5 wipe test), or the other Phase 0 spikes
  (WiFi/BLE coexistence, scan-duty, 3rd GATT service, 2024 screen blanking).
- **Does affect:** §8.8.2a (retracted), §8.8.6 (drop pitch bend), §8.1
  (`rssi_trend` removed), §5.4 (`TREND_*` / `PING_BEND_PCT` tunables removed),
  the "Finding them" narrative, §11 Phase 0 item 5 (resolved → no-go), §12 RSSI
  risk row (resolved).
