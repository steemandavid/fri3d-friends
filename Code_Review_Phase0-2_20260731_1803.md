# Phase 0–2 Code Review — Gotcha (Assassin) game

**Document ID:** FRI3D-REVIEW-P0-2-001
**Reviewer:** Code Review Agent
**Date:** 2026-07-31
**Scope:** Phase 0 (hardware spikes) · Phase 1 (backend) · Phase 2 (badge-side game)
**FSD Reference:** `Implementation_Plan_Gotcha_20260726.md` (rev. 5, ~3050 lines)
**Commit Reviewed:** `80568a9` — "Phase 2 close-out: consent verified on-badge; demo deferred; Phase 2 code-complete"
**Test suite at review time:** `313 passed` in 7.8 s (0 failed, 0 skipped)

---

## Verdict: MAYBE — do not start Phase 3 until the five CRITICALs are closed

Phase 0 is the strongest work in the project and I could not fault it: every published
number reproduces from the raw data with the shipped analysis tools, the NO-GO on the
RSSI trend is honest and correctly propagated into the design, and the two binding
scheduling rules it produced are actually honoured in the shipped code. Phase 1's
architecture is genuinely well-judged — "derive, don't schedule", the `lives` table, the
interval algebra, the badge-simulator harness that doubles as an interop test — and
Phase 2's pure layer (wire format, admission, LRU, the asymmetric proximity filter,
persistence, request signing) is careful, defensive and well tested.

The problems are not architectural. They cluster in three write paths that the test
suite does not exercise: `events.py`'s kill handlers, the admin dashboard's HTML
rendering, and the `fri3d_friends.py` ↔ `ble_proximity.py` seam where a game-admitted
peer (a peer with **no shared group** — which by D9 is exactly what a target is) meets
code written when every peer had one. **Five CRITICAL defects, all reproduced on this
commit**, three of which make a player permanently unkillable and one of which disables
the Phase 2 headline feature — the LED radar bar — precisely when the game is happening.

The reason none of these were caught is consistent and worth stating plainly: **every
full-stack kill test posts exactly one kill per batch after forcing the target pointer
by hand, and the two-badge field test used two badges that share a group.** Both
shortcuts remove the conditions under which these bugs exist.

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

| File | LOC | Purpose |
|------|-----|---------|
| `Phase0_RSSI_Trend_Spike_20260729.md` | — | Spike 5: RSSI trend NO-GO + fallback validation |
| `Phase0_Coex_GATT_Duty_Display_20260730.md` | — | Spikes 1/3/4/6: coexistence, GATT, scan duty, display |
| `tools/analyze_rssi.py` / `analyze_shadow.py` / `analyze_coex.py` | 704 | Phase 0 analysis; re-run during this review |
| `server/gotcha_server/service.py` | 482 | Sync payload, enrollment, reconcile |
| `server/gotcha_server/events.py` | 544 | Event ingest — kill, killed_by, dodge, heartbeat, optout |
| `server/gotcha_server/scoring.py` | 255 | §2 scoring, streak, boards, hit list |
| `server/gotcha_server/ring.py` | 313 | §3.2 ring build, splice, inherit |
| `server/gotcha_server/state.py` | 355 | §9.6 derived state model, decay, outage detection |
| `server/gotcha_server/admin.py` | 602 | §9.4 admin endpoints + auth |
| `server/gotcha_server/pages.py` | 317 | Player card + admin dashboard |
| `server/gotcha_server/auth.py` / `crypto.py` | 292 | §6.2 signed transport |
| `server/gotcha_server/db.py` / `config.py` / `app.py` / `main.py` / `clock.py` / `groups.py` | 872 | Schema, tunables, routes, entry point |
| `app/…/gotcha.py` | 1202 | Badge: config, truce, filter, radar, ping, queue, state, signing, sync |
| `app/…/gotcha_app.py` | 373 | `GotchaController` — lifecycle, sync scheduling, consent, opt-out |
| `app/…/ble_proximity.py` | 761 | HSNT v2 beacon, `admit_peer`, `evict_lru`, `rssi_prox` |
| `app/…/fri3d_friends.py` | 2823 | UI hooks: radar, LED bar, ping, menu, consent screen |
| `app/…/beacon_service.py` | 194 | Boot beacon service (unchanged this phase) |
| `tests/` (11 files) | ~3300 | 313 tests incl. `badge_sim.py` interop harness |

**Verification method.** Every CRITICAL and every MAJOR marked ✅ below was reproduced
by me on this commit — server findings against the real ASGI app through the `BadgeSim`
harness, badge findings by executing the shipped functions on the host. Findings marked
⚠️ are code-level readings I confirmed by reading the source but did not execute.
Throwaway repro scripts were written to the session scratchpad; **no project file was
modified, created or deleted by this review** other than this report.

---

## 1. Coverage Analysis

### Phase 0 — hardware spikes

| # | Spike | FSD | Status | Notes |
|---|---|---|---|---|
| 1 | WiFi/BLE coexistence | §11.1 | ✅ **DONE** | Reproduced: 3.66 → 3.01 → 1.53 adv/s at 50 % duty. Worst gap 14.9 s vs `EVICT_MS` 30 s. |
| 2 | Sync durability (heap, TLS, HMAC, 1000-sync soak) | §6.2 | ✅ **DONE** | Both halves closed; RFC 4231 vectors on-device; heap flat. |
| 3 | Third GATT service | §5.2 | ✅ **DONE** | Handle groups `[16,18] [21,23,25,27,30,32] [35,37,40,42]`, 512-byte buffer OK. |
| 4 | Scan duty 50 % → 12.5 % | §8.7 | ✅ **DONE** (analysis) / ⚠️ **NOT IMPLEMENTED** (ladder) | The *binding* half is satisfied — 50 % is unconditional, so a hunt is never starved. The ~37 mA background saving is unbanked (see P0-4). |
| 5 | RSSI trend | §8.8.2a | ✅ **DONE — NO-GO, fallback applied** | Reproduced across all five walks. Trend, pitch bend and `rssi_trend()` correctly removed everywhere. |
| 5r | Worn-on-worn threshold walk | §11.1 | ❌ **NOT DONE** | Pre-committed fallback (`KILL_RSSI = −68`) also not applied — see D-1. |
| 6 | 2024 screen blanking | §8.7 lever 1 | ✅ **DONE — PARTIAL** | Honest write-up; correctly deferred to Phase 6 measurement. |

**Phase 0 assessment: PASS.** I re-ran all three analysis tools against the committed
raw logs. Every published figure reproduces exactly, including the §11.1 pre-committed
`KILL_RSSI` table and the asymmetric-vs-symmetric arm-window comparison. The spike
reports are unusually honest — the RSSI report explicitly retracts an earlier
mischaracterisation of the noise distribution in its own §3(b), and the coexistence
report flags that lever 1 "as written does not exist". This is the standard the rest of
the project should be held to.

### Phase 1 — backend

| FSD area | Status | Evidence |
|---|---|---|
| §9.2 player endpoints (`/v1/enroll`, `/v1/sync`, `/v1/events`) | ✅ DONE | All present, signed, tested |
| §9.3 event types (9 of 9 parsed) | ⚠️ PARTIAL | All 9 handled; `dodge` mis-attributes (D-13), `attack_started` writes but is never read (D-16) |
| §9.4 admin endpoints | ✅ DONE (+1 extra, documented) | 14 routes, all gated by `require_host()` |
| §9.5 anti-cheat | ⚠️ PARTIAL | Soul verification defeated (C-2); cooldown never re-checked (D-16); Sybil detector disabled by config (D-9) |
| §9.6 derived state model | ✅ DONE | Four statuses derived, no cron; precedence tested |
| §2.1/2.2/2.4 scoring + decay | ⚠️ PARTIAL | Idempotent and correct in mechanism; anchor bug on queued kills (D-11) |
| §2.3 group boards | ⚠️ PARTIAL | Ranks by points; §2.3 says Σ `total_kills` (D-19) |
| §3.2 ring | ⚠️ PARTIAL | Build/splice/inherit correct in isolation; bounty kills orphan players (D-8) |
| §3.4 soul commitment | ❌ **BROKEN** | Commitment is not binding within a life (C-2) |
| §6.2 signed transport | ✅ DONE | Full-request-target signing, nonce replay cache, constant-time compare |
| §5.4 live retuning | ⚠️ PARTIAL | Works, but accepts any value of any type (D-10) |
| §13 consent/privacy (schema) | ✅ DONE | No age/cohort, no location, no `witnesses[]` — verified against the schema |

### Phase 2 — badge

