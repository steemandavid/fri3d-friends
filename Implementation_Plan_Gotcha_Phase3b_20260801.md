# Implementation Plan — Gotcha Phase 3b: the Duel (§5.3)

**Date:** 2026-08-01 · **Status:** PLANNED, NOT STARTED (handoff — paused before implementation).
**Predecessor:** Phase 3a (Reveal) committed `669db48` (0.11.5, 336 tests); connect path proven.
**Spec:** `Implementation_Plan_Gotcha_20260726.md` §5.3 (flow), §5.2 (GATT), §3.4 (soul), §5.8 (spawn), §5.5 (radio).

## Context / outcome

Phase 3b is the actual gameplay: a hunter connects to its target, writes `ATTACK`; the target runs
an alarm + hold timer; the target either escapes (dodges) or the hold completes and the hunter takes
the target's **soul** (§3.4) as cryptographic kill-proof, inherits the target's target (D10), reports
the kill. Plus **spawn protection** (§5.8). Ends with a real two-badge chase → KILLED → soul verify →
score + inheritance.

## KEY DESIGN PIVOT — escape mechanic (deviation from §5.3)

**`gap_conn_rssi` does NOT exist on this MicroPython build** (verified against the bluetooth module
API — the full method list has no connection-RSSI call). §5.3's "both sides sample RSSI every 100 ms;
rssi < FLEE_RSSI for FLEE_MS = escape" is therefore **not implementable**. Escape becomes
**link-drop**: the victim runs out of BLE range → the connection drops before `KILL_HOLD_MS` elapses →
`DODGED`. §5.3 already lists "link drops before hold elapses" as an escape, so this is the documented
fallback (same posture as the Phase-0 RSSI-trend retraction). `FLEE_RSSI`/`FLEE_MS` go unused; the
link supervision-timeout replaces them.

**Probe-gated enhancement:** implementation step 0 runs one `mpremote exec` to check whether the
*badge firmware* (which predates the docs) exposes `gap_conn_rssi` anyway. If yes, add the granular
escape back; if not, ship link-drop. Either way the rest of the duel is unchanged.

## What's already in place (reuse, don't rebuild)

- `gotcha.py`: `make_soul`/`commitment`/`verify_soul` (§3.4), `score_preview` (§2.1), `truce_active`,
  tunables (`KILL_HOLD_MS`, `FLEE_*`, `DODGE_*`, `INSTANT_KILL_MS`, `ATTACK_COOLDOWN_MS`,
  `SPAWN_PROTECT_S`, `BOUNTY_STREAK`), state fields (`dodges`, `protected_until`, `respawn_at`).
- `gotcha_gatt.GotchaService`: `GOTCHA_SVC` with ATTACK/DUEL/SPOILS/REVEAL already registered;
  `handle_irq` + central-connect tracking + the IRQ-forwarder from BLEProximity.
- `gotcha_app.GotchaController`: `_do_reveal` (the connect template), `request_*`/`cancel_*`,
  `_strip_action` (the D29 ladder — `kill_enabled` currently False), `_gatt_busy`, the tick/drain.
- `contact_exchange.gatt_write` (reusable central write — extend for subscribe/notify/read).
- `fri3d_friends`: buzzer `_buzzer` (PWM, IRQ-safe), `_flash_leds`, `_gatt_busy` LED guard, `_stop_task`.
- Notify pattern: `ble_setup._notify_status` → `ble.gatts_notify(conn, handle, data)`.
- Server: kill/killed_by/dodge/attack_started events already handled (Phase 1).

## Build (Layer A pure → GATT → controller → UI)

**Layer A — `gotcha.py` (+ host tests):**
- `DuelState` — lvgl-free victim state machine (§5.6: reusable by beacon_service in Phase 4).
  `begin_attack(attacker_pid, hold_ms, dodges_left)`; `tick(now_ms, link_up)` → `"hold"|"killed"|"dodged"`;
  `spoils()` → fresh soul + inherited target. Effects via injected callbacks (`on_engaged`,
  `on_dodge`, `on_kill`). Instant-kill when `dodges_left == 0` (hold = `INSTANT_KILL_MS`, no escape).
- `DodgeLedger` — per-(attacker,victim) counting with `DODGE_DECAY_MS` reset; persisted in `state.dodges`.
- `validate_attack(...)` → `ok|busy|no_game|truce|dead|wrong_target|protected|on_cooldown|bounty`.
- Spawn-protect + cooldown helpers; event builders (`attack_started`, `kill`, `killed_by`, `dodge`, `dodged`).

**Layer B — on-badge:**
- `GotchaService`: ATTACK write → `on_attack(parsed, conn)`; DUEL notify via `gatts_notify`; SPOILS
  value written via `gatts_write` when the duel ends (hunter's `gattc_read` then returns it).
- `GotchaController`: hunter `_do_attack()` (clone `_do_reveal` connect, then discover ATTACK+DUEL+SPOILS
  + the DUEL CCCD → write CCCD enable-notify → write ATTACK → wait `GATTC_NOTIFY` ENGAGED → hold bar →
  wait KILLED/DODGED → on KILLED `gattc_read(SPOILS)` + `verify_soul` + `score_preview` + adopt
  inherited target offline + queue `kill`; on DODGED queue `dodge`). Victim: tick `DuelState` from
  `tick()`; `kill_enabled=True`; `request_attack()` + abort; spawn-protect on respawn.
- `fri3d_friends`: alarm = buzzer-PWM siren + ONE red-LED write at start/end (no animation, §5.5);
  "UNDER ATTACK — RUN!" / "ATTACKING <name> + hold bar" / death+respawn screens; X = abort; cancel task.

## Order / testing
0. Probe `gap_conn_rssi` (decides escape detail). 1. Layer A + tests (`tests/test_gotcha.py`).
2. GotchaService handlers. 3. Controller `_do_attack` + victim tick + `kill_enabled`. 4. fri3d_friends UI.
5. Bump MANIFEST; full suite green (336 → ~350+). 6. Two-badge probe (clean, single-app, badge-to-badge
— avoids the WiFi-timing/adv-conflict that blocked host-vs-badge testing in 3a).

## Risks
- `gap_conn_rssi` → link-drop escape (above).
- Multi-step hunter GATT (subscribe CCCD → write → notify → read) > Reveal's one-shot write; clone
  `gatt_write` sequencing + add CCCD-enable + notify-wait + read.
- DUEL notify requires the hunter subscribed (it must write the CCCD) — extra discover/write step.
- Radio arbitration: alarm via buzzer PWM (IRQ-safe) + one LED write; victim can't be attacked while
  attacking (single slot); `_gatt_busy` guard covers `_update_leds`.
- Keep `DuelState` lvgl-free for Phase 4 reuse.
