# Gotcha backend (Phase 1)

The authority for roster, ring, kills, scoring, game state and anti-cheat —
tier 1 of `Implementation_Plan_Gotcha_20260726.md` §0. FastAPI + SQLite, one
process, no ORM, no migration tool, no template engine, no build step: the
deployment target is a laptop in a field (§6.1).

**Status: Phase 1 complete** (API, scoring, ring, admin console, page
skeletons, badge-simulator test harness). Phase 2 is the badge side; Phase 5
replaces the page skeletons and adds HTTPS.

## Running it

```bash
# dev, from this directory
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
GOTCHA_DB=/tmp/gotcha.sqlite3 GOTCHA_ADMIN_PASSWORD=secret \
  .venv/bin/python -m gotcha_server.main --port 8080

# tests (from the repo root; they need no server running)
python3 -m pytest tests/ -q

# smoke-test a deployed instance over the network
python3 tools/smoke.py http://192.168.1.57:8080 --badges 6 --password secret
```

Deployment on the game laptop: `sudo deploy/install.sh`, undone by
`sudo deploy/uninstall.sh`. Every host-level change is listed with its revert
command in [`DEPLOY_LOG.md`](DEPLOY_LOG.md).

## Layout

| File | What lives there |
|---|---|
| `clock.py` | The injectable clock and the *only* place the camp timezone appears. |
| `config.py` | §5.4 tunables (pushed to badges) and server-side rules (not pushed). |
| `crypto.py` | Server half of the signed-HTTP scheme, card tokens, admin sessions. |
| `groups.py` | Group normalisation/hashing — a deliberate copy of the badge's, parity-tested. |
| `db.py` | Schema and the single-connection SQLite wrapper. |
| `state.py` | Everything time-derived: truce, quiet hours, decay, dormancy, staleness, status. |
| `ring.py` | Ring construction and maintenance (pure functions over `{pid: target}`). |
| `scoring.py` | Points, streaks, deaths, leaderboards, hit list. |
| `service.py` | Glue: enrollment, sync payload, and `reconcile()`. |
| `events.py` | Event ingest (§9.3) with all server-side re-checks. |
| `admin.py` | Admin API + the dashboard document. |
| `pages.py` | Backend-served HTML (D31): player card skeleton, working admin dashboard. |
| `app.py` | Routes only. No rules. |

## Two design decisions worth knowing before you read the code