| FSD area | Status | Evidence |
|---|---|---|
| §4 HSNT v2 wire format | ✅ DONE | Byte-for-byte per spec; `OVERHEAD = 12` reproduces the plan's arithmetic; reserved-bit rejection present |
| §4 widened admission + pinned LRU | ✅ DONE (pure) / ❌ **CRASHES** (integrated) | `admit_peer`/`evict_lru` are correct and tested; the resulting `shared_id=None` peer crashes the UI (C-5) |
| §8.8.2 asymmetric proximity filter | ✅ DONE | §11.1's correctness requirement met — the symmetric EWMA does **not** ship on the hunt path |
| §8.8.2 radar bar (screen + LED) | ⚠️ **PARTIAL** | Both exist; they use **different mappings** and disagree by up to 3 segments (D-20) |
| §8.8.6 hunt ping | ⚠️ PARTIAL | Built; silent floor off by one segment, rate ladder unreachable (D-21) |
| §8.8.3 whole-strip states | ⚠️ PARTIAL | Truce→dark works; `solid_frame` (dead/protected) is written, tested and **never called** |
| §8.8.7 contact lost (`KWIJT`) | ❌ MISSING | No helper, no state, no test |
| §7 connectivity check | ⚠️ PARTIAL | Works, but polled not event-driven, no 1.1.1.1 fallback, `online` never invalidated (D-24) |
| §8.2 persistence | ✅ DONE | Atomic temp+rename, correct MicroPython flush/close, corrupt-file degradation — with one gap (D-27) |
| §8.3 networking / signing | ✅ DONE | Matches the server byte-for-byte; proven over 1000 on-badge round trips |
| §8.4 UI — status chip, target strip | ✅ DONE | Live on hardware |
| §8.4 UI — Gotcha screen, focusable hunt strip | ❌ MISSING | Two flat menu rows instead; Phase 3's A-ladder has no host widget |
| §8.4 demo mode | ✅ DONE (colour) / ⚠️ PARTIAL (sound) | Built and offered from the consent screen; sound half moot under `SILENT = True` |
| §13 first-run consent | ✅ DONE | Built once and hidden, focus ladder correct, X = "Niet meedoen" |
| §13 exit on the badge | ⚠️ **PARTIAL** | The button works locally; **the server never learns** (D-6) |
| §9.3 heartbeat cadence | ❌ MISSING | `flush_events` and the heartbeat are never called from anywhere in `app/` |
| §5.4 `HUNT_SYNC_DEFER` | ✅ DONE (defer) / ❌ (cap) | The Phase 0 rule is honoured; the mandated cap is not (D-5) |
| §8.9 Dutch | ✅ DONE (substance) / ⚠️ (glyphs) | All Gotcha strings Dutch; three non-ASCII chars will render as boxes (D-28) |
| §8.10.4 update survival | ❌ NOT BUILT | Correctly scoped to Phase 5, but the wipe is now *verified*, so the risk is live today |

---

## 2. Deviation Report

Severity: **CRITICAL** (data loss, game-breaking, or security compromise) · **MAJOR**
(spec deviation or probable bug) · **MINOR** (improvement) · **INFO** (observation).

### CRITICAL

#### C-1 · CRITICAL · Stored XSS on the admin dashboard hands the game to any player ✅ *verified*
**`server/gotcha_server/pages.py:275-289`**, sources at **`app.py:74`** and **`events.py:460-466`**
**FSD §9.4, §9.5**

The player card's script defines and uses an `esc()` helper (`pages.py:121`). **The admin
dashboard's script does not** — it has only `j()` and `stat()`. Four sinks interpolate
attacker-controlled strings straight into `innerHTML`:

```js
275:  Object.entries(f.versions).map(([k,v])=>'<span class="pill">'+k+': '+v+'</span>')  // app_version
281:  (g.broadcast ? '<span class="pill">omroep: ' + g.broadcast + '</span>' : '')
285:  L.total.map((e,i)=>'<tr>…<td>'+e.name+' #'+e.pid+'</td>…')                        // display_name
288:  L.hitlist.map(x=>'<span class="pill warn">'+x.name+' #'+x.pid+…)                  // display_name
```

`display_name` is capped at 32 chars but never sanitised (`app.py:74`). Worse,
`app_version` is capped at 16 chars **on enrollment only** (`app.py:91`) — the heartbeat
handler stores it with **no cap at all**:

```python
# events.py:460-466
app_version = ev.get("app_version")
db.execute("UPDATE players SET … app_version=COALESCE(?, app_version) WHERE pid=?",
           (…, app_version if isinstance(app_version, str) else None, pid))
```

**Failure scenario.** This is a hacker camp and a flashable badge is the stated threat
model. An enrolled player sends one signed heartbeat with an arbitrary-length
`app_version` containing `<img src=x onerror=…>`. The version histogram includes *every*
enrolled badge, so no rank or kill is needed. `tick()` re-runs every 5 s
(`pages.py:309`), there is no CSP, and the script runs same-origin with the
`gotcha_admin` cookie — it can drive every §9.4 endpoint: end the game, kick 700
players, void kills, call a permanent truce, or exfiltrate `/v1/admin/export`.

The irony: `html_escape` exists at `pages.py:62-66` and its docstring asserts it covers
*"the one place a user-supplied string is interpolated into a page"*, which is false;
`test_server_api.py:1113` tests exactly that one place and misses the other four.

**Fix:** copy the player page's `esc()` into the admin script and wrap `k`, `v`,
`g.broadcast`, `e.name`, `x.name`; cap `app_version` in `events.py:466` with `[:16]`.

---

#### C-2 · CRITICAL · The soul commitment is not binding — any victim can repudiate any kill ✅ *reproduced*
**`server/gotcha_server/events.py:326-339`** (`_rotate_commitment`) → **`service.py:125-130`** (`start_life`)
**FSD §3.4**

`start_life` is `INSERT … ON CONFLICT(pid, life_id) DO UPDATE SET commitment=excluded.commitment`,
and `_rotate_commitment` calls it with the player's **current** `life_id`. A
heartbeat-supplied commitment therefore **overwrites the live commitment in place**. The
`lives` table keeps history *across* lives but not *within* one — which is exactly the
guarantee §3.4 needs.

Reproduced on this commit:

```
a holds v's real soul; kill queued (HUNT_SYNC_DEFER guarantees it is queued mid-chase)
v sends heartbeat {"commitment": <fresh>}   -> {'accepted': [...], 'rejected': []}
a flushes the genuine kill                  -> {'rejected': [{'reason': 'bad_soul'}]}
RESULT victim=active
```

`_rotate_commitment`'s own docstring asserts the opposite — *"rotating cannot invalidate
a proof that is still in someone's offline queue, so a victim gains nothing by rotating
early"*. That is true across lives and false within one, and the code takes the
within-a-life path. This defeats the entire §3.4 anti-cheat mechanism: any player can
become unkillable by heartbeating a fresh commitment.

**Fix:** only fill a commitment that is absent —
`… DO UPDATE SET commitment=excluded.commitment WHERE lives.commitment IS NULL` — which
still serves the legitimate post-respawn case, where `apply_death` left it `NULL`.

---

#### C-3 · CRITICAL · A voided kill row permanently blocks every future kill on that life — reachable with zero malice ✅ *reproduced*
**`server/gotcha_server/events.py:157-165`** (dup lookup) and **`events.py:225-235`** (void insert)
**FSD §3.4, §9.6, §10.2**

`_h_killed_by` inserts a **voided** kill row keyed `(victim_pid, reported_life)` when
`_check_kill_legal` rejects the pairing — correct so far, the victim is spared. But
`_h_kill`'s duplicate lookup does **not** filter `voided=0`, and `kills` has
`UNIQUE (victim_pid, victim_life_id)`. The voided row occupies the victim's life slot
forever; every later genuine kill on that life is refused `already_dead`; and because
the victim never dies, `life_id` never advances.

Reproduced with **no cheating anywhere** — just an ordinary offline victim:

```
assassin kills v legitimately        -> v dead, life 0 -> 1, respawn scheduled
+40 min, v respawns                  -> v active, life 1, protected 90 s
v's queued killed_by finally lands   -> kills row (victim=1001, life=1, voided=1,
                                                   void_reason='protected')
a NEW hunter's fully legitimate kill
   on life 1 with v's CURRENT soul   -> {'rejected': [{'reason': 'already_dead'}]}
RESULT victim=active — and permanently unkillable
```

`RESPAWN_S` is 30 min and §10.3 is built around hours-long offline queues, so this will
happen on the first afternoon at camp. Because the badge drops `rejected` uuids from its
queue, the new hunter's kill is lost permanently.

Two contributing errors: the missing `voided=0` filter, and `reported_life`
(`events.py:211-213`) resolving from `players.life_id` rather than from the `lives` row
whose `[started_at, ended_at)` contains `at`.

**Fix:** add `AND voided=0` to the dup lookup, and resolve `reported_life` from `lives` by `at`.

*(Note: I also tested the deliberate variant — a badge nominating an arbitrary
non-hunter as its killer. That is handled correctly: the row is voided as
`not_your_target`, points 0, victim stays active. The malicious path only becomes
dangerous because of the missing `voided=0` filter above.)*

---

#### C-4 · CRITICAL · A handler exception commits a half-applied kill; `db.rollback()` is dead code ⚠️ *verified by inspection*
**`server/gotcha_server/events.py:83-89`**, **`db.py:292-294`**
**FSD §9.6**

The `except Exception` arm records the event as *rejected* and **commits**, with no
rollback. `_apply_kill` performs five writes across four tables before its own
`db.commit()`, so a failure between them is made permanent. I confirmed by `grep` that
`Database.rollback` has **zero callers anywhere in the server**, and that `db.lock`'s
docstring — *"Held for the whole of a request's read-modify-write (see routes)"* — is
also false: no route acquires it.

Result of a mid-handler failure: the assassin's score is banked, nobody dies, an orphan
`kills` row is left behind (which then triggers C-3), and the event is marked rejected
so the badge drops it and never retries.

Today this is only *latent* because every route is `async def`, so all DB work is
serialised on one event-loop thread. Converting a single handler to plain `def` would
move it to Starlette's threadpool and make the shared connection, `cur.lastrowid` in
`_insert_kill`, and cross-request `commit()` genuinely racy.

**Fix:** `db.rollback()` as the first statement of both `except` arms in `ingest_batch`
(safe — `reconcile` and each prior event have already committed), plus a middleware-level
rollback on unhandled exceptions.

---

