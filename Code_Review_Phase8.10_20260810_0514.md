# Phase §8.10 Code Review — Versions, kill switches, heartbeat/flush and the fleet nudge

**Document ID:** FRI3DFRIENDS-REVIEW-P8.10-01
**Reviewer:** Code Review Agent
**Date:** 2026-08-10
**Scope:** §8.10.1 (kill switches, 0.11.19) · §8.10.3 + §9.3 (heartbeat + event flush, 0.11.20) · §8.10.3 (broadcast banner + version nudge, 0.11.21)
**FSD Reference:** `Implementation_Plan_Gotcha_20260726.md` (spec + plan in one document)
**Commits reviewed:** `cef6ed1`, `5983702`, `7694f9f`, `1338498` (docs)
**Commit Reviewed (HEAD):** `1338498`
**Test run:** `python3 -m pytest tests/ -q` → **401 passed, 1 warning, 62.93 s** (matches the claim in `7694f9f`)

---

## Verdict: PASS WITH NOTES

The headline of this phase is correct and important: the badge→server event-upload half of
the game loop was genuinely unbuilt on hardware, and `_do_sync` now performs
heartbeat → flush → sync in the §9.3 order, inside the existing online/`_defer_for_bar`
envelope. That closes prior-review finding **D-7 (MAJOR)** from
`Code_Review_Phase0-2_20260731_1803.md`, and it closes it well — the error isolation
(a failed flush never blocks the sync GET), the heartbeat de-dup, the droppable-on-overflow
classification, and the 16-char `app_version` cap are all right, and the new tests pin the
behaviour rather than restating the implementation. The kill switches and the version nudge
are likewise sound in their core logic.

What holds this back from a clean PASS is that two of the three liveness signals the new
heartbeat carries are **wrong at the source**, and both feed server logic that will
misbehave in the field: `target_seen_ago_s` mixes an epoch clock with a monotonic tick
counter (F-1), and `peers_seen` counts *friends* where the server means *anyone nearby*
(F-2). Neither is caught by a test, both were bench-validated only in states where the
wrong value happened to look plausible (`peers_seen = 0`, no target in range), and both are
two-or-three-line fixes. A third gap (F-3) is that the heartbeat omits `quiet`, leaving
§10.4a personal quiet hours — a child-safety feature — non-functional end to end.

With camp imminent, F-1 and F-2 should be fixed and redeployed before badge handout. F-3 is
a judgement call the host should make explicitly rather than by omission.

---

## Table of Contents

