# Phase 0 spikes 1, 3, 4, 6 — results

**Date:** 2026-07-30 · **Plan ref:** §11 Phase 0 items 1/3/4/6, §8.7 levers 1–3, §5.2
**Outcome:** #3 **GO** · #1 **GO with a scheduling rule** · #4 **GO mechanically, NO for the
hunt path** · #6 **PARTIAL — lever 1 does not exist on 2024**

Raw data in `probes/logs/coex_*.{json,csv}`. Tooling: `probes/coex_pkg/coex.py`
(one-shot on-badge probe), `tools/run_coex.sh` (host-side condition driver),
`tools/analyze_coex.py`, `tools/coex_load_server.py`,
`tools/spike6_display_sleep.py`, `tools/recover_badge_port.py`.

## Setup

Three badges: **1cdb…** the scanner under test, **9070…** (`Tarpon 41b`) and
**3485…** (2024, `Badge2024lijn`) both advertising their HSNT beacon from the boot
service at the launcher. Desk distances, so absolute rates are higher than the
field walks in `Phase0_RSSI_Trend_Spike_20260729.md` — what matters here is the
*ratio* between conditions, measured back to back in one sitting.

Six conditions, 60 s each, two scan duties × three WiFi states. WiFi state and
traffic load are driven from the **host**, not from inside the probe — see
"Two traps" below. "busy" is a continuous `ping -i 0.01 -s 500` flood; the badge
answered **6038 of 6100** (50 % duty) and **5958 of 6223** (12.5 % duty), so the
load is real two-way radio work, ~90 packets/s each way.

## Spike 3 — a third GATT service fits: **GO**

`gatts_register_services((exchange, setup, gotcha))` in **one** call returns three
handle groups:

| service | characteristics | handles |
|---|---|---|
| exchange (`6e4000 10`) | 2 | `[16, 18]` |
| setup (`6e4000 20`) | 6 | `[21, 23, 25, 27, 30, 32]` |
| gotcha (`6e4000 30`) | 4 | `[35, 37, 40, 42]` |

`gatts_set_buffer(SPOILS, 512, True)` also succeeds. §5.2's constraint — build the
Gotcha characteristics inside `ContactExchange._ensure_services()` and hand handles
over with a `bind_handles()` method — is correct as written and needs no change.

## Spikes 1 and 4 — the numbers

| duty | WiFi | adverts/s | vs WiFi-off | median gap | worst gap |
|---|---|---|---|---|---|
| **50 %** (60/120 ms) | off | **3.66** | — | 0.16 s | 1.6 s |
| 50 % | associated, idle | 3.01 | **82 %** | 0.25 s | 2.3 s |
| 50 % | associated, transferring | 1.53 | **42 %** | 0.50 s | 6.7 s |
| **12.5 %** (30/240 ms) | off | **0.93** | — | — | 4.6 s |
| 12.5 % | associated, idle | 0.83 | **89 %** | — | 7.9 s |
| 12.5 % | associated, transferring | 0.30 | **32 %** | — | 14.9 s |

### Spike 1 — WiFi + BLE coexistence: **GO, with a scheduling rule**

1. **Associated but idle is nearly free**: 82 % / 89 % of the WiFi-off detection
   rate. Keeping the link up costs little scan performance.
2. **Actively transferring is expensive**: 42 % / 32 % — a **58–68 % loss** while
   data is moving. It is a fairly uniform slowdown (median inter-advert gap 0.16 →
   0.50 s at 50 % duty) rather than long stalls; there was one 5.3 s outlier.
3. **Presence never flaps.** The worst gap anywhere, including the worst combined
   case, is **14.9 s against `EVICT_MS` of 30 s**. No peer was ever evicted.

**The architecture does not need revisiting** — the plan's trigger for that was
coexistence *badly* degrading the scan, and idle association does not. What the
data does demand is a **scheduling rule**, because a sync during a hunt halves the
radar's update rate at exactly the wrong moment:

> **Do not sync while the hunt bar is lit.** Defer the §6.2 sync until the radar
> is below `PING_FROM_SEG`, or until the hunt screen is closed. §8.7's budget
> already assumes WiFi is raised only ~1.7 % of the time, so deferring costs
> nothing; syncing *during* the endgame costs the player the kill.

Caveat: the load here is heavier than a real periodic signed sync, so 42 %/32 % is
a worst case for the duration of a transfer, not a steady state.

### Spike 4 — scan duty 50 % → 12.5 %: **GO mechanically, NO for the hunt path**

1. **The duplicate filter stays OFF.** The stream stays steady at 12.5 %; nothing
   collapses after ~3 s. This **confirms the plan's reading of `DESIGN.md` §3**:
   the load-bearing part is *passing explicit `interval_us`/`window_us` at all*,
   not the specific 50 % ratio. That hypothesis is now tested, not assumed.
2. **The cost is exactly proportional**: 3.66 → 0.93 adv/s is **25 % kept**, i.e.
   precisely the 12.5/50 duty ratio. There is no efficiency to be found — you buy
   ~37 mA with a 4× slower radar, linearly.