#### C-5 · CRITICAL · A game-admitted peer crashes the render tick, silently killing the LED radar bar ✅ *reproduced*
**`app/…/fri3d_friends.py:1138`** (`_fill_row`) ← **`ble_proximity.py:733-747`** (`current_peers`) ← **`fri3d_friends.py:223`** (`_sig_from_id`)
**FSD §4, §8.8, §8.4**

`admit_peer` now admits the Gotcha target with **no shared group** (D9: the target is
almost never a group-mate), so its `_seen` entry carries `shared_id: None`
(`ble_proximity.py:643`). `current_peers()` emits that `None` as the third tuple element.
`_fill_row` then calls `self._color_for_gid(gid)` **outside any try/except**, and
`_sig_from_id(None)` evaluates `None * 137.508`:

```
peer = ('Target', None, None, -50, 1000)
CRASH: TypeError unsupported operand type(s) for *: 'NoneType' and 'float'
```

The six detail rows are built once in `_build_idle` (`fri3d_friends.py:1568-1569`) and
merely hidden, so `_refresh_nearby` fills them **every tick regardless of panel
visibility**. The exception is swallowed by the main loop's blanket
`except Exception: pass` (`fri3d_friends.py:1905-1906`).

**Failure scenario.** The moment your target comes into BLE range, every subsequent line
of the tick is skipped for as long as they remain in range:

```
1882  self._gc_tick(now)              ← runs
1883  self._render_gotcha()           ← runs  (this is why the field test looked fine)
1884  self._hunt_ping(now)            ← runs
1886  self._refresh_nearby()          ← RAISES HERE
1892  self._update_leds(now)          ← SKIPPED  ← the §8.8 LED radar bar
1893  self._refresh_battery(now)      ← SKIPPED
1894  self._refresh_clock(now)        ← SKIPPED  (clock freezes)
1895  self._refresh_setup(now)        ← SKIPPED
1896  self._resync_time(now)          ← SKIPPED  (NTP stops)
1897  banner auto-hide                ← SKIPPED  (banners stick forever)
1899  backlight dim                   ← SKIPPED
```

**The Phase 2 headline deliverable — the LED radar bar — is dead in exactly the
situation it exists for.** The on-screen radar keeps working because `_render_gotcha`
runs *before* the exception, which is precisely why the two-badge hardware test passed:
badges 9070 and 1cdb share a group, so `gid` was never `None`.

**Fix (one line):** `col = self._color_for_gid(gid) if gid is not None else COL_MUTED`,
and make `_sig_from_id` `None`-tolerant as `_led_friend_frame:1702` already is.

---

### MAJOR — Phase 0

#### D-1 · MAJOR · `KILL_RSSI` ships −65, but §11.1 pre-committed −68 because the walk was skipped ✅ *verified*
**`app/…/gotcha.py:274`** and **`server/gotcha_server/config.py:17`** · **FSD §11.1**

§11.1: *"If the walk is not done: build Phase 2's radar anyway, but ship `KILL_RSSI` at
**−68** rather than −65."* The §11 Phase 2 close-out still lists the worn-on-worn walk
as outstanding. Both defaults ship −65.

**Nuance, in fairness to the implementer:** I re-ran `tools/analyze_shadow.py`, and its
own decision rule selects **−65** at both the 0 dB and the expected −4 dB penalty (worst
hold 18.6 s, 0 % false-arm). Shipping −65 is therefore defensible on the evidence. But
§11.1 is a *pre-committed* decision, and the point of pre-committing is not to relitigate
it after the fact. It is also live-tunable, so this is a one-field change either way.

**Also worth correcting in the plan:** §11.1 says shipping −68 costs *"3 % false arming
on pedestal data"*. The table it cites gives **10 %** at −68 and 3 % at −65 — the 3 % is
the −65 figure. Whichever value is chosen, the plan's stated cost is wrong.

#### D-2 · MINOR · The 12.5 % background scan duty is not implemented ✅ *verified*
**`app/…/ble_proximity.py:69`** · **FSD §8.7 lever 2/4, Phase 0 item 4**

`SCAN_INTERVAL_US = 120000` is unconditional. **The binding half of the Phase 0 rule is
satisfied** — 50 % is always used, so a hunt is never starved — but the ~37 mA background
saving is unbanked. Phase 0 said to wire this into the lever-4 battery ladder, which is
§8.7/Phase 6 work, so the omission is defensible; flagging it so it is not forgotten.

#### D-3 · MINOR · `analyze_rssi.py`'s verdict line states the opposite of its own conclusion ✅ *verified*
**`tools/analyze_rssi.py`** — the NO-GO banner reads *">> NO-GO: a single (af,as,deadband)
triple meets the >=80% bar in every condition"*. It should read *"**no** single triple
meets…"*. A reader skimming the tool output could take it as a GO. The written report is
correct; only the tool string is inverted.

#### D-4 · INFO · The 12.5 %-busy condition rests on 18 total adverts ✅ *verified*
`probes/logs/coex_busy_30_240` yields n=9 adverts per peer over 60 s. The conclusion it
drove (*keep 50 % while hunting*) is the conservative one, so thin data endangers
nothing — but the "0.30 adv/s / 32 %" figure should not be quoted as precise.

### MAJOR — Phase 1 (backend)

#### D-5 · MAJOR · `HUNT_SYNC_DEFER_MAX_S` is defined on both sides and enforced on neither ✅ *verified*
**`app/…/gotcha_app.py:150-158`**, constant at `gotcha.py:284` / `config.py:72`
**FSD §5.4 constraint, §10.3; `server/README.md:90-99`**

The server README is explicit: *"The server cannot enforce that anchoring — **Phase 2
must implement it**"*, anchored at the **last successful sync**, flat 900 s, to stay
under `OUTAGE_GAP_MIN` (1200 s). The badge defers on `_bar_lit()` with no cap and never
references the constant (`grep` finds no use in `app/`). It also ignores the
`HUNT_SYNC_DEFER` on/off tunable, so an admin disabling deferral has no effect.

**Failure:** two dev badges on a table, or a four-player endgame, or a target who sits at
the same campfire — the bar stays lit, sync never runs, and at small scale the server
reads camp-wide silence as an outage and pauses dormancy accounting for everyone. §10.3
names this as *"not theoretical at small scale"*.

#### D-6 · MAJOR · Opt-out and opt-in never reach the server ✅ *verified*
**`app/…/gotcha_app.py:347-357`**; server handlers exist at **`events.py:516-531`**
**FSD §3.2, §9.3, §13**

`opt_out()` sets local state, drops the beacon block and stops syncing (`is_enrolled()`
returns False). The `optout` event is never queued, and `GotchaSync.flush_events` has
**no call site anywhere in `app/`**. §3.2 requires *"Splice out immediately; the hunter
is reassigned on their next sync"*.

**Failure:** a player who withdraws consent — the §13 "a kid who wants out must get out in
a few seconds" case — stays somebody's assigned target and is simply unfindable for up to
`TARGET_STALE_H` (6 h). This manufactures §3.3's stated worst failure mode ("I wandered
for four hours and never found anyone") with a UI button. Compounding it, `opt_in()`
cannot clear a server-side opt-out either.

#### D-7 · MAJOR · The badge never sends a heartbeat, so §9.3's cadence contract is unmet ✅ *verified*
**`app/…/gotcha_app.py:227-252`** · **FSD §9.3, §10.1**

§9.3: *"Cadence: queued once per `SYNC_S`, immediately before the sync flush, so every
sync carries exactly one."* `_do_sync` calls neither. Notably, **the test harness does
implement it** (`tests/badge_sim.py:107-113` — *"the real order"*), so the reference
implementation and the shipped implementation have diverged. The consequences (stale-target
detection, group snapshots, battery/version telemetry, personal quiet-hour re-check) all
land in Phase 3+; the gap is worth closing before Phase 3 builds on it.

#### D-8 · MAJOR · A bounty kill applies ring inheritance and orphans a player every time ✅ *reproduced*
**`server/gotcha_server/events.py:290-295`** · **FSD §3.2 rule 10, §3.3**

§3.2's *"Kill → `assassin.target = victim.target`"* is written for the assassin **who was
hunting the victim**. `_apply_kill` applies it to bounty kills too, where the assassin is
not the victim's hunter.

Reproduced on a clean 10-player ring:

```
before: killer 1002 -> 1007 ; victim 1001 hunted by 1003
1002 bounty-kills 1001       -> accepted
after: killer 1002 -> 1010
after a full round of syncs: orphans=[1007]  double-hunted={1010: [1002, 1003]}
```

`reconcile()` never repairs it: loop 3 checks only that each player *has* a valid target,
never that each player *has a hunter*. Player 1007 is un-hunted for the rest of camp and
silently out of the game. The bounty layer is §3.3's designated safety valve against
exactly this failure mode, so it degrades continuously.

**Fix:** only inherit when `assassin["target_pid"] == victim["pid"]`; otherwise
`ring.splice_out` the victim and leave the assassin's pointer alone.

#### D-9 · MAJOR · `forwarded_allow_ips="*"` with no proxy voids the only Sybil detector ✅ *verified*
**`server/gotcha_server/main.py:31-33`** · **FSD §9.2, §9.5**

```python
uvicorn.run(app, …, proxy_headers=True, forwarded_allow_ips="*")
```

