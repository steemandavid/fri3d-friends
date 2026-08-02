# Implementation Plan — Gotcha Phase 3b: the Duel (§5.3)

**Date:** 2026-08-01 · **Status:** ✅✅ **VERIFIED END-TO-END ON HARDWARE (2026-08-02, 0.11.13).**
Full kill proven host-BLE → badge: connect → discover GOTCHA_SVC → ATTACK → ENGAGED
(hold 5000, dodges_left 1) → 5 s hold → KILLED → SPOILS soul disclosed; "UITGESCHAKELD
… respawn" confirmed on-badge. Only the link-drop DODGE sub-case not yet shown live.
**Predecessor:** Phase 3a (Reveal) committed `669db48` (0.11.5, 336 tests); connect path proven.
**Spec:** `Implementation_Plan_Gotcha_20260726.md` §5.3 (flow), §5.2 (GATT), §3.4 (soul), §5.8 (spawn), §5.5 (radio).

## On-badge bring-up (0.11.6 → 0.11.14) — six real bugs found + fixed

1. **Hunt strip unreachable by the keypad** — `_establish_focus` only added `_menu_btn`;
   now adds `_g_target` when a target shows + renders the `A: AANVALLEN` label.
2. **`duel_session` UUID dict-key miss** — `bluetooth.UUID` isn't reliably hashable, so
   `want.get(data[4])` matched nothing; compare with `==` like `gatt_write`.
3. **`gatts_register_services` EBUSY while advertising** — `ensure_radio` cycles
   `active(False)/active(True)` before its first register; app registers before `begin()`.
4. **`active(True)` on an already-active radio WIPES the whole GATT registration** (a
   registered handle EINVALs right after — verified). `begin()` now guards `if not active()`.
   This was the "victim serves no service / n=5, no ATTACK/DUEL" root cause.
5. **Duel required WiFi** — connectable + reveal/attack `game_running` gated on `game_live`;
   now `_in_game()` (== enrolled, offline-capable). §8.7: WiFi up ~1.7% of the time.
6. **Victim's dense scan suppresses the inbound GATTS-write IRQ** — main loop now pauses
   the scan (`suspend()`) while a central is connected (`being_connected()`), per §5.5/§5.6.

Test harness: `probes/host_duel_hunter.py` (host BLE central drives an ATTACK; connect via
`find_device_by_address` to dodge BlueZ cache misses). Note: this dev box's BT reads the
badges at −95 dBm (marginal); badge-to-badge is the reliable link.

**DEV truce override (0.11.14, revert before camp):** `gotcha.py` DEFAULTS truce → 00:00/00:01
and server game truce set 00:00-00:01, so the night truce doesn't block development. **Pre-camp
checklist:** truce → 22:00/08:00 (badge DEFAULTS + server), `SILENT=True`→`False`, remove the
`duel_log.txt`/`gotcha_dbg.txt` dev writers + the IRQ-counter debug logging.

## Build status (what shipped)

- **Step 0 — `gap_conn_rssi` probe: DONE, absent (verified on-badge 2026-08-01).**
  `dir(bluetooth.BLE)` has only `gap_connect`/`gap_disconnect`, no connection-RSSI call.
  `gattc_read`/`gatts_notify` present. Escape = LINK-DROP, as planned.
- **Layer A (gotcha.py) — DONE.** `build/parse_attack_payload`, `build/parse_duel_payload`
  (+`DUEL_REFUSED`), `build/parse_spoils_payload`, `validate_attack`, `DodgeLedger`,
  `DuelState`, `protection_active/_left_s`, `cooldown_ready`, `attack_started/kill/
  killed_by/dodge` event builders. +26 host tests (`tests/test_gotcha.py`).
- **Layer B (gotcha_gatt.py) — DONE.** ATTACK write→`on_attack(parsed,conn)`, `drain_attacks`,
  `notify_duel` (stages value + notifies), `set_spoils`, `central_conn`; DUEL write-buffer.
- **Layer B (contact_exchange.py) — DONE.** `duel_session` central handshake (connect→
  discover→CCCD subscribe best-effort→write ATTACK→await DUEL notify/poll-read→read SPOILS).
- **Layer B (gotcha_app.py) — DONE.** `_do_attack`/`_handle_duel_result` (verify soul, adopt
  inherited target offline, optimistic score, queue kill), victim `apply_attack`+`_tick_duel`
  +`_on_duel_kill`/`_on_duel_dodge`, `kill_enabled=True`, cooldown-gated `request_attack`,
  `cancel_attack`, UNDER_ATTACK gflag.
- **Layer C (fri3d_friends.py) — DONE.** `_render_duel` + `_siren` (buzzer PWM, IRQ-safe),
  one red-LED write at start / one dark at end, ONDER-AANVAL / AANVALLEN / death banners,
  hunt-strip A → attack/abort, cancel-on-exit. Also wired the previously-unrendered hunter
  message (`reveal_msg_text`) so GOTCHA!/refusals/reveal text now show.

**Remaining:** the live two-badge duel run (step 6) — deploy 0.11.6 to two clean-booted
badges (single app, no stale gotcha.b1), chase → KILLED → soul verify → score+inheritance,
and a link-drop DODGE. Validates the CCCD-at-value+1 assumption + notify delivery.

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
