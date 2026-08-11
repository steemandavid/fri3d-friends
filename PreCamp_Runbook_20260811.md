# Pre-Camp Runbook — 2026-08-11

What is left before camp (14–16 Aug 2026), and how to do each part. Steps 1–3 are
**hardware-gated**: the code side is verified here, and the remaining work is a
physical action with exact commands. Steps 4–6 are code, handled in the same session
(truce check, web pages, §8.10.3 full-screen).

---

## Step 1 — §11.1 worn-on-worn threshold walk  *(needs 2 people + 2 badges)*

**Tooling verified present and coherent (2026-08-11):**
- `probes/rssi_walk_pkg/walk.py` — prompted multi-walk activity (Dutch screens,
  writes `walk_<N>.csv` + `walk_<N>_markers.csv`, target filter from `/rssi_cfg.json`).
- `tools/pull_walks.sh <port>` — pulls every `walk_*` pair into `probes/logs/`.
- `tools/analyze_shadow.py [logdir]` — measures the 1-body shadow from the existing
  pedestal walks AND prints the pre-committed `KILL_RSSI` table (the §11.1 numbers).
- `KILL_RSSI` is **live-tunable from the admin page** (§5.4), so the walk's outcome is
  a **config change, not a rebuild**.

**Do this (≈30 min, two people, both wearing a badge in normal wear position):**
1. On the walker badge, set the target: `mpremote ... exec "import json;json.dump({'name':'<target-name>'},open('/rssi_cfg.json','w'))"` then launch **RSSI Walk** from the launcher.
2. Run the prompted walk **twice**: (a) both walkers facing each other on approach,
   (b) target facing *away* (worst realistic body-shadow geometry). Follow each A-prompt.
3. Pull + analyse:
   ```
   tools/pull_walks.sh /dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_<id>-if00
   /tmp/ff-venv/bin/python tools/analyze_shadow.py probes/logs
   ```