3. **But it is too slow for the hunt.** On this desk 12.5 % gives 0.47 adv/s per
   peer. The field walks measured only **0.7–1.0 adv/s per peer at 50 % duty**, so
   in a field 12.5 % lands near **0.2/s — one sample every 4–5 s** — and with WiFi
   transferring, 0.15/s, **one sample every ~7 s**. `KILL_HOLD_MS` is 5000: at that
   rate a hunter cannot accumulate a sustained-proximity window at all, and the
   §8.8.2 `rssi_prox` filter has nothing to filter.

**Recommendation:** adopt 12.5 % duty **only in the non-hunting background state**,
which §3.3 says is most of the time, and keep 50 % whenever a hunt is live (bar at
or above `PING_FROM_SEG`, or the hunt screen open). That captures most of the
~37 mA without breaking the kill. Wire it into the §8.7 lever-4 battery ladder
rather than making it a global constant.

## Spike 6 — 2024 screen blanking: **PARTIAL, and lever 1 as written does not exist**

Measured on the 2024 badge (`3485…`), from the running firmware rather than docs:

1. **There is no backlight or power GPIO.** The live driver instance
   (`mpos.board.fri3d_2024.st7789.ST7789._displays[0]`) reports
   `_backlight_pin = None`, `_power_pin = None`, and both `get_backlight()` and
   `get_power()` return **−1**. `set_backlight()`/`set_power()` are no-ops.
   `DESIGN.md` §1 is confirmed empirically.
2. **The panel is write-only.** `RDDPM (0x0A)`, `RDDID (0x04)` and `RDDST (0x09)`
   all read back `0xFF` — no MISO on this wiring, so panel state cannot be
   queried. Any blanking has to be open-loop.
3. **The sleep commands do work, and are reversible.** Over
   `display_bus.tx_param(cmd)` (single-argument form): `DISPOFF (0x28)`,
   `SLPIN (0x10)`, `SLPOUT (0x11)`, `DISPON (0x29)` are all accepted without
   error, and LVGL survives — `screen_active().invalidate()` redraws correctly and
   the launcher comes back intact.
4. **Observed result: the screen goes black but the backlight keeps glowing** (both
   in `DISPOFF` and in the deeper `SLPIN`). Confirmed visually, 2026-07-30.

**So lever 1 does not deliver what §8.7 hoped on the 2024.** The ~50 mA in the
budget table is "display **+ backlight**", and the backlight LEDs are the bulk of
it. A panel command stops the panel's own logic and source drivers; it cannot
switch off a backlight with no GPIO behind it. What remains is an unquantified
panel-logic saving — and it cannot be quantified here, because the badge has no
current sensing (`BatteryManager` exposes voltage only). **Measure with the inline
USB meter in Phase 6** alongside the other five scenarios.

Two things are still worth having:
- A genuinely black screen is a real **UX state** for the §8.7 battery ladder at
  10 %, and for not broadcasting your hunt to whoever is standing next to you.
- Whatever the panel-logic saving turns out to be, it is free and reversible.

**Incidental finding for lever 3:** ping RTTs to the badge ranged **38–672 ms**
with a median far above the LAN floor — WiFi power save is evidently **already
active**. Lever 3 ("verify whether `WifiService` sets `wlan.config(pm=...)`") is
therefore probably already banked, not an available ~65 mA. Confirm with the meter
before counting it.

## Two traps that cost real time (worth knowing before Phase 1)

1. **`json.dump(obj, open(path, "w"))` silently loses everything on MicroPython.**
   The file object is never flushed or closed, so the buffer dies with it and you
   get a 0-byte file. It destroyed a complete 9-minute run. Always
   `f = open(...); json.dump(obj, f); f.flush(); f.close()`.
2. **Never toggle WiFi from inside a measurement Activity.** `WifiService`
   (re)connecting takes the **foreground**, which fires `onPause` on your activity
   — so any `TaskManager` task gated on a `running` flag is silently killed
   mid-run. That ate the first attempt at these six conditions. Set WiFi from the
   host REPL *before* launching the probe; `mpos.AppManager.start_app(fullname)`
   launches it without touching the badge. (`temporarily_enable()` also takes a
   required positional arg; `temporarily_disable()` takes none.)

Also: a badge that has been scanning hard can wedge its USB-CDC completely — the
`/dev` node enumerates but raw reads return 0 bytes. `tools/recover_badge_port.py`
does a `USBDEVFS_RESET` and brings it back; use it sparingly.

## Phase 0 status after this

| # | spike | status |
|---|---|---|
| 1 | WiFi + BLE coexistence | ✅ GO + scheduling rule (no sync during a live hunt) |
| 2 | Sync durability | ⚠️ partial — heap + on-device RFC 4231 HMAC done; the 1000-sync soak needs the Phase 1 backend |
| 3 | Third GATT service | ✅ GO |
| 4 | Scan duty reduction | ✅ GO mechanically; 12.5 % for background only, 50 % while hunting |
| 5 | RSSI trend | ✅ resolved NO-GO (`Phase0_RSSI_Trend_Spike_20260729.md`); worn-on-worn threshold check still owed before Phase 2 |
| 6 | 2024 screen blanking | ⚠️ PARTIAL — commands work, backlight cannot be cut; quantify in Phase 6 |

Everything blocking is answered. The two remaining items (the 1000-sync soak, the
worn-on-worn walk) are each gated on work that comes later — the backend, and
Phase 2's radar respectively — and neither blocks starting Phase 1.