**Derive, don't schedule.** `protected`, `dormant`, `stale` and the decayed
`streak` are computed from timestamps every time they are asked for. §2.2 argues
this for streak decay ("correct regardless of when the timer actually runs —
important, because the backend may be unreachable for hours"); the same argument
applies to all of them, so there is no cron, no worker and no queue in this
server. The one thing that cannot be derived is a target pointer, so
`service.reconcile()` acts on the derivations — respawn the due, splice out the
dormant and stale, give a target to anyone lacking one — and it runs at the top
of every sync and every event batch. The game repairs itself as a side effect of
badges talking to it.

**The badge is untrusted except about its own death.** Truce, quiet hours,
protection, cooldowns, dodge limits, target validity and repeat-kill scoring are
all re-checked here (§9.5). The single exception is §9.6's rule that a badge is
authoritative for its own death — so a `killed_by` is believed, and the server
then decides separately whether the *kill* counted (§10.2).

## Interpretation decisions made here

The plan is unusually precise, but four points needed a call. All four are
commented at the code:

1. **`METHOD || PATH` includes the query string** (`crypto.py`, `auth.signing_path`).
   Otherwise `?board=` and `?limit=` are unauthenticated. **The badge must sign
   the full request target** — this is a contract Phase 2 has to match.
2. **`total_kills` and `score` are both stored** (`scoring.py`). §2.1 ranks board 1
   by `total_kills` while §2 awards 1 or 2 points per kill; those are different
   numbers, so both are kept and both are returned. The "total" board ranks by
   points. A repeat kill inside 6 h scores 0 and does not count as a kill for the
   assassin — it is still a death for the victim.
3. **A `lives` table holds each life's commitment** (`db.py`). §3.4 rotates the
   soul every life, but a kill proof can arrive hours late (§10.3) after the
   victim has respawned. Keeping the history means the soul itself identifies
   which life it ended, so a late proof still verifies and still dedupes onto one
   death instead of looking like cheating.
4. **`POST /v1/admin/truce_schedule`** is not in §9.4's list but exists
   (`admin.py`), because the nightly window is pushed to badges and every other
   timing constant is host-adjustable.

**One cross-layer constraint to know about.** `HUNT_SYNC_DEFER_MAX_S` (§5.4, 900 s)
must stay below `state.OUTAGE_GAP_MIN` (20 min): a badge deferring its sync mid-chase
is silent on purpose, and §10.3's outage detection cannot tell that from the server
being down — if deferral outlasted the window, a camp-wide chase would pause dormancy
accounting for everyone. It holds only because the plan anchors the cap at the **last
successful sync** (flat 900 s) rather than at deferral start (`SYNC_S`×1.2 + 900 =
1260 s, which breaches). **The server cannot enforce that anchoring — Phase 2 must
implement it**, which is why it is spelled out at the constant in `config.py`. Both
values are live-tunable, so raising the deferral cap from the admin page at camp can
break dormancy accounting; raise `OUTAGE_GAP_MIN` first.
`tests/test_server_plan_parity.py` guards the ordering and also measures that the
60 s bucket rounding in `outage_intervals()` runs in the safe direction (measured gap
≤ true gap, so a maximal 900 s deferral is never reported as an outage at any bucket
phase).

Two smaller ones: `ENROLL_MAX_PER_IP_HOUR` is deliberately loose (900) because
Friday morning is 700 badges at once and the camp network may NAT them behind one
address; and `build_ring` seeds §3.2's randomised construction with a group-aware
deal, because a plain shuffle has a local minimum that the specified local repair
cannot escape when two large groups are of similar size (see `ring._interleave`).

## Measured

On the dev laptop, against a database holding 700 enrolled players:

| | |
|---|---|
| Sync latency (incl. `reconcile` over 700 players) | **10.8 ms** → ~93 req/s |
| Required (§6.1: 700 badges ÷ 300 s) | **2.3 req/s** — 40× headroom |
| Signed sync response | **1.55 KB** |
| Initial ring build, 700 players, 40 groups | **0.2 s**, 0 group conflicts |
| Enrolling 700 badges | 4.1 s |
| **1000 consecutive signed syncs** against the deployed server | median **5.5 ms**, p95 9.6 ms, 99.5 req/s, **no drift** (latency fell as caches warmed); service RSS flat at 35 MB, every response signature and nonce verified |

The last row is the **server half of §11 item 2's soak**. The gate itself is about
the *badge's* heap and only a badge can answer it; `tools/smoke.py --soak 1000`
proves the server holds up over the same run, so badge time is not spent
discovering a server problem. The nonce cache held 1003 rows immediately after the
run, which is correct — they were all inside the ±10 min replay window; steady
state at 700 badges is ~1400 rows.

## Not built yet (and where it belongs)

- **HTTPS / Let's Encrypt DNS-01, ports 80+443** — Phase 5 (§6.1). Today the
  service listens on :8080 and `/v1/enroll` is reachable over plain HTTP, which
  is fine on a dev LAN and **must not ship as the camp default** (§6.3's release
  checklist item).
- **Player card, four leaderboards, hit list, QR flow as real pages** — Phase 5
  (D31). `pages.py` has the skeleton and the working admin dashboard.
- **Training mode** (§5.9) — Phase 6; `training_enabled` ships `false`.
- **`amnesty` modifier** — accepted and stored, not yet interpreted by any rule.