There is no reverse proxy — the service is the edge (`DEPLOY_LOG`: *"no ports 80/443
bound"*). uvicorn therefore trusts `X-Forwarded-For` from any peer, so
`request.client.host` (`app.py:67`) is whatever the caller says. A Sybil farmer randomises
it per `/v1/enroll`: the 900/hour cap never trips, and §9.5's only Sybil signal —
`audit`'s `enroll_clusters` grouped by `ip` (`admin.py:534-537`) — never reaches its
`HAVING n >= 5` threshold. The plan calls Sybil *"the real hole"* and puts the whole
weight on detection; this line removes the detector. **One-line fix: delete both kwargs.**

#### D-10 · MAJOR · `set_tunables` accepts any value of any type; one admin request can brick the camp ✅ *verified*
**`server/gotcha_server/service.py:64-81`** · **FSD §5.4, §8.10.1**

```python
known = set(DEFAULTS)          # includes server-only rules, e.g. SIG_WINDOW_S
for k, v in (updates or {}).items():
    if k in known:
        cfg[k] = v             # no type check, no range check
```

`auth.py:46` then does `int(cfg.get("SIG_WINDOW_S", …))`. `{"SIG_WINDOW_S": "ten"}` raises
inside `verify_request` on **every** badge request → HTTP 500 camp-wide, unsigned, so
badges silently discard it and show nothing. Recovery means hand-editing
`games.config_json` with `sqlite3` in a field — exactly what §5.4 exists to avoid.
`SIG_WINDOW_S: 0` is the same outage with no exception to grep for.

#### D-11 · MAJOR · An integral-float tunable silently stops every badge from syncing ✅ *proved end-to-end*
**`app/…/gotcha.py:90-95`** (`_cj_float`) vs **`server/gotcha_server/crypto.py:29-31`**
**FSD §6.2**

The badge's hand-rolled `canonical_json` renders `2500.0` as `2500`; the server's stdlib
`json.dumps` renders it as `2500.0`. Response signatures are computed over
`canonical_json(payload)` on both sides, and the sync `config` block is a server-controlled
dict of tunables that `set_tunables` stores **without coercion** (D-10). Proved:

```
integral-float tunable  -> badge verifies response: False
int / non-integral float -> badge verifies response: True
```

**Failure:** a host posts `{"PROX_ALPHA_UP": 1.0}` from a script on Friday afternoon →
every badge in camp stops syncing, silently, with no distinguishing error. Request signing
is immune (the server hashes raw received bytes); only responses are affected. Exposure is
currently limited because the admin dashboard has no tunables form — the endpoint is
curl-only — but that is luck, not design.

**Fix:** coerce tunables to `type(TUNABLE_DEFAULTS[k])` server-side, and add an integral
float to `tests/test_server_crypto.py`'s payload set (it carries `0.6` but no `1.0`).

#### D-12 · MAJOR · Two kills in one batch: the second is rejected, and the streak counts one ✅ *reproduced*
**`server/gotcha_server/events.py:61-96`**, **`:280-281`**, **`scoring.py:77`** · **FSD D16, §2.1, §3.3**

`ingest_batch` reads the `reporter` row **once per batch** and passes that stale row to
every handler. Reproduced on the real ring with no forced targets:

```
a.report_kill(v1); a.report_kill(v2); a.flush()   # one POST — what a sweep produces
accepted=1  rejected=[{'reason': 'not_your_target'}]
assassin total_kills=1  streak_at_last_kill=1   2nd victim: active
```

D16 removes the kill cooldown *specifically* so table sweeps are legal, §9.5 calls
refusing a real sweep *"breaking the best moment in the game"*, and `HUNT_SYNC_DEFER`
guarantees a sweep arrives as one batch. The badge then drops the rejected uuid, so the
kill is gone. The streak half applies even when both kills are accepted.

**Fix:** re-read the reporter row at the top of each event inside `ingest_batch`'s loop.

#### D-13 · MAJOR · Backdated and forward-dated events bypass protection, truce and quiet hours ⚠️ *code-level*
**`server/gotcha_server/events.py:41-48`** (`rule_time` accepts `server_at + 600` and up to 48 h past)
**FSD §5.8, §9.5, §10.4**

`is_protected(victim, at)` is evaluated at the badge-supplied `at`. The 10-minute forward
tolerance exists for RTC skew but is applied to a 90-second window, so a badge can walk
through spawn protection. Symmetrically, backdating to 21:55 lets a badge score at 03:00
during the truce. `test_a_kill_made_before_the_truce_still_counts_when_it_uploads_later`
pins the permissive behaviour, so the suite endorses the hole. The tension with §10.3
(late events must be accepted) is resolvable: an event dated before the reporter's
*previous* successful sync would have been flushed then.

#### D-14 · MAJOR · Unlimited re-enrollment grants permanent spawn protection on the unauthenticated endpoint ⚠️ *code-level*
**`server/gotcha_server/service.py:296-314`** · **FSD §5.8, §9.2, §10.5**

The `existing is not None` branch unconditionally sets `protected_until = ts + SPAWN_PROTECT_S`
(90 s) and bumps `life_id`. `/v1/enroll` is unsigned and `enroll_rate_ok` allows 5 attempts
per `badge_key` per 300 s — one every 60 s against a 90 s window. The `life_id` bump is a
second repudiation channel: it ends the current life, so a pending genuine proof is refused
`life_over`. §10.5's wiped-`gotcha.json` path needs *one* protected re-enrollment, not one
per minute.

#### D-15 · MAJOR · `peers_seen > 0` refreshes your own `last_seen`, so §10.1 never fires in company ⚠️ *code-level*
**`server/gotcha_server/events.py:507-508`** · **FSD §10.1, §9.6**

§10.1 is *"not seen **by anyone**"*. Evidence that others saw you comes from
`revealed`/`dodge`/`kill`/another player's `target_seen_ago_s` — not from your own count
of peers. A badge sitting still in a tent with two other badges never goes stale, so its
hunter is stranded for the whole event: §3.3's named failure mode, generated by the
mitigation meant to prevent it.

#### D-16 · MAJOR · `ATTACK_COOLDOWN_MS` is written but never re-checked ⚠️ *code-level*
**`server/gotcha_server/events.py:410-425`** · **FSD §9.5**

§9.5 lists attack cooldowns among the rules that *"are re-checked here"* and says *"never
trust badge-side enforcement"*. The `attacks` table and `idx_attacks_pair` exist, but
`grep "FROM attacks"` finds only dashboard counters. A badge with the cooldown removed can
hammer a target every second and nothing notices — not even the audit page.

#### D-17 · MAJOR · Batch overflow is returned as `rejected`, so a conforming badge drops kills ⚠️ *code-level*
**`server/gotcha_server/app.py:137-142`** · **FSD §10.3** (*"never drop a `kill`/`killed_by`"*)

Events past `MAX_EVENTS_PER_POST` land in the same `rejected` list as permanent refusals,
with no way to distinguish "retry later" from "never". `badge_sim.flush()` — the designated
reference for `GotchaSync` — removes both accepted and rejected uuids. A kill at position
201 in a queue is lost. **Fix:** a separate `deferred` list the badge must re-queue.

#### D-18 · MAJOR · Admin credentials and session cookie travel in cleartext; no login throttle; PBKDF2 on the event loop ⚠️ *code-level*
**`server/gotcha_server/admin.py:53-71`**, **`main.py:31-33`** · **FSD §9.1** (*"session login on `/admin` over HTTPS"*)

`set_cookie` omits `secure` (deliberately, for the dev LAN), but there is exactly one
listener — `:8080`, plain HTTP. D21 explicitly governs the **badge** path only; §6.2 does
not extend it to `/admin`. Separately, `admin_login` is `async def` and calls a 120 000-round
PBKDF2 (~50 ms) synchronously with no rate limit or lockout, so ~20 attempts/second
saturate the single event loop and every badge sync stalls behind them.

#### D-19 · MAJOR · Unbounded request body is buffered before authentication ⚠️ *code-level*
**`server/gotcha_server/auth.py:70`**, **`app.py:69`**

`await request.body()` runs after only header/timestamp checks (and, on `/v1/enroll`,
with no credentials at all). No `Content-Length` guard, no uvicorn default limit. A 2 GB
body OOMs the single-process server on the game laptop; `Restart=always` makes it a loop.

### MAJOR — Phase 2 (badge)

#### D-20 · MAJOR · Three different RSSI→segment mappings; the LED bar is flat across the entire final approach ✅ *reproduced*
**`app/…/gotcha.py:489-501`** (`prox_fraction`), **`:540-572`** (`hunt_segments`), **`gotcha_app.py:305-307`**
**FSD §8.8.2** — *"the same RSSI→bucket mapping … so the two readouts always agree and teach each other"*

Measured with shipped defaults, n=5:

| `rssi_prox` | screen bar `round(5f)` | spec `ceil(5f)` | LED bar `hunt_segments` | ping |
|---|---|---|---|---|
| −88 | 0 | 1 | 2 blue | silent |
| −84 | 1 | 1 | **3 amber** | silent |
| −80 | 1 | 2 | **4 amber** | silent |
| −76 | 2 | 2 | 4 amber | silent |
| −72 | 3 | 3 | 4 amber | silent |
| −68 | 3 | 4 | 4 amber | 1325 ms |
| −66 | 3 | 4 | 4 amber | 1175 ms |
| −64 | 4 | 4 | **5 red** | 350 ms ×2 |
| −60 | 4 | 5 | 5 red | 350 ms ×2 |
| −58 | 5 | 5 | 5 red | 350 ms ×2 |

Three problems: none of the three mappings is the spec's `ceil(n·fraction)`; the LED bar
is **frozen at 4-of-5 amber across −80…−66** — 14 dB covering the entire final approach,
which §8.8.2a measured as the only band with usable signal; and at kill range the LED bar
says 5-of-5 red while the screen bar says 3-of-5, so the two readouts teach each other the
wrong thing. A hunter walking a target down from 5 m to 1 m sees no LED change at all.

**Fix:** derive `lit` from `prox_fraction` per §8.8.2 and keep KILL/REVEAL only as colour
overrides.

#### D-21 · MAJOR · The hunt-ping silent floor is off by one segment; §8.8.6's rate ladder is unreachable ✅ *reproduced*
**`app/…/gotcha.py:628-632`** · **FSD §5.4 `PING_FROM_SEG`, §8.8.6**

`thr = (pfs / 5.0)` → 0.6. The code's own comment says `PING_FROM_SEG` is *"in screen-bar
segments"* — but the screen bar uses `round(5f)`, so segment 3 begins at f ≥ **0.5**, not
0.6. Consequences, all measured: the ping is silent until −69 dBm, so single-tap pings
exist only in the 4 dB window −69…−65 before jumping to the kill-range double-tap; §8.8.6's
*"segment n−1 → 700 ms"* rung **never occurs** (the interval goes 1400 → 1175 → 350 ms);
and with D-1 applied (−68) the single-tap band collapses to ~1 dB.

Meanwhile `_bar_lit()` (`gotcha_app.py:156-158`) gates `HUNT_SYNC_DEFER` on
`radar_segs >= 3`, i.e. f ≥ 0.5 — so *"the bar is at `PING_FROM_SEG`"* means **three
different dBm values in three places**.

#### D-22 · MAJOR · The v2 game block is lost after any pause/resume, and an offline badge never admits its target ⚠️ *code-level*
**`app/…/fri3d_friends.py:1748`**, **`gotcha_app.py:120-124, 255-264`** · **FSD §4, §5.6, §10.3**

`onResume` calls `self._ble.begin(groups, name, rssi_floor)` with **no `game=`**, so
`begin()` sets `self._game = None` and rebuilds `_adv` without the block. `_push_game_context`
is cache-gated (`if gb != self._game_block`) and only called from `_do_sync`, so it compares
the freshly computed block against the stale cache, finds them equal, and never re-pushes.

**Failure:** open Settings, or get bumped by any foreground steal, and the badge advertises
no game block indefinitely — its hunter's `admit_peer` drops it and can never find it. This
is D3's "closing the app is a shield" arriving by accident. Separately, `start()` never calls
`set_game_context()`, so a badge booting **offline** with a persisted target never admits it,
and the radar stays dark — contradicting §10.3/D6's offline promise.

#### D-23 · MAJOR · Blocking network I/O runs on the OS asyncio loop ✅ *verified*
**`app/…/gotcha_app.py:168-194`** (`_conn_probe`), **`gotcha.py:1085-1113`** (`GotchaSync._get/_post`)
**FSD §7, §8.3**

`_conn_probe` is an `async def` containing **zero awaits**: a blocking `usocket.connect`
with `settimeout(4)` followed by a blocking `urequests.get(…, timeout=8)`. `TaskManager.create_task`
puts it on the *same* event loop, so up to ~12 s of DNS + connect + HTTP stalls LVGL, the
BLE tick drain and any in-flight contact swap — every 30 s. The base app already knows the
remedy: `_resync_time` (`fri3d_friends.py:2031`) dispatches `ntptime.settime()` to `_thread`
for exactly this reason. `GotchaSync` documents the deviation from §8.3's `DownloadManager`
mandate (the probe found `post_url` absent), which is defensible, but `TaskManager.wait_for`
cannot interrupt a blocking C call, so §8.3's mandated timeout bound does not actually exist.

Aggravating: `tick()` gates sync on `self.online` but **not on `wifi_up`**, and `online` is
never set False when WiFi drops (D-24), so with the link down the loop blocks for the full
timeout on every 60 s retry.

#### D-24 · MAJOR · §7's connectivity check is polled, and `online` is never invalidated ✅ *verified*
**`app/…/gotcha_app.py:19, 139-141`** · **FSD §7**

§7: *"Run the check once at startup and on a `ConnectivityManager` change event — **not on
a poll loop**."* `CONN_EVERY_MS = 30000` re-probes forever. Conversely, when WiFi drops no
probe runs (it is gated on `wifi_up`), so `self.online` keeps its stale `True`, `no_network()`
stays False, and the `geen netwerk` strip never appears — §7 calls this *"the single most
likely support question at camp"*.

Also missing: §7's specified **1.1.1.1:80 fallback**, so "server down" and "no internet"
are indistinguishable.

#### D-25 · MAJOR · A malformed truce schedule silently turns the night truce OFF ✅ *proved*
**`app/…/gotcha.py:329-335`** · **FSD §10.4, §5.4**

`cfg.d["truce_from"] = str(sched["from"])` with no parse validation; `parse_hm` then returns
`None` and `_in_window` returns `False`. Proved:

```
truce_schedule {"from": "22.00", "to": "08:00"}  ->  truce_active at 23:00 camp = 'none'
(control, well-formed schedule)                  ->  'camp'
```

A host typing `22.00` instead of `22:00` disables the camp night truce on **every badge**
within `SYNC_S`. §10.4's stated failure mode is *"a screaming badge in a tent full of
sleeping children"*. This fails **open**; it must fail closed to the `DEFAULTS` window.

#### D-26 · MAJOR · An unsynced clock produces a 6-hour phantom truce, then no truce ever ✅ *proved*
**`app/…/gotcha.py:362-364, 963-965`** · **FSD §8.3, §10.4, D6**

`clock_offset_s` defaults to 0 and both NTP and `_bootstrap_clock` need the network. A badge
that has never had WiFi reports camp-local `02:00 + uptime`:

```
uptime  0h -> camp-local 02:00  truce=camp     uptime  7h -> 09:00  truce=none
uptime  5h -> camp-local 07:00  truce=camp     uptime 12h -> 14:00  truce=none
uptime  6h -> camp-local 08:00  truce=none     uptime 23h -> 01:00  truce=camp
```

So an offline badge is unplayable for its first ~6 h, and thereafter its truce and personal
quiet window fire at arbitrary wall-clock times. §10.4 says the badge *"does not need a sync
to know the truce"*. **Fix:** treat an unknown clock (`synced_at is None`) as sound-suppressed.

#### D-27 · MAJOR · A structurally-corrupt but JSON-valid `gotcha.json` permanently kills syncing ✅ *proved*
**`app/…/gotcha.py:872-874`** → **`:928-936`** · **FSD §8.2**

`load()` copies any top-level value regardless of type. Proved:

```
gotcha.json = {"enrolled": true, "pid": 1001, …, "state": "broken"}
apply_sync RAISED: TypeError 'str' object does not support item assignment
```

`GotchaSync.sync()` does not guard the call, so the coroutine dies; `_do_sync` catches, logs
and reschedules — forever. Truncated/invalid JSON degrades correctly; only the "valid JSON,
wrong shapes" case poisons state. **Fix:** type-check per key on load, and reset-to-blank on
an `apply_sync` failure.

#### D-28 · MAJOR · The badge enrolls as `BadgeXXXX`, never the player's chosen name ⚠️ *code-level*
**`app/…/gotcha_app.py:48-53, 216`** · **FSD §8.4, §9.2, §13**

`_dev_name` returns `"Badge" + uid[-4:]` whenever `machine` imports — i.e. always on-device.
Every hunter's target strip and every leaderboard row reads `Badge9070` instead of the chosen
or auto-generated nickname. §13: *"Players choose their display name."* Looks like probe
leftovers. Compounding it, `configure()` is called only once from `_setup_gotcha`, so a
phone-setup save never reaches the controller.

#### D-29 · MAJOR · `GFLAG_ALIVE` is advertised unconditionally, including when dead ⚠️ *code-level*
**`app/…/gotcha_app.py:270`** — `gf = bp.GFLAG_ALIVE`, with no reference to `state.alive`.
**FSD §4, §8.4 D11.** Every dead badge broadcasts ALIVE, so D11's "peer at someone's badge to
see if they are safe to approach" reports the opposite of the truth. `GFLAG_PROTECTED` is
never set either, though `protected_until` is already in state.

#### D-30 · MAJOR · Enrollment posts the `player_key` over plain HTTP ⚠️ *code-level*
**`app/…/gotcha_app.py:114, 215`**, **`gotcha.py:1144`** · **FSD §6.2, §6.3**

`enroll_url` defaults to `api_url`. §6.2's entire security argument rests on *"exactly one
TLS handshake … it closes the key-delivery hole"*, and §11 records that TLS was *proven* to
work on this badge (12/12 handshakes, flat heap). Server-side HTTPS is Phase 5, so this is a
known deferral — but the badge neither refuses nor warns, and it is already on §6.3's release
checklist. Anyone sniffing the camp LAN gets a player's 32-byte key and can forge their kills
indefinitely.

#### D-31 · MAJOR · The reported `app_version` is hardcoded and already stale ✅ *verified*
**`app/…/gotcha_app.py:217`** — `"0.11.0"` against a MANIFEST of `0.11.2`.
**FSD §8.10.3**: *"bump it on every release or the fleet histogram and the update nudge both
lie."* `fri3d_friends.py:58-63` already has `_read_version()`.

#### D-32 · MAJOR · Game-admitted peers leak into the friends UI ⚠️ *code-level*
**`app/…/ble_proximity.py:733-747`**, consumed at **`fri3d_friends.py:1947-1968`** · **FSD §4, §8.4**

Same root cause as C-5. Your Gotcha target appears in `Vrienden dichtbij: <target>`, in the
detail cards with group `?`, in the `VRIENDEN DICHTBIJ n` count, and in `has_peers()` — which
also suppresses the backlight dim. Besides being wrong, it tells the friends panel your target
is nearby. **Fix:** filter `current_peers()` to `shared_id is not None`.

#### D-33 · MAJOR · The target strip overlaps the `Menu` pill ⚠️ *code-level, needs hardware to confirm*
**`app/…/fri3d_friends.py:451-455`** vs **`:1012-1013`**

`_g_target` sits at `x=8, y=H-24` with `set_width(W-40)`, left-aligned, `LONG_MODE.WRAP`; the
Menu pill occupies `x=100…196, y=H-24`. The Gotcha label is created *after* the pill, so it
draws on top. Anything longer than ~11 characters — `WAPENSTILSTAND`, `Otter 42 — zoek...` —
runs through the Menu affordance, and a wrapped second line lands off-screen. §8.9.2 warns
about exactly this class of defect and says only hardware catches it.

### MINOR / INFO (selected)

| # | Severity | Finding | Location |
|---|---|---|---|
| D-34 | MINOR | The `gotcha_dbg.txt` writer is change-gated on a **float** (`prox`), so it writes to flash on essentially every advert (~1–3/s) during a hunt, on the render thread. The comment claims "negligible flash wear". Already on the pre-camp removal list. | `fri3d_friends.py:699-714` |
| D-35 | MINOR | `SILENT = True` still ships in 0.11.2, so the §8.8.6 hunt ping is mute on every badge. Documented as a pre-camp flip; it is still in the code at HEAD. | `fri3d_friends.py:179` |
| D-36 | MINOR | The demo task is never tracked or cancelled; `_stop_task` covers `_task`, `_splash_task`, `_exch_task` only. Press X during the ~8 s demo and an orphan coroutine touches LVGL and the LEDs on a paused Activity — the F-4 class the exchange task is explicitly guarded against. | `fri3d_friends.py:501-526, 1802-1823` |
| D-37 | MINOR | `solid_frame` is written **and tested** but has no caller, so §8.8.3's dead/protected/battery-low strip states never appear. §8.8.7's `KWIJT` contact-lost cue has no helper, no state and no test. | `gotcha.py:603-609`; absent |
| D-38 | MINOR | `hunt_ping` compares `(now_ms - last_ping_ms)` with raw subtraction instead of `ticks_diff`. After the 2³⁰ wrap (~12.4 days uptime) the ping goes permanently silent. Camp is 3 days, so low real-world risk. | `gotcha.py:649` |
| D-39 | MINOR | `_hex` is **defined twice**; the second shadows the first module-wide. Both agree today, but the docstring explaining the on-badge `.hexdigest()` bug describes a function that no longer exists at runtime. | `gotcha.py:40, 704` |
| D-40 | MINOR | Three non-ASCII characters (`·` U+00B7, `—` U+2014) in the always-visible status chip. The built-in `font_montserrat_*` are ASCII-only — the codebase already avoids U+2026 for exactly this reason (`_short`, `fri3d_friends.py:1005`). | `gotcha_app.py:323, 330, 332` |
| D-41 | MINOR | Group names have no length cap (`clean_groups` caps the *count* at 5, not the length), so a signed heartbeat can store 5 × 1 MB names. | `groups.py:15-58` |
| D-42 | MINOR | CSV formula injection in the admin export: `_csv_cell` quotes `,"\n` but not a leading `=`/`+`/`-`/`@`. | `admin.py:581-587` |
| D-43 | MINOR | No `PRAGMA busy_timeout`; `DEPLOY_LOG` documents hosts running `sqlite3` against the live file at camp, which would make the server throw `database is locked` immediately. | `db.py:260-266` |
| D-44 | MINOR | `SCHEMA_VERSION = 1` is stored but never read and there is no migration ladder — schema is `CREATE TABLE IF NOT EXISTS` only, so a Phase 5 column addition will not reach the camp database. | `db.py:24, 268` |
| D-45 | MINOR | The hit list advertises `dormant` and `stale` players (filters `base_status='active'` only), pushing bounty targets that cannot be found — the opposite of §10.1's intent. | `scoring.py:229-231` |
| D-46 | MINOR | Group boards rank by **points**, not Σ `total_kills` as §2.3 specifies (so a bounty kill contributes 2). README interpretation #2 covers `board_total`, not the group boards. | `scoring.py:173-215` |
| D-47 | MINOR | A heartbeat carrying `groups: []` wipes the player's groups (DELETE-then-insert; an empty list is a valid list). | `events.py:470-471` |
| D-48 | MINOR | `card_token` (24 h lifetime) rides in the query string with `access_log=True`, so it lands in journald and any Referer. §9.1 calls it "short-lived". | `app.py:172, 199`; `config.py:90` |
| D-49 | MINOR | `EventQueue(events)` applies dedup but not `MAX_QUEUE` on **load**, so an externally-written file loads unbounded into RAM. | `gotcha.py:718-726` |
| D-50 | MINOR | `clamp_quiet` is applied on the BLE-setup path only; `configure()` and `_do_sync` take `quiet` raw, so a hand-edited `{"from":"12:00","to":"13:00"}` produces a midday self-halt. | `gotcha_app.py:115, 235` |
| D-51 | INFO | `DESIGN.md` §11 (friend LEDs) is **not** marked superseded, which §8.8.1 explicitly requires when the radar bar ships. | `DESIGN.md:377` |
| D-52 | INFO | §13's required README statement — *"the nametag, friend finder and contact swap remain fully offline; Gotcha is an optional online mode"* — is absent from both `README.md` and the MANIFEST `long_description`, which still promises "no WiFi/network needed". | `README.md`, `MANIFEST.JSON` |
| D-53 | INFO | No default `gotcha.api` / `gotcha.enroll` ships in `config.json`, so a fresh install is inert. Understandable while the DNS name (§14.1 A7) is open; must not be forgotten at release. | `config.json` |
| D-54 | INFO | `ring.splice_in` can hand a player themselves as a target if every random pick misses (falls back to `pool[0]`), violating its own stated invariant 2. I could **not** reach this from ordinary play — reachable only via admin `reassign` with a null target. | `ring.py:204-221` |
| D-55 | INFO | Fallback paths return **constants** (`"0123456789abcdef"` for the nonce, `"0000000000000000"` for event uuids) if `os.urandom` is unavailable — a repeated nonce dies in the replay cache; a repeated uuid dedupes distinct kills into one. | `gotcha.py:690-701, 982-988` |
| D-56 | INFO | `/api-docs` is public and enumerates every `/v1/admin/*` route; `--admin-password` on the command line is visible in `ps aux`. | `app.py:54`; `main.py:26` |

---

## 3. Plan vs. Implementation

`Implementation_Plan_Gotcha_20260726.md` is both the FSD and the implementation plan
(§11 carries the phasing and per-phase exit criteria), and `Plan_Review_Gotcha_20260728.md`
records the pre-implementation readiness review. There is no separate approved plan
document for Phases 0–2.

| Plan item | Planned | Actual | Status |
|---|---|---|---|
| **Phase 0** deliverables | Six spikes + two written reports + a go/no-go | Both reports written; all six answered; all figures reproduce from raw data | ✅ **Met** |
| Phase 0 → Phase 2 gate | Worn-on-worn walk *"owed before Phase 2 builds the radar"* | Not done; the pre-committed fallback (−68) also not applied | ⚠️ **Deviation** (D-1) |
| Phase 0 rule: no sync during a live hunt | Defer below `PING_FROM_SEG` | Implemented (`_bar_lit`) | ✅ Met |
| Phase 0 rule: 12.5 % duty background only | Wire into the lever-4 ladder | Not implemented; 50 % unconditional | ⚠️ Deferred (D-2) — safe direction |
| Phase 0 rule: never ship the symmetric EWMA on the hunt path | Asymmetric `prox_filter` | Implemented and fed 0.60/0.08 at `start()` and every sync | ✅ Met |
| **Phase 1** files | `server/` (§9): API, scoring, ring, admin, pages skeleton | All present, plus `DEPLOY_LOG.md` and `tools/smoke.py` | ✅ Met |
| Phase 1 testing strategy | *"Fully testable with the badge-simulator pytest fixture"* | `tests/badge_sim.py` built; it signs with the badge's own `gotcha.py` | ✅ Met — and better than planned |
| Phase 1 interpretation calls | 4, all to be commented at the code | All 4 present and commented; #1 and #3 verified correct | ✅ Met |
| Phase 1 measured performance | 2.3 req/s needed | 10.8 ms/sync at 700 players (93 req/s) | ✅ Exceeded |
| **Phase 2 Layer A** (pure half) | `gotcha.py` + v2 beacon + admission/LRU | Built; 300+ host tests | ✅ Met |
| **Phase 2 Layer B** (integration) | `GotchaSync`, §7 check, UI/LED/menu wiring | Built and proven on two badges | ⚠️ **Met with C-5** — the hardware proof used two group-sharing badges, which masks the crash |
| Phase 2 exit criterion | *"Ends with two badges enrolled, each showing the other as target with a live on-screen radar bar **and** a live LED bar"* | On-screen radar proven; **the LED bar is disabled by C-5 for any non-group-mate target** | ❌ **Not met** |
| Phase 2 scope: §8.4 Gotcha screen + focusable hunt strip | *"the hunt strip + `Gotcha` menu row + focus integration"* | Two flat menu rows; strip is a plain label | ❌ Not built |
| Phase 2 scope: hunt ping (§8.8.6) | *"builds alongside the bar; makes the radar testable by ear"* | Built, but muted by `SILENT=True` and its rate ladder is unreachable | ⚠️ Partial (D-21, D-35) |
| Phase 2 scope: demo mode | Colour **and** sound walkthrough, ~20 s | Colour only, ~8 s (sound moot under `SILENT`) | ⚠️ Partial |
| §13 first-run consent | Not originally in Phase 2; added at close-out | Built and verified on-badge | ✅ Exceeded scope |
| Pre-camp dev flags | `SILENT=True→False`; truce `23:00–07:00 → 22:00–08:00`; remove `gotcha_dbg.txt` | Truce **already** 22:00–08:00 on both sides (this close-out note is stale); the other two still present | ⚠️ 1 of 3 done |
| §8.10.4 update survival | Scoped to Phase 5 | Not built | ✅ Correctly deferred — but the wipe is now *verified*, so `contacts.json` loss is a live risk today |

**Undocumented deviations, and whether they seem justified.** Three, all defensible and
all commented at the code: `urequests` instead of §8.3's mandated `DownloadManager`
(justified — `post_url` is absent on this firmware, and the 1000-sync soak validated the
substitute, though the timeout guarantee is lost, D-23); the extra
`POST /v1/admin/truce_schedule` endpoint (justified and documented as interpretation call
#4); and `ring._interleave`'s group-aware seeding instead of §3.2's literal shuffle
(justified by a written local-minimum analysis). The project's habit of writing the reason
down at the code is genuinely good and made this section easy to audit.

---

## 4. Edge Cases & Safety

| Edge case | Handling | Risk |
|---|---|---|
| Target in range with no shared group (the **normal** case, D9) | **Crashes the render tick** | **CRITICAL** — C-5 |
| Victim offline across its own respawn | Voided row blocks all future kills on the live life | **CRITICAL** — C-3 |
| Victim heartbeats a fresh commitment mid-chase | Kill proof invalidated | **CRITICAL** — C-2 |
| Table sweep (2+ kills, one batch) | Second kill rejected `not_your_target` | **MAJOR** — D-12 |
| Bounty kill | Ring inheritance misapplied; a player is orphaned every time | **MAJOR** — D-8 |
| Corrupt `gotcha.json`, truncated/invalid JSON | ✅ Degrades to a fresh state | None |
| Corrupt `gotcha.json`, valid JSON, wrong types | Sync dies permanently | **MAJOR** — D-27 |
| Malformed truce schedule from admin | Fails **open** — no truce | **MAJOR** — D-25 |
| Badge with no network, ever | Phantom truce 6 h, then no truce ever | **MAJOR** — D-26 |
| Badge clock corrected by NTP after the first sync | `clock_offset_s` is one-shot (`synced_at is None`) → permanent `stale_ts` lockout with no recovery path | **MAJOR** — `gotcha.py:1163`; the OS NTP-syncs on WiFi connect, so this is a race, not a certainty |
| Sync deferred by a permanently lit bar | Unbounded; at small scale reads as a camp-wide outage | **MAJOR** — D-5 |
| Peer table under 700 badges | ✅ 64-entry LRU with the target pinned; verified the target survives as the oldest entry | None |
| Peer stops advertising a game block | `pid` cleared but `gflags` retains its last value — stale BOUNTY/TRUCE | MINOR |
| Truce/quiet at midnight boundary | ✅ Half-open windows, wrap handled, both boundaries tested | None |
| Midnight-wrap in `evict_lru` / `_breathe_env` | Raw comparison / modulo on `ticks_ms` (2³⁰ wrap ≈ 12.4 days) | INFO — camp is 3 days |
| Replay of a signed request | ✅ `PRIMARY KEY (pid, nonce)` makes it an atomic INSERT failure; no TOCTOU | None |
| Cross-pid / cross-endpoint signature replay | ✅ Key looked up by `X-Pid`; METHOD‖PATH in the message | None |
| Concurrent syncs from 700 badges | ✅ Serialised on one event loop; measured 93 req/s vs 2.3 needed | None *today* (see §5) |
| Power loss mid-write | ✅ Atomic temp+rename on both `gotcha.json` and `config.json` | None |
| AppStore update | State destroyed (verified behaviour); §8.10.4 not built | Accepted — Phase 5 |

---

## 5. Concurrency & Platform Issues

**Badge (MicroPythonOS asyncio).**

- **Blocking I/O on the OS loop** is the systemic issue (D-23). `_conn_probe` is an
  `async def` with zero awaits containing two blocking calls totalling up to 12 s, fired
  every 30 s. `GotchaSync`'s blocking `urequests` at least yields 80 ms afterwards and is
  documented, but `TaskManager.wait_for` cannot interrupt a blocking C call.
- **IRQ discipline is preserved and this deserves credit.** The BLE IRQ still only copies
  into a bounded 256-entry `_pending`; all parsing, `_seen` mutation, eviction and LRU work
  runs on the loop thread in `tick()`. The widened admission moved no work into the IRQ.
- **LED writes remain suppressed during a swap and during a setup session** (`fri3d_friends.py:1856, 1891`)
  — the field-bug-2 rule (WS2812 writes disable IRQs and starve a phone's GATT).
- **Task lifetime:** the demo task is untracked and uncancelled (D-36). `_syncing`/`_enrolling`
  are not reset in `start()`, so if a foreground steal destroys rather than cancels a task
  (a known project hazard: toggling WiFi kills the Activity's tasks), the flag latches and
  the badge never syncs again for that session.
- **Frame caching is correct:** `hunt_bar` is pure and the caller dedups the whole frame, so
  §8.8.4's "dark and steady-red cost zero `lights.write()`" holds.

**Server (FastAPI + SQLite).**

- **Safety is currently accidental, not designed.** Every route is `async def`, so all DB
  work is serialised on one event-loop thread and "database is locked" cannot arise from
  within the process. But `db.lock` is never acquired (its docstring says otherwise) and
  `db.rollback()` is never called. Converting a single handler to plain `def` would move it
  to Starlette's threadpool and make the shared connection, `cur.lastrowid` in `_insert_kill`,
  and cross-request `commit()` genuinely racy — with C-4 as the consequence. **This deserves
  a comment at `db.py`'s header**, which today justifies the single connection on load
  grounds only.
- `await request.body()` inside `verify_request` is the one yield point between reading the
  player row and using it. Impact today is one stale sync payload, self-correcting.
- No `busy_timeout` (D-43), so an external `sqlite3` session at camp causes immediate 500s.
- A 120 000-round PBKDF2 runs synchronously on the event loop with no login throttle (D-18):
  ~20 attempts/second stall every badge sync.

---

## 6. Error Handling

**Good.** Defensive parsing that genuinely never raises: `GameConfig.from_sync`, `sig_ok`,
`verify_response`, `clamp_quiet`, `verify_soul`, `parse_payload` (bounds-checked, magic- and
company-gated, reserved-bit-rejecting, degrading a truncated game block to `game=None`).
`GotchaState.load()` degrades a truncated or invalid file to a fresh state. Every Gotcha
entry point in `fri3d_friends.py` is try/except-wrapped and `self._gc = None` degrades
cleanly to "no game, still a nametag". No stack trace reaches a client: `create_app` never
sets `debug=True` and the `HTTPException` handler returns only short constants. A corrupt or
missing DB fails loudly into the systemd restart loop with the error in the journal — the
right failure for a laptop in a field. `ingest_batch` commits and catches **per event**, so
one bad event cannot poison a batch — that discipline just needs to extend outward (C-4).

**Gaps.**

- **The blanket `except Exception: pass` in the main loop converts a crash into silent
  feature loss** (C-5). This is the single most damaging error-handling decision in the
  codebase: it turned a `TypeError` into "the LED bar mysteriously doesn't work". At minimum
  it should log through `_gc_log` so the failure is visible in `gotcha_dbg.txt`.
- No rollback anywhere on the server (C-4).
- `GotchaState.save()` swallows all errors and returns `False`; every caller ignores the
  return, so a full or read-only filesystem means state silently never persists.
- A bare `except Exception` reports every nonce INSERT failure as `replay` (`auth.py:79-84`),
  so a locked or full disk looks like a crypto bug in the logs.
- Type-shape corruption in persisted state is unhandled (D-27).
- A failed join is silent: `request_enroll` fires and forgets, and `_maybe_show_consent`
  re-opens the identical overlay a tick later, which reads as "the button does nothing".
  §7: *"Never fail silently."*

---

## 7. Code Quality

**Genuinely strong, and worth saying explicitly:**

- **MicroPython hygiene is excellent.** No f-strings, `%`-formatting throughout, the portable
  `_hex()` instead of `.hexdigest()`, no dict-ordering assumptions (`canonical_json` sorts,
  `from_sync` iterates `DEFAULTS`, `load` iterates the blank schema), and `json.dumps` →
  `write` → `close` → `rename` rather than the project's known `json.dump(obj, open(p,"w"))`
  trap.
- **The pure/impure split is deliberate and pays off.** `gotcha.py` and `ble_proximity.py`'s
  wire-format half are host-testable with no device tree, and the injectable
  reader/writer/renamer on `GotchaState` is a nice touch.
- **Reasons are written down at the code**, not just in the plan — the four server
  interpretation calls, `ring._interleave`'s local-minimum analysis, `clock.py`'s fixed camp
  offset, `note_return` before `note_sync`, the `_cj_float`/`ticks` comments. This made the
  review tractable and is a habit to keep.
- **`state.py`'s interval algebra** (merge/clip/daily-window, half-open bounds, midnight
  wrap as one interval) is the best-engineered module in the project. I tried to break the
  08:00 boundary, the host-truce-overlapping-nightly-truce merge and the grace extension;
  all behave correctly.
- **`test_server_plan_parity.py`** *measures* the `outage_intervals()` rounding direction
  across all 60 bucket phases rather than arguing it, and guards against a vacuous pass. That
  is unusually rigorous.
- **LVGL practice is consistent with v0.10.0**: overlays built once and hidden, `_bind_event`
  rather than raw `add_event_cb`, `_make_focusable` with a fallback, and every open/close
  routed through `_set_focus`/`_establish_focus`.
- **Prior review findings were addressed.** I spot-checked the Phase 5 review's five MAJORs
  (F-1 UTF-8 percent-decoding, F-2 apostrophe escaping, F-3 full-body read, F-4 exchange task
  cancellation, F-5 Y-gate) — all fixed and recorded in the changelog.
- **The opt-out fix (`1191558`) is complete on the badge side.** I traced every local path
  back into enrollment: `tick()`'s auto-enroll is gated on `ever_enrolled()`, `_do_enroll`
  re-checks `is_opted_out()`, `request_enroll` funnels through `_do_enroll`, `consent_needed()`
  requires `not ever_enrolled()`. There is no remaining local path back in. (The server side
  is missing — D-6.)

**Substantive quality issues:**

- **Duplicated logic that has already diverged in intent.** `gotcha.prox_filter` is tested
  but `ble_proximity._filter_prox` is what runs; three separate RSSI→segment mappings exist
  (D-20); `_hex` is defined twice (D-39). `ble_proximity.py:480` also *defaults* the alphas to
  the symmetric 0.3/0.3 that §11.1 forbids on the hunt path — safe in the Activity (overridden
  in `start()`) but `beacon_service.py` never calls `set_prox_filter`, so Phase 4's background
  hunt would inherit the forbidden filter.
- **Docstrings that assert the opposite of the code.** `_rotate_commitment` (C-2),
  `db.lock`'s "see routes" (C-4), `html_escape`'s "the one place" (C-1), `_g_dbg`'s "negligible
  flash wear" (D-34). Each of these is a comment that actively prevented the bug from being
  found.
- **Dead code that looks live:** `solid_frame` (written and tested, never called),
  `Database.rollback`, `SCHEMA_VERSION`, the `attacks` table's cooldown data.

### Test-suite assessment

313 tests, all green, running in 7.8 s. Strong where it is strong: RFC 4231 vectors,
badge↔server byte parity over 8 payload shapes, the v2 beacon round-trip including reserved
bits and UTF-8 truncation, `admit_peer`/`evict_lru` across all cases, the §9.6 status
precedence, `state.py`'s decay arithmetic against §2.2/§2.4's stated numbers, and the
degenerate ring cases.

**The gaps are structural and they are exactly where the CRITICALs live:**

1. **Every full-stack kill test posts one kill per batch after `_force_target`.** C-3, D-8
   and D-12 all live in that gap.
2. **`_is_single_cycle` exists in `test_server_ring.py` but is never applied to the database
   after API kills.** The one full-stack ring test asserts only "no self-target" and "target
   is alive" — never that every alive player *has a hunter*. Running it after
   `test_bounty_kill_scores_two` would have caught D-8 immediately.
3. **`current_peers()` is completely untested** (it needs a `time.ticks_*` shim), which is
   why nobody noticed the `shared_id=None` tuple it now emits. One test would have caught
   **C-5 and D-32**.
4. **`gotcha_app.py` has no tests at all.** Its pure parts are testable with a fake `ble` and
   fake `state` in ~60 lines: `_make_game_block` (would catch D-29), `_refresh_view`'s
   segment mapping, and the opt-out/consent gates (which would lock in the `1191558` fix).
5. **Tests that pin the bug rather than the spec.**
   `test_hunt_ping_silent_below_floor_and_disabled` asserts `hunt_ping(-80, …) is None` —
   but −80 **is** `REVEAL_RSSI`, where §8.8.6 specifies a 700 ms ping. The test locks in
   D-21, and its comment (*"PING_FROM_SEG=3 -> thr 0.6 -> -69 dBm"*) records the off-by-one
   as intended. `test_hunt_segments_matches_table_n5` is titled "matches table" but samples
   only −90/−80/−70/−65, skipping −85 and −75 where the mappings diverge most (D-20).
   `test_a_kill_made_before_the_truce_still_counts_when_it_uploads_later` pins the backdating
   behaviour that D-13 identifies as a hole.
   `test_gameconfig_defaults_when_no_sync` asserts `KILL_RSSI == -65`, so it will keep D-1's
   value green.
6. **No test covers:** `ticks_ms` wraparound anywhere; a malformed truce schedule (D-25);
   corrupt-but-valid-JSON state (D-27); floats in `canonical_json` (D-11 — `test_server_crypto.py`
   carries `0.6` but no `1.0`); `HUNT_SYNC_DEFER_MAX_S` badge-side behaviour (D-5); the
   unsynced-clock truce (D-26); a heartbeat-borne commitment rotation (C-2); or a late
   `killed_by` after respawn (C-3).

**Six cheap additions would have caught nine of the findings above:** assert the alive-player
pointer graph is one cycle after every full-stack kill test; post two kills in one flush;
flush a `killed_by` after the victim's respawn; rotate a commitment via heartbeat between an
assassin's kill and its flush; call `current_peers()` with a game-admitted peer; and put an
integral float in the crypto payload set.

---

## 8. Summary

| Category | Critical | Major | Minor | Info |
|----------|----------|-------|-------|------|
| Spec conformance | 0 | 12 | 8 | 4 |
| Plan conformance | 0 | 2 | 3 | 1 |
| Correctness | 3 | 11 | 5 | 2 |
| Safety | 1 | 6 | 3 | 2 |
| Concurrency | 0 | 3 | 2 | 2 |
| Error handling | 1 | 4 | 4 | 1 |
| Code quality | 0 | 1 | 6 | 3 |
| **Total (deduplicated)** | **5** | **33** | **23** | **9** |

**By phase:** Phase 0 — 0 critical, 1 major (D-1), 3 minor/info. Phase 1 — 4 critical, 15
major. Phase 2 — 1 critical, 17 major.

---

## 9. Recommendation

### Do not start Phase 3 yet.

Phase 3 (the duel and the Reveal) builds directly on the kill path, the ring and the LED
radar bar. Three of the five CRITICALs are *in* that kill path and one disables the radar
bar, so Phase 3 would be built on foundations that are known-broken and would make the
defects far harder to isolate.

**Blocking — close before Phase 3 (est. one focused day):**

1. **C-5** — one line in `_fill_row`. The LED radar bar, the clock, the battery display and
   the banner timeout are all dead whenever the game is actually happening. This also
   invalidates Phase 2's stated exit criterion, so fix it and re-run the two-badge test
   **with badges that do not share a group**.
2. **C-2** — one `WHERE lives.commitment IS NULL` clause. Without it the §3.4 soul mechanism
   provides no anti-cheat guarantee at all, and §9.5 says the soul *"carries the anti-cheat
   weight on its own"*.
3. **C-3** — add `AND voided=0` to the dup lookup and resolve `reported_life` from `lives`
   by `at`. Reachable with zero malice on the first afternoon at camp.
4. **C-1** — copy `esc()` into the admin script; cap `app_version` in the heartbeat handler.
5. **C-4** — `db.rollback()` in both `except` arms of `ingest_batch`.
6. **D-12** — re-read the reporter row per event. Without it, sweeps (which D16 exists to
   permit) do not work, and Phase 3 will be tested with sweeps.
7. **D-8** — gate ring inheritance on `assassin.target == victim`. Every bounty kill
   currently orphans a player permanently.

**Strongly recommended before the first playtest:**

8. **D-9** (one line: delete `proxy_headers`/`forwarded_allow_ips`), **D-10** and **D-11**
   (tunable type validation fixes both) — three small changes that between them prevent a
   camp-wide outage and restore the Sybil detector.
9. **D-22** (game block lost on resume) and **D-5** (deferral cap) — both are game-integrity
   issues that will present as "my badge stopped working" and be very hard to diagnose in a
   field.
10. **D-25**, **D-26**, **D-27** — the three fail-open/fail-permanent paths on the badge.
11. **D-20** and **D-21** — the radar mappings. These are the player's entire proximity cue
    now that the trend is retracted; getting them wrong makes the game feel broken even when
    everything else works. **Do this before the worn-on-worn walk**, since the walk is meant
    to calibrate a bar that currently disagrees with itself.
12. **D-28**, **D-29**, **D-31** — one line each: name, alive flag, version. All three
    currently make the game lie to players or to the host dashboard.

**Then, and only then:** run the §11.1 worn-on-worn walk (~30 min, two people) and set
`KILL_RSSI` from its result — resolving D-1 with data rather than with the fallback.

**Also worth scheduling, not blocking:** the six test additions listed in §7; the §8.4
Gotcha screen and focusable hunt strip (Phase 3's A-ladder has nowhere to attach without
them); and the pre-camp flag sweep (`SILENT`, `gotcha_dbg.txt`, the §13 README statement,
`DESIGN.md` §11 superseded).

### Credit where it is due

The engineering discipline here is well above average: reasons written at the code, spikes
that reproduce from raw data, a test harness that doubles as an interop proof, honest
retractions in the spike reports, and a plan that pre-committed its own fallbacks. The
defects found are not the result of carelessness — they are the result of two specific test
shortcuts (one kill per batch; two group-sharing badges) that each removed exactly the
condition under which the bugs exist. Closing those two gaps in the test suite is worth more
than any individual fix on this list.