1. [Coverage Analysis](#1-coverage-analysis)
2. [Deviation Report](#2-deviation-report)
3. [Plan vs. Implementation](#3-plan-vs-implementation)
4. [Edge Cases & Safety](#4-edge-cases--safety)
5. [Concurrency & Platform Issues](#5-concurrency--platform-issues)
6. [Error Handling](#6-error-handling)
7. [Code Quality](#7-code-quality)
8. [Summary](#8-summary)
9. [Recommendation](#9-recommendation)

---

## Files Reviewed

| File | Purpose in this phase |
|------|-----------------------|
| `app/com.fri3dcamp.fri3dfriends/gotcha.py` | `heartbeat_event()` builder; `version_tuple()`; `bounty_enabled` gate in `validate_attack` |
| `app/com.fri3dcamp.fri3dfriends/gotcha_app.py` | `_do_sync` heartbeat→flush→sync order; `_queue_heartbeat`; `_compute_nudge`; `take_fleet_banner`; `tick()` signature |
| `app/com.fri3dcamp.fri3dfriends/fri3d_friends.py` | Foreground siren `alarm_enabled` gate; battery/peers into `tick()`; `_render_fleet_banner` |
| `app/com.fri3dcamp.fri3dfriends/beacon_service.py` | Background `_on_engaged` alarm gate; background `tick()` with `background=True` |
| `app/com.fri3dcamp.fri3dfriends/MANIFEST.JSON` | 0.11.18 → 0.11.21 |
| `tests/test_gotcha.py` | heartbeat shape, `version_tuple`, bounty downgrade (+8) |
| `tests/test_gotcha_callbacks.py` | `_do_sync` order/dedup/isolation, `_compute_nudge` ×5, `take_fleet_banner` ×3 (+13) |
| `tests/test_beacon_service.py` | alarm kill switch, muted-but-visible (+2) |

Read for contract parity (not under review): `server/gotcha_server/events.py`,
`service.py`, `admin.py`, `config.py`, `state.py`, `tests/badge_sim.py`,
`app/.../ble_proximity.py`.

---

## 1. Coverage Analysis

### §8.10.1 — Per-feature kill switches

| Requirement | Status | Evidence |
|---|---|---|
| Four switches pushed in the sync `config` block | ✅ DONE | `server/gotcha_server/config.py:75-78`; parity test `tests/test_server_plan_parity.py:29` |
| Absent switch means `true` (older-backend safety) | ✅ DONE | `gotcha.py:310-311` defaults; every read site uses `cfg.get(<k>, True)` (`gotcha.py:782, 982`, `beacon_service.py:343`, `fri3d_friends.py:824`); tests pop the key and re-assert |
| `reveal_enabled` gated | ✅ DONE (pre-existing) | `gotcha.py:782` |
| `alarm_enabled` mutes the siren, keeps the badge visibly under attack | ⚠️ PARTIAL | `beacon_service.py:339-344` and `fri3d_friends.py:824` gate the **siren** only; the reveal chirp, dodge relief chirp and death tone are ungated — see **F-4** |
| `bounty_enabled` | ✅ DONE | `gotcha.py:982` — a stray bounty write downgrades to a plain attack |
| `training_enabled` | ✅ N/A | Ships `False`; no code path (Phase 6), documented |

### §8.10.2 — Wire-format discipline

Not a code deliverable this phase. Spot-checked and still honoured: HSNT `ver` untouched;
`GameConfig.from_sync` and `apply_sync` remain defensive parses that ignore unknown keys
(`gotcha.py:1520-1540`); no version gate exists on server event ingest.

### §8.10.3 — Seeing the fleet, and nudging it

| Requirement | Status | Evidence |
|---|---|---|
| Heartbeat sent once per `SYNC_S` | ✅ DONE | `gotcha_app.py:341-352` |
| Event queue actually flushed | ✅ DONE — **the critical fix** | `gotcha_app.py:346-350`; closes prior D-7 |
| §9.3 order heartbeat → flush → sync | ✅ DONE | asserted in `test_do_sync_queues_heartbeat_then_flushes_then_syncs` |
| `app_version` rides the heartbeat; admin histogram current | ✅ DONE | `gotcha.py:1200-1202`; bench-validated (pid 1004) |
| `battery` on the heartbeat | ✅ DONE | both callers read `BatteryManager.get_battery_percentage()` |
| `background` flag distinguishes app-open from boot responder | ✅ DONE | `beacon_service.py:495-497` passes `background=True`; `admin.py:443` splits on it |
| `groups` snapshot on the heartbeat | ✅ DONE | see **F-9** for the empty-list edge |
| `peers_seen` | ⚠️ **WRONG SEMANTICS** | counts friends only — **F-2** |
| `target_seen_ago_s` | ❌ **BROKEN** | epoch-vs-ticks clock mix — **F-1** |
| `quiet` (server re-check, §10.4a; `events.py:557`) | ❌ MISSING | **F-3** |
| Sync response carries `min/latest version` + `broadcast` | ✅ DONE | `service.py:512-514`; parsed at `gotcha_app.py:363-366` |
| `< min` → prominent `UPDATE NODIG` **screen** | ⚠️ PARTIAL | delivered as a banner line, not a screen — deferred, documented |
| `≥ min, < latest` → one dismissible line | ✅ DONE | `_compute_nudge`, `gotcha_app.py:409-424` |
| Absent floor → never nag | ✅ DONE | tested (`test_compute_nudge_no_server_floor_is_none`) |
| Unreadable own version → never nag | ✅ DONE | `version_tuple("?") == ()`, tested |
| `broadcast` rendered in the existing banner widget | ✅ DONE | `fri3d_friends.py:866-881` |
| `broadcast` capped at 120, treated as text only | ✅ DONE | capped both sides; `pages.py` escapes |
| One-shot per change, no re-spam | ✅ DONE (with **F-6**) | `take_fleet_banner`, `gotcha_app.py:426-438` |
| **`< min` stops hunting; victim responder keeps running** | ❌ **NOT IMPLEMENTED** | deferred — see **D-2** |

### §8.10.4 — Data survival

Step 1 shipped in 0.11.17 (out of scope here). Step 3 ("flush before updating") remains
deferred and now has a natural attach point that did not exist before — see **D-3**.

---

## 2. Deviation Report

### D-1 · MINOR (INFO) · Field names differ from the plan text
The plan (§8.10.3) specifies `min_app_version` / `latest_app_version` on the sync response.
Both sides implement `app: {min_version, latest_version}` (`service.py:512`,
`gotcha_app.py:418-419`). Client and server agree, so nothing breaks; the *plan* is the
stale artefact. Correct the plan text so a future reader doesn't "fix" the code to match.

### D-2 · MAJOR · The stay-killable hunting gate is not implemented
§8.10.3 is unambiguous that a badge below `min_app_version` "stops **hunting** (no attack,
no reveal) but its **victim-side responder keeps running**". Today `_compute_nudge` produces
a string and nothing else — a badge below the floor keeps hunting with whatever incompatible
code motivated the floor in the first place. The commit message defers this deliberately and
argues the banner ranks higher, which is fair for the *nudge*; but the gate is the part that
makes `min_app_version` a control rather than a suggestion. Setting a floor mid-camp
currently does nothing except print a line. Either build the gate or drop `min_version` from
the admin UI so the host isn't misled into thinking they have a lever.

### D-3 · MINOR · §8.10.4 step 3 (flush before updating) still unbuilt, but now cheap
The rationale for deferring was "no UI to attach to yet". The fleet banner is that UI. When
`_compute_nudge` returns `UPDATE NODIG`, forcing `_next_sync_ms = 0` and showing
`Even synchroniseren voor je update...` would turn the one genuinely unrecoverable loss (the
unsent queue) into no loss. Two lines, and it is the stated purpose of the section.

### D-4 · MINOR · `alarm_enabled` is narrower than "the nuisance-noise mute"
See F-4.

---

## 3. Plan vs. Implementation

The plan file carries its own BUILD STATUS markers (added in `1338498`), so this comparison
is unusually direct.

| Plan item | Planned | Actual | Status |
|---|---|---|---|
| §8.10.1 badge-side reads for all four switches | 4 switches honoured, absent = on | 3 honoured + `training_enabled` N/A; `alarm_enabled` covers siren only | ✅ substantially, ⚠️ F-4 |
| §8.10.3 report the version | `app_version` on heartbeat | Done, bench-validated | ✅ |
| §8.10.3 heartbeat itself | one per `SYNC_S`, §9.3 order | Done | ✅ |
| §8.10.3 broadcast banner | existing banner widget, 120 cap | Done | ✅ |
| §8.10.3 version nudge (soft line) | dismissible line | Done (transient banner, auto-hides) | ✅ |
| §8.10.3 `UPDATE NODIG` screen | prominent full screen | Banner line | ⚠️ DEFERRED (documented) |
| §8.10.3 stay-killable hunting gate | `< min` stops hunting | Not built | ❌ DEFERRED (documented) — **D-2** |
| Files modified | not enumerated in advance | 4 source + manifest + 3 test files | ✅ tightly scoped, no scope creep |
| Testing strategy | host tests + bench validation | 401 host tests green (verified by this review); bench on 9de4 for each of the three commits | ✅ |
| Implementation order | switches → heartbeat/flush → UI | Followed exactly (0.11.19 → .20 → .21), one bench-validated deploy per step | ✅ exemplary |

The BUILD STATUS markers are honest about what was deferred, including the ⚠️ admission that
the flush path was unbuilt. There are **no undocumented deviations**. The defects found below
are implementation bugs, not silent scope changes.

---

## 4. Edge Cases & Safety

### F-1 · CRITICAL · `target_seen_ago_s` mixes epoch milliseconds with monotonic ticks
**`app/com.fri3dcamp.fri3dfriends/gotcha_app.py:398-404`** · §9.3, §10.1, §3.2

```python
peer = self.ble.peer_by_pid(tp) if tp is not None else None
if peer is not None and peer.get("last_seen_ms") is not None:
    target_ago = max(0, int((int(time.time()) * 1000 -
                             int(peer["last_seen_ms"])) // 1000))
```

`peer["last_seen_ms"]` is written as `time.ticks_ms()` (`ble_proximity.py:711, 725`) — a
monotonic uptime counter that wraps at 2³⁰ ms on MicroPython. `int(time.time()) * 1000` is
wall-clock epoch milliseconds (~8.4 × 10¹¹ on the MicroPython 2000 epoch, ~1.8 × 10¹² on the
Unix epoch). Subtracting one from the other is meaningless.

**Failure scenario.** Hunter's badge has its target in range right now (`last_seen_ms` ≈
uptime, say 300 000). Computed `target_ago` ≈ 838 000 000 s. On ingest,
`events.py:568-570` does `note_seen(target_pid, ts - min(ago, MAX_EVENT_AGE_S))`, clamping to
48 h ago, and `service.note_seen` is `last_seen_at = MAX(COALESCE(last_seen_at,0), ?)` —
which only moves forward, so the write is a **no-op**. Net effect: the single best piece of
evidence that a target is awake is discarded on **every** heartbeat, precisely when it is
most informative. §10.1 stall detection and the §3.2 dormancy splice lose their primary input;
a player who is visibly present all afternoon drifts toward `stale` and can be spliced out of
the ring. The badge simulator passes `target_seen_ago_s` in directly
(`tests/badge_sim.py:146`), so `tests/test_server_api.py:435,710` exercise the server path
with correct values and never see this — no test covers `_queue_heartbeat`'s computation.

**Fix (3 lines):**
```python
target_ago = max(0, time.ticks_diff(time.ticks_ms(), int(peer["last_seen_ms"])) // 1000)
```
and add a test that a peer seen `N` ms ago yields `N // 1000`.

### F-2 · MAJOR · `peers_seen` counts friends only, not nearby badges
**`fri3d_friends.py:718-720`** and **`beacon_service.py:491-494`** · §9.3, §9.5, §10.1

Both callers use `len(self._gc.ble.current_peers())`. `current_peers()` deliberately filters
out every peer with `shared_id is None` (`ble_proximity.py:809-828`) — it is the *friends UI*
accessor, and its docstring says so. A badge standing in a crowd of fifty strangers reports
`peers_seen = 0`.

Two server behaviours read it with the opposite meaning:
- `events.py:576-577`: `if peers: note_seen(pid, ts)` — the "standing in a populated place"
  sighting bump, explicitly there to stop a present player drifting to `stale`. Dead for
  anyone not surrounded by their own friends. This compounds F-1: both sighting channels fail
  together.
- `admin.py:528-531`: the §9.5 lonely-kill anti-cheat report selects kills where
  `COALESCE(p.peers_seen, 99) <= 1`. With friends-only counting, most badges will report 0–1,
  so most legitimate kills land on the suspicion list and the report becomes noise.

The bench validation recorded `peers_seen NULL→0` on a badge with no peers at all, which is
exactly the state where the bug is invisible.

**Fix:** count the raw peer table. There is no public accessor today (`has_peers()` is also
friends-only, `ble_proximity.py:831-837`), so add e.g. `def peer_count(self): return
len(self._seen)` alongside it and call that. Keep `current_peers()` untouched — the friends UI
depends on the filter.

### F-3 · MAJOR · The heartbeat omits `quiet`, so §10.4a personal quiet hours are inert
**`gotcha.py:1182-1204`** (`heartbeat_event`) · §10.4a (D25)

`_h_heartbeat` reads `ev.get("quiet")`, clamps it via `state.clamp_quiet` and persists
`quiet_from`/`quiet_to` (`events.py:552-561`). No badge code ever puts `quiet` in an event or
any other request body (`enroll_body` has no such field either). The channel exists on the
server and has no sender.

The flow is in fact inverted: the server always emits `me.quiet`, defaulting to the camp
truce (`service.py:480, 505`), and the badge overwrites its local value with it —
`self.quiet = (payload.get("me") or {}).get("quiet") or self.quiet`
(`gotcha_app.py:361`) and `self.d["quiet"] = q if isinstance(q, dict) else None`
(`gotcha.py:1531-1532`). Since the server's value is always a dict, a personal window a
player set in `config.json` via the phone page or the on-badge editor is **replaced by the
camp truce on the first sync**.

**Failure scenario.** A parent sets 20:00–08:00 on a child's badge. It holds until the next
sync (≤ 5 min), then reverts to 22:00–08:00. The badge sirens at 20:45 in a family tent —
the exact outcome §10.4a exists to prevent. Server-side, `state.in_quiet` and the dormancy
pause also never see the personal window.

The overwrite half is pre-existing; the missing sender is this phase's, because this phase
built the heartbeat and matched it to `BadgeSim.heartbeat` (which also omits `quiet`) rather
than to the server handler. Add `quiet=self.quiet` to the `heartbeat_event` call and to the
builder, and make the sync read-back not clobber a locally-set window.

### F-4 · MINOR · `alarm_enabled` mutes the siren but not the other game noises
`_on_spotted`'s reveal chirp (`beacon_service.py:329-335`), the dodge relief chirp
(`:346-352`), the death tone (`:355-361`) and the foreground `_sting` on reveal
(`fri3d_friends.py:795-799`) are all ungated. If the host flips `alarm_enabled` off at 03:00
because badges are waking the campsite, chirps continue. They respect the *local* `sound`
setting, which is the player's control, not the host's kill switch. Gate all game-initiated
audio on `alarm_enabled` — the switch is described in the plan as "the nuisance-noise mute",
not "the siren mute".

### F-5 · MINOR · `version_tuple` comparison is length-sensitive
`(0, 11) < (0, 11, 0)` is True in Python. A host who types `min_version: "0.11"` into the
admin form puts every `0.11.x` badge below the floor and shows the whole camp `UPDATE NODIG`;
`latest_version: "0.12"` nags a `0.12.0` badge forever. The nudge is currently harmless
(D-2), but it becomes a real lockout the moment the hunting gate is built. Pad both tuples to
equal length with zeros before comparing.

### F-6 · MINOR · A cleared-then-reissued broadcast is silently swallowed
`take_fleet_banner` (`gotcha_app.py:430-433`) latches `_shown_broadcast` and never clears it
when `self.broadcast` becomes `None` (the admin "Wissen" button, `pages.py:235`). Host sends
"Spel gepauzeerd", clears it, then sends "Spel gepauzeerd" again an hour later — nothing is
shown. Reset `_shown_broadcast = None` whenever the incoming broadcast is falsy.

### F-7 · MINOR · Nudge and broadcast are not read from persisted state
`apply_sync` already stores `broadcast` and `app` into `gotcha.json`
(`gotcha.py:1537-1541`), but `_compute_nudge`/`self.broadcast` read only the live payload
(`gotcha_app.py:363-366`). A badge that boots with WiFi down — the normal case, ~98% per §8.7
— shows neither the standing broadcast nor the nudge until a sync lands. Reading the
persisted copy at `configure()` time costs nothing and removes the duplicate storage.

### F-8 · INFO · `alive` is hardcoded `True`
`heartbeat_event` always emits `"alive": True` regardless of `state.alive`. The server's
handler ignores the field, so nothing misbehaves — but it is a field that says something
false, and the next person to read it will believe it.

### F-9 · INFO · The heartbeat now exercises the open D-47 group-wipe path every `SYNC_S`
`heartbeat_event` includes `groups` whenever it is a list, and `[]` is a list; the server's
`set_groups` is DELETE-then-insert, so an empty list wipes the player's groups
(prior review D-47, still open). Correct when the player genuinely has no groups, but any
transient path that leaves `self.groups == []` — a partial config load in the boot service,
for instance — now wipes them server-side on the next sync instead of never. Cheap guard:
send `groups` only when non-empty, or fix D-47 server-side to ignore an empty list.

### F-10 · INFO (positive) · Omitting `commitment` from the heartbeat is the right call
The server's `_h_heartbeat` accepts a `commitment` and the surrounding comment presents it as
a needed safety net for an offline respawn. The badge does not send one — which is correct,
because prior review **C-2 (CRITICAL)** showed a heartbeat-borne commitment let any victim
repudiate any kill. The server-side fix is in place (`_rotate_commitment` now fills only when
absent, `events.py:383-388`), so sending it would be safe today, but the fresh commitment
already rides the `killed_by` event, which is a `KEEP_TYPE` and is mirrored to `/prefs` since
0.11.17. Not sending it is defence in depth. Worth a comment in `heartbeat_event` so nobody
"completes" the shape later.

---

## 5. Concurrency & Platform Issues

No new problems. Specifically checked:

- **Nothing new blocks the OS asyncio loop.** `_queue_heartbeat` is pure computation over an
  in-memory list; `flush_events` is the existing coroutine with its `await self._yield()`
  after the POST. The known project constraint (BLE work must run as an asyncio task on the OS
  loop, never a blocking call) is respected.
- **The §5.4 coexistence budget holds.** The new traffic is inside the existing
  `enrolled and online and not _syncing and not _defer_for_bar(now)` gate
  (`gotcha_app.py:242-245`), so there is still no radio contention mid-chase. The flush adds
  one POST per sync window — within budget.
- **`_syncing` is the mutex** and `_do_sync` sets it before the heartbeat and clears it in
  `finally`, so the dedup-then-add sequence cannot interleave with itself. Correct.
- **Forced-sync paths** (`_next_sync_ms = 0` after a kill, death, or rejoin —
  `gotcha_app.py:944, 1095, 1118`) now also emit a heartbeat. Desirable, and the dedup keeps
  it at one queued heartbeat regardless.
- **Queue pressure.** Heartbeats are correctly excluded from `KEEP_TYPES`, so they are the
  first thing dropped at `MAX_QUEUE = 40`, and a queue full of kills refuses the heartbeat
  rather than dropping a kill (`gotcha.py:1294-1317`). Right priority.
- **Background/foreground duplication.** Both the Activity and the boot service drive a
  `GotchaController` with the same pid, but never concurrently (the service releases the radio
  when the app takes the foreground), so there is no double-heartbeat race.
- `from mpos import BatteryManager` inside the boot service's tick is a repeated import in a
  hot-ish path; MicroPython caches modules in `sys.modules`, so the cost is a dict lookup. Fine.

---

## 6. Error Handling

Solid, and better than the surrounding code in places.

- Flush and sync are wrapped **separately** (`gotcha_app.py:346-350`), so a failed flush never
  costs the badge its config refresh. This is the right call given WiFi is down ~98% of the
  time, and it is directly tested (`test_do_sync_flush_failure_does_not_block_sync`).
- `flush_events` removes only the server's `accepted` uuids and is idempotent on retry
  (`gotcha.py:1803-1826`) — a lost POST re-uploads whole and the server dedups.
- Battery and peer reads are individually `try`-wrapped in both callers, so a `BatteryManager`
  failure degrades to `battery=None` (omitted from the event) rather than killing the tick.
- `take_fleet_banner` is called inside a `try/except: return` in the renderer
  (`fri3d_friends.py:874-878`), so a banner bug cannot take down the UI loop.

One gap: `_queue_heartbeat` mutates `state.queue` without a `state.save()`. If the flush then
fails, the heartbeat exists only in RAM and is lost to a power pull. Harmless (a heartbeat is
only ever the latest truth) but it means the persisted queue and the live queue diverge
between syncs — worth one line of comment so it reads as deliberate.

---

## 7. Code Quality

Consistent with the established style: dense §-referenced comments explaining *why*, defensive
`cfg.get(k, default)` reads, small pure builders in `gotcha.py` with the wiring in
`gotcha_app.py`. Three substantive notes:

1. **Test isolation — `_nudge_controller` permanently monkeypatches a module global.**
   `tests/test_gotcha_callbacks.py` does `gotcha_app._app_version = lambda: my_version` with no
   teardown. Every subsequent test in the session sees the last patched version. It is benign
   today only because the `_do_sync` tests happen to run first; add a `monkeypatch` fixture
   before that ordering changes and someone loses an afternoon.
2. **`_compute_nudge` takes the whole payload** just to read `payload["app"]`. Passing the
   `app` dict (or the two version strings) would make it a pure function and remove the
   `isinstance` dance at `gotcha_app.py:414-415`.
3. **`_app_version()` re-opens and JSON-parses `MANIFEST.JSON` on every call** — every
   heartbeat and every nudge computation. Once per `SYNC_S`, so the cost is irrelevant; a
   module-level cache would be one line and removes a filesystem dependency from the sync path.
   (The docstring's reasoning for not hardcoding the literal is right and should stay.)

Naming, separation of concerns and the banner-priority ordering (duel > arrival > fleet, with
the fleet banner deliberately *not* consuming its one-shot while a higher-priority banner owns
the strip) are all clean.

---

## 8. Summary

| Category | Critical | Major | Minor | Info |
|---|---|---|---|---|
| Spec conformance | 0 | 1 (D-2) | 3 (D-1, D-3, D-4) | 0 |
| Plan conformance | 0 | 0 | 0 | 1 (all deferrals documented) |
| Correctness | 1 (F-1) | 2 (F-2, F-3) | 2 (F-5, F-7) | 2 (F-8, F-9) |
| Safety | 0 | 1 (F-3, child-safety impact) | 1 (F-4) | 0 |
| Concurrency | 0 | 0 | 0 | 0 |
| Error handling | 0 | 0 | 1 (unsaved queue mutation) | 0 |
| Code quality | 0 | 0 | 3 | 0 |

**Prior-review findings addressed by this phase:** D-7 (MAJOR, badge never heartbeats/flushes)
— **closed**. C-2 (CRITICAL, heartbeat commitment repudiation) — server fix confirmed in
place, and the badge correctly does not send the field. D-47 (MINOR, empty `groups` wipes) —
still open server-side and now reachable every sync (F-9). D-50 (MINOR, unclamped `quiet` on
the `configure`/`_do_sync` path) — still open and directly related to F-3.

---

## 9. Recommendation

**GO to the next phase, conditional on three fixes before badges are handed out.**

The phase did the most valuable thing available: it found and fixed a silent, total failure of
the event-upload path that would have made the entire game unscorable at camp, and it did so
in small bench-validated increments with real test coverage. That work is sound and should
ship.

**Must fix before handout** (all small, all in code this phase touched):

1. **F-1** — `target_seen_ago_s` clock domain. One line (`time.ticks_diff`) plus a test.
   Without it, §10.1 stall detection and §3.2 dormancy run blind and can splice present
   players out of the ring.
2. **F-2** — `peers_seen` must count all nearby badges, not friends. Add
   `BLEProximity.peer_count()` and use it in both callers. Without it, the second sighting
   channel is also blind and the §9.5 anti-cheat report is noise.
3. **F-3** — decide `quiet` explicitly. Either send it on the heartbeat and stop the sync
   read-back clobbering a locally-set window, or accept that personal quiet hours do not exist
   this year and remove the setting from the phone page and the on-badge editor so no parent
   believes they set it. Silently reverting to 22:00 is the worst of the three options.

**Should fix, cheap:** F-4 (gate all game audio on `alarm_enabled`), F-5 (pad version tuples),
F-6 (reset the broadcast latch), and the test-isolation issue in §7.1.

**Host decision, not a code fix:** D-2. If `min_app_version` is to remain in the admin UI
during camp, the stay-killable hunting gate needs building — as it stands the field is a
control that does nothing. If it is not going to be built before Friday, say so in the plan and
grey the field out.
