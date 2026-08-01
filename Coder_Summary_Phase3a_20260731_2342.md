# Coder Run Summary: Phase 3a — The Reveal (Gotcha)

**Date:** 2026-07-31 23:42
**Phase:** 3a (Reveal, plan §5.7) — first half of Phase 3
**Plan File:** `/home/john/.claude/plans/temporal-munching-badger.md`

## What Was Implemented

The Reveal: the disambiguator that makes a hunter's target flash gold + chirp + show
SPOTTED when the hunter presses A within `REVEAL_RSSI`. Built first (per §11) because it
is the shortest possible GATT interaction (write → ack → disconnect → flash) and proves the
connect path the duel (Phase 3b) will share.

- **Layer A (pure, host-tested)** in `gotcha.py`: `build/parse_reveal_payload` (compact
  JSON `{g,h,t,n}`), `decide_strip_action` (the §5.7 D29 escalating ladder, attack branch
  gated off until 3b), `reveal_ready` (per-hunter cooldown), `validate_reveal` (responder
  verdict — deliberately NO protection/cooldown check, per §5.7/§5.8), `spotted_active`,
  `reveal_event`/`revealed_event` (log-only, NOT keep-types).
- **Gotcha GATT server** (`gotcha_gatt.py`, new): `GotchaService` registers `GOTCHA_SVC`
  with all four characteristics now (ATTACK/DUEL/SPOILS stubbed for 3b, REVEAL live) so the
  handle layout is locked. Lvgl-free, injected `on_reveal` callback, IRQ-safe queue +
  `drain_reveals`, central-connect tracking for the radio-busy guard.
- **BLEProximity**: `addr` added to the peer entry + `addr_for_pid()`; a connectable beacon
  mode (`set_connectable`, plumbed through begin/set_game/resume); `_irq` forwards non-scan
  events to an injected Gotcha dispatch hook (§5.6).
- **ContactExchange**: `attach_gotcha` + position-based `bind_handles` (robust to which
  services are attached); a reusable `gatt_write` central-write coroutine (clones the proven
  `_run_client` connect path) for the hunter.
- **GotchaController**: `strip_action`/`request_reveal`/`_do_reveal` (hunter) +
  `apply_reveal`/`is_spotted`/`spotted_text` (target) + radio-busy getters; drains inbound
  reveals in `tick`; enables connectable when enrolled ∧ game-live.
- **fri3d_friends.py**: attaches `GotchaService`, routes the BLE IRQ, registers the GATT
  services after `ble.begin`, makes the hunt strip the focusable A-action row, adds the
  `_gatt_busy` LED-skipping guard in `_loop`, renders the SPOTTED gold flash + chirp, and
  cancels an in-flight reveal on stop.
- MANIFEST bumped **0.11.3 → 0.11.4**.

## Files Created / Modified
| File | Change |
|------|--------|
| `app/.../gotcha.py` | +§1i Reveal pure logic (payload, ladder, cooldown, validation, spotted, events) |
| `app/.../gotcha_gatt.py` | NEW — GotchaService GATT server (4 chars, REVEAL handler) |
| `app/.../ble_proximity.py` | addr field + addr_for_pid; connectable mode; IRQ forwarder |
| `app/.../contact_exchange.py` | attach_gotcha + bind by position; reusable gatt_write |
| `app/.../gotcha_app.py` | controller reveal methods (hunter + target), drain, connectable |
| `app/.../fri3d_friends.py` | service attach, IRQ route, GATT register, A-press, busy guard, SPOTTED, cancel |
| `app/.../MANIFEST.JSON` | 0.11.3 → 0.11.4 |
| `tests/test_gotcha.py` | +9 tests (payload, ladder, cooldown, validation, spotted, events) |
| `tests/test_ble_proximity.py` | +3 tests (addr_for_pid, connectable flag, IRQ forwarder) |

## Test Results
`python3 -m pytest tests/ -q` → **333 passed** (was 321; +12). `py_compile` clean on every
touched app module (incl. the lvgl-importing `fri3d_friends.py`). No server changes
required (`reveal`/`revealed` shipped in Phase 1).

## Deviations from the Plan
None of substance. One scope note: the **lvgl hunt-strip focus routing** (which object A
fires on, and whether the Menu button vs. the strip gets the press) is wired but **flagged
for on-badge verification** — it cannot be host-tested and the drawer-fix focus system is
sensitive. The `request_reveal()` API is the clean entry point the probe can also drive
directly.

## Outstanding Work / Follow-ups
- **The two-badge probe (Layer-B exit gate) — NOT yet run.** Hardware IS available (3
  Espressif badges by-id; backend `running`, 4 players). Deploying 0.11.4 to two badges +
  driving a reveal is hard-to-reverse + iterative, so it is staged for a focused session
  with the user's go-ahead. **Risks to verify on hardware:** (1) the connectable HSNT beacon
  (does NimBLE accept it with the game block? Flags-AD/name-budget cost?); (2) the
  register-services-after-begin order; (3) the lvgl A-on-strip focus routing; (4) the
  IRQ-forwarder + gatt_write IRQ handoff around suspend/resume.
- Out-of-band (user/field, non-blocking): §11.1 worn-on-worn walk (gates `KILL_RSSI` for the
  *duel*, not Reveal); infra asks A7/A8; tap-verify consent on a fresh badge.
- Next code phase: **3b — the duel** (wire ATTACK/DUEL/SPOILS handlers on the already-
  registered characteristics; flip `kill_enabled`).