4. Read the **median RSSI standing at 1 m** (the "penalty" vs the −57 dBm pedestal
   value) from section 1, then apply the pre-committed response from the table the
   script prints (or the plan's §11.1 table):
   - 0 to −4 dB expected → `KILL_RSSI = -65` (unchanged)
   - −8 → −68 · −12 → −71 · −16 → −77
   - worse than −16 → also cut `KILL_HOLD_MS` to 2500 before loosening further.

**If the walk is NOT done:** ship `KILL_RSSI = -68` (one step loose, ~3 % false-arm on
pedestal data) and treat the first real playtest as the measurement. Do not let this
block anything else.

---

## Step 2 — validate a real KILL over the flush path  *(needs WiFi up)*

**Already proven by composition (2026-08-11 review):**
- The **on-badge flush path** (`gotcha.py:GotchaSync.flush_events` → signed POST
  `/v1/events` → server accepts → `queue.remove(accepted)`) was **bench-validated on
  9de4 at 0.11.20** when the heartbeat refreshed the pid-1004 DB row (app_version,
  battery, peers_seen, bg_service all landed). The heartbeat is queued and flushed by
  the *same* `flush_events` call a kill uses — only the event `type` differs.
- The **server accepting + scoring a `type:"kill"`** is covered by `tests/badge_sim.py`
  + `test_server_api.py` (kill → `total_kills`/`score` increment, repeat-kill window,
  bounty). 444 tests green this session.

**Live on-badge demo could not complete at the bench (2026-08-11):** 9de4's WiFi is
down here (`casarural` out of range / creds not auto-stored), so `flush_events` had no
link. Also note the server verifies a kill's `soul` against the victim's registered
commitment (§3.4), so a *scoring* kill cannot be faked — it requires a real duel's
disclosed soul. 9de4 does carry **2 real queued `dodge` events** (attacker 9999) that
are valid flush payload once WiFi is up.

**To do the live demo (at camp, WiFi up):**
1. SSH the server, snapshot pid 1004: `SELECT pid,total_kills,score FROM players WHERE pid=1004`.
2. On a badge with WiFi up and the app running, trigger a flush and watch the queue drain:
   ```
   sudo /tmp/ff-venv/bin/mpremote connect <port> exec \
     "import beacon_service as bs,asyncio; gc=bs._ACTIVE._gc; \
      asyncio.run(gc.sync.flush_events(gc.api_url)); print(len(gc.state.queue))"
   ```
   (recover a wedged CDC with USBDEVFS_RESET on `/dev/bus/usb/<bus>/<dev>` — does not reboot.)
3. The cleanest *scoring* proof is a real two-badge A-press duel (the path proven
   0.11.13); the kill it produces rides this same flush path and will bump the
   assassin's `total_kills`/`score` on the next sync.

---

## Step 3 — Flags AD on-hardware re-verification  *(code correct; badge stale)*

**Repo code (0.11.29): CORRECT + tested.**
- `contact_exchange.py:82-83` — `build_exchange_adv` prepends `flags_ad = bytes([0x02,0x01,0x06])`
  before the manufacturer AD; `return flags_ad + mfg`.
- `ble_proximity.py:304` — `build_payload(connectable=True)` prepends the Flags AD
  (§5.7 probe finding); the load-bearing game beacon for the duel connect path.
- Tests: `test_contact_exchange.py:60` (Flags-first), `test_ble_proximity.py`
  (`test_build_payload_connectable_prepends_flags_and_still_parses`,
  `test_name_budget_connectable_reserves_flags`). 444 green.

**On-badge (9de4, 2026-08-11): `contact_exchange.py` is STALE.** The badge reports
`MANIFEST.JSON` version **0.11.29**, but its deployed `contact_exchange.py` is the old
build (docstring "one manufacturer AD structure", no `0x02,0x01,0x06` literal; a live
`build_exchange_adv()` call returned bytes starting `0b ff ff …` = manufacturer AD
with **no** Flags prefix). This is the version-bump-without-real-deploy hazard — the
MANIFEST advanced but the module didn't ship. The **game beacon** (`ble_proximity`)
is unaffected and proven deployed (the 0.11.13 duel connect worked).

**Action before camp:** redeploy the **current repo code** to every badge (don't trust
the MANIFEST number alone — verify a loaded symbol, per the `badge-deploy-verify-loaded-code`
note). After redeploy, re-confirm on-badge:
```
sudo /tmp/ff-venv/bin/mpremote connect <port> exec \
  "import contact_exchange as ce; print(ce.build_exchange_adv(1)[:3]==bytes([0x02,0x01,0x06]))"
```
→ must print `True`.

---

## Step 4 — truce / camp schedule  ✅ checked, no code change needed

- Server (live DB, game 1): `truce_from=22:00 truce_to=08:00`, `truce_active=0`,
  `QUIET_EARLIEST=20:00 QUIET_LATEST=10:00`. Matches the badge defaults in
  `gotcha.py` (`truce_from/to` 22:00–08:00, D7 night truce). Appropriate for camp.
- `SILENT = False` in `fri3d_friends.py:213` ✓ (siren armed for camp).
- No `gotcha_dbg.txt` writer in the app ✓.
- **Advisory (admin page, not code):** `min_version`/`latest_version` are NULL — set them
  to the frozen ship version so the §8.10.3 update nudge/gate can fire if a post-launch
  fix is pushed (currently inert). `end_at` is NULL — consider setting game-end (16 Aug
  close) so scoring/dormancy closes cleanly. Neither blocks camp.

## Step 5 — Phase 5 web pages  ✅ built this session (server code; **live needs redeploy**)

The player card (`/gotcha/`) was already functionally complete (stats, token-gated
target, all 4 leaderboards, hit list, QR flow, auto-refresh) — the "skeleton" docstring
was stale, now corrected. Added this session:
- **`/klassement`** — a standalone public standings page (4 boards + hit list, full-width,
  auto-refresh) for browsing/projecting without a QR. Linked from the player card header.
- `tests/test_pages.py` (7 tests): page render, 4-board support, public-endpoint shapes,
  and a kill→leaderboard proof via the badge simulator.

**Deploy:** the live backend serves the player card but `/klassement` is **404** — the
server needs a redeploy of current `server/`. (Live `/gotcha/` already shows a "klassement"
link, so there is drift between the repo and the running backend; a clean redeploy resolves
both.) 455 tests green.

## Step 6 — §8.10.3 full-screen UPDATE NODIG  ✅ built this session (badge code)

The stay-killable hunting gate was already built+wired (0.11.22: `below_min` blocks
`request_attack`/`request_reveal`, victim responder untouched). This session added the
**prominent full-screen** half that was the last DEFERRED piece:
- `gotcha_app.py`: `update_prompt()` — the dynamic line (re-derived live, not latched):
  "even synchroniseren..." while the queue holds unsent events, "alles opgeslagen..." once
  drained. Shared `UPDATE_PROMPT_*` constants; 4 new tests.
- `fri3d_friends.py`: a create-once full-screen `_update_overlay` (same discipline as the
  card/setup overlays), driven by `_refresh_update()` each tick. Dismissible (A/X/"Sluiten");
  one showing per below-min stint (rising edge re-arms); never steals the screen from a
  duel/under-attack/overlay; the hunting gate stays armed after dismiss. `onBackPressed`
  wired.
- 455 tests green; `py_compile` clean. **Needs an on-hardware smoke test on deploy** (like
  all LVGL UI) — set `min_version` above the badge's version on the admin page and confirm
  the screen shows, the close button works, and hunting is refused.
