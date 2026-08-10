# !Fri3d Friends — Code review of §8.10 + remediation of every finding — 2026-08-10 (session 2)

Ran `/codereviewer` over the §8.10 phase (commits `cef6ed1` / `5983702` / `7694f9f`, versions
0.11.19–0.11.21), then fixed everything it found. **0.11.21 → 0.11.22.** Host suite **401 → 416
pass**. Nothing deployed to a badge this session — the fixes are code + tests + docs only.

Review document: `Code_Review_Phase8.10_20260810_0514.md` (verdict: PASS WITH NOTES).

## 1. Session setup — this host has no pytest
Same minimal-host problem as 2026-08-09 (no pip, no pytest). Bootstrapped from PyPI wheels:

```bash
cd /tmp && for p in pytest iniconfig pluggy packaging; do
  u=$(curl -s https://pypi.org/pypi/$p/json | python3 -c "import sys,json;d=json.load(sys.stdin);print([f['url'] for f in d['urls'] if f['filename'].endswith('py3-none-any.whl')][0])")
  curl -sLO "$u"; done
mkdir -p /tmp/pylibs && python3 -c "import zipfile,glob;[zipfile.ZipFile(f).extractall('/tmp/pylibs') for f in glob.glob('/tmp/*.whl')]"
PYTHONPATH=/tmp/pylibs python3 -m pytest tests/ -q
```

`python3 -m venv` / `ensurepip` do **not** work here (Debian strips the bundled wheels —
"Install the python3-pip package to use pip itself"). Unpacking pure-python wheels onto
`PYTHONPATH` is the working route. `fastapi`/`starlette` *are* installed system-wide, so the
server tests run too.

Syncthing was **stopped** (`systemctl --user stop syncthing`) for the duration of the edits and
restarted afterwards — per the standing folder-churn caveat.

## 2. What the review found (3 real defects, all in code shipped 0.11.19–0.11.21)

### F-1 · CRITICAL · `target_seen_ago_s` mixed clock domains
`gotcha_app._queue_heartbeat` computed `int(time.time())*1000 - peer["last_seen_ms"]`, but
`last_seen_ms` is a **`ticks_ms()`** reading (monotonic uptime, wraps at 2³⁰), not wall clock.
Result ≈ 8.4×10⁸ s → server clamps to `MAX_EVENT_AGE_S` (48 h) → `note_seen` only moves forward
→ **the write is a no-op**. So the single best evidence that a target is awake was silently
discarded on *every* heartbeat, precisely when the target *was* in range. §10.1 stall detection
and the §3.2 dormancy splice lost their primary input.

Why nothing caught it: `BadgeSim.heartbeat` passes `target_seen_ago_s` in directly, so the
server-side tests exercised the field with correct values; no test covered the badge-side
computation. Bench validation ran with no target in range.

**Fix:** `max(0, time.ticks_diff(time.ticks_ms(), int(peer["last_seen_ms"])) // 1000)` + 3 tests.

### F-2 · MAJOR · `peers_seen` counted friends only
Both callers used `ble.current_peers()`, which deliberately filters `shared_id is None` — it is
the *friends UI* accessor. A badge in a crowd of fifty strangers reported `peers_seen = 0`.
Two server behaviours read it with the opposite meaning:
- `events.py` `if peers: note_seen(pid, ts)` — the "standing in a populated place" sighting bump
  (compounds F-1: both sighting channels failed together).
- `admin.py` §9.5 lonely-kill report selects `COALESCE(p.peers_seen, 99) <= 1` — with friends-only
  counting most badges report 0–1, so most *legitimate* kills land on the suspicion list.

Bench had recorded `peers_seen NULL→0` on a badge with no peers at all — the one state where the
bug is invisible.

**Fix:** new `BLEProximity.peer_count()` → `len(self._seen)`; both callers use it.

### F-3 · MAJOR · §10.4a personal quiet hours were inert end-to-end
`_h_heartbeat` reads `ev["quiet"]` and **no badge code ever sent it**. Worse, the flow was
inverted: the server always emits `me.quiet` defaulting to the camp truce, and
`_do_sync` did `self.quiet = (payload.get("me") or {}).get("quiet") or self.quiet` — so a
personal window set in `config.json` (phone page or on-badge editor) was **replaced by the camp
truce on the first sync**. A parent setting 20:00 on a child's badge got 22:00 back within
`SYNC_S`, and the badge sirens at 20:45 in a family tent — the exact outcome §10.4a exists to
prevent. The server's `in_quiet` re-check and dormancy pause never saw the window either.

**Fix:** heartbeat carries `quiet`; `configure()` records the configured window in `_quiet_cfg`;
the sync read-back adopts the server value **only when the badge has none configured**.

## 3. Spec deviation closed — the stay-killable hunting gate (D-2)
§8.10.3 requires a badge below `min_app_version` to stop **hunting** while its **victim-side
responder keeps running** (if falling behind removed you from the game, not updating would be
perfect invulnerability — the D3 failure mode). 0.11.21 deferred this, so `min_version` in the
admin UI was a control that only printed a banner line. Now built:

- `GotchaController.below_min` set by `_compute_nudge`.
- `_hunting_blocked()` gates `request_attack` / `request_reveal` only (with a Dutch on-screen
  reason, "UPDATE NODIG -- jagen uit").
- `apply_attack` / `apply_reveal` **untouched** — the badge stays killable.
- Test asserts both halves: hunting refused, inbound REVEAL still lands and still fires the
  spotted flash.

## 4. ⚠️ `version_lt` already existed — 0.11.21 duplicated it with a worse one
The review flagged that `_compute_nudge` ordered `version_tuple()` results, which is
length-sensitive: `(0, 11) < (0, 11, 0)` is True, so a host typing a two-segment floor `0.11`
into the admin form would put **every 0.11.x badge below min** and show the whole camp UPDATE
NODIG. While fixing it I found `gotcha.version_lt(a, b)` at `gotcha.py:290` — a correct,
zero-padding, string-taking, already-tested helper from the earlier §8.10 work. 0.11.21 had not
used it and had reintroduced the bug in a parallel code path.

**Fix:** deleted the duplicate; `_compute_nudge` uses the original `version_lt` for ordering,
and `version_tuple` is now documented + tested as a *readability guard only* ("is this a real
version at all"), with a `Do NOT order two of these with <` warning in its docstring.

## 5. Everything else from the review
| ID | Fix |
|---|---|
| F-4 | `alarm_enabled` widened from "the siren" to **every game-initiated sound** — new `beacon_service._alarm_on()` gates the reveal chirp, dodge relief chirp and death tone; `fri3d_friends._render_spotted` gates its `_sting`. LEDs still never gated. The hunt radar ping is deliberately **excluded** (it has its own `PING_ENABLED`; muting it would blind the hunter rather than quiet the campsite). |
| F-6 | `take_fleet_banner` re-arms `_shown_broadcast` when the host clears the broadcast — otherwise re-sending the same text later was silently swallowed. |
| F-7 | `configure()` seeds `broadcast` + nudge from the persisted `state.d`, so a badge booting offline (the normal case, §8.7) is not silent until the next sync. |
| F-8 | heartbeat `alive` reflects `state.alive` instead of a hardcoded `True`. |
| F-9 | an **empty** `groups` list is omitted from the heartbeat — the server's `set_groups` is DELETE-then-insert, so `groups: []` from a half-failed config load would wipe the player's groups every `SYNC_S` (prior review D-47, now unreachable from this path). |
| F-10 | comment in `heartbeat_event` documenting why it deliberately carries **no `commitment`** (the C-2 repudiation hole) so nobody "completes the shape" later. |
| D-3 | §8.10.4 step 3 partially built: below the floor the banner reads *"even synchroniseren voor je update..."* while events are queued and *"alles opgeslagen"* once they are not; `_do_sync` retries at 60 s instead of `SYNC_S` until the queue drains. |
| D-1 | plan §8.10.3 corrected: the field names are `app: {min_version, latest_version}`, never the `min_app_version` of earlier drafts. |
| §7.1 | `_app_version` monkeypatch is now a `monkeypatch` fixture instead of a permanent module-global assignment (was leaking into every later test in the session). |
| §7.2 | `_compute_nudge(app)` takes the `app` dict, not the whole payload. |
| §7.3 | `_app_version()` caches after the first **successful** read (a `"?"` is never cached, so a transient FS failure cannot permanently disable the nudge). |

## 6. 🐛 Pre-existing test bug found while fixing the above
`tests/test_gotcha_callbacks.py::_make_controller` used a **fixed** state path
`/tmp/__gc_cb_gotcha.json`. `GotchaState` persists and reloads it, so the victim-path tests'
`killed_by` events accumulated **across runs** until the 40-slot queue was full of `KEEP_TYPES`
— at which point `EventQueue.add()` correctly refuses everything else, and the new heartbeat
tests failed for a reason with nothing to do with heartbeats. Now a fresh
`tempfile.mkdtemp()` per controller.

Real-world corollary worth remembering: **a badge holding 40 unsent kills sends no heartbeats
until some drain.** That is the intended priority (a kid's kills outrank telemetry), not a bug.

## 7. Files touched
| File | Change |
|---|---|
| `gotcha.py` | removed duplicate `version_lt`; moved/rewrote `version_tuple` next to it as a readability guard; `heartbeat_event` gains `alive`/`quiet`, omits empty `groups`, documents the no-commitment rule |
| `gotcha_app.py` | F-1 clock fix, `quiet` upload + non-clobbering read-back, `below_min` + `_hunting_blocked`, `_compute_nudge(app)` via `version_lt`, D-3 messaging + fast retry, broadcast latch re-arm, offline seed in `configure()`, `_app_version` cache |
| `ble_proximity.py` | new `peer_count()` |
| `beacon_service.py` | new `_alarm_on()` gating all four victim callbacks; `peer_count()` |
| `fri3d_friends.py` | `peer_count()`; `alarm_enabled` on the reveal sting |
| `MANIFEST.JSON` | 0.11.21 → **0.11.22** |
| `tests/test_gotcha.py` | `version_lt` padding, heartbeat `alive`/`quiet`/empty-groups, version_tuple retitled |
| `tests/test_gotcha_callbacks.py` | fresh temp state per controller, `monkeypatch` fixture, 10 new heartbeat-content + quiet + hunting-gate tests |
| `tests/test_ble_proximity.py` | `peer_count()` vs `current_peers()` |
| `Implementation_Plan_Gotcha_20260726.md` | §8.10.1 + §8.10.3 BUILD STATUS for 0.11.22; §9.3 heartbeat row gains `background` + a warning block on the two easy-to-get-wrong fields |

## 8. Verification
- Host suite **416 pass** (401 → 416; +15 net). Full run, not a subset.
- `python3 -m py_compile` clean on all five touched app modules.
- **Not** bench-validated — no badge was flashed this session. 0.11.22 has never run on hardware.

## 9. Follow-ups
- **Deploy 0.11.22 to 9de4 / fac0 / bac8 and bench-validate** before camp. Specifically worth
  watching on-device: `target_seen_ago_s` landing as a small number in the DB with a target in
  range, `peers_seen` > 0 in a room with other badges, and the `quiet` window appearing in
  `players.quiet_from/quiet_to`.
- Prior review **D-47** (server-side: a heartbeat with `groups: []` wipes groups) is still open;
  the badge no longer sends that, but the server should ignore an empty list regardless.
- Prior review **D-50** (badge-side `clamp_quiet` is only applied on the BLE-setup path) still
  open — the server clamps on ingest, so a hand-edited `config.json` window is corrected
  server-side but enforced unclamped badge-locally until the next sync.
- Still deferred by design: the prominent full-screen UPDATE NODIG screen (the banner carries the
  text today), and `training_enabled` (Phase 6, no code path).

---

# !Fri3d Friends — Gotcha §8.10 kill switches + the missing heartbeat/flush path + fleet nudge — 2026-08-10

Continued the Phase 5 §8.10 ("hotfix / update path") work. Three commits, all host-tested
(**401 pass**) and bench-validated on the 3 USB badges. Started **0.11.18**, ended **0.11.21**.
The headline is that the badge→server **event-upload half of the game loop was unbuilt on real
hardware** — fixed and proven end-to-end.

## 1. §8.10.1 — alarm + bounty kill switches (`cef6ed1`, 0.11.19)
The backend already pushes `reveal_enabled`/`bounty_enabled`/`training_enabled`/`alarm_enabled`
in the sync `config` block, but the badge-side reads were missing for two:
- **`alarm_enabled`** — `beacon_service._on_engaged` still fires the held red-LED write (a muted
  badge stays visibly under attack) but skips `_start_siren` when off; the foreground siren trigger
  in `fri3d_friends.py` gates on the same flag. Absent switch ⇒ enabled (older-backend safety).
- **`bounty_enabled`** — `gotcha.validate_attack` downgrades a stray bounty write to a plain target
  attack ("ok") when bounties are off; absent ⇒ "bounty" (on).
- `reveal_enabled` was already gated; `training_enabled` has no code path yet (ships False, Phase 6).
- **Bench-proven on 9de4:** ATTACK still engages (`VICTIM ENGAGED by=9999`) but `SIREN_UNTIL=0`
  with `alarm_enabled=False`.

## 2. §8.10.3 + §9.3 — ⚠️ the badge heartbeat + event-flush path (`5983702`, 0.11.20)
**Critical finding:** the badge queued `kill`/`reveal`/`dodge`/`killed_by`/`attack_started` into
`state.queue`, but **`flush_events` was never called anywhere on the badge, and no heartbeat was
ever sent.** So kills scored on a badge never reached the server — the upload path was exercised
only by the badge simulator in tests, never by real hardware. (The prior session's changelog even
flagged this at item D-6/D-7: "need flush_events/heartbeat".)
- `gotcha.heartbeat_event()`: builder matching `BadgeSim.heartbeat`'s shape
  (`alive`/`battery`/`peers_seen`/`target_seen_ago_s`/`groups`/`background`/`app_version`),
  `app_version` capped at 16 (server C-1 bound).
- `gotcha_app._do_sync()`: now does **heartbeat → flush → sync** once per `SYNC_S` (§9.3 order).
  Queues exactly one heartbeat (de-duping any prior unsent one), flushes, then the GET sync. Flush
  failure never blocks sync (WiFi down ~98% of the time).
- `tick()` gains `battery`/`peers_seen`/`background`; `_gc_tick` (foreground) and the boot
  `beacon_service` pass them (background=True from the boot service → admin sees `bg_service=1`).
  Gated by the existing `online`/`_defer_for_bar` envelope so the new traffic stays inside the §5.4
  coexistence budget (no sync mid-chase).
- **Bench-validated on 9de4** (boot service, WiFi=`casarural`, Funnel HTTPS): pid 1004 DB row
  refreshed `app_version 0.11.0→0.11.20`, `battery NULL→100`, `peers_seen NULL→0`, `bg_service 0→1`,
  `last_seen_at` current. A kill traverses the identical flush path.

## 3. §8.10.3 — broadcast banner + version-nudge (`7694f9f`, 0.11.21)
The sync response already carried `min_app_version`/`latest_app_version` + `broadcast` (server-side
since Phase 1, parsed into state since 0.11.x) but the badge never rendered any of it:
- `gotcha.version_tuple()`: dotted-version compare; a no-digit string (`'?'` from an unreadable
  MANIFEST) parses to `()` so the nudge never fires from an unknown own version.
- `gotcha_app._compute_nudge()`: `< min` → "UPDATE NODIG"; `≥ min, < latest` → soft "Nieuwe versie
  beschikbaar"; `≥ latest` or no server floor → `None`.
- `gotcha_app.take_fleet_banner()`: one-shot edge detector — returns a NEW broadcast (capped 120)
  or nudge once per change, then `None` (no re-spam every sync).
- `fri3d_friends._render_fleet_banner()`: shows it via the existing banner widget, lowest priority
  (only when no duel/arrival banner owns the strip).
- **Bench-validated on 9de4:** a broadcast set in the game row reached `gc.broadcast` over
  `/v1/sync`; nudge computed `0.11.21` vs min `0.11.0`/latest `0.11.30` correctly; banner surfaced.
- **DEFERRED (lower priority, per the plan):** the prominent full-screen UPDATE NODIG + the
  stay-killable hunting gate ("< min stops hunting, victim responder keeps running").

## 4. Backend access + deploy notes (for future sessions)
- **Backend reachable via Tailscale IP `100.64.72.86`** (john-ThinkPad-E15); LAN `192.168.1.57` SSH
  is "No route to host" (Mullvad/Tailscale routing churn). `ssh john@100.64.72.86`;
  `curl http://100.64.72.86:8080/healthz`; DB `/var/lib/gotcha/gotcha.sqlite3` via `sudo python3 -c`.
  Badges talk to it over the **Tailscale Funnel** HTTPS endpoint `https://john-thinkpad-e15.tail44c8ab.ts.net`.
- **Admin cookie auth via curl didn't take** (`/admin/login` → `/v1/admin/broadcast` ⇒ login_required).
  Bench workaround: write game-row fields directly in SQLite
  (`UPDATE games SET broadcast=..., min_version=..., latest_version=...`); `/v1/sync` reads them live.
- **Post-Phase-4 deploy is more wedge-prone:** the boot beacon_service now runs the full proximity
  stack (scan + victim respond), not advertise-only, so BLE IRQs disrupt USB-CDC during cp even at
  the launcher. Reliable pattern: `reset.py` (`machine.reset`, throws I/O as it reboots — normal) →
  `sleep 8` → ONE chained cp session (`cp a + cp b + ...`). A wedged file: reset + retry just that
  file (mpremote's "Up to date" dedup skips matching files). **USBDEVFS_RESET**
  (`fcntl.ioctl(fd, 21780)` on `/dev/bus/usb/<bus>/<dev>`) recovers a wedged CDC without a replug.
- **Probe the running boot service:** write a script to `/tmp`, `mpremote run /tmp/x.py` (NOT inline
  eval — badges run aiorepl). `import beacon_service as bs; bs._ACTIVE` is the live service;
  `_ACTIVE._gc` its headless controller; `_gc.broadcast`/`_gc.nudge_text`/`_gc.take_fleet_banner()`
  read §8.10.3 state post-sync. A USB reset does NOT reboot (code stays in memory); `machine.reset()` does.

## 5. Verification
- Host suite **401 pass** (+15 new this session: alarm kill-switch, bounty downgrade, heartbeat
  shape, §9.3 order, dedup, no-heartbeat-pre-enroll, flush-failure-isolates-sync, version_tuple,
  `_compute_nudge` ×4, `take_fleet_banner` ×4).
- All 3 badges (9de4, fac0/Badge2024lijn, bac8) on **0.11.21**; all 5 §8.10.3 method markers
  verified present on-device.

---

# !Fri3d Friends — Before-camp hardening + externally-exposed backend (Tailscale Funnel, HTTPS sync) — 2026-08-09

Five days to camp (14–16 Aug). Session did the before-camp dev-flag reverts, brought the 3 USB
badges to current, and — when the B&B WiFi turned out to isolate clients — stood up an
**externally-reachable backend over the public internet** plus the badge HTTPS support to use it.
Started 0.11.14, ended **0.11.16**. Two commits: `f681c09`, `8a78ac7`.

## 1. Working-tree cleanup
- The whole uncommitted changeset (~60 files) was **executable-bit churn** (100644→100755) from
  files round-tripped through a permission-blind medium — **zero content edits**. Fixed at the root
  with `git config core.fileMode false`; churn won't recur. Only `.claude/` (session dir) left untracked.

## 2. Before-camp dev-flag reverts (`f681c09`, 0.11.14→0.11.15)
- `gotcha.py` DEFAULTS truce `00:00/00:01` → **`22:00/08:00`** (camp night truce, D7).
- `fri3d_friends.py` `SILENT = True` → **`False`** (kill siren + hunt pings now sound).
- Removed the `gotcha_dbg.txt` writer (`_g_dbg` method + call + `_g_dbg_last` init).
- Byte-compiled clean; truce default parsed (1320/480) on host.

## 3. Badge ops — host toolchain bootstrap (this host is minimal)
This host (ThinkPad, `john-ThinkPad-E15`) has **no mpremote/pip/pytest** (Python 3.14, `ensurepip`
locked). Recipe saved to memory (`badge-dev-host-toolchain`):
- Bootstrap mpremote from PyPI wheels into `/tmp` (`mpremote` + `platformdirs`), run via `PYTHONPATH`.
- **ModemManager grabs the ttyACM ports** → `sudo systemctl stop ModemManager`.
- **`john` not in `dialout`** (EACCES reads as "in use") → ran mpremote via `sudo`. Permanent fix:
  `sudo usermod -aG dialout john` + re-login; plus a udev rule (`ID_MM_DEVICE_IGNORE` for VID `303a`).
- Badges run the asyncio REPL → use `mpremote ... run file.py`, not multi-line `eval`.

## 4. Badge probe + deploy 0.11.15 → cleanup
- Probed all 3 (9de4/ttyACM0, fac0-Badge2024lijn/ttyACM1, bac8/ttyACM2): alive, enrolled, but
  **versions fragmented** (0.11.7 / 0.11.13 / 0.11.14) with dev cruft.
- Deployed 0.11.15 to all 3 via `tools/deploy.sh` (explicit code-file list incl. `gotcha_gatt.py`,
  **excluding `config.json`**), RESET=1, sha-verified. bac8 (former half-deployed casualty) clean.
- Removed stale `gotcha_dbg.txt` + `duel_log.txt`; reset 9de4's stale fake `clock_offset_s`
  (946703400 → 946684800). Confirmed on-badge truce default `22:00 → 08:00`.

## 5. Backend on this machine + truce reset
- The backend was **already running here**: `/opt/gotcha/venv/bin/python -m gotcha_server.main`
  on `:8080` (systemd). This machine is on **casarural WiFi at `192.168.1.177`** (the old
  `192.168.1.57` was a different network).
- Truce reset to 22:00–08:00 via `POST /v1/admin/truce_schedule` over **localhost** (the task that
  was VPN-blocked last session — now local, no Tailscale/Mullvad issue).

## 6. casarural WiFi isolates clients → external exposure
- Diagnosis: badges (.183/.184/.185) and ThinkPad (.177) all on casarural, but **neither can reach
  the other** (ping 100% loss, TCP EHOSTUNREACH/ETIMEDOUT), **no host firewall** (ufw inactive,
  INPUT ACCEPT). L2 ARP resolved but all data dropped = **AP client isolation**.
- The ThinkPad's WiFi card is **managed-only (no AP mode)**, no USB adapter → can't host a hotspot.
- Fix: **Tailscale Funnel** (Tailscale already on the ThinkPad):
  `sudo tailscale funnel --bg 8080` → `https://john-thinkpad-e15.tail44c8ab.ts.net` → `127.0.0.1:8080`
  (HTTPS-only, auto Let's Encrypt). Undo: `sudo tailscale funnel --https=443 off`.

## 7. Badge HTTPS sync support (`8a78ac7`, 0.11.15→0.11.16)
- ESP32 has **no root-CA store** → urequests HTTPS fails `MBEDTLS_ERR_SSL_CA_CHAIN_REQUIRED`.
- `gotcha.py GotchaSync._patch_tls_no_verify()`: for `https://` URLs, monkeypatch `ssl.wrap_socket`
  → `cert_reqs=CERT_NONE` around the single blocking urequests call, then restore. **Safe because
  every request is HMAC-signed (D21)** — integrity/auth doesn't depend on the TLS cert. `_get`/`_post`
  gate it on the URL scheme; plain-HTTP path and host tests unchanged (host helper no-ops → None).
- Validated empirically first: urequests uses `ssl.wrap_socket` (the patch flips verification);
  `urequests.get` over the funnel returned `200 {"ok":true,...}`.

## 8. Badges on casarural WiFi + funnel — verified end-to-end
- mpos stores WiFi in `/prefs/com.micropythonos.system.wifiservice/config.json` as
  `{"access_points": {SSID: {"password": ...}}}` — added `casarural` on all 3, rebooted → connected.
- Set each badge `config.json gotcha.api`/`enroll` = the funnel URL. Deployed 0.11.16 to all 3.
- **Proven:** 9de4 signed `GET /v1/sync` over the funnel → **200**; backend `synced_15m` **0→1**.
  (Backend log source IP is Tailscale's funnel egress, not the badge LAN IP — expected.)

## Notes / follow-ups
- **App does not autostart** on these dev badges (boot to mpos launcher). The sync *path* is proven;
  autonomous sync needs the app launched (A-press) or set to autostart. At camp they'll be running.
- **The funnel URL is public** — internet bots started scanning it within seconds (harmless 404s;
  admin login is the gate). Inherent to "reachable from an external network."
- **Pytest suite (355) not run this session** — no pip/pytest on this host; run on the dev ThinkPad.
- Optional host fixes still open: `dialout` group membership; ModemManager udev rule (it's stopped
  for this session, restarts on reboot).
- Phase 6 (dry run + power measure) and Phase 5 §8.10.4 (contacts.json preservation across AppStore
  updates — a live data-loss bug) remain the priority code work before camp.

---

# !Fri3d Friends — Gotcha Phase 3b: the duel, built + VERIFIED end-to-end on hardware — 2026-08-02

Implemented Phase 3b (the duel, §5.3) from the plan, then brought it up on real badges and
**proved a full kill end-to-end**. Started 0.11.6, ended **0.11.14, 355 host tests green**.

## Build (host-tested pure logic + on-badge wiring)
- **`gotcha.py` (Layer A, +26 tests):** `DuelState` (lvgl-free victim state machine, reused by
  the Phase-4 background responder), `DodgeLedger` (bridges server-synced `me.dodges` ints with
  local offline decay + cooldown), `validate_attack` (ok/busy/no_game/truce/dead/wrong_target/
  protected/on_cooldown/bounty), ATTACK/DUEL/SPOILS/`build_duel_payload` (+REFUSED) payloads,
  `protection_active/_left_s`, `cooldown_ready`, and `kill/killed_by/dodge/attack_started`
  event builders (shapes matched to the server's ingest).
- **`gotcha_gatt.py`:** ATTACK write → `on_attack(parsed, conn)`, `drain_attacks`, `notify_duel`
  (stages value + notifies for a poll-read fallback), `set_spoils`, `central_conn`, IRQ counters.
- **`contact_exchange.py`:** `duel_session` central handshake (connect → discover → best-effort
  CCCD subscribe → write ATTACK → await ENGAGED then KILLED/DODGED → read SPOILS).
- **`gotcha_app.py`:** hunter `_do_attack`/`_handle_duel_result` (verify soul, adopt inherited
  target offline per D10, optimistic score, queue kill), victim `apply_attack`/`_tick_duel`/
  `_on_duel_kill`/`_on_duel_dodge`, `kill_enabled=True`, cooldown-gated `request_attack`,
  `cancel_attack`, `being_connected`, `_in_game`, persistent `duel_log.txt`.
- **`fri3d_friends.py`:** `_render_duel` + `_siren` (buzzer PWM), one red-LED write at duel
  start / one dark at end, ONDER-AANVAL / AANVALLEN / death banners, hunt-strip A→attack/abort,
  scan-pause while connected, cancel-on-exit.

## SIX real on-badge bugs found + fixed (the hard part — each blocked the duel silently)
| # | Bug | Fix |
|---|-----|-----|
| 1 | Hunt strip unreachable by keypad (`_establish_focus` only had `_menu_btn`) | add `_g_target` to focus set + render `A: AANVALLEN` |
| 2 | `duel_session` keyed a dict by `bluetooth.UUID` (not hashable) → discovery matched nothing | compare with `==` like `gatt_write` |
| 3 | `gatts_register_services` **EBUSY while advertising** → nothing registered | `ensure_radio` cycles `active(False/True)` first; register before `begin()` |
| 4 | **`active(True)` on an already-active radio re-inits NimBLE and WIPES the GATT registration** (handle EINVALs after) — the "victim serves no service / n=5" root cause | `begin()` guards `if not self._ble.active()` |
| 5 | Duel required WiFi (connectable + `game_running` gated on `game_live`) | gate on offline-capable `_in_game()` (== enrolled); §8.7 WiFi ~1.7% |
| 6 | Victim's dense scan **suppresses the inbound GATTS-write IRQ** | main loop `suspend()`s scan while a central is connected (§5.5/§5.6) |

## Verification (host-BLE → badge)
`probes/host_duel_hunter.py` (host BLE central; connect via `find_device_by_address` to beat
BlueZ cache misses) drove a full kill against Badge2024lijn:
`connect → GOTCHA_SVC + ATTACK/DUEL/SPOILS → write ATTACK → DUEL{engaged,h=5000,d=1} → 5s hold
→ DUEL{killed} → SPOILS soul=b504603d…`. On-badge screen showed **"UITGESCHAKELD… respawn 1732s"**.
Refusals along the way (`truce`, `protected`) were correct validation firing. **Only the
link-drop DODGE sub-case not yet demoed live** (victim was killed → 30-min respawn).

## Environment / gotchas (see memory `gotcha-phase-status`)
- **This dev box's BT reads the badges at −95 dBm** (marginal; scans see them, connects flaky) —
  badge-to-badge is the reliable link. `hciconfig hci0 reset` between runs.
- **Deploy:** cp wedges USB-CDC while the app is foregrounded (scanning); `mpremote reset` to the
  launcher first (beacon service is advertise-only = quiet enough), then cp fast, ideally all files
  in ONE chained `mpremote` invocation. Repeated USBDEVFS resets can knock a badge **off the USB
  bus** (needs a physical replug — hit 9de4 + bac8).
- **Server/admin (from john-ai):** SSH `192.168.1.57`, sudo; admin pw in `/etc/gotcha/gotcha.env`
  (`mWCtbOZoo9W5VEl`); DB `/var/lib/gotcha/gotcha.sqlite3` (no sqlite3 CLI — use `sudo python3`);
  admin login `POST /admin/login host=&password=` → cookie; `POST /v1/admin/player/{pid}`
  (reassign/protect/…), `POST /v1/admin/truce_schedule`. `sync` does NOT bump last_seen/app_version
  (only heartbeats do) — don't infer "offline" from a stale version.
- **DEV truce override (0.11.14):** badge DEFAULTS truce → **00:00/00:01** + server game truce
  00:00-00:01 so the night truce doesn't block dev. **Revert before camp** (with `SILENT→False`,
  remove dev log writers). 5 truce tests made robust to the default value.

## State at session end
- **9de4** (1004) + **Badge2024lijn** (1007) both on 0.11.13/0.11.14; bac8 half-deployed (its own
  extra deploy wedged — inconsistent, needs finish/rollback). All Phase-3b code committed
  (`cf449c9`…`7d9cef3`). **9de4 fell off the USB bus** at session end — needs a physical replug
  before the new `gotcha.py` (00:00-00:01 truce) can be pushed to it.

---

# !Fri3d Friends — Gotcha Phase 3b plan + session handoff — 2026-08-01

Paused development for handoff to another session/model. Phase 3a (Reveal) is **built +
committed (`669db48`, 0.11.5, 336 tests)** with the connect path PROVEN on-badge. Drafted the
**Phase 3b (the duel) plan** — saved to `Implementation_Plan_Gotcha_Phase3b_20260801.md`
(planned, not started; the next session resumes there).

Key handoff notes for the next session:
- **Phase 3b escape mechanic pivots to link-drop**: `gap_conn_rssi` does NOT exist on this
  MicroPython build (verified against the bluetooth API), so §5.3's RSSI-threshold escape is
  unimplementable — escape = run out of range → link drops before `KILL_HOLD_MS` (the plan's own
  fallback). Plan step 0 re-probes the badge firmware for it anyway.
- **Reveal full end-to-end not captured** — blocked by test-harness issues only (WiFi-timing on
  the continuously-syncing shipping app + probe/shipping-app advertising-set conflict + churned
  badges), NOT a game blocker. Re-run as a clean badge-to-badge test (two badges running only the
  probe). Findings in memory `gotcha-connect-path-findings` / `gotcha-reveal-probe-status`.
- **Dev badges:** 9de4 (pid 1004) + bac8 (pid 1003) enrolled; BAdge2024lijn not enrolled (no
  gotcha.api in config). gotcha.b1 probe app removed from 9de4/bac8. Backend running.
- **Overall phase status** in memory `gotcha-phase-status` (START THERE next session).

---

# !Fri3d Friends — Gotcha Phase 3a on-badge probe: connect path PROVEN + Flags-AD fix shipped — 2026-08-01

Ran the Phase 3a Reveal probe on the three dev badges (9de4 / bac8 / BAdge2024lijn).
**The core question is answered YES: a badge accepts a Gotcha GATT connection** — a host
bleak client connected to the badge running the shipping `GotchaController`+`GotchaService`,
and the Gotcha service (all 4 chars) was discoverable on a clean launch. Suite **333 → 336**
(+3 Flags-AD tests). MANIFEST **0.11.4 → 0.11.5**.

Four hard findings from the probe (all in memory `gotcha-connect-path-findings`); one needed
a shipping-code fix, the rest are operational/test-harness:

- **Connectable advert MUST carry a Flags AD** — `gap_advertise(connectable=True)` with only
  the HSNT manufacturer AD is advertised but NOT accepted as connectable (BlueZ/hcitool hang
  forever). **Fixed** in `ble_proximity.build_payload`/`name_budget`: `connectable=True`
  prepends `02 01 06` and reserves 3 name bytes. `parse_payload` already skips non-MFG ADs.
- **WiFi transfers block BLE connections** (a sync in flight → connect hangs). The game's
  `HUNT_SYNC_DEFER` already covers this; the probe syncs once then stops. This is why the
  continuously-syncing shipping app is hard to connect to, while the probe (sync-once) worked.
- **`gatts_register_services` is once-per-power-on** — relaunching the Gotcha task in a
  session leaves handles unbound. Operational rule: one launch per boot (a clean boot is the
  only reliable reset; the dev badges resist software reset).
- **BlueZ can't scan + connect at once** ("Operation already in progress"). Fixed in the host
  hunter (stop the scanner before connecting).

**Full write-REVEAL→SPOTTED end-to-end not yet captured:** blocked by churned badge state
(repeated cancel/relaunch flooded TaskManager; the stale `gotcha.b1` probe app kept
auto-starting on 9de4/bac8 and wedging USB-CDC) + the WiFi-timing flakiness on the
always-syncing shipping app. Needs a clean-boot, single-launch run (replug, no churn) — the
probe with WiFi-stop + the fixed hunter should then pass in one shot. Findings saved to
memory for the next session.

---

# !Fri3d Friends — Gotcha Phase 3a: the Reveal (§5.7) — 2026-07-31

First half of Phase 3: the **Reveal** — the disambiguator that makes a hunter's target
flash gold + chirp + show SPOTTED when the hunter presses A within `REVEAL_RSSI`. Built
first because it is the shortest GATT interaction (write → ack → disconnect → flash) and
proves the connect path the duel (Phase 3b) shares. **Suite: 321 → 333 passed** (+12 host
tests). MANIFEST **0.11.3 → 0.11.4**. Not yet deployed/probed on a badge.

Until now the game was radar/beacon-only (`connectable=False`, no Gotcha GATT service). 3a
stands up the whole connect substrate:

- **Layer A (pure, `gotcha.py`)**: `build/parse_reveal_payload`, `decide_strip_action`
  (§5.7 D29 ladder; attack branch gated off until 3b), `reveal_ready`, `validate_reveal`
  (no protection/cooldown check — §5.7/§5.8), `spotted_active`, `reveal/revealed_event`.
- **`gotcha_gatt.py` (new)**: `GotchaService` registers `GOTCHA_SVC` with all 4 chars now
  (ATTACK/DUEL/SPOILS stubbed for 3b, REVEAL live) so the handle layout is locked; lvgl-free,
  injected `on_reveal`, IRQ-safe queue.
- **`ble_proximity.py`**: `addr` in the peer entry + `addr_for_pid()`; connectable beacon
  mode; `_irq` forwards non-scan events to the Gotcha responder (§5.6).
- **`contact_exchange.py`**: `attach_gotcha` + position-based bind; reusable `gatt_write`
  central-write coroutine (clones the proven `_run_client`).
- **`gotcha_app.py` / `fri3d_friends.py`**: hunter `_do_reveal` (suspend→connect→write→
  resume), target `apply_reveal` (gold flash + chirp + SPOTTED), the `_gatt_busy` LED-skipping
  guard (§5.5), connectable-on-game-live, and the focusable hunt-strip A-action.

**Probe (Layer-B exit gate) NOT yet run** — hardware is available (3 Espressif badges;
backend `running`), but deploying + driving a 2-badge reveal is iterative and hard-to-reverse,
so it is staged for a focused session. Risks to verify on hardware: the connectable HSNT
beacon (Flags-AD/name budget), register-services-after-begin order, the lvgl A-on-strip focus
routing, and the IRQ handoff around suspend/resume.

---

# !Fri3d Friends — Gotcha Phase 0–2 code-review fixes (5 CRITICALs + 12 MAJORs, +8 regression tests) — 2026-07-31

Acted on **`Code_Review_Phase0-2_20260731_1803.md`** (the review from the previous
session, entry below). Closed **all 5 CRITICALs**, the two "blocking" MAJORs, and a
strong set of "strongly-recommended" MAJORs, each with a regression test that fails
on `80568a9` and passes now. **Suite: 313 → 321 passed** (8 new tests), 0 failed.
MANIFEST bumped **0.11.2 → 0.11.3** (app code changed). Not yet deployed to a badge.

Syncthing was stopped for the duration of the edits (project dir is Syncthing-synced;
heavy multi-file edits risk ENOENT/data-loss) and restarted at the end.

## CRITICALs — all fixed

| # | Fix | Files |
|---|---|---|
| **C-1** stored XSS on admin dashboard | Added `esc()` to the dashboard script; wrapped the 4 sinks (`app_version`, `broadcast`, 2×`display_name`); capped `app_version[:16]` in the heartbeat handler | `pages.py`, `events.py` |
| **C-2** soul commitment not binding within a life | `_rotate_commitment` no-ops when the current life already has a commitment; `start_life` SQL gained `WHERE lives.commitment IS NULL` | `events.py`, `service.py` |
| **C-3** voided row permanently blocks kills | Dup lookup filters `voided=0`; `reported_life` resolved from the `lives` window by `at` (inclusive end, earliest life); `_insert_kill` clears a stale voided marker before a genuine kill (avoids the `UNIQUE(victim_pid,victim_life_id)` collision) | `events.py` |
| **C-4** half-applied kill committed | `db.rollback()` as first statement of both `except` arms in `ingest_batch` | `events.py` |
| **C-5** game-admitted peer crashes render tick | `current_peers()`/`has_peers()` skip `shared_id is None` (root D-32 fix); `_color_for_gid` is `None`-tolerant (defense-in-depth) | `ble_proximity.py`, `fri3d_friends.py` |

## MAJORs — fixed

| # | Fix | Files |
|---|---|---|
| **D-8** bounty kill orphans a hunter | Ring inheritance only when `is_target`; otherwise `splice_out` the victim, leave assassin pointer alone | `events.py` |
| **D-12** table sweep 2nd kill refused | `ingest_batch` uses a request-entry reporter snapshot for the 1st event, then folds in the reporter's target *after each accepted event* — captures intra-batch inheritance without adopting `reconcile`'s reassignment | `events.py` |
| **D-9** spoofable `X-Forwarded-For` voids Sybil detector | Removed `proxy_headers`/`forwarded_allow_ips="*"` (this process is the edge) | `main.py` |
| **D-10** `set_tunables` accepts any type | `_coerce_tunable` coerces each value to its default's type; uncoercible values rejected, not stored | `service.py` |
| **D-11** integral-float tunable breaks response sigs | Server `canonical_json` normalizes integral floats to int form to match the badge's `_cj_float`, incl. the `-0.0` exception | `crypto.py` |
| **D-5** `HUNT_SYNC_DEFER` had no cap | `_defer_for_bar` caps the hold at `HUNT_SYNC_DEFER_MAX_S` from the **last successful sync**; honours the on/off tunable | `gotcha_app.py` |
| **D-22** game block lost on resume / offline target not admitted | `start()` clears the change-gate caches and re-pushes the game block + `set_game_context` | `gotcha_app.py` |
| **D-25** malformed truce schedule fails open | `from_sync` adopts a schedule only when **both** ends parse as HH:MM; else keeps the DEFAULTS 22:00–08:00 window (fail closed) | `gotcha.py` |
| **D-27** corrupt-but-valid-JSON state poisons sync | `load()` type-guards each key against its blank default (a wrong-typed value is rejected) | `gotcha.py` |
| **D-28 / D-31** enrolls as BadgeXXXX / hardcoded version | Enroll under the chosen name (auto-nick only when unset); report the real MANIFEST version via `_app_version()` | `gotcha_app.py` |
| **D-29** ALIVE advertised unconditionally | `_make_game_block` sets ALIVE only when not dead and PROTECTED when protected (derived from status) | `gotcha_app.py` |
| **D-32** game peers leak into friends UI | Same root as C-5 (`current_peers`/`has_peers` filter) | `ble_proximity.py` |
| **D-40** non-ASCII in the always-visible chip | `·`/`—` → `-` (built-in montserrat fonts are ASCII-only) | `gotcha_app.py` |

## Regression tests added (8)

`test_two_kills_in_one_batch_both_land` (D-12), `test_a_heartbeat_cannot_rotate_the_live_commitment` (C-2),
`test_a_late_killed_by_after_respawn_leaves_the_victim_killable` (C-3),
`test_bounty_kill_does_not_orphan_the_victims_hunter` (D-8),
`test_heartbeat_app_version_is_capped` (C-1) — in `tests/test_server_api.py`;
integral-float payloads incl. `-0.0` in `tests/test_server_crypto.py` (D-11);
`test_current_peers_and_has_peers_exclude_game_admitted` (C-5/D-32) in `tests/test_ble_proximity.py`;
`test_from_sync_malformed_truce_schedule_fails_closed` (D-25) and
`test_gotcha_state_load_valid_json_wrong_types_degrades_safely` (D-27) in `tests/test_gotcha.py`.
These close the two test shortcuts the review named: *one kill per batch after `_force_target`*,
and *two group-sharing badges*.

## Non-obvious implementation notes

- **`killed_by` life resolution (C-3):** the query is
  `started_at <= at AND (ended_at IS NULL OR ended_at >= at) ORDER BY life_id ASC LIMIT 1`.
  Inclusive `>=` + earliest life is deliberate — `apply_death` sets the old life's
  `ended_at` and the new life's `started_at` to the **same instant**, so a death that
  lands on the boundary must map to the life that *ended* there, not the one that began.
  Getting this wrong first broke `test_both_halves_of_one_death_dedupe` and
  `test_a_replayed_soul_cannot_kill_the_next_life` (a spurious voided row on the new life).
- **D-12 vs `reconcile`:** a naive per-event re-read of the reporter row also picks up
  `reconcile`'s target reassignment (it strips a's target once the victim goes dormant),
  which broke `test_a_kill_made_before_the_truce_still_counts_when_it_uploads_later`. The
  fix uses the pre-`reconcile` entry snapshot for the first event and refreshes only *after*
  an accepted event.
- **D-11 float parity:** the badge's `_cj_float` keeps `-0.0` as `"-0.0"` (guarded), so the
  server normalizer mirrors that exact exception — the crypto test pins it with a `-0.0`
  payload.

## Deferred (with reason) — not blocking, noted for follow-up

- **D-20 / D-21 (radar segment mappings)** — the review sequences these *with* the
  worn-on-worn walk as calibration; existing tests pin the current mapping. Re-deriving
  `lit` blind risks miscalibrating the only proximity cue.
- **D-23 / D-24 (blocking I/O on the OS loop; event-driven connectivity)** — a `_thread`
  dispatch / `ConnectivityManager`-event refactor in untested glue; higher risk.
- **D-6 / D-7 (opt-out / heartbeat reaching the server)** — need `flush_events`/heartbeat
  call sites wired into the Activity loop; review scopes consequences to Phase 3+.
- **D-26 (unsynced-clock phantom truce)** — needs nuanced cross-module sound-suppression.
- **D-30, D-33, D-13–D-19** — HTTPS (Phase 5), hardware layout, and code-level anti-cheat
  items, several unreproduced and off the Phase-3 critical path.
- **D-38 / D-39 and other MINORs** — low real-world risk (ping wrap at 12.4 days vs 3-day
  camp) with host-test friction.

## Verification

```bash
python3 -m pytest -q     # 321 passed in ~8 s
python3 -m py_compile app/com.fri3dcamp.fri3dfriends/{gotcha_app,fri3d_friends,ble_proximity,gotcha}.py
```

`gotcha_app.py` and `fri3d_friends.py` remain host-untested (the review flagged this);
their fixes were compile-checked and kept to small, clearly-correct edits. The pure
layers (`gotcha.py`, `ble_proximity.py` wire half, all server modules) carry the new tests.

---

# !Fri3d Friends — Gotcha Phases 0–2 full code review (5 CRITICALs, all reproduced) — 2026-07-31

A read-only review of **Phase 0 (hardware spikes), Phase 1 (backend) and Phase 2
(badge-side game)** at commit `80568a9` / MANIFEST 0.11.2, against
`Implementation_Plan_Gotcha_20260726.md`. Output:
**`Code_Review_Phase0-2_20260731_1803.md`** (1102 lines) in the project root.
**No project file was modified** — `git status` shows only the new report.

**Verdict: MAYBE — do not start Phase 3 until the five CRITICALs are closed.**
Phase 3 (duel + Reveal) builds on the kill path, the ring and the LED radar bar;
three CRITICALs are *in* the kill path and one disables the radar bar.

## Method

Plan mode first, then four parallel review agents (Phase 1 core / Phase 1 edge /
Phase 2 pure half / Phase 2 integration), with **every load-bearing claim
re-verified by me** before it entered the report. Findings are marked
✅ *reproduced* (executed on this commit) vs ⚠️ *code-level* (read, not run).
Two agent claims did **not** survive verification and were corrected or dropped —
subagent output was treated as a lead, not as a finding.

Repro harness: throwaway pytest files in the session scratchpad driving the real
ASGI app through `tests/badge_sim.py`, run with

```bash
PYTHONPATH="$PWD/app/com.fri3dcamp.fri3dfriends:$PWD/server:$PWD/tests" \
  python3 -m pytest <scratchpad>/test_verify.py -q -s -p no:cacheprovider -p conftest
```

(the `-p conftest` + `PYTHONPATH` dance is needed because the file lives outside
the project rootdir, so pytest will not pick `tests/conftest.py` up on its own).

Project suite at review time and after: **313 passed, 0 failed, 0 skipped** (7.7 s).

## 1. Phase 0 — re-audited from raw data: PASS

All three analysis tools were re-run against the committed logs. **Every published
figure reproduces exactly**, which is the strongest single result of the review.

| Tool | Reproduced |
|---|---|
| `tools/analyze_coex.py` | 3.66 → 3.01 → 1.53 adv/s at 50 % duty; worst gap 14.9 s vs `EVICT_MS` 30 s; GATT handle groups `[16,18] [21,23,25,27,30,32] [35,37,40,42]` |
| `tools/analyze_rssi.py` | NO-GO across all five walks (up 32–69 %, bar 80 %) |
| `tools/analyze_shadow.py` | §11.1's pre-committed `KILL_RSSI` table and the asymmetric-vs-symmetric arm windows, line for line |

Both binding Phase 0 rules **are** honoured in shipped code: sync is deferred while
the bar is lit (`gotcha_app.py:156-158`), and the scan stays at 50 % unconditionally
so a hunt is never starved. The §11.1 correctness requirement — never ship the
symmetric `a=0.3` EWMA on the hunt path — is also met.

Phase 0 findings (all minor):

- `KILL_RSSI` ships **−65** though §11.1 pre-committed **−68** when the worn-on-worn
  walk is skipped (it was). *Nuance:* `analyze_shadow.py`'s own decision rule picks
  −65 at both 0 dB and the expected −4 dB penalty, so −65 is defensible on the
  evidence — but the point of a pre-commitment is not to relitigate it.
- **Plan correction:** §11.1 says shipping −68 costs *"3 % false arming"*. Its own
  table gives **10 %** at −68; 3 % is the −65 figure.
- `tools/analyze_rssi.py`'s verdict banner states the **opposite** of its conclusion
  (*"a single triple meets the >=80% bar"* — should be *"no single triple"*). Report
  text is correct; only the tool string is inverted.
- The 12.5 %-busy coex row rests on **n=9 adverts per peer**; don't quote it as precise.
- The 12.5 % background scan duty is unimplemented (~37 mA unbanked) — safe direction,
  belongs to the §8.7 lever-4 ladder.

## 2. The five CRITICALs (all reproduced)

| # | Where | What |
|---|---|---|
| **C-1** | `pages.py:275-289` | **Stored XSS on the admin dashboard.** The player card defines `esc()`; the admin script does not, and interpolates `app_version`, `broadcast`, `display_name` into `innerHTML`. `_h_heartbeat` (`events.py:460-466`) stores `app_version` with **no length cap** (enroll caps at 16). One signed heartbeat from any enrolled player → script runs same-origin with the `gotcha_admin` cookie on the host's phone. |
| **C-2** | `events.py:326-339` → `service.py:125-130` | **The soul commitment is not binding.** `_rotate_commitment` calls `start_life` with the *current* `life_id`, and the upsert overwrites the live commitment in place. `lives` keeps history across lives, not within one. Reproduced: victim heartbeats a fresh commitment mid-chase → assassin's genuine kill returns `bad_soul`, victim stays active. Defeats §3.4 entirely. |
| **C-3** | `events.py:157-165` + `:211-235` | **A voided kill row permanently blocks that life.** The dup lookup does not filter `voided=0`, and `kills` has `UNIQUE(victim_pid, victim_life_id)`. Reproduced **with zero malice**: assassin kills v (life 0→1) → v respawns → v's queued `killed_by` lands, voided as `protected` at life **1** → every later legitimate kill on life 1 returns `already_dead`, and since v never dies, `life_id` never advances. `RESPAWN_S` is 30 min, so this happens on the first camp afternoon. |
| **C-4** | `events.py:83-89`, `db.py:292` | **No rollback anywhere.** The `except` arm records the event as *rejected* and commits. `Database.rollback` has **zero callers**; `db.lock`'s docstring ("held for the whole of a request's read-modify-write, see routes") is false — no route acquires it. A mid-handler failure banks the score, kills nobody, leaves an orphan `kills` row (→ C-3), and the badge drops the event. |
| **C-5** | `fri3d_friends.py:1138` ← `ble_proximity.py:733` ← `:223` | **A game-admitted peer crashes the render tick.** `admit_peer` admits the target with **no shared group** (D9), so `shared_id=None`; `current_peers()` emits it; `_fill_row` calls `_color_for_gid(gid)` unguarded → `None * 137.508` → `TypeError`, swallowed by the loop's blanket `except Exception: pass` (`:1905`). Everything after `_refresh_nearby()` is skipped for as long as the target is in range — **`_update_leds` (the Phase 2 headline LED radar bar), battery, clock, NTP resync, banner auto-hide, backlight dim.** |

C-5's blast radius, in loop order:

```
1883  self._render_gotcha()      <- runs (this is why the field test looked fine)
1886  self._refresh_nearby()     <- RAISES
1892  self._update_leds(now)     <- SKIPPED   <- the §8.8 LED radar bar
1893-97 battery / clock / setup / NTP / banner / dim   <- SKIPPED
```

Phase 2's stated exit criterion (*"a live on-screen radar bar **and** a live LED
bar"*) is therefore **not met**.

## 3. Why none of this was caught

Two specific test shortcuts, each of which removed exactly the condition under
which the bug exists:

1. **Every full-stack kill test posts one kill per batch after `_force_target`.**
   C-3, the bounty-orphan bug and the sweep bug all live in that gap.
2. **The two-badge hardware test used badges that share a group** (9070 + 1cdb),
   so `shared_id` was never `None` and C-5 could not fire.

Plus: `current_peers()` has **no test at all** (needs a `time.ticks_*` shim), and
`gotcha_app.py` has **no tests at all**.

Four tests also pin the *bug* rather than the spec — notably
`test_hunt_ping_silent_below_floor_and_disabled` asserts `hunt_ping(-80) is None`,
but −80 **is** `REVEAL_RSSI`, where §8.8.6 specifies a 700 ms ping.

**Six cheap additions would have caught nine findings:** assert the alive-player
pointer graph is one cycle after every full-stack kill test; post two kills in one
flush; flush a `killed_by` after respawn; rotate a commitment via heartbeat between
a kill and its flush; call `current_peers()` with a game-admitted peer; put an
integral float in the crypto payload set.

## 4. Selected MAJORs (33 total)

**Reproduced:**

- **Two kills in one batch → the second is rejected** `not_your_target`
  (`events.py:61-96` reads the reporter row once per batch). D16 removed the kill
  cooldown *specifically* so sweeps are legal, and `HUNT_SYNC_DEFER` guarantees a
  sweep arrives as one batch. Streak under-counts too.
- **Every bounty kill orphans a player.** `_apply_kill` applies §3.2's inheritance
  to bounty kills, where the assassin is not the victim's hunter. Reproduced on a
  10-player ring: `orphans=[1007] double-hunted={1010: [1002, 1003]}`. `reconcile()`
  never repairs it — loop 3 checks every player *has* a target, never that every
  player *has a hunter*.
- **An integral-float tunable silently stops every badge syncing.** Badge
  `canonical_json` renders `2500.0` as `2500`; the server's stdlib `json.dumps`
  renders `2500.0`. Proved end-to-end: `PROX_ALPHA_UP: 1.0` → badge response
  verification `False`. `set_tunables` stores admin values with no coercion.
- **A malformed truce schedule fails OPEN.** `{"from": "22.00"}` → `truce_active`
  at 23:00 camp returns `'none'`. A host typing `22.00` disables the night truce on
  every badge within `SYNC_S`.
- **An unsynced clock gives a 6 h phantom truce, then none ever**
  (camp-local `02:00 + uptime`).
- **Corrupt-but-valid-JSON `gotcha.json` kills syncing permanently** —
  `{"state": "broken"}` → `apply_sync` raises `TypeError`, `_do_sync` catches,
  logs and reschedules forever.
- **Three different RSSI→segment mappings.** Screen bar `round(5f)`, spec `ceil(5f)`,
  LED bar threshold-based — and the **LED bar is frozen at 4-of-5 amber across
  −80…−66 dBm**, the entire final approach. At kill range the LED bar says 5/5 red
  while the screen says 3/5.
- **Hunt-ping silent floor off by one segment** (`thr = pfs/5.0` = 0.6, but the
  screen bar's segment 3 starts at 0.5). §8.8.6's 700 ms rung is unreachable;
  single-tap pings exist only in the 4 dB window −69…−65. `_bar_lit()` uses a
  *third* threshold, so "the bar is at `PING_FROM_SEG`" means three different dBm
  values in three places.

**Code-level:**

- `HUNT_SYNC_DEFER_MAX_S` defined on both sides, **enforced on neither** — the
  server README explicitly says *"Phase 2 must implement it"*. A permanently lit bar
  starves sync; at small scale the server reads it as a camp-wide outage.
- **Opt-out never reaches the server.** `flush_events` has **no call site anywhere
  in `app/`**, and no `optout` event is queued. A player who withdraws consent stays
  somebody's target, unfindable, for up to `TARGET_STALE_H` (6 h).
- **No heartbeat is ever sent** — yet `tests/badge_sim.py:107` implements the §9.3
  cadence correctly. The reference harness and the shipped badge have diverged.
- **The v2 game block is lost after any pause/resume** — `onResume` calls
  `_ble.begin(...)` with no `game=`, and `_push_game_context` is cache-gated so it
  never re-pushes. D3's "closing the app is a shield" arriving by accident. An
  offline badge never admits its target at all.
- `forwarded_allow_ips="*"` with **no reverse proxy** → client IP is caller-controlled,
  voiding the enroll rate limit *and* §9.5's only Sybil detector.
- `set_tunables` accepts any value of any type, including server-only `SIG_WINDOW_S`
  → `{"SIG_WINDOW_S": "ten"}` is a camp-wide 500 with no signed error.
- Blocking I/O on the OS asyncio loop: `_conn_probe` is an `async def` with **zero
  awaits** containing a 4 s socket connect + an 8 s `urequests` GET, every 30 s.
- §7 connectivity is **polled** (spec says event-driven), `online` is never
  invalidated when WiFi drops, and the 1.1.1.1 fallback is missing.
- `GFLAG_ALIVE` advertised unconditionally (dead badges broadcast ALIVE — inverts D11).
- Badge enrolls as **`BadgeXXXX`**, never the player's chosen name (§13).
- `app_version` hardcoded `"0.11.0"` vs MANIFEST `0.11.2`.
- Enrollment posts `player_key` over **plain HTTP** (§6.2 requires the one TLS handshake).
- Backdated/forward-dated `at` bypasses spawn protection, truce and quiet hours.
- `peers_seen > 0` refreshes your **own** `last_seen`, so §10.1 never fires in company.
- `ATTACK_COOLDOWN_MS` is written to `attacks` and **never read**.
- Batch overflow returns kills in the `rejected` list → the reference badge drops them.
- Admin: cleartext password/cookie on :8080, no login throttle, 120k-round PBKDF2
  synchronously on the event loop, unbounded body buffered pre-auth.

## 5. Notable MINOR/INFO

- `gotcha_dbg.txt` is change-gated on a **float** (`prox`), so it writes to flash
  ~1–3×/s during a hunt, on the render thread. Comment claims "negligible flash wear".
- `SILENT = True` still ships in 0.11.2 — the hunt ping is mute on every badge.
- The demo task is untracked and uncancelled (`_stop_task` covers `_task`,
  `_splash_task`, `_exch_task` only) — the F-4 class the exchange task is guarded against.
- `solid_frame` is written **and tested** but has **no caller** → §8.8.3's
  dead/protected/battery-low strip states never appear. §8.8.7 `KWIJT` is absent entirely.
- `_hex` is **defined twice** (`gotcha.py:40, 704`); the second shadows the first.
- Three non-ASCII chars (`·`, `—`) in the always-visible status chip; the built-in
  fonts are ASCII-only (the codebase already avoids U+2026 for this reason).
- `hunt_ping` uses raw `now_ms - last_ping_ms` instead of `ticks_diff` → permanently
  silent after the 2³⁰ wrap (~12.4 days; camp is 3 days).
- **`DESIGN.md` §11 is not marked superseded**, which §8.8.1 requires when the radar
  bar ships. §13's required README statement ("Gotcha is an optional online mode")
  is absent from both `README.md` and the MANIFEST `long_description`.
- The truce close-out note is **stale**: both sides already ship 22:00–08:00, not
  23:00–07:00. Two of the three pre-camp dev flags remain.
- **Demo mode is built**, contrary to "demo deferred" in the commit message — what
  was deferred is the on-badge tap-verification.

## 6. Things confirmed correct (worth not re-reviewing)

- §4 HSNT v2 wire format byte-for-byte; `OVERHEAD = 12` reproduces the plan's arithmetic;
  company-id + magic gating, reserved-bit rejection, UTF-8 boundary truncation.
- `admit_peer` / `evict_lru` pure and correct; the target survives eviction as the
  oldest entry. IRQ discipline preserved (bounded 256-entry `_pending`; all parsing
  on the loop thread).
- Request signing matches the server byte-for-byte including the **full request target
  with query** (server README interpretation #1); nonce replay via
  `PRIMARY KEY (pid, nonce)` with no TOCTOU; constant-time compare throughout.
- Badge tunable defaults vs server: **zero value mismatches** on shared keys.
- Atomic temp+rename persistence with correct MicroPython flush/close semantics.
- Truce/quiet half-open windows with midnight wrap; `_coerce` checks `bool` before `int`.
- `state.py`'s interval algebra and `test_server_plan_parity.py`, which *measures* the
  `outage_intervals()` rounding direction across all 60 bucket phases.
- Prior Phase 5 review's five MAJORs (F-1…F-5) all fixed and recorded.
- The opt-out fix `1191558` is complete **on the badge side** — every local path back
  into enrollment traced; only the server half is missing.
- No `WifiService.save_network/forget_network/disconnect` anywhere; no credential in
  the repo. No age/cohort, no location, no `witnesses[]` in the schema (§13 honoured).

## 7. Recommended fix order (from §9 of the report)

**Blocking, before Phase 3 (~one focused day):** C-5 (one line in `_fill_row`) →
C-2 (one `WHERE lives.commitment IS NULL`) → C-3 (`AND voided=0` + resolve
`reported_life` from `lives` by `at`) → C-1 (`esc()` + cap `app_version`) →
C-4 (`db.rollback()`) → sweep fix (re-read the reporter row per event) →
bounty inheritance gate.

**Then re-run the two-badge test with badges that do NOT share a group.**

**Before the first playtest:** the `forwarded_allow_ips` one-liner, tunable type
validation (fixes both the brick and the float-signature bug), the game-block
re-push, the deferral cap, the three fail-open badge paths, the radar mappings
(**before** the worn-on-worn walk — the walk calibrates a bar that currently
disagrees with itself), and the name/alive-flag/version one-liners.

**Then:** run the §11.1 walk and set `KILL_RSSI` from data rather than the fallback.

## Notes

- The review was read-only by construction: `git status` after the session shows a
  single `??` entry, the report itself. Repro scripts live in the session scratchpad
  and are ephemeral.
- The project's habit of **writing reasons down at the code** (the four server
  interpretation calls, `ring._interleave`'s local-minimum analysis, `clock.py`'s
  fixed camp offset) made the audit tractable — worth keeping.
- Conversely, four docstrings assert the **opposite** of their code
  (`_rotate_commitment`, `db.lock`, `html_escape`, `_g_dbg`) and each actively
  prevented its bug from being found.
- The defects are not carelessness. They are two test shortcuts, each of which
  removed exactly the condition under which the bug exists. Closing those two gaps
  is worth more than any individual fix on the list.

---

# !Fri3d Friends — Gotcha Phase 2 close-out: first-run consent (§13) — 2026-07-31

The last Phase 2 code piece — the **§13 first-run consent screen** — is built,
deployed (MANIFEST 0.11.2) and **verified on-badge (bac8)**: a never-enrolled
badge that detects a running game shows a one-time 'Gotcha' overlay (explanation
+ `Meedoen` / `Niet meedoen` / `Laat zien wat de badge doet`); Meedoen enrolls,
Niet meedoen declines for the session, X = decline. Auto-enroll was removed —
consent drives enrollment. Controller gained a `/healthz` game-state probe +
`consent_needed`/`request_enroll`/`decline_consent`.

Bug fixed en route: opt-out was instantly undone because `tick()` gated
auto-enroll on `not self.enrolled` (also true while opted out) → re-enrolled
(`GotchaState.enroll` resets `opted_out`) → 'Meedoen' re-opts-out. Now gated on
`not ever_enrolled()` + a defensive `_do_enroll` guard (commit `1191558`).

**Known issue, deferred:** the in-consent / menu **demo mode** runs but does not
render correctly (colours/captions off) — to investigate later. Logged, not
blocking.

**Phase 2 is CODE-COMPLETE.** Two field items remain (neither is code):
1. §11.1 worn-on-worn threshold walk (~30 min, two people, `tools/analyze_shadow.py`)
   to finalise `KILL_RSSI`; if skipped, ship −68 and measure at first playtest.
2. Before camp: `SILENT=True→False`, truce schedule `23:00–07:00→22:00–08:00`,
   remove the `gotcha_dbg.txt` writer.
Next: **Phase 3 (the duel + Reveal).**

---

# !Fri3d Friends — Gotcha Phase 2: integrated into the shipping app (radar live) — 2026-07-30

The Phase 2 exit is now in the **shipping `fri3d_friends.py` app**, not just the
probe: two real badges run the actual app, enroll, sync, target each other, and
show a **live on-screen radar bar lit red at kill range**.

**On-badge result (9070 + 1cdb → `192.168.1.57:8080`, game `running`):**

| badge | online | halted | radar | rssi_prox | chip | target |
|---|---|---|---|---|---|---|
| 9070 (Badgebac8) | ✅ | no | **segs 5 (red)** | −50 dBm | LEEFT · streak 0 · 0 kills | Badge9de4 |
| 1cdb (Badge9de4) | ✅ | no | **segs 5 (red)** | −47 dBm | LEEFT · streak 0 · 0 kills | Badgebac8 |

Read off each badge's `gotcha_dbg.txt` (a dev-only, change-gated status file the
renderer writes — see below). This validates, in the real app: `GotchaController`
drive from the main loop, enroll-on-online, the signed sync + `apply_sync`, the
**§7 connectivity probe** (`online=True` — and it correctly distinguishes a
hotspot-with-no-route, which hung the probe), the v2 beacon + `set_game_context`
(target admitted/pinned out-of-group), asymmetric `rssi_prox`, the **truce
evaluation** (correctly `halt=True` at 22:12 camp time under the 22:00–08:00
schedule; lifted after a schedule change + re-sync), and the **UI** (status chip
+ target strip + 5-seg radar, colour-ramped blue→amber→red).

## Files

- `app/…/gotcha_app.py` (**new**) — `GotchaController`: the non-lvgl glue that
  ties `GotchaState`/`GotchaSync`/`GameConfig` to the live `BLEProximity`. Drives
  the §7 connectivity probe, enroll-on-online, periodic sync (deferred while the
  radar bar is lit, ±20 % jitter), and pushes the v2 game block + admit/pin the
  target on every sync. Network I/O on `TaskManager.create_task` tasks; `tick()`
  is called from the Activity loop. No host tests (app glue) — the pure half it
  relies on is covered.
- `app/…/fri3d_friends.py` — surgical Gotcha hooks: `_setup_gotcha()` (lazy
  `import gotcha_app` in a try/except, so a Gotcha fault → "no game", never "no
  nametag", §8.6), the pre-built hidden status-chip/target-strip/radar widgets
  (`_render_gotcha`, set_text + show/hide only), lifecycle hooks
  (`_gc_start`/`_gc_stop`/`_gc_tick`), and a dev-only `_g_dbg` status-file write.
  `__init__` gotcha attrs; `MENU_MAX` and the friend-LED path are untouched
  (those are the remaining tasks). Every entry point is try/except-wrapped.
- `app/…/MANIFEST.JSON` — **0.10.0 → 0.11.0** (the version string is now
  load-bearing, §8.10.3).
- `tools/deploy.sh` — `gotcha_app.py` added to the deploy file list.

## Test caveats (restore before camp)

- It is **22:12 camp time** (night), so under the real 22:00–08:00 schedule the
  radar is correctly dark (`WAPENSTILSTAND`). To film the lit radar I
  **temporarily shifted the truce schedule to 23:00–07:00** (`POST
  /v1/admin/truce_schedule`) and force-re-synced each badge
  (`AppManager.restart_launcher()` → `start_app`, which re-fires onResume →
  immediate sync). **Restore the schedule to 22:00–08:00** (`{"from":"22:00",
  "to":"08:00"}`) when done; the instant truce is already off.
- `_g_dbg` writes `gotcha_dbg.txt` (change-gated, so negligible flash wear) — a
  dev aid only; **remove for camp**.
- **`SILENT = True` in `fri3d_friends.py` suppresses the physical buzzer entirely**
  (added so the night test didn't wake anyone): `_setup_buzzer` skips PWM init, so
  `_sting`/`_ping_chirp` are physically mute; the hunt ping still runs its logic and
  bumps `self._g_pings` (visible in `gotcha_dbg.txt`). **Flip to `SILENT = False` and
  redeploy to re-enable sound.** (The on-badge ping *counter* needs the guard fix
  in `_hunt_ping` deployed — it's local but a wedged-deploy left the old copy; the
  muting itself is unaffected.)
- 1cdb wedged mid-deploy (advertising boot-beacon + an interrupted deploy); a
  single `mpremote reset` recovered it. Deploy the app with
  `tools/deploy.sh <serial-id>` (sha-verified, by-id); push a dev `config.json`
  (name/groups/`gotcha.api`) separately.

## Remaining for Phase 2

The **LED radar bar + hunt ping (task 9) are now DONE too** (see the next entry):
`_update_leds` renders `hunt_bar` when hunting (friend LEDs otherwise), and
`_hunt_ping`/`_ping_chirp` add the falling-chirp double-tap on the buzzer
priority ladder. Verified running on 9070 (prox −50 → 5 red LEDs + double-tap
ping). **Task 10 CODE-COMPLETE (2026-07-31):** the menu grows two rows when a game
has ever been joined -- **`Gotcha demo`** (cycles the LED colour language
blue→amber→red→gold→green with Dutch captions, ~8 s; sound muted under
`SILENT`) and **`Stoppen met Gotcha`/`Meedoen met Gotcha`** (§13 opt-out/in:
persists, drops/re-raises the game block, re-syncs on rejoin). Done as menu
ITEMS reusing the existing focus/click machinery (`MENU_MAX` 5→7, row height
30→26 to fit) -- no new focusable-screen system. Controller gained
`ever_enrolled`/`is_opted_out`/`opt_out`/`opt_in`. 313 host tests green;
build is on 9070's flash (sha-verified). **Not yet tap-verified on-device**
(the wedge blocked a clean relaunch) -- needs a 9070 reboot + Menu tap-test.

---

# !Fri3d Friends — Gotcha Phase 2, Layer A: the host-testable pure half — 2026-07-30

Phase 2 has started, layered (pure half first, then on-badge). This entry lands
**Layer A** — everything in the badge-side game logic that is unit-testable on a
host with no hardware and no network. It compiles and the full suite is green
(**313 passed**, up from 246). Nothing is deployed to a badge yet; that is
Layer B.

Scope chosen: build the pure logic + HSNT v2 beacon + persistence first, report
green, **then** move to the on-badge UI/LED/menu. Backend for on-badge testing
will be the shared `192.168.1.57:8080` instance (Phase 0 already proved badges
reach it). Checkpoint target stays the plan's Phase 2 exit: two badges enrolled,
each showing the other as target with a live on-screen + LED radar bar.

## Files

- `app/…/gotcha.py` — the pure half grows from crypto-only (248 lines) to the
  full game-logic layer. Added (all host-tested, no `bluetooth`/`mpos`/`lvgl`):
  - **GameConfig.from_sync** — defensive parse of the §5.4 tunables block + the
    `game.truce_schedule`; coerces types, drops unknown keys, falls back to
    badge defaults (mirrors `server/…/config.py` TUNABLE_DEFAULTS). Never raises.
  - **Time / truce / quiet** — `camp_minutes`, `parse_hm`, `hm_str`,
    `truce_active` (returns "none"/"camp"/"personal"/"both"; only camp pauses
    decay, §2.2), `clamp_quiet` (snaps a personal window into the 20:00–10:00
    band, rejects inverted/garbage). Camp-local HH:MM via a fixed **+2 h CEST**
    offset, matching `server/…/clock.py` (server times are UTC; badge is
    NTP-UTC, `clock_offset_s` aligns it).
  - **Proximity** — `prox_filter` (the §8.8.2 asymmetric EWMA, fast-attack /
    slow-decay — the difference between a working kill and a broken one),
    `prox_fraction` (canonical 0..1 over the −90…−55 dBm band, n-independent so
    `PING_FROM_SEG` means the same proximity on the 4-LED 2024 and 5-LED 2026),
    `hunt_segments` / `hunt_bar` (the LED radar; keys off live `KILL_RSSI`/
    `REVEAL_RSSI` so "all red = kill range" holds after a camp retune),
    `breathe_period_ms`, `solid_frame` (the §8.8.3 whole-strip states).
  - **hunt_ping** — (freq, burst, interval, taps) on the same clock as the bar;
    silent below `PING_FROM_SEG`, double-tap at kill range, "drop not queue" made
    pure via a `last_ping_ms` arg (§8.8.6).
  - **score_preview** — optimistic §2 UI update (target 1 / bounty 2 / repeat 0).
  - **EventQueue** — bounded (MAX_QUEUE 40), dedup-by-uuid, drops oldest
    non-kill on overflow, never a kill/killed_by.
  - **GotchaState** — atomically-persisted `gotcha.json` (temp + `os.rename`,
    injectable FS so it is host-tested), merges a verified `/v1/sync` payload
    (me↔target↔state↔dodges↔quiet↔hitlist↔app↔clock_offset), enroll/opt-in/out.
  - **Signed-HTTP shaping + GotchaSync** — pure `signed_get`/`signed_post`/
    `verify_response`/`enroll_body`/`new_nonce` (host-tested; sign over the full
    request target incl. query, matching `server auth.signing_path`), plus the
    on-badge **`GotchaSync`** `urequests` client (`enroll`/`sync`/`flush_events`,
    clock-bootstrap from `/healthz`, `finally`-safe socket close). NOT host-tested
    (urequests is MP-only) — the shaping it relies on is.
- `app/…/ble_setup.py` — `sanitize_config` gains a validated `gotcha` block
  (`enrolled`/`quiet`/`enroll`/`api`); a hostile `null` can't wipe it, and the
  personal quiet window is clamped via `gotcha.clamp_quiet` (daytime start snaps
  to 20:00; inverted → None = camp truce). +6 host tests.
- `app/…/ble_proximity.py` — **HSNT v2** beacon (plan §4): `VERSION` 1→2, a
  `blocks` byte + optional 5-byte game block (`pid`/`gflags`/`streak`);
  `build_payload`/`parse_payload` now carry `game` (v1 still parsed for safety);
  `name_budget(game=...)`; `build_game_block`/`parse_game_block`; gflag bit
  constants. Plus the §4 pre-existing fix: **`admit_peer`** (widens admission to
  the target pid / bounty during a live game) and **`evict_lru`** (64-entry LRU
  that pins target/bounty), wired into `BLEProximity` with a new `rssi_prox`
  peer field (asymmetric, via `set_prox_filter`), `set_game_context`,
  `peer_by_pid`. `current_peers()` shape unchanged → no base-app break.
- `tests/test_gotcha.py` — +40 tests (62 total). `tests/test_ble_proximity.py` —
  +10 tests (55 total). `tests/test_ble_setup.py` — +6 gotcha-sanitize tests.
  Existing v1 beacon tests updated for the v2 `blocks` byte (name budget −1).
  **Full suite: 313 passed** (was 246), no regressions.

## Interpretations worth flagging (Layer B must match)

- **Radar mapping.** The LED bar (`hunt_segments`) keys off the live
  `KILL_RSSI`/`REVEAL_RSSI` thresholds (so the affordance survives a retune);
  `prox_fraction` is a separate linear map over the fixed −90…−55 band used by
  the on-screen bar and the ping's silent floor. Both are monotonic in
  `rssi_prox`; the exact LED count at a given dBm is display polish, all
  server-retunable. Breathe period is a geometric 3800→700 ramp (exact
  endpoints, approximates the §8.8.2 table).
- **Sync clock.** Badge stores `clock_offset_s = server_time − time.time()` and
  derives camp-local minutes as `(effective_now_min + 120) % 1440` (CEST). This
  is the one place a camp timezone constant lives on the badge; it is documented
  and must change with `server/…/clock.py` if the camp is ever run in winter.
- **`synced_at`** is stored as the integer `server_time` (not an ISO string) —
  simpler and directly usable for "synced N min ago".

## Next (Layer B, on-badge)

The host-testable work is exhausted. Remaining for the Phase 2 exit, all
on-badge: the **§7 connectivity check** (a TCP-connect probe to the API host in
a `TaskManager` task, surfacing `no network — check WiFi in Settings`); wiring
`GotchaState` + `GotchaSync` + the v2 beacon game block + `set_game_context`
into `fri3d_friends.py` (status chip, target strip, on-screen + LED radar bar,
hunt ping, `Gotcha` menu row + screen, focus integration, demo mode) and
`beacon_service.py` (advertise the game block); then deploy to two badges,
flip the shared backend to `running`, enroll both, and verify the Phase 2 exit —
each shows the other as target with a live on-screen + LED radar bar.

Two on-badge API probes (9070 + 1cdb, 2026-07-30) fix the plan's §8.3
assumptions: **`TaskManager.wait_for(coro, timeout=…)` DOES exist** on this
firmware (the app just hasn't used it yet), and **`DownloadManager.post_url`
does NOT** (only `download_url`). So `GotchaSync` uses **`urequests`** (the path
the §11 1000-sync soak already proved) under a `TaskManager` task. Corrected in
memory `mpos-firmware-api-gaps`.

---

# !Fri3d Friends — Gotcha Phase 2: Layer B proven on real badges (the probe) — 2026-07-30

The Phase 2 exit condition — *two badges enrolled, each showing the other as
target with a live radar* — is **proven on real hardware** via a throwaway probe,
before touching the shipping `fri3d_friends.py`. This validates every piece of
Layer A end-to-end on-device and caught one real bug.

**Result (badges 9070 + 1cdb → shared backend `192.168.1.57:8080`, game `running`):**

| badge | pid | status | target | seen? | rssi_prox |
|---|---|---|---|---|---|
| 9070 (Devbac8) | 1003 | active | Dev9de4 (1004) | **SEEN** | **−47 dBm** |
| 1cdb (Dev9de4) | 1004 | protected | Devbac8 (1003) | **SEEN** | **−46 dBm** |

Proven on-device: **enroll** (unsigned POST), **signed sync** (HMAC verify +
`apply_sync`), **target assignment** (the ring correctly paired the two active
badges 1003↔1004 and ignored two leftover stale "Soak" players), **HSNT v2
beacon** (game block carrying `pid`), the **widened admission** (`set_game_context`
admits the out-of-group target) + **pinned LRU**, the **asymmetric `rssi_prox`**
filter, **`gotcha.json` persistence**, and the **clock bootstrap** from `/healthz`
(`clock_offset_s` correctly maps the badge's ~30-yr-off RTC to server time).

## The bug it caught (fixed)

`gotcha.py`'s crypto half — inherited, host-tested only — called
**`hashlib.sha256(...).hexdigest()`**, which **does not exist on MicroPython**
(`sha256` has `.digest()` only; the `mpos-firmware-api-gaps` memory already
warned this). `commitment()`/`verify_soul()`/`_new_uuid()` crashed on the badge
*before* enroll's `try/except`, silently breaking enrollment (and would have
broken kill proofs in Phase 3). The soak probe never hit it because it carried
its own crypto (`ubinascii.hexlify`), not `gotcha.py`'s. **Fix:** a portable
`_hex(bytes)` helper (manual lowercase hex over `.digest()`, identical to
CPython's `hexdigest()`), used in all three. Verified on-badge with a full crypto
self-test (RFC 4231 HMAC, commitment, sign/verify_response). 313 host tests still
green. `bytes.fromhex()` (used by `sign_request`) **does** work on this firmware.

## Files

- `app/…/gotcha.py` — the `_hex` fix (commitment/verify_soul/_new_uuid).
- `app/…/ble_proximity.py` — `BLEProximity.begin(game=...)` + `set_game(game)` to
  advertise/refresh the v2 game block (needed by the probe and the integration).
- `probes/gotcha_b1_pkg/{MANIFEST.JSON,gotcha_b1.py}` — the throwaway probe:
  enroll → sync → advertise v2 → admit target → show it when seen with
  `rssi_prox`. Writes a pollable status file (BLE advertise+scan wedges USB-CDC,
  but per-file `mpremote cp` still works when exec is wedged).

## What remains (integration into the shipping app)

The probe replaces nothing in `fri3d_friends.py` yet. Remaining for the *shipped*
Phase 2 exit: wire `GotchaState`/`GotchaSync`/`set_game`/`set_game_context` into
`fri3d_friends.py` and `beacon_service.py`; render the **on-screen radar bar +
LED radar bar** (`hunt_bar`) + **hunt ping** from the now-proven `rssi_prox`; the
**status chip / target strip / `Gotcha` menu row / focus integration / demo
mode**; and the **§7 connectivity check** (the probe passed `is_connected()` but
hung on a badge that was actually a hotspot with no route — the TCP-connect probe
is the sufficiency test the shipping code needs). Method proven; integration next.

## Reproducing the on-badge test (resume here)

Backend: the shared instance `192.168.1.57:8080` (a separate host from `john-ai`/
192.168.1.165). It must be in state `running` for target assignment; flip it with
the admin cookie (password is session-only, NOT in this public repo — read it on
`.57` with `sudo grep GOTCHA_ADMIN_PASSWORD /etc/gotcha/gotcha.env`):

```bash
curl -c /tmp/gc -X POST http://192.168.1.57:8080/admin/login -d "host=claude&password=<PW>"
curl -b /tmp/gc -X POST http://192.168.1.57:8080/v1/admin/game/1/state \
     -H 'Content-Type: application/json' -d '{"state":"running"}'
```

Probe deploy + launch (per badge — `gotcha.py` + `ble_proximity.py` ride along):

```bash
P=/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_<mac>-if00
mpremote connect "$P" exec "import os; os.mkdir('/apps/gotcha.b1')"
mpremote connect "$P" cp probes/gotcha_b1_pkg/MANIFEST.JSON \
    probes/gotcha_b1_pkg/gotcha_b1.py \
    app/com.fri3dcamp.fri3dfriends/gotcha.py \
    app/com.fri3dcamp.fri3dfriends/ble_proximity.py :/apps/gotcha.b1/
mpremote connect "$P" exec "from mpos import AppManager; AppManager.refresh_apps(); print(AppManager.start_app('gotcha.b1'))"
sleep 12
mpremote connect "$P" cp :/gotcha_b1_status.txt .   # poll (exec is wedged while BLE advertises; cp still works)
mpremote connect "$P" reset                          # stand down
```

Leftover stale "Soak" players (1001/1002) target the dev badges but can't be
targeted back; ignore them or `POST /v1/admin/player/<pid> {"action":"kick"}`.
The dev badges (Devbac8=1003 on 9070, Dev9de4=1004 on 1cdb) re-enroll idempotently
by BLE-MAC `badge_key`, so they keep their pids across probe restarts.

---

# !Fri3d Friends — Gotcha Phase 0 §11 item 2: the on-badge 1000-sync soak — 2026-07-30

The **last Phase 0 action** is done: the **on-badge half** of the 1000-signed-sync
soak. The server half was already closed (`server/tools/smoke.py --soak 1000`:
median 5.5 ms, flat RSS, every response verified); this is the part "only a badge
can answer," per the plan — the same 1000 syncs driven from a real badge, watching
`gc.mem_free()`. **It passes cleanly**, and with it §11 item 2 is **fully
RESOLVED**. No app code shipped to the fleet; throwaway probe only.

**Verdict (badge 1cdb… → deployed backend 192.168.1.57:8080):**

| | |
|---|---|
| Signed syncs | **1000/1000 HTTP 200, 1000 verified, 0 errors, 0 retries** |
| RFC 4231 HMAC self-test | **ok** (hand-rolled HMAC-SHA256 proven correct at startup) |
| Heap free | **7147 → 7139 KB**, steady drift **−2784 B over 900 syncs** (~3 B/sync — noise, not a leak) |
| Heap band | 7138–7147 KB across every 100-sync checkpoint (±0.1 %); no OOM, no fragmentation |
| Latency | median 237 ms, p95 413 ms, 2.8 req/s (badge→server over WiFi; the server's internal 5.5 ms excludes the radio trip) |

Every one of the 1000 responses had its signature and nonce verified against a
HMAC recomputed on-badge over a canonical-JSON re-serialisation of the payload —
so this is full **badge-signer ↔ server-verifier byte interop, both directions,
over 1000 real signed round trips**, not just "the server returned 200."

The full record is `probes/logs/soak_result.json`; the throwaway probe is
`probes/soak_pkg/{soak.py,MANIFEST.JSON}`, driven by `tools/run_soak.sh`.

**Two findings worth keeping (neither is a design problem):**

1. **1000 fresh back-to-back TCP connections exhaust the badge's lwIP socket/PCB
   pool.** The first (unpaced) run hit `OSError(104)` (ECONNRESET) in a cascade
   from sync ~694 — TIME_WAIT PCBs accumulate faster than they drain when you
   hammer new connections with no pause. Real syncs are **300 s apart**, so this
   never happens in production. An 80 ms pacing between syncs (plus a bounded
   retry on `OSError`) made the run 1000/1000 clean. The heap was flat even in
   the failing run — the errors were purely network-layer.
2. **A long WiFi soak leaves the badge's USB-CDC flaky, and over-resetting it
   cascades into an enumeration fault that needs a physical replug.** (Already in
   memory `mpos-firmware-api-gaps`; reaffirmed twice this session.) `run_soak.sh`
   now settles + retries the result pull, and the result survives on flash
   regardless, so a wedged pull never loses data.

**Platform facts the probe had to work around** (saved to memory
`mpos-firmware-api-gaps`): MicroPython has no `hmac` (HMAC-SHA256 hand-rolled over
`hashlib`); `hashlib.sha256` has `.digest()` but **no `.hexdigest()`** (use
`ubinascii.hexlify`); `json.dumps` has `separators` but **no `sort_keys`**, and
**its dicts do not preserve insertion order**, so canonical JSON must be built by
walking the object and emitting `sorted(keys())` directly (delegating scalars to
`json.dumps` for matching number/string formatting); and the **badge clock is
~30 yr off**, so the signed `ts` is bootstrapped from the server's `server_time`
and echoed per-sync.

**Cleanup:** the throwaway probe was removed from the badge. The soak enrolled two
fake players ("Soak") in the dev backend; they are harmless and the DB is reset for
camp. Note: the live backend on this host is now **Caddy-fronted on :8080**, not
the `gotcha.service` systemd unit described in `server/DEPLOY_LOG.md` (the unit is
not loaded; `players` persisted through a `/var/lib/gotcha` wipe, so the live DB is
elsewhere) — a deployment-drift item to reconcile, not a soak concern.

## Phase 0 status after this

| # | spike | status |
|---|---|---|
| 1 | WiFi + BLE coexistence | ✅ GO + scheduling rule |
| 2 | Sync durability | ✅ **RESOLVED** — heap + on-device HMAC + TLS + **1000-sync soak (server half *and* on-badge half)** |
| 3 | Third GATT service | ✅ GO |
| 4 | Scan duty reduction | ✅ GO mechanically; 12.5 % background-only |
| 5 | RSSI trend | ✅ NO-GO, upheld; worn-on-worn check → §11.1 before Phase 2 |
| 6 | 2024 screen blanking | ⚠️ PARTIAL; quantify via the USB meter in Phase 6 |

**Phase 0 is closed.** Every question capable of invalidating downstream work is
answered with data, including the one residual that was structurally gated on the
backend existing. Phase 1 (backend) and Phase 2 (badge) are unblocked.

---

# !Fri3d Friends — Phase 0 audited, corrected and closed (spikes 1/3/4/6 + TLS) — 2026-07-30

Two jobs. First, **audit** the previous session's Phase 0 conclusions and its
rewrite of `Implementation_Plan_Gotcha_20260726.md` — is the RSSI-trend NO-GO
sound, and is the plan fit to build from? Second, **close the remaining Phase 0
spikes** (1 WiFi/BLE coexistence, 3 third GATT service, 4 scan duty, 6 2024 screen
blanking). Both done. The audit confirmed the NO-GO but found three overstated
numbers and one missed design consequence that turned out to be
correctness-critical. Plan and spike report corrected; new report written for the
four spikes. **Phase 0 is now closed with one residual that structurally cannot
close before Phase 1 exists.** No app code shipped to the fleet.

## 1. Audit of the RSSI-trend NO-GO — verdict: sound, reproduced independently

Re-derived from the raw CSVs with a **third** estimator (trailing-window
least-squares, sign-scored, pooled over all five walks) rather than trusting
`tools/analyze_rssi.py`:

| trailing window | approach correct | retreat | stand |
|---|---|---|---|
| 4 s | 56 % | 81 % | 11 % |
| **8 s** (the spike's) | **70 %** | **83 %** | **21 %** |
| 12 s | 77 % | 86 % | 29 % |
| 20 s | 89 % | 94 % | 47 % |
| 30 s | 100 % | 92 % | 89 % |

Same verdict, and it pins the mechanism: the sign only becomes reliable at a
**20–30 s window**, exactly the report's "far too laggy" claim. Five walks, two
independent estimator families, one answer. **The retraction stands.**

## 2. Three numbers the report overstated (all corrected in place)

| claim | reality | why it mattered |
|---|---|---|
| "±15–25 dB noise, present even standing still" | min–max, outlier-driven. Robust spread at 1 m is **IQR 4–22 dB**, p90 within ~5 dB of median. The noise is a **tight mode + one-sided deep fades** — 12–28 % of samples ≥15 dB *below* median | This phrasing had propagated into §8.8.2a, §12 and the narrative. Asymmetric noise demands an **asymmetric filter** — see §3 |
| "real approach slope ~0.1–0.5 dB/s" | whole-phase regression: **+0.50…+0.78** approach, **−0.50…−1.38** retreat | ~2× understated; verdict unchanged |
| "stand ≈ 0–5 %" | artifact of scoring against a 1–3 dB deadband; **21 %** at 8 s on a physical criterion (\|slope\| < 0.3 dB/s) | 0 % reads as "catastrophically broken" when the real story is "needs 30 s" |

Also **added**, because it is a stronger root cause than the slope figure: the
approach **is not a ramp**. Median RSSI per fifth of a 40 m→1 m approach runs
`−93 → −88 → −88 → −85 → −74`. From 40 m to ~5–10 m there is **no usable signal at
all**; essentially all the gain arrives in the last few metres.

## 3. The thing the report did not check: does the fallback actually work?

The report asserted the absolute bar and kill handshake were "unaffected". Re-scored
from the same five walks:

**Absolute separation is strong and reproducible** — 1 m median **−57 dBm**, 5 m+
median **−83…−86 dBm**, in all five walks. Raw-sample thresholding:

| threshold | detect at 1 m | false alarm at 5 m+ |
|---|---|---|
| −60 dBm | 70.6 % | 0.7 % |
| **−65 dBm** | **80.7 %** | **2.8 %** |
| −70 dBm | 82.9 % | 9.0 % |
| −75 dBm | 82.9 % | 17.2 % |

**But the smoothing has to be asymmetric.** At `KILL_RSSI = −65`:

| smoothing | armed at 1 m | false-arm at 5 m+ | longest continuous arm window |
|---|---|---|---|
| symmetric EWMA `a = 0.3` (shipped today) | 74 % | 0 % | **5.6** – 17.3 s |
| **asymmetric 0.60 up / 0.08 down** | **100 %** | 3 % | **24.5 – 34.5 s** |
| max-of-last-3 | 99 % | 6 % | 17.1 – 34.5 s |

The symmetric filter's worst walk clears `KILL_HOLD_MS = 5000` by only 12 %.

## 4. Body shadow quantified — and the filter turns out to be correctness-critical

The walks put the advertiser on a **pedestal**; the real game wears both badges.
The penalty was measurable from the *existing* data: within a walk the approach has
the badge **facing** the target and the retreat has the walker's own body **in the
path**, so pairing distance-matched slices measures one body's shadow.

```
POOLED one-body shadow: median -4.0 dB, mean -3.1 dB, range -14..+12 (n=14)
POOLED advert rate:     1.12/s facing vs 0.86/s shadowed = 77 % kept
```

Far smaller than the raw noise figures imply. *Caveat, stated in the docs: time is
the distance proxy, so it assumes a steady pace — it predicts the worn-on-worn
walk's outcome, it does not replace it.*

Projecting a uniform extra penalty forward (`tools/analyze_shadow.py`) produced the
session's most important finding:

| penalty | asymmetric filter | symmetric EWMA `a=0.3` |
|---|---|---|
| 0 dB (pedestal) | 24.5 s hold | 5.6 s hold |
| **−4 dB (expected)** | **18.6 s hold** | **1.8 s — KILL UNWINNABLE** |
| −8 dB | 1.8 s — fails | 0 s |
| −12 dB | 0 s | 0 s |

**The symmetric EWMA's 12 % margin is already consumed by one extra body.** So the
asymmetric filter is not a refinement of the smoothing — it is the difference
between a working kill and a broken one. Said so explicitly in §8.8.2 and the spike
report.

Loosening is cheap, though — false arming at 5 m+ stays ≤ 4 % out to −74 dBm — so
the residual became a **pre-committed lookup table** (new plan §11.1):

| measured penalty | `KILL_RSSI` | worst-walk arm window | false-arm |
|---|---|---|---|
| 0 to −4 dB *(expected)* | **−65, unchanged** | 18.6–24.5 s | 0–3 % |
| −8 dB | −68 | 13.0 s | 0 % |
| −12 dB | −71 | 13.0 s | 0 % |
| −16 dB | −77 | 18.6 s | 0 % |
| worse | cut `KILL_HOLD_MS` to 2500 before loosening further | — | past −77 costs real false arms |

Bar = the **worst** of five walks holding ≥ 10 s against a 5 s `KILL_HOLD_MS` (2×
margin). `REVEAL_RSSI` needs no check at all: 100 % at 1 m even at −16 dB.

## 5. Plan edits made

| area | change |
|---|---|
| §"Finding them" | **Rewritten, not annotated.** The disproven warmer/colder prose is gone (it had been left as primary text with a correction banner above it — the pattern that puts wrong strings on badges). Now states the measured range limit: flat past ~10 m, only moves in the last few metres. One-line provenance note replaces the 7-line banner |
| §8.8.2 | New: bar calibrated to **−90…−55 dBm**; the **asymmetric `rssi_prox` filter** with its measured justification and the −4 dB correctness argument |
| §5.4 | `PROX_ALPHA_UP` 0.60 / `PROX_ALPHA_DOWN` 0.08; `HUNT_SYNC_DEFER` + `HUNT_SYNC_DEFER_MAX_S` 900 |
| §8.1 | `prox_filter()` / `prox_fraction()` added to the pure-function surface |
| whole hunt path | repointed `rssi_ewma` → `rssi_prox` (§5.3, §5.7, §8.4, §8.8.2, §8.8.6, §10); `rssi_ewma` stays for the friends list, where a symmetric average is the honest thing to show |
| §8.8.6 | pitch-bend removal rewritten as prose rather than struck-through history |
| §11 | items 1/3/4/6 resolved with data; item 2 narrowed; **new §11.1** worn-on-worn protocol; verdict **GO for Phase 1** |
| §12 | trend risk + coexistence risk closed; pedestal risk **downgraded Medium–High → Medium** (exposure is now one live-tunable value); new narrow row for the `KILL_RSSI` headroom; new row for "a sync mid-chase blunts the radar" |
| §14.2 | **A5 marked resolved** — it had been executed on 2026-07-29 but the row still read as an open action item |
| §8.7 | levers 1, 2, 3 and the lever-4 ladder all updated with measured results |
| Start-here preamble | Phase 0 closed; points at both spike reports |

Naming note: the new section is **§11.1**, not §11a — `DESIGN.md §11a` already
exists and is cited three times in this plan. It was also relocated to *after* the
Phase 0→6 list so it stops interrupting the phase narrative.

## 6. Spike 3 — third GATT service: **GO**

`gatts_register_services((exchange, setup, gotcha))` in **one** call:

| service | chars | handles |
|---|---|---|
| exchange `6e4000 10` | 2 | `[16, 18]` |
| setup `6e4000 20` | 6 | `[21, 23, 25, 27, 30, 32]` |
| gotcha `6e4000 30` | 4 | `[35, 37, 40, 42]` |

`gatts_set_buffer(SPOILS, 512, True)` also succeeds. §5.2's pattern is correct as
written — no change needed.

## 7. Spikes 1 + 4 — coexistence and scan duty

Six conditions, 60 s each, back to back. Scanner **1cdb…**; advertisers **9070…**
(`Tarpon 41b`) and **3485…** (`Badge2024lijn`), both beaconing from their boot
service. "busy" = continuous `ping -i 0.01 -s 500` from the host; the badge answered
**6038/6100** (50 % duty) and **5958/6223** (12.5 %), i.e. real two-way radio work.

| duty | WiFi | adv/s | vs off | median gap | worst gap |
|---|---|---|---|---|---|
| **50 %** (60/120 ms) | off | **3.66** | — | 0.16 s | 1.6 s |
| 50 % | idle | 3.01 | **82 %** | 0.25 s | 2.3 s |
| 50 % | transferring | 1.53 | **42 %** | 0.50 s | 6.7 s |
| **12.5 %** (30/240 ms) | off | **0.93** | — | — | 4.6 s |
| 12.5 % | idle | 0.83 | **89 %** | — | 7.9 s |
| 12.5 % | transferring | 0.30 | **32 %** | — | 14.9 s |

**Spike 1 → GO, with a scheduling rule.** Idle association is nearly free; a
transfer costs **58–68 %**, as a uniform slowdown rather than long stalls (one 5.3 s
outlier). **Presence never flaps** — worst gap anywhere 14.9 s against `EVICT_MS`
30 s. The architecture stands; the sync scheduler changes → `HUNT_SYNC_DEFER`.

**Spike 4 → GO mechanically, NO for the hunt path.** The duplicate filter **does**
stay off at 12.5 %, confirming `DESIGN.md` §3's real load-bearing claim (explicit
`interval_us`/`window_us`, not the 50 % ratio). But the cost is **exactly
proportional** — 25 % kept, i.e. the duty ratio. Per peer that is 0.47/s on a desk →
~0.2/s in a field → **0.15/s with WiFi busy, one sample every ~7 s** against a 5 s
`KILL_HOLD_MS`. Adopt 12.5 % **only in the non-hunting background state**; keep 50 %
while a hunt is live. Wired into the lever-4 battery ladder.

## 8. Spike 6 — 2024 screen blanking: **PARTIAL, lever 1 as written does not exist**

1. **No backlight or power GPIO.** `mpos.board.fri3d_2024.st7789.ST7789._displays[0]`
   has `_backlight_pin = None`, `_power_pin = None`; `get_backlight()`/`get_power()`
   both return **−1**. `DESIGN.md` §1 confirmed from running firmware, not docs.
2. **The panel is write-only** — `RDDPM (0x0A)`, `RDDID (0x04)`, `RDDST (0x09)` all
   read back `0xFF` (no MISO). Any blanking is open-loop.
3. **The commands work and reverse cleanly.** `DISPOFF (0x28)`, `SLPIN (0x10)`,
   `SLPOUT (0x11)`, `DISPON (0x29)` via `display_bus.tx_param(cmd)` (single-arg
   form); LVGL survives, `screen_active().invalidate()` redraws, launcher intact.
4. **Observed (visually confirmed): black screen, backlight still glowing** — in
   both `DISPOFF` and the deeper `SLPIN`.

So the ~50 mA in §8.7 is display **+ backlight** and the LEDs dominate it: a panel
command cannot switch off a backlight with no GPIO behind it. What remains is an
unquantified panel-logic saving, and it **cannot** be quantified on-badge
(`BatteryManager` exposes voltage only) → **A4, Phase 6, inline USB meter**. Kept
anyway: a black screen is a real state for the battery ladder and for not
broadcasting your hunt.

**Incidental, for lever 3:** ping RTTs to an associated badge ran **38–672 ms**, far
above the LAN floor — the signature of DTIM power save **already being active**. So
lever 3's ~65 mA is probably already banked, not available. Flagged in §8.7.

## 9. Phase 0 item 2 — the TLS half closed, and it needed no backend

"Confirm one enrollment HTTPS handshake succeeds" does not require the Gotcha
backend, only *an* HTTPS host. Result on badge **1cdb…**:

```
baseline mem_free 7 407 232
handshakes 0/3/6/9/11  mem_free 7 411 888  (identical at every checkpoint)
TLS handshakes ok=12 fail=0 | net +4 624 bytes | lowest seen 7 407 232
512 KB contiguous bytearray after TLS churn -> OK
```

Plus a single 1.3 MB body pulled through TLS in 19.6 s. **TLS neither leaks nor
fragments on this build**, so D21 (one TLS handshake at enrollment, then signed
plain HTTP) is *verified* rather than assumed.

**Still owed:** the **1000-consecutive-signed-sync soak**, which genuinely needs a
verifier → end of Phase 1. It is a soak for heap stability, not a question that can
invalidate the design; the two that could (PSRAM heap, TLS behaviour) are answered.

## 10. Phase 0 final status

| # | spike | status |
|---|---|---|
| 1 | WiFi + BLE coexistence | ✅ GO + `HUNT_SYNC_DEFER` |
| 2 | Sync durability | ⚠️ heap + on-device RFC 4231 HMAC + **TLS** done; 1000-sync soak → end of Phase 1 |
| 3 | Third GATT service | ✅ GO |
| 4 | Scan duty reduction | ✅ GO mechanically; 12.5 % background-only |
| 5 | RSSI trend | ✅ NO-GO, audited and upheld; worn-on-worn check → §11.1, gates Phase 2's radar |
| 6 | 2024 screen blanking | ⚠️ PARTIAL; quantify via A4 in Phase 6 |
| A5 | AppStore-update wipe | ✅ destructive → §8.10.4 must be built |

**Every question capable of invalidating downstream work is answered**, and two
answers changed the design (the trend retraction, the coexistence scheduling rule).
What remains needs the thing being measured to exist first.

## 11. Files

**New:**

| path | purpose |
|---|---|
| `Phase0_Coex_GATT_Duty_Display_20260730.md` | spikes 1/3/4/6 report |
| `probes/coex_pkg/{MANIFEST.JSON,coex.py}` | one-shot on-badge scan probe (throwaway; removed from the badge afterwards) |
| `tools/run_coex.sh` | host-side condition driver (WiFi state + ping load + pull) |
| `tools/deploy_coex.sh` | install/remove the probe |
| `tools/coex_load_server.py` | ~1 KB HTTP endpoint standing in for a sync |
| `tools/analyze_coex.py` | scores spikes 1/3/4 from the raw logs |
| `tools/analyze_shadow.py` | body-shadow measurement + the §11.1 `KILL_RSSI` table |
| `tools/spike6_display_sleep.py` | 2024 panel blanking test |
| `tools/recover_badge_port.py` | `USBDEVFS_RESET` unwedge |
| `probes/logs/coex_*.{json,csv}`, `coex_verdict.txt`, `shadow_verdict.txt` | raw data + verdicts |

**Modified:** `Implementation_Plan_Gotcha_20260726.md`,
`Phase0_RSSI_Trend_Spike_20260729.md`, memory `mpos-firmware-api-gaps` + `MEMORY.md`.

**Nothing committed** — left in the working tree for review.

## 12. Platform lessons (saved to memory `mpos-firmware-api-gaps`)

- **`json.dump(obj, open(path, "w"))` silently loses everything on MicroPython.**
  The file object is never flushed or closed, so the buffer dies with it → 0-byte
  file. **Destroyed a complete 9-minute run.** Always
  `f = open(...); json.dump(obj, f); f.flush(); f.close()`.
- **Never toggle WiFi from inside a measurement Activity.** `WifiService`
  (re)connecting takes the **foreground**, firing `onPause` — which silently kills
  any `TaskManager` task gated on a `running` flag. **Ate the first attempt at the
  six conditions.** Set WiFi from the host REPL *before* launching.
  `temporarily_enable(x)` also takes a **required positional arg**;
  `temporarily_disable()` takes none.
- **`mpos.AppManager.start_app("<fullname>")` launches an app from the REPL** — no
  tapping the launcher. `get_foreground_app()` confirms; `restart_launcher()` returns.
- **A hard-scanning badge can wedge its USB-CDC completely** — `/dev` node
  enumerates, raw reads return 0 bytes, `mpremote` cannot enter raw REPL. Fixed by
  `USBDEVFS_RESET` (`tools/recover_badge_port.py`); use sparingly. On recovery the
  on-badge results were intact — only the *pull* had failed.
- **`mp()`-style pipelines always exit 0**, so `mp cp … && echo "ok"` reports false
  success. `run_coex.sh` now verifies with `[ -s "$dest" ]`.
- The 2024 display SPI is **write-only** (no MISO) — panel state is unreadable.

## 13. Gotchas / follow-ups

- **ufw blocked the load server.** Port 8099 gave the badge `OSError(116)`
  (ETIMEDOUT) despite the host `curl` working — a host `curl` to its own LAN IP goes
  over loopback and bypasses `ufw INPUT`, so it proves nothing. Switched to
  **port 12345**, which was already `ALLOW 192.168.1.0/24` in ufw, rather than
  changing the firewall. Badge answers 500-byte pings but **not** 1000-byte ones
  (0 replies), so the load uses `-s 500`.
- ✅ **`HUNT_SYNC_DEFER` / `HUNT_SYNC_DEFER_MAX_S` were missing from
  `server/gotcha_server/config.py` — since fixed by the Phase 1 session**, which also
  added `tests/test_server_plan_parity.py`. (`PROX_ALPHA_UP/DOWN` were already
  present and the `TREND_*`/`PING_BEND_PCT` retraction correctly absorbed.) No file
  under `server/` was touched from this session. See §14 for the constraint that came
  back out of it.
- **Phase 1 landed in parallel** (backend at `192.168.1.57:8080`), so the item-2
  **1000-sync soak is now runnable** — that is the single remaining Phase 0 action.
- **§11.1 worn-on-worn walk** before Phase 2 builds the radar. If skipped: ship
  `KILL_RSSI = −68` and treat the first playtest as the measurement.
- `rssi.walk` is **deliberately left installed** on badge **1cdb…** — it is the
  tooling the §11.1 walk needs.
- Test suite went 140 → **254** during the session; the increase is Phase 1's
  server tests from the parallel work, not this session's.

## 14. Cross-component constraint found by the Phase 1 session (and the hole it exposed)

The Phase 1 model flagged that **`HUNT_SYNC_DEFER_MAX_S` (900 s) must stay below its
outage-detection window `OUTAGE_GAP_MIN` (20 min)**: §10.3 pauses dormancy when sync
volume collapses, and a deferring badge is a badge *deliberately* not talking, so a
long chase could be misread as the server having been down — pausing dormancy
accounting camp-wide. Verified and correct. `state.outage_intervals()` measures
stretches where the server heard from **nobody** (aggregate `sync_beats` minute
buckets, not per-badge), so one deferring badge is invisible; the failure needs
*simultaneous* deferral, which is unlikely at 700 badges but trivial with **two dev
badges or a four-player endgame**.

**Their guard test was necessary but not sufficient, because of an ambiguity in my
§5.4 spec.** I had written "hard ceiling on hunt-deferred syncing" without saying
*from when*, and Phase 2 has not implemented it yet:

| anchor | max badge silence | vs 1200 s |
|---|---|---|
| from deferral start (the intuitive reading) | jittered `SYNC_S` ≤360 s + 900 = **1260 s** | **breach** — and their test still passes |
| **from last successful sync** | **900 s flat** | safe, ~5 min margin, immune to `SYNC_S` retuning |

Pinned to the second, in three places: **§5.4** (the tunable row plus a dedicated ⚠️
constraint row giving the 1260 s arithmetic, and a warning that both values are
live-tunable so **raising this one from the admin page at camp can break dormancy
accounting** — raise `OUTAGE_GAP_MIN` first), **§10.3** (the reciprocal note, for
anyone *lowering* `OUTAGE_GAP_MIN`), and **§9.2** (the endpoint annotation names the
anchor). Suggested back to them: assert the anchor semantics once the badge side
exists, and note that `outage_intervals()`'s 60 s bucket granularity eats margin
first if anyone ever tightens it.

## 15. Documentation updated at session close

- **`DESIGN.md` §1 "Verified hardware / API facts"** — five new/extended rows, since
  this is the project's platform-reality record and the spikes were platform facts:
  the **backlight** row now carries the root cause (`_backlight_pin = None` /
  `_power_pin = None`, `get_*` → −1 — a wiring fact, not a missing API); new rows for
  **2024 panel sleep** (commands work + reverse; write-only panel, `RDD*` → `0xFF`),
  **scan duty linearity**, **WiFi/BLE coexistence**, **three GATT services in one
  call**, and **TLS not fragmenting the heap**.
- **`DESIGN.md` §3 scan paragraph** — its "this is load-bearing" warning now records
  that the *explicit args* were confirmed to be the operative part, not the 50 %
  ratio, together with the proportional-cost bound.
- **`DESIGN.md` recovery/discipline notes** — the USB-CDC wedge + `USBDEVFS_RESET`
  recovery, the silent `json.dump` data loss, the WiFi-foreground-steal trap,
  `AppManager.start_app()` for scripted runs, and the shell pipeline exit-status
  gotcha.
- **`README.md`** — repo layout now lists `probes/`, the three analysis tools and
  `recover_badge_port.py`; new paragraph pointing at the plan and both Phase 0
  reports, with the warning that several plan assumptions did not survive contact.

---

# !Fri3d Friends — Gotcha Phase 1: the backend game server — 2026-07-30

Implemented **Phase 1 of `Implementation_Plan_Gotcha_20260726.md` §11** end to
end: the FastAPI + SQLite backend in `server/`, deployed under systemd on the
Ubuntu game laptop at **192.168.1.57:8080**. No badge code touched — Phase 1 is
deliberately badge-free. **140 → 246 host tests green.**

## 1. What was built

`server/gotcha_server/`, ~2 900 lines, one process, no ORM, no migration tool, no
template engine, no build step — the deployment target is a laptop in a field.

| Module | Contents |
|---|---|
| `state.py` | §9.6's status model, §2.2 streak decay, truce + personal quiet hours (§10.4/§10.4a), dormancy (§2.4), staleness (§10.1) |
| `ring.py` | §3.2 construction with group-conflict repair; splice in/out, inheritance, position swaps |
| `scoring.py` | Points, streaks, deaths, four leaderboards, live hit list |
| `events.py` | All nine §9.3 event types with every server-side re-check |
| `service.py` | Enrollment, rebind, the sync payload, `reconcile()` |
| `admin.py` | §9.4 admin API + the dashboard document |
| `pages.py` | Backend-served HTML (D31): working admin dashboard, player-card skeleton, Dutch (D26) |
| `auth.py` / `crypto.py` | §6.2 signed requests and signed response envelopes |

**Two architectural choices**, both written up in `server/README.md`:

- **Derive, don't schedule.** `protected`, `dormant`, `stale` and the decayed
  streak are computed from timestamps on read. §2.2 argues this for decay
  ("correct regardless of when the timer actually runs"); the same argument
  applies to all of them, so there is **no cron, no worker, no queue**. Target
  pointers cannot be derived, so `reconcile()` acts on the derivations at the top
  of every sync and every event batch — the game repairs itself as a side effect
  of badges talking to it.
- **The badge is untrusted except about its own death** (§9.5/§9.6). Truce, quiet
  hours, protection, dodge limits, target validity and repeat-kill scoring are all
  re-checked server-side; `killed_by` is believed, and the server separately
  decides whether the kill *counted* (§10.2 — an invalid pairing is voided and the
  victim keeps their streak).

## 2. The badge simulator (§11's harness)

`tests/badge_sim.py` is written as *the badge*, not as a test helper: it holds a
soul, a `player_key` and an offline queue, and it signs and verifies with the
badge's own `gotcha.py` (the hand-rolled MicroPython HMAC + canonical JSON). So
every API test is simultaneously an interop test in both directions, and Phase 2's
`GotchaSync` has a reference implementation to match. `tests/test_server_api.py`
drives it through 66 scenarios; `test_server_crypto.py` pins byte-parity between
badge and server (canonical JSON, request/response signatures, group ids vs
`ble_proximity`).

## 3. Bugs found and fixed while testing

- **A death's two halves did not dedupe.** `apply_death` increments `life_id`, so
  the victim's later `killed_by` looked for a kill against the *new* life and
  created a second one. Fixed properly with a **`lives` table** holding each
  life's commitment: the soul itself now identifies which life it ended, so a
  proof that spent two hours in an offline queue still verifies after the victim
  respawned and rotated — and dedupes onto one death. Without this, a late but
  entirely honest kill report would have failed and looked like cheating. Plan
  §3.4 annotated.
- **§3.2's local repair stalls.** With two large groups of similar size (Chiro vs
  a makerspace — a plausible camp), a shuffled ring lands on 4–5 same-group edges
  and *no single successor-swap improves it*, so the specified hill-climb reported
  conflicts for a ring that has a perfect solution. Seeded the construction with a
  group-aware deal and added a position-swap neighbourhood: 700 players in 40
  groups now build **0 conflicts in 0.2 s**; genuinely unsatisfiable shapes still
  start the game and report the count honestly (step 4).
- **`_edge_cost` scored the wrong edges** (`{i, i-1, j, j-1}` instead of the four
  a successor swap actually moves), which is why the repair never converged.
- **A returning dormant badge was not protected.** §9.6 says "any sync →
  `protected`"; it was being spliced straight back into the ring and was instantly
  attackable coming off the charger. Added `service.note_return`.
- **Dormancy could mass-dormant the camp.** §10.3 requires dormancy to pause when
  sync volume collapses. The first cut treated any single quiet minute as an
  outage, which made 15-minute test cadences look like a permanent outage; now it
  looks for a **≥20 min silence**, which is what actually distinguishes "the
  server was down" from "a quiet night".
- **`{"action":"protect","seconds":0}` re-armed the default 90 s** (`or` treating 0
  as absent) instead of clearing protection. Now `<= 0` sets NULL.
- **`inherit`'s re-splice could make a player their own target.** Replaced the
  ad-hoc pointer hand-off with `swap_positions`, which handles the two adjacency
  cases and provably keeps one cycle.
- **The admin dashboard 500ed when logged in.** The page body is HTML+CSS+JS
  containing literal `%` signs (`onder 20%`), and it was assembled with
  `%`-formatting — `TypeError: not enough arguments for format string` on the one
  page a host actually opens. Now assembled by explicit replacement, with the
  host's own name HTML-escaped, and there is a test that renders it.
- **The database was world-readable.** systemd created `/var/lib/gotcha` 0755 and
  SQLite the file 0644, so every badge's `player_key` — a credential issued once
  over TLS and never re-transmitted (§6.2) — was readable by any user on the
  laptop. Fixed with `StateDirectoryMode=0750` and `UMask=0027`.
- **The enrollment IP rate limit was too tight** (60/h): Friday morning is 700
  badges at once and the camp network may NAT them behind one address. Raised to
  900/h — it is an abuse guard, not a game rule, and §9.5's clustering audit is
  what actually catches a farm.

## 4. Interpretation calls (all commented at the code, plan annotated)

1. **`METHOD || PATH` includes the query string.** Otherwise `?board=`/`?limit=`
   are unauthenticated. **Phase 2 must sign the full request target.**
2. **`total_kills` *and* `score` are both stored.** §2.1 ranks board 1 by
   `total_kills` while §2 awards 1 or 2 points; those are different numbers.
3. **`lives` table** — see above.
4. **`POST /v1/admin/truce_schedule`** added (not in §9.4): the nightly window is
   pushed to badges and every other timing constant is host-adjustable. A camp
   running to 01:00 otherwise has no way to move it.

## 5. Deployment and measurements

`server/deploy/install.sh` creates a `gotcha` system user, a venv in
`/opt/gotcha`, the database in `/var/lib/gotcha`, secrets in `/etc/gotcha` and a
hardened systemd unit with restart-on-failure (§6.1). `uninstall.sh` reverses all
of it; **`server/DEPLOY_LOG.md` records every host-level change with its undo
command**, so the laptop can be returned to its prior state after camp.
`server/tools/smoke.py` (stdlib only) drives a deployed instance over the network.

Last smoke run against the deployed server: enroll ×6 → signed sync → **replay
refused (200 then 401)** → ring built (0 conflicts) → kill scored → dashboard
`kills_10m=1`. The kill was first refused with `truce` because the run happened at
06:00, inside the 22:00–08:00 night truce — the rule working exactly as D7
specifies; the smoke tool now moves the window aside and restores it.

Measured against a database holding **700 enrolled players**: **10.8 ms/sync**
(≈93 req/s) versus the **2.3 req/s** §6.1 needs — 40× headroom; signed sync
response **1.55 KB**; initial ring build 0.2 s.

Deployed instance left with an **empty database, game in `lobby`**, truce
22:00–08:00.

## 6. Reconciled with the plan edits that landed mid-session

The plan was being edited by a parallel Phase 0 session while this was being
written (`Implementation_Plan_Gotcha_20260726.md` changed at 06:06). Diffed the
whole file against the state Phase 1 was built from and checked every hunk for
backend impact:

- **`HUNT_SYNC_DEFER` (true) and `HUNT_SYNC_DEFER_MAX_S` (900)** were added to §5.4
  an hour after `config.py` was written, and were missing from `TUNABLE_DEFAULTS`.
  **Added, and verified reaching a badge on the deployed server** (36 tunables
  pushed). Both are badge-side behaviour, but §5.4 requires every tunable to be
  server-pushed or the admin page cannot reach it.
- **`HUNT_SYNC_DEFER_MAX_S` (900 s) sits deliberately below `OUTAGE_GAP_MIN`
  (20 min)** — noticed while adding it. Deferral is a badge choosing not to talk; if
  it could outlast the outage window, a long chase would read as the server having
  been down and would pause dormancy accounting camp-wide (§10.3). Asserted in a
  test so raising one without the other fails. The Phase 0 session then pinned the
  **anchor** in §5.4 — the cap is measured from the *last successful sync*, not from
  when deferral began, which is what keeps total silence flat at 900 s instead of
  `SYNC_S`×1.2 + 900 = 1260 s. **The server cannot enforce that anchoring** (it only
  ever observes silence, and both anchorings look identical until it is too long),
  so it is spelled out at the constant in `config.py` as a Phase 2 obligation.
- **Checked the 60 s bucket rounding in `outage_intervals()`** rather than assuming
  it: a silence is measured from `bucket_of(prev_sync) + 60` to
  `bucket_of(next_sync)`, so the measured gap is always **shorter** than the true one
  (at most `true - 1`). The rounding therefore *adds* margin against a false outage
  instead of eating it — a maximal 900 s deferral measures as no outage at any of the
  60 possible bucket phases, and nothing under 1201 s of true silence is ever
  declared. The cost lands on the other side: a genuine outage of up to 1259 s can be
  missed, which is the right way round, because under-declaring loses a little
  dormancy accuracy while over-declaring pauses dormancy for the whole camp. Both
  bounds are now pinned by a test that measures them.
- **`PROX_ALPHA_UP` / `PROX_ALPHA_DOWN`** were already absorbed (0.60 / 0.08) ✅.
- **Sync deferral does not break staleness**, checked: the heartbeat reports
  `target_seen_ago_s` as an *age*, and the server records `note_seen(target,
  ts - ago)`, so a deferred sync arriving 15 minutes late still dates the sighting
  correctly (§10.1).
- **§11 item 2's 1000-sync soak** is now explicitly an end-of-Phase-1 item against
  the real backend. Ran the **server half**: `smoke.py --soak 1000`, median 5.5 ms,
  **no drift** (latency fell as caches warmed), 99.5 req/s, service RSS flat at
  35 MB, every signature and nonce verified. The on-badge heap half still needs a
  badge.
- **Everything else in the diff is Phase 2 badge work** and needs nothing here: the
  `rssi_ewma` → `rssi_prox` renames on the hunt path, `prox_filter`/`prox_fraction`
  in `gotcha.py`'s pure half, the −90…−55 dBm bar calibration, scan-duty and
  display-sleep findings, the third-GATT-service result, and §11.1's worn-on-worn
  threshold check.

**New guard: `tests/test_server_plan_parity.py`** (7 tests) parses §5.4 out of the
plan and asserts the table and `TUNABLE_DEFAULTS` agree in both directions —
missing tunables, revived struck-through ones (the four RSSI-trend constants must
stay dead), undocumented additions, and mismatched numeric defaults. This drift was
invisible and would have shipped a tunable the admin page could not reach; with two
sessions editing one plan it would have happened again.

## 7. Not built (and where it belongs)

HTTPS / Let's Encrypt DNS-01 and ports 80+443 are **Phase 5** (§6.1) — today the
service is :8080 and `/v1/enroll` is reachable over plain HTTP, fine on a dev LAN
and a release-checklist item never to ship (§6.3). The player card, four
leaderboards, hit list and QR flow are skeletons until Phase 5. Training mode
(§5.9) is Phase 6 and ships `training_enabled: false`. The `amnesty` modifier is
stored but not yet interpreted by any rule.

**Next: Phase 2** — badge-side connectivity check, enrollment, sync, v2 beacon and
the LED radar. Note its blocking prerequisite is still open: §11 item 5's
**worn-on-worn RSSI walk pair** must run before the radar thresholds are trusted.

## 8. Session wrap-up

- **The deferral/outage coupling is now tested by measurement, not by assertion.**
  `test_deferral_is_never_reported_as_an_outage_at_any_bucket_phase` sweeps all 60
  bucket phases of a maximal 900 s deferral and pins both boundaries (nothing under
  1201 s of true silence is ever declared an outage; up to 1259 s can be missed), so
  a future change to the bucketing fails a test rather than quietly moving the
  margin. The Phase 2 obligation — anchor the cap at the **last successful sync** —
  is written at the constant in `config.py`, with the arithmetic for both anchorings,
  and referenced from `state.outage_intervals()`'s docstring and `server/README.md`.
- **Root `README.md`** now documents `server/` in the project layout and has a
  "Phase 1 — the backend — is done" paragraph with the two commands a newcomer needs
  (`pytest tests/ -q`, `smoke.py`). `server/README.md` gained a "one cross-layer
  constraint" section covering the same coupling.
- **Final state: 255 tests green**; deployed instance on 192.168.1.57:8080 running the
  current code, empty database, game in `lobby`, truce 22:00–08:00, enabled at boot.

# !Fri3d Friends — Gotcha Phase 0 spikes (A5/heap/HMAC done; RSSI-trend NO-GO → fallback) — 2026-07-29

Began implementing `Implementation_Plan_Gotcha_20260726.md` (rev. 5) from its
"Start here" preamble, Phase 0 first. No app code shipped to the fleet; this is
spikes + the pure-half foundation. 118 → **140 host tests green** throughout. All
on `feat/contact-swap-splash-portal`. Three dev badges connected (Espressif
by-id; the 2 CH340 tracker ports were never touched).

## 1. A5 — AppStore update WIPES the app directory (§14.2, decisive)

Replicated the AppStore update path locally on a 2026 badge (no BadgeHub/network
needed): `AppManager.install_mpk(zip, "apps/com.fri3dcamp.fri3dfriends")` over a
folder holding `config.json`+`contacts.json` left a folder containing ONLY the
.mpk's files — the user-data files were gone, manifest bumped 0.9.0→0.9.1. So
**`install_mpk` deletes the app dir and re-extracts** (the docs even list
"destination folder already exists" as an install-failure cause). mpos is frozen
bytecode (`.frozen/mpos`, not on the FS, not introspectable) so this empirical
test is the only confirmation. **Verdict: §8.10.4 MUST be built** — and
`contacts.json` is silently destroyed by every AppStore update in the *shipped*
v0.10.0 app today, a pre-existing bug. Saved to memory
`mpos-appstore-update-wipes-appdir`.

## 2. Heap check (Phase 0 spike #2 input) + HMAC on-device

- `gc.mem_free()` ≈ **6.86 MB** at the launcher → the MicroPython heap is in the
  8 MB **PSRAM**, not internal SRAM. Fragmentation is not the binding constraint;
  D21's one-TLS-handshake-then-signed-HTTP is safe (saved to `badge-heap-psram`).
- **gotcha.py pure crypto half** (new, `app/…/gotcha.py`): HMAC-SHA256 hand-rolled
  over `hashlib.sha256` (MicroPython has no `hmac`), `canonical_json` (hand-rolled
  for byte-identical output on MP + CPython), request/response sign+verify, the
  soul triple (`make_soul`/`commitment`/`verify_soul`), `version_lt`. Verified
  against **RFC 4231 vectors on host AND on a badge**, plus stdlib cross-checks
  proving badge-signer ↔ server-verifier byte interop. `tests/test_gotcha.py`
  (new, 22 tests). 140 total green.

## 3. 2024 badge crash fixed (stale deploy)

The 2024 badge's app crashed: `ImportError: can't import name parse_groups_field`
at `fri3d_friends.py:39`. Its `fri3d_friends.py` was v0.10.0 (imports
`parse_groups_field`) but its `ble_proximity.py` was older and lacked it — a
half-finished deploy. Redeployed the current code files via `tools/deploy.sh`
(sha-verified), **config.json excluded** so "Badge2024lijn" + its groups were
preserved. App loads cleanly now on all three badges.

## 4. RSSI-trend spike — NO-GO, fallback applied (the big one)

The plan's most load-bearing untested assumption (§8.8.2a: a hunter steers on the
RSSI *derivative* — "warmer/colder", shown as a ping pitch bend). Built tooling,
ran 5 open-field walks (advertiser on a ~1.2 m pedestal), analyzed with two
estimators. **Verdict: retracted.**

- **Tooling (all new, in `probes/` + `tools/`):** `probes/rssi_walk_pkg/walk.py`
  (a prompted LVGL Activity — on-screen Dutch instructions, A advances + writes a
  timestamped marker per phase, multi-walk → `walk_<N>.csv`), `probes/rssi_log.py`
  (async boot/logger), `tools/analyze_rssi.py` (replays raw adverts through an
  `(af, as, deadband)` grid + windowed linear regression, scores §8.8.2a,
  auto-pairs `walk_<N>.csv` with `walk_<N>_markers.csv`), `tools/rssi_walk.sh`,
  `tools/deploy_rssi_walk.sh`, `tools/deploy_rssi_logger.sh`, `tools/pull_walks.sh`.
- **Result (`Phase0_RSSI_Trend_Spike_20260729.md`, raw data in `probes/logs/`):**
  the robust regression estimator is consistent across all 5 walks — **approach
  ≈ 52–61 %** (bar 80 %), **stand ≈ 0–5 %**, retreat ≈ 66–80 %. The spec'd
  `fast−slow` EWMA bounced 23–100 %; its "passes" (e.g. open2 100 %) were **false
  positives** (real approach slope only ~0.1 dB/s). Root cause is SNR: real slope
  ~0.1–0.5 dB/s vs ±15–25 dB multipath/body-shadow noise (present even standing
  still at 1 m), at ~0.7–1 advert/s. No estimator/retuning fixes it. Walk 1 was
  NOT botched — its regression (58 %) matched the others.
- **Fallback (applied to the plan):** drop the trend EWMAs
  (`TREND_ALPHA_*`/`TREND_DEADBAND_DB`), `rssi_trend()`, and the ping **pitch
  bend** (`PING_BEND_PCT`). KEEP the LED radar bar, on-screen bar, and ping
  **rate** (absolute proximity, which works). Kill/Reveal unaffected. Narrative
  "Finding them" corrected. Plan §8.8.2a retracted, §8.8.6/§5.4/§8.1 updated,
  §11 item 5 + §12 risk resolved. Saved to memory `gotcha-rssi-trend-no-go`.

## 5. Platform lessons learned (memory)

- **BLE work MUST run as an asyncio task on the OS loop** (`TaskManager` + short
  non-blocking polls) — a blocking `mpremote` script sees **0 scan IRQs** (MPS
  dispatches them through its one loop), and **`asyncio.run()` deadlocks** (MPS
  owns the loop) — that deadlock + over-resetting pushed one badge into a USB
  enumeration fault needing a physical replug. An advertising badge's USB-CDC is
  wedged. (`badge-ble-async-osloop`.)
- **App manifests must be `MANIFEST.JSON` (UPPERCASE)** — LittleFS is
  case-sensitive; a lowercase `MANIFEST.json` isn't read (app registers as
  `fullname="Unknown"`, boot service never starts). (Added to `mpos-firmware-api-gaps`.)
- Two real bugs found by on-device testing of the probe: `_pending.clear()` after
  `batch=_pending` aliases the same list (must **rebind** `_pending=[]`, matching
  `ble_proximity`); and locking one BLE address lost nearly every advert (filter
  by **name** each advert instead).

## Notes / follow-ups

- **Phase 0 remaining (lower-stakes, independent):** WiFi/BLE coexistence (#1),
  scan-duty reduction (#4), 3rd-GATT-service fit (#3), 2024 screen blanking (#6),
  1000-sync soak (#2 — needs the backend).
- **Phase 1 (backend, FastAPI+SQLite in `server/`)** is unblocked — the crypto
  foundation (gotcha.py signer) + the §6.2 transport contract are in place; the
  backend verifier reuses `canonical_json`/HMAC.
- A5 confirmed §8.10.4 (data survival across updates) must be built — affects
  `contacts.json` (no server copy) most.
- Badges left: B (1cdb…) has the `rssi.walk` test app installed (empty groups);
  A (9070…, Tarpon 41b) and the 2024 (3485…, Badge2024lijn) at launcher, healthy.

---

# !Fri3d Friends — Gotcha plan readiness review + rev. 5 (hand-off ready) — 2026-07-28

Full readiness review of `Implementation_Plan_Gotcha_20260726.md`, then a rev. 5
rewrite that folds the review and the day's networking answers in and rebases the
plan on the shipped v0.10.0 navigation model. Deliverables:
`Plan_Review_Gotcha_20260728.md` (new) and the plan itself, now **self-contained
and ready to hand to a fresh implementation session**. No app code changed; 118
host tests green.

## 1. The review (claim-by-claim cross-check against the repo)

Method: complete read of the plan, then verification of every named symbol,
constant, UUID, line ref and behavioural claim against `ble_proximity.py`,
`contact_exchange.py`, `ble_setup.py`, `beacon_service.py`, `fri3d_friends.py`,
`DESIGN.md`, the Phase-5 code review, `docs/setup/index.html` and the
MicroPythonOS docs. The plan's factual claims were almost uniformly correct.
Four blockers found:

- **B1** — direct conflict with the (then-planned, same-day-shipped) menu
  redesign: the plan extended the raw button layer v0.10.0 deletes.
- **B2** — §6.2's response signature lived in an HTTP header, but
  `DownloadManager.post_url()` returns body bytes only (no headers, no status):
  unverifiable on the badge. Forced fix: JSON body envelope
  `{ts, nonce, sig, payload}` with canonical-JSON HMAC.
- **B3** — `_process_result()` drops adverts sharing no group before they reach
  `_seen`, and a Gotcha target is by design out-of-group: **the radar would
  never see the target.** Fix: admit game-block beacons regardless of group, and
  pin the current target (and bounties) in the new LRU cap.
- **B4** — `docs/` is GitHub Pages (HTTPS) and cannot call a plain-HTTP API
  (mixed content) nor a LAN-only backend.

Plus majors: the §8.9 translation pass had already shipped (stale scope), the
backend had no home, `witnesses[]` was an unresolved build-or-drop tension,
stale rev metadata, small schema gaps (heartbeat cadence, `life_id`, enroll
payload mismatch, QR rendering location); and a set of minors (battery-level
mismatch 10 %/20 %, demo-mode drift, dual `DORMANT_H` values, line-ref drift).

## 2. Decisions taken (user + Fri3d infra)

| Topic | Decision |
|---|---|
| B1 input model | Resolved by v0.10.0 shipping; plan rebased (D29, below) |
| B4 web hosting | **Backend serves the player/admin pages itself** (D31) |
| `witnesses[]` | **Dropped for v1** (D30); parser tolerates the key for revival |
| Backend stack | **FastAPI + SQLite in `server/`** in this repo, systemd-run, badge-simulator pytest fixture as the Phase 1 harness |
| Networking | Fri3d confirms badges reach the internet; a **fixed public IP is routed to the on-site game laptop**; ports 80/443 open internally + externally (Ward). IP not known in advance → **address by low-TTL DNS name; the `.mpk` ships hostnames only**; A record repointed on arrival |
| TLS | Let's Encrypt via **DNS-01** (dev is behind a Fritz!Box with no external :80/:443; forwards :8066→80, :8446→443 for off-LAN dev only — release checklist: dev ports never ship) |
| `DORMANT_H` | 12 h normative (was dual-valued 24/12) |

## 3. Rev. 5 of the plan (all folded in, body no longer contradicts anything)

- New decisions **D29** (all input rides the v0.10.0 focus model: focusable
  **hunt strip** with the §5.7 A-ladder `radar/onthullen/AANVALLEN/afbreken`,
  `Gotcha` main-menu row with `MENU_MAX` 6, Gotcha screen absorbing radar
  detail + opt-out + training + demo, consent mini-menu, duel screens consume
  X), **D30**, **D31**. Target version → **v0.11.0**.
- §6.1 rewritten around D31 (tunnel options deleted); §6.2 body-envelope
  signing; §4 admission widening + pinned LRU (and the corrected "not an IRQ
  path" description); §8.9.4 rewritten to "translation shipped — remnants
  only"; §9 witnesses removed, stack fixed, heartbeat cadence + `life_id` +
  enroll payload specified, on-badge QR via the `_update_setup_qr` pattern;
  §14.1: A2 resolved, new **A7** (register DNS name + confirm DNS-01 API) and
  **A8** (arrival-day check: do badges resolve the hostname with the uplink
  down? fallback = IP literal in the §6.3 slot); Phase 0 renumbered with
  **A5 (AppStore-wipe test) first**; battery ladder harmonized (hint at 20 %,
  persistent last-LED blink from 10 %); every `press MENU` converted (final
  grep clean); "Start here" preamble makes the plan self-contained.
- Adopt-prompt invulnerability re-verified against v0.10.0: **still unbounded**
  (X dismisses it now, but unattended it is indefinite) — §5.5's two fixes stand.

## Notes / follow-ups

- Hand-off prompt for the implementing session was drafted (in-conversation).
- Ward Q&A captured in the review's B4 update; the Discord message sent asked
  about on-site routing, uplink-drop behaviour, ports, and DNS — answered:
  *"werk bij voorkeur met een DNS met lage TTL. Poorten is 'zeker intern, maar
  ook extern' geen probleem."*
- Next actions: register the game hostname + verify DNS-01 support (A7), run
  A5 on a bench badge, then start Phase 0/1 per the plan.

---

# !Fri3d Friends — v0.10.0 joystick-menu shipped (implemented + on-device debug) — 2026-07-28

Implemented `Implementation_Plan_Menu_20260728.md` (the joystick-menu redesign +
2026 OS-drawer fix), debugged it live on the three connected badges, and packaged
v0.10.0 for BadgeHub. All on `feat/contact-swap-splash-portal`. Version bumped
0.9.0 → 0.10.0. 118 host tests stay green throughout.

Badges (by stable serial-id; board type is NOT in the serial — see memory
`badge-usb-ports`): `90706901bac80000` & `1cdbd49d9de40000` = 2026,
`348518acfac00000` = 2024.

## 1. The menu redesign (plan §4a–4e), all in `fri3d_friends.py`

- **Focus-group helpers (the drawer fix):** `_make_focusable` (uses
  `mpos.ui.add_focus_border`), `_apply_focus`/`_set_focus`/`_establish_focus`/
  `_release_focus`. Our focusables are the default LVGL group's *only* members
  while foregrounded → the keypad drives them, never the OS bar. Membership is
  reconciled per state-change and emptied on pause (launcher/editor get a clean
  group).
- **Menu overlay + nametag affordance:** `_build_menu` (create-once `MENU_MAX`
  `lv.button` rows) + a bottom "Menu" pill (`_build_menu_button`). `_open_menu`/
  `_close_menu`/`_do_menu_action` wire the 5 items (Vrienden dichtbij / Contact
  ruilen / Geluid / Telefoon-setup / Instellingen) to existing methods.
- **`onBackPressed`** returns `True` to close an overlay, `False` to quit — so X
  closes the menu without quitting (the OS-level back hook; the app never polled
  X). This was the key mechanism, confirmed from the MPOS app-lifecycle docs.
- **Adopt prompt → focusable rows** (lv.button + a "Meedoen" confirm row);
  deleted `_handle_adopt_buttons`.
- **Configure-me → 3-row mini-menu** (Op badge instellen / Telefoon-setup /
  Overslaan). The 240px screen can't fit 3 rows + a scannable QR, so the
  phone-setup QR now opens in the setup-window overlay via *Telefoon-setup*
  (drops the old "always advertising on Configure-me" behaviour — a phone pairs
  only after selecting it).
- **Removed the raw-poll input model:** `_handle_buttons`, `_handle_b_button`,
  `_held`, `_edge`, `_setup_buttons`, all `BTN_*`/`START_PIN`/`SETUP_HOLD_MS`
  maps, `_start_configure_setup`/`_run_configure_setup`, and the
  `_controls_*`/`_hint_*` legend. AST-verified: 22 new methods in, 10 old gone.

## 2. On-device debugging — three real bugs found after deploy

Deployed only the 2 changed files (`fri3d_friends.py` + `MANIFEST.JSON`) via
`tools/deploy.sh` to preserve each badge's `config.json`. Verified by reproducing
`import`/build/focus logic on the badges over `mpremote` (the REPL is healthy at
the launcher; an app running with BLE up wedges USB-CDC — recover with one
`mpremote reset`, or `sudo usbreset <bus>/<dev>` for a deep wedge).

- **"could not load app"** = `NameError: name 'H' isn't defined` at import. The
  new MENU geometry constants referenced `H`/`W` but were placed where
  `SETUP_HOLD_MS` used to be — ~60 lines **before** `H`/`W` are defined by the
  `mpos.DisplayMetrics` block. (py_compile can't catch it; my first on-device
  "build" check missed it because it called `_build_idle` directly, not
  `onCreate`.) Fix: moved the block after the metrics definition.
- **Three firmware-vs-docs API gaps** (this MicroPythonOS build predates
  docs.micropythonos.com — saved to memory `mpos-firmware-api-gaps`):
  - no `mpos.add_focus_highlight` → use **`mpos.ui.add_focus_border`**;
  - the focus group has `add_obj` but **no `remove_obj`/`focus_obj`** → use
    top-level **`lv.group_remove_obj(o)`** / **`lv.group_focus_obj(o)`**;
  - guarded `add_event_cb` with a `_bind_event` helper (3-arg then 2-arg).
- **"threw an exception, it might be glitchy"** = `AttributeError: ...has no
  attribute '_strip_focus'`. `onCreate` called `self._strip_focus()` (a method I
  referenced but never defined — I named it `_release_focus`). It threw on the
  *last* line of `onCreate`, after the screen was built → the OS loaded the
  screen but warned; the 2026 OS recovered, the 2024 OS quit on dismiss (exactly
  the user's report). Fix: removed the redundant call (`onResume`'s
  `_establish_focus` already reconciles the group). Verified `CREATE_OK` on
  badges 1 & 2.

## 3. UX fixes from user feedback

- **Adopt prompt defaults unchecked.** `[True]*…` → `[False]*…` (join nothing by
  accident). "Meedoen" with nothing checked now **silently quits** the prompt
  (per user: no hint, no join). Verified on badge 2.
- **Live pill refresh.** A newly-added group's pill no longer waits for a reboot:
  `_place_pills` now pre-builds `MAX_PILLS` slots once; `_refresh_pills()`
  updates label/colour/visibility in place and repositions the friends line (same
  safe pattern as the detail rows — no widget create/delete, dodging the
  "deleting live widgets crashes" landmine). Wired into `_adopt_groups_now` and
  `_apply_reload`. Verified on badge 1: adding a group rendered a 4th pill
  immediately (friends line 162→188). Banner changed from "…herstart de app" to
  "…erbij".
- **Contact ruilen intermittent reboot** (badge 1, 2 of ~many tries). `_do_exchange`
  + the BLE swap are fully try/except-guarded (errors log to `exch.log`), so a
  reboot is a **C-level ESP32 panic** (heap exhaustion / NimBLE race), not a
  Python error. Added `gc.collect()` before the radio-heavy window as a
  low-risk mitigation. **Not a confirmed fix** — pinning it needs the
  Guru-Meditation backtrace from serial while a 2-badge swap runs.

## 4. BadgeHub package v0.10.0

Built per README "Build & publish" (deterministic zip, `touch -t 202501010000`,
sorted `zip -X -r -0`). Staged to `/storage/fileshare/com.fri3dcamp.fri3dfriends/`
(the user's pickup folder), all consistency-checked (sha):

| file | purpose |
|---|---|
| `com.fri3dcamp.fri3dfriends_0.10.0.mpk` | Create-Project upload (single top-level folder; in-pkg MANIFEST 0.10.0; icon `icon_64x64.png`) |
| `metadata.json` | manual-refresh path (version 0.10.0, executable matches, long_description synced to the menu model) |
| `icon-64x64.png` | manual-refresh path — **hyphen** name per README issue #1 (icon_map `{"64x64":"icon-64x64.png"}`); sha-identical to the in-pkg icon |

Corrected stale memory `badgehub-publish-fileshare` (it had the pre-issue-#1
underscore icon name). Note: re-uploading the `.mpk` to an *existing* BadgeHub
project does **not** refresh metadata/icon — clean path is delete+recreate from
the `.mpk`, fallback is manually re-uploading icon + metadata.json.

## 5. Docs

README controls/setup sections rewritten to the menu model (joystick/A/X, the
menu-item table, the drawer-fix note, Configure-me mini-menu, live pill refresh).
DESIGN.md §7 flagged with a v0.10.0 input-change note (its per-button GPIO /
`_held`/`_edge` details are retained as pre-v0.10.0 reference).

## Notes / follow-ups

- **Interactive checks still owed (can't be automated):** tap-to-launch on each
  badge (no more "could not load app"), and confirm joystick moves highlight / A
  activates / X closes / **no OS drawer** on any press.
- **Contact ruilen reboot:** to pin, capture badge 1's raw serial during a
  2-badge swap and decode the backtrace. `gc.collect` mitigation is live on all 3.
- All 3 badges deployed with `RESET=1` (clears the cached `sys.modules` so the
  next launch loads v0.10.0) and left at the launcher.

---

# !Fri3d Friends — on-badge v0.9.0 testing → 2026 OS-drawer diagnosis → joystick-menu redesign plan — 2026-07-28

On-hardware test of v0.9.0 on the dev badges, which surfaced a 2026-only input
problem, a full investigation of its root cause, and an agreed redesign. **Output is a
plan, not shipped code** — `Implementation_Plan_Menu_20260728.md` (committed `ccfd16a`).

## 1. What testing found

Walked v0.9.0 through the manual tests on two 2026 badges (`90706901bac80000` "Tarpon
41", `1cdbd49d9de40000` "David2026b") and, later, a 2024 badge (`348518acfac00000`).

- **Auto-nickname, group adoption (multi-select), and the on-badge editor all work on
  hardware** — the editor's `SharedPreferences` → `sanitize_config` round-trip was
  verified live (incl. the `bool("off")` trap and preset→dBm mapping).
- **Adopt prompt bug:** a stale `_pending_adopt` could survive a later swap and name the
  wrong peer — fixed (clear it at the top of `_offer_groups`). Also fixed the 2-line
  title overlapping the first group row (rows moved to y=50).
- **Ghost-splash bug** (X showed the splash, X-again quit): root-caused to a **double
  `setContentView`** (splash screen pushed, then nametag pushed → stale OS-stack entry).
  Fixed by making the splash a **full-screen overlay** on the main screen with a single
  `setContentView`. *(These two fixes are the "splash & adopt fixes" recorded in the
  entry below; committed `12aab97`.)*
- **The 2026 OS-drawer hijack** (the headline finding): pressing our buttons pops up the
  MicroPythonOS top-bar/drawer.

## 2. Drawer root cause (fully investigated on-device)

The 2026 keypad indevs (joystick + button expander) drive the **shared default LVGL
focus group**, which also holds the OS top-bar/drawer focusables. Our app **bypasses
LVGL and polls buttons raw**, so it adds **nothing** to that group — every press is
"unclaimed" and the OS grabs it.

Confirmed live:
- Redirecting the keypad indevs to an empty group **stopped the drawer** — and also
  broke the launcher (proving it's the same keypad→OS-group path). So any redirect must
  be **scoped to foreground**, not global.
- **Focus-group model = ONE shared default group, membership per-activity.** Measured
  `get_obj_count()`: launcher foreground → 37; **our app foreground → 0 (empty)**. So if
  we add only our own focusables they become the *only* keypad target and the bar is
  unreachable — the drawer fix falls out of using the input system correctly, with **no
  restore footgun** (we never touch indev→group wiring).

## 3. Nav-convention investigation (settles how a menu would navigate)

Captured the real button→LVGL-key map by installing an on-badge async poller that logs
to a file (decouples from host-side timing).

- **2024 (measured):** joystick → `UP/DOWN/LEFT/RIGHT`; **A → `ENTER` (select)**;
  **X → `ESC` (back)**; B/Y emit ASCII `'B'`/`'Y'` (not nav keys); START/MENU → OS codes
  2/3. The 2024 **has a joystick** and a keypad indev (correcting an old DESIGN note that
  said its buttons aren't an OS indev; also **no touchscreen** — `has_pointer` False).
- **2026:** same native joystick indev + the OS-wide `A=ENTER`/`X=ESC` convention. Raw
  codes not captured (the expander delivers via an internal queue, not `get_key()`
  polling) — accepted, to be confirmed concretely at build time.
- An earlier `Y=up/B=down` guess was **wrong** and is dropped.

## 4. Agreed redesign (planned, not built)

A **single joystick-navigated on-badge menu** replaces the raw-poll button scheme + the
`A:list B:mute Y:swap` legend. Rows are **focusable `lv.button`s with `CLICKED`
handlers**, so the OS does navigation + select for free (no key-mapping code), identical
on both boards. This *is* the drawer fix (our focusables become the only keypad target).
Also removes the awkward long-press-B (phone-setup becomes a menu row). Full detail,
item list, risks and verification in `Implementation_Plan_Menu_20260728.md`.

## 5. Operational

- **nostr boot service disabled** on the two 2026 dev badges — it ships a
  `NostrBootService` that thrashes relays until thread exhaustion (`can't create
  thread`), contaminating tests. `MANIFEST.JSON` backed up to `.bak`; reversible (flip
  `boot_completed_disabled` back).
- **Stacked-instance gotcha:** launching the app repeatedly via the *home* button (not
  back/quit) stacks multiple app instances (saw 5) — the artifact behind the original
  intermittent Test-1 splash-quit. Exit with **back/X** (destroys) to avoid it.
- New tooling: `tools/deploy.sh` (sha-verified deploy; `RESET=1` opt-in reboot; probes
  REPL readiness; `tr -d '\r'` on the remote sha) and `tools/serialcap.py` (passive,
  reconnecting console capture). Both committed by the parallel session.
- Corrected the `badge-usb-ports` memory (it labelled the `348518…` boards 2026; they're
  **2024** — probe `get_hardware_id()`, don't infer board from serial).

## 6. Branch note

A **parallel Claude session shares this branch** (`feat/contact-swap-splash-portal`) and
committed the v0.9.0 features (`c621ce4`), the Dutch UI translation (`fa7b644`), and my
splash/adopt fixes (`12aab97`). At session end its `Implementation_Plan_Gotcha_20260726.md`
edits were still uncommitted in the tree — left untouched.

---

# !Fri3d Friends — Gotcha plan rev. 3: training mode + update path; splash & adopt fixes — 2026-07-28

Design session plus two hardware-driven code fixes.
`Implementation_Plan_Gotcha_20260726.md`: **~1875 → 2310 lines** (rev. 3), adding two
features that came out of review rather than from the peer specification.

## 1. Update / hotfix path (D27, plan §8.10)

**The problem:** D8's "no backward compatibility required" is true only until badges are
handed out on Friday morning. After that there are ~700 units in the field, most of
which will never be updated during the event, and every change is a live migration
across a population you cannot reach.

**The answer is mostly not an update mechanism.** Every threshold, timer and rule is
already server-pushed (§5.4), so the config channel *is* the hotfix channel. Added
**per-feature kill switches** (`reveal_enabled`, `bounty_enabled`, `training_enabled`,
`alarm_enabled`) to complete it — a broken mechanic gets disabled camp-wide in one click
and lands on every badge within `SYNC_S`. **Absent switch must read as `true`** so an
older backend cannot disable features by omission.

**No OTA** (§8.10.5). Writing a self-updater for 700 devices three weeks out, whose
failure mode is "badge no longer boots", loses badly to a nudge screen plus the
AppStore that is already installed.

The nudge: sync response gains `app: {min_version, latest_version}` and a free-text
`broadcast` line (which covers "update de app", "spel gepauzeerd" and "prijsuitreiking
om 17:00" with one mechanism). `app_version` added to `heartbeat`; the admin dashboard
gets a **version histogram** — you cannot manage an update you cannot see.

> ⚠️ **An out-of-date badge must stay killable.** A badge below `min_app_version` stops
> **hunting** but its **victim-side responder keeps running**. If falling behind removed
> you from the game, *not updating* would be perfect invulnerability — the identical
> failure mode D3 exists to prevent.

**Wire-format discipline (§8.10.2), which matters more than the nudge:** never bump
HSNT `ver` during the camp. Receivers drop unknown versions, so a `ver = 3` hotfix
would split the camp into two populations that cannot see each other at all. Extend via
the reserved `blocks` bits 1–7 and `gflags` bits 6–7. GATT payloads: additive keys only,
responders ignore unknown keys.

### ⚠️ A pre-existing data-loss bug found while specifying this

**Everything persists inside the app directory** — the one an AppStore update replaces:

```
/apps/com.fri3dcamp.fri3dfriends/config.json     name, groups, sound, rssi_floor, quiet hours
/apps/com.fri3dcamp.fri3dfriends/contacts.json   every contact ever swapped
/apps/com.fri3dcamp.fri3dfriends/gotcha.json     pid, player_key, soul, score, event queue
```

Gotcha state is the *safe* one: `badge_key` is the stable BLE MAC and §10.5 already
re-enrolls to the same `pid` with score intact; the only true loss is the unsent event
queue, fixed by flushing before an update.

**`contacts.json` is the casualty, and it is not a Gotcha problem.** There is no server
copy and there never will be — the swap is deliberately offline-only. **If updates wipe
the directory, v0.9.0 is silently destroying users' contacts today.**

Whether MicroPythonOS actually wipes it is **untested**, so nothing was designed around
either answer. New open item **A5** (§14.2), flagged as the cheapest high-value test in
the document: sentinel files on a bench badge, publish a throwaway 0.9.1, update from
the on-badge AppStore, see what survives.

## 2. Training mode (D28, plan §5.9)

Went through three designs before settling. Worth recording the reasoning, because the
first two are the obvious ones and both are wrong.

| Design | Why rejected |
|---|---|
| **Solo simulator** (synthetic ghost target, no radio) | Dropped by request. Would have been a good dev tool but teaches nothing about real RF. |
| **Silent probe** (victim's badge runs the duel invisibly) | If the target gives no feedback it does not need to *participate*, and shouldn't — see below. |
| **Mutual opt-in** ✅ | Both sides consent, so everything is real except the consequences. |

**Why the silent version failed on inspection**, even though it needs no rules at all:

- **Reveal becomes unpracticeable.** Reveal's entire product is *their badge flashes so
  you can identify them*. Suppress that and it returns "yes, that pid is in range",
  which the radar already said.
- **Silent invulnerability windows.** One connection slot (§5.5): a badge held in a
  silent duel answers `BUSY` to a *real* attack. Trickle training probes at a friend and
  they become very hard to kill, with nobody able to see why.
- **It becomes a weapon if it touches real state** — silently burning a victim's single
  dodge (rule 5) sets them up for an instant real kill by a confederate.
- Unattributable battery drain on a budget §8.7 already calls marginal.

**The chosen design.** Both players pick `Oefenmodus` within `TRAINING_WINDOW_S`;
badges pair via the **HXCG overlapping-window pattern** from the contact swap, signalled
by a new **`gflags` bit5 `SEEKING_TRAINING`** — one reserved bit, no new beacon, no new
scan. (§5.1 rejected HXCG for *kills* because a kill is one-sided; mutual consent is
exactly what it was built for.) Within a session each badge is the other's target, so
both players practise hunting **and** dodging.

**The prize is dodge practice.** Rule 5 gives one dodge per assassin per life, so
without training every player's first escape attempt is also their only one, spent while
they are still working out what the siren means.

### The three isolation disciplines (§5.9.3) — each closes a named exploit

1. **Override the target, never swap it.** A save-and-restore temp variable corrupts on
   a mid-session crash: the badge wakes believing the training partner *is* its real
   target, and if that reached flash it survives the reboot. An override fails
   correctly. `gotcha.json`'s `target` is never written during a session.
2. **A disposable soul.** A real kill ends in soul disclosure and the backend credits a
   kill on nothing but `sha256(soul) == commitment` (§3.4) — so a real soul is a
   *bankable kill*, and two friends could farm each other by "training".
3. **Presentation-only death.** Full alarm, death screen and countdown, but no
   `alive=false`, no `respawn_at`, no streak change, no dodge-ledger decrement, no
   `killed_by`, and a dummy target in `SPOILS`. Otherwise "let's train" removes someone
   from the game for 30 minutes.

Nothing is queued and nothing is uploaded; the production scoring path never sees a
training event.

### Not a shield, and no truce logic

Training holds no connection open — it is a series of short duels, so the BUSY windows
match a real duel's. A real `ATTACK` between duels is honoured normally and **aborts
the session**; the beacon keeps `ALIVE`/`BOUNTY` honest and never sets `TRUCE`.
`TRAINING_SESSION_S` (300 s) and `TRAINING_REENTRY_S` (600 s) are belt-and-braces
against *social* abuse ("I'm training, don't kill me").

**Training carries no truce and no quiet-hours logic at all, by decision** (§5.9.5).
Both parties consented seconds earlier and are standing together; where they practise is
their own responsibility, exactly as with rule 14's safe zones. **This is the simpler
implementation, not the more permissive one** — a gate would drag the truce schedule,
`clock_offset_s` and each player's personal window into the training path. The rules
card carries a courtesy line instead. The real game's truce behaviour is unchanged.

**Sequenced last in Phase 6 and explicitly droppable.** Development does not depend on
it: two dev badges in a throwaway backend game exercise the real duel, handshake and
soul disclosure, which is a better protocol test than training mode will ever be.

## 3. Code: splash overlay + adopt-panel layout (found on hardware)

Two fixes to `fri3d_friends.py` made **outside the design work**, from running the
translated build on a badge.

### Splash is now an overlay, not a second screen

`_build_splash(scr)` builds a full-screen overlay **on the nametag screen**;
`setContentView` is called **exactly once** in `onCreate`, and `_enter_main` reveals the
nametag by setting `lv.obj.FLAG.HIDDEN` on the splash.

> 🐛 **The bug it fixes.** Pushing the splash as its own content view and then pushing
> the nametag left a **ghost entry on the OS screen stack**: pressing **X** (OS back)
> popped the nametag and *revealed the splash again*, needing a second X to quit.

The splash is **hidden, never deleted** — deleting a live widget hard-crashes this build
(the same landmine as the config-reload screen rebuild). Documented in `DESIGN.md` §8.

### Adopt prompt rows moved 30 → 50 px — Dutch-translation fallout

The multi-group title is two lines in Dutch (`<peer> zit in N groepen` /
`Welke meedoen?`) where the English was one. At `montserrat_16` (~19 px/line) the second
line reached ~y=44 and the first row at y=30 sat on top of it. Rows now start at y=50
and the title gets an explicit width; 5 rows × 20 px ends ~y=130, clear of the footer.

> **This is the general risk of the translation pass, now confirmed rather than
> predicted.** Dutch runs ~15 % longer, so **any label that gains a line breaks every
> hand-positioned widget beneath it, and only hardware catches it.** Both `DESIGN.md`
> §11a.1 and plan §8.9.2 now say so, and call for a screen-by-screen pass on a real
> badge rather than a read-through.

## Verification

- `python3 -m pytest tests/ -q` → **118 passed**
- `fri3d_friends.py` parses; `_rbox()` signature confirmed compatible with the new
  splash call site

## Known gaps / follow-ups

- ⚠️ **A5 (new, top priority): does an AppStore update preserve
  `/apps/com.fri3dcamp.fri3dfriends/`?** Decides whether §8.10.4 needs building at all,
  and whether v0.9.x is destroying contacts today.
- ⚠️ **A6: do the built-in `font_montserrat_*` carry Latin-1?** Still assumed no; the
  ASCII-only rule stands until someone renders `ë é ï` and reads it back.
- ⚠️ **The rest of the Dutch UI is still not width-checked on hardware.** One overflow
  found and fixed; assume more.
- Gotcha remains **plan only** — no `gotcha.py`, no backend, no web pages.
- `MANIFEST.JSON` still at 0.9.0; the Dutch UI, the splash fix and the adopt fix are all
  unreleased.

# !Fri3d Friends — Gotcha plan rev. 2 (peer-spec merge) + Dutch UI translation — 2026-07-26

Second session of the day. Two halves:

1. **Design** — compared our Gotcha plan against an independent functional spec written
   in parallel by another Fri3d participant, and merged the ideas worth taking.
   `Implementation_Plan_Gotcha_20260726.md` grew **1362 → ~1875 lines** (rev. 2).
2. **Code** — first application changes for v0.10.0: the whole user interface was
   **translated to Dutch**, and the LED design was reworked.

Unlike the earlier session today, **this one did modify application files.**

## Part 1 — Merging the peer specification

Source: `/storage/fileshare/Gotcha_Badge_Game_Specificatie_1_tot_30.txt` (Dutch, 30
numbered chapters, hardware-agnostic). It is a *functional spec*; ours is an
*implementation plan* for one specific badge. High conceptual overlap, and the
disagreements were mostly about what 700 badges at a real campsite do to a design.

### Adopted (with the decision id added to the plan)

| # | Idea | Landed in |
|---|---|---|
| D22 | **Reveal** — target's badge flashes gold + chirps, and *they know* | §5.7 (new), rule 2, GATT `REVEAL` char, 3 tunables |
| D23 | **LED colour language** | §8.8 (rewritten, see below) |
| D24 | **Spawn / join protection**, 90 s | §5.8 (new), `gflags` bit4, rule 8 |
| D26 | **All UI in Dutch** | §8.9 (new) — implemented this session |
| — | Demo mode (learn the lights + sounds in 15 s) | §8.4, §13 |
| — | Battery warning ladder 20/10/5 % | §8.7 lever 4 |
| — | Badge rebind (broken badge → new hardware, score intact) | §9.4, §10.5 |
| — | Live dashboard metric list; multiple concurrent admin phones | §9.4 |
| — | Reworked state model | §9.6 (new) |

**Reveal is the best idea in their document.** RSSI is a scalar: it walks you into a
crowd of thirty and then goes flat. Their answer — the badge never names the target,
you press Reveal and only the real one lights up — solves the last ten metres. We kept
our target name (it makes the hunt narratable) and added Reveal as the
crowd-disambiguation move. The cost is paid in the same instant as the benefit: you buy
their location by telling them a hunter is within a few metres, which is self-limiting,
so `REVEAL_COOLDOWN_S` (120 s) is a backstop rather than the primary brake.

Two implementation calls worth recording:

- **Reveal shares MENU with attack**, escalating by distance (attack in kill range →
  reveal in reveal range → radar detail). A/B/Y/START are all bound already
  (A = detail, B = mute / long = setup, Y = swap, START = exit). The ladder is
  monotonic in proximity so it cannot misfire in the dangerous direction, and the
  screen names the action before it is pressed.
- **Reveal is a GATT write, not a beacon flag.** The cheap version (advertise
  "revealing pid X" and let X notice while scanning) fails exactly where it matters:
  `beacon_service.py` advertises but deliberately does **not** scan (§5.6), so a
  connectionless reveal would silently never work against players with the app closed.

### Rejected, and why

| Their rule | Why not |
|---|---|
| **Badge off / flat battery = elimination** (§14, §15) | §8.7 says the app gets ~11 h against a 16 h waking day. This would eliminate a large slice of the camp for a logistics failure. Ours: respawn (rule 8). |
| **Server is sole source of truth; badges decide nothing** (§2, §8) | At a campsite this makes dead zones into places the game stops, and into invincibility zones. Ours: D6/D10, queue events and hand the inherited target over inside the kill handshake. |
| **Shields** (§12) | Redundant with dodges; two overlapping defensive systems. |
| Separate child/adult rings (§4, §19) | Replaced — see below. |

Also noted: their spec has **no proof of physical presence** — the server sees a POST
claiming a kill and cannot distinguish it from one sent from a tent. That is what our
commitment–disclosure "soul" (§3.4) exists for.

### Naming collision fixed

§3.4 was "commitment–**reveal**", the standard crypto term. Since rev. 2 adds a
**Reveal** game mechanic, the crypto is now called **commitment–disclosure**
throughout, and the plan tells the implementer to write `disclose_soul()`, not
`reveal_soul()`.

## Part 2 — Kids and adults → personal quiet hours (D25)

Their §4/§19 separates children and adults into disjoint target chains with their own
play hours. Digging in, that bundles **three different problems**: safety (an adult
walking up to a child), fairness (adults dominate the boards), and sleep (kids go to
bed before 22:00).

Separate rings only addresses fairness, and **does not even deliver the safety it
implies** — our bounty rule (streak ≥ 3 is fair game for everyone) and target
inheritance both cross cohorts, so a real guarantee means two fully disjoint games:
two rings, two hit lists, eight boards, two ceremonies. It also requires recording
**which badges belong to minors**, a category of data this design has otherwise avoided
(D17, §13), and it deletes the best story the game can produce.

**Decision (D25): one ring, no age data anywhere, plus personal quiet hours** (§10.4a).
Any player sets their own window, 20:00 earliest to 10:00 latest; it is not age-gated
and serves an adult who sleeps at 21:00 identically.

Two exploits this opened, both closed in the spec:

1. **Asymmetry** — "unkillable but still hunting" would have been found on Friday
   afternoon. The window blocks attacking *and* being attacked.
2. **Decay freezing** — declaring 20:00–10:00 would otherwise freeze a streak 14 h/day
   and let someone hold the crown by sleeping. So **only the camp-wide truce pauses
   streak decay**; personal windows do not (§2.2). An early night costs ~2 h of decay.

Skipped for now: "finale mode" (their §29), left open in the plan.

## Part 3 — LEDs: the whole strip becomes the radar (D23)

**The friend-LED feature is removed.** `DESIGN.md` §11's one-LED-per-nearby-friend
breathe is replaced by a **proximity bar** across all LEDs (4 on 2024, 5 on 2026):

| `rssi_ewma` | Lit | Colour | Animation |
|---|---|---|---|
| not detected | 0 | — | dark |
| far | 1 | blue | breathe 3800 ms |
| closing | 2–3 | blue → amber | breathe 2400 → 1400 ms |
| reveal range | n−1 | amber | breathe 700 ms |
| kill range | **all n** | **red** | steady |

Whole-strip overrides: under attack (red, **steady** — the WS2812 IRQ constraint, not a
style choice), revealed (gold), kill (green), dead (slow red pulse), protected (white),
low battery (last LED orange only, so a dying badge can still hunt).

Three reasons this beat sharing the strip:

- **It is the power budget.** §8.7's biggest lever is blanking the screen — but the
  radar currently *lives* on the screen, so today that lever blinds the hunter. A bar
  is a *length*, pre-attentive and legible at several metres, in a way a single
  colour-coded dot is not.
- **Average LED draw falls.** Friend LEDs breathe whenever anyone is nearby; the hunt
  bar is dark whenever the target is out of range, which is most of the time (§3.3).
- **No information is lost** — the friends panel and group pills still show everyone.

Sequencing recorded in §8.8.5: **do not delete the friend-LED code before the bar
exists** (that just leaves a dead strip), and `_hsv()` / the group→hue derivation must
survive the deletion because the on-screen pills still use it.

## Part 4 — Dutch translation (implemented, D26 / §8.9)

Every string the player sees is now Dutch. Code, comments, docstrings and log output
stay English.

| File | Scope |
|---|---|
| `app/…/fri3d_friends.py` | ~42 strings: banners, prompts, first-run screen, controls hints, adopt prompt, on-badge editor field titles |
| `app/…/ble_setup.py` | the 5 `RANGE_PRESETS` labels |
| `docs/setup/index.html` | ~59 strings: whole phone setup page incl. all status/error text |
| `tests/test_ble_setup.py` | label assertions updated |
| `README.md`, `DESIGN.md` | quoted UI strings + a new language/glyph section |

### ⚠️ The font landmine — found before writing any copy

UI chrome renders in **built-in** `font_montserrat_12/14/16/24/28`. On a stock lvgl
build these carry **ASCII only**: `ë`, `é`, `—`, `…`, `✓`, `·` render as missing-glyph
boxes, **with no warning at build time**.

- **Rule: UI copy is pure ASCII.** Costs nothing in Dutch (`een`, not `één`).
- **Player names are exempt** — the 42 px label uses the bundled **Latin-1** subset TTF
  (`montserrat_name.ttf`), so `Zoë`/`Renée` render correctly. Never strip accents from
  a name.
- **This surfaced pre-existing bugs.** v0.9.0 was already shipping `…`, `✓`, `·` and
  `—` inside UI strings. All removed. `_short()`'s `…` became `"..."` with the slice
  width adjusted (`n-1` → `n-3`, guarded by `max(1, …)`) so rendered width is
  unchanged; the friends-line cap went `[:89]+"…"` → `[:87]+"..."`.

### `RANGE_PRESETS` is a round-trip key, not just display

The on-badge editor passes dropdown options as `[(label, label)]`, and
`settings_to_config()` matches the returned string against `RANGE_PRESETS` labels — so
translating them is a **behavioural** change and had to land together with
`tests/test_ble_setup.py`. (The `sound` radiobutton was safe: its value `"on"`/`"off"`
is separate from its label, so only `("Aan","on")`/`("Uit","off")` labels changed.)

### Terminology, fixed once in plan §8.9.3

`doelwit` (target), `reeks` (streak), `premie` / `premielijst` (bounty / hit list),
`onthullen` (reveal), `ontsnappen` (dodge), `uitschakelen` (kill), `terugkomen`
(respawn), `wapenstilstand` (truce), `stiltetijd` (quiet hours), `beschermd`
(protected), `klassement` (leaderboard). Register is **`je`, never `u`**; loanwords the
audience actually uses (`badge`, `groep`, `swap`, `wifi`) are kept.

## Verification

- `python3 -m pytest tests/ -q` → **118 passed**
- All six app modules parse (`ast.parse`)
- Scripted check: **0 non-ASCII characters remain in any UI string literal**
- Both translation passes were applied by assert-checked scripts (every old string had
  to match exactly once, or the script aborted without writing)

## Known gaps / follow-ups

- ⚠️ **Nothing was deployed to a badge this session.** Two badges are on USB
  (`usb-Espressif_Systems_Espressif_Device_1cdbd49d9de40000-if00`,
  `…_90706901bac80000-if00`) but were not flashed.
- ⚠️ **Dutch strings are not width-checked on hardware.** Dutch runs ~15 % longer than
  English on a 296×240 fixed-font screen with no reflow, and several labels were
  already near their limits. **This is the first thing to check on the next deploy.**
- ⚠️ **The ASCII-only assumption is unverified.** Nobody has confirmed this build's
  built-in fonts actually lack Latin-1. Plan §8.9.1 and `DESIGN.md` §11a.1 record the
  check: render `ë é ï` in `font_montserrat_16` and read it back with
  `get_all_widgets_with_text()` (screenshots cannot answer this — `DESIGN.md` §1).
- The LED bar and everything else in rev. 2 is **plan only** — no Gotcha code exists.
  `DESIGN.md` §11 still documents the friend LEDs, correctly, because they still ship.
- `MANIFEST.JSON` is still at 0.9.0; the Dutch UI is unreleased.

# !Fri3d Friends — Gotcha (Assassin) game: design + implementation plan — 2026-07-26

Design-only session. Produced **`Implementation_Plan_Gotcha_20260726.md`** (~1360
lines), a hand-off-ready plan for adding a camp-wide game of
[Assassin/Gotcha](https://en.wikipedia.org/wiki/Assassin_(game)) to the app for Fri3d
Camp (**Fri 14 – Sun 16 August 2026**, badges handed out Friday morning). **No code
was written and no application file was modified.** Target version v0.10.0.

The camp is short: excluding the 22:00–08:00 truce it is **~37 playable hours**, and
plan §2.4 now reads every duration constant against that budget. One is actively
wrong at this length — `DORMANT_H` at 24 h is 65 % of the game, so a badge switched
off on Friday night would strand its hunter until Sunday. Recommend 12 h.

The plan was built through three rounds of interview; the decisions below are settled
(D1–D20 in the plan), not proposals.

## Architecture

Three tiers. **BLE does the physical game, HTTP does the bookkeeping.**

| Tier | Role |
|---|---|
| Backend (new) | Authority: roster, ring, kills, scoring, game state, anti-cheat |
| Badge (`gotcha.py`, new) | Radar, kill handshake, alarm, offline event queue |
| Web pages (new, static) | Player card, 4 leaderboards, host admin console |

**BLE gossip was considered and rejected**: a camp site produces hot pockets, dead
zones and connectivity islands: an epidemic protocol demos well with 3 badges and
disintegrates at 700. Badges poll one endpoint every **5 min** (D13) — chosen to
protect the BLE scan, which `DESIGN.md` §3 calls load-bearing.

## The three mechanisms that make it work

1. **Kill proof = commitment–reveal ("the soul").** Each badge generates 16 random
   bytes per life and uploads only `sha256(soul)`. The secret is released *only* over
   a completed kill handshake, so holding the preimage proves two badges were metres
   apart. Verifiable with nothing but sha256, and **no key distribution to 700
   badges**. The badge also receives its target's commitment, so it can verify a kill
   **offline**.
2. **Target inheritance rides the handshake** (D10). The victim hands over
   `{soul, tgt:{pid,name,commitment}}` in one payload, so inheritance works in a WiFi
   dead zone with no server round-trip. The backend reconciles later.
3. **Perishable streaks** (D4). Bounties on leaders would otherwise make "hide your
   badge in a tent" the dominant strategy. A streak holds 3 h after your last kill,
   then decays 1 per 2 h; totals never decay. Decay is derived server-side from
   `last_kill_at` (idempotent), so a powered-off badge decays fastest — it cannot even
   dodge.

## Gameplay

- Assigned target, hunted via an RSSI radar bar. **MENU** attacks at close range; the
  victim's badge **screams** and has ~5 s to break range. **1 dodge per assassin per
  life**, then the next attack is instant (answers "run away forever"). 60 s cooldown
  between attempts.
- **Respawn (30 min), not elimination** — eliminating a 9-year-old at 09:30 Friday for
  a flat battery is a punishment for logistics, not a game.
- **Bounties**: streak ≥ 3 makes you fair game for everyone, worth double.
- **No kill-rate cooldown** (D16): table sweeps are legal and earn the story. Consequence
  recorded in the plan: `MAX_KILLS_PER_HOUR` must **flag, not block**.
- Four leaderboards: individual total/streak, group total/per-member (min 3 members).
  Group membership is snapshotted at kill time; inflating a roster dilutes your own
  per-member average, which is the anti-stuffing mechanism.
- **Alive/dead shown on the nametag and in the beacon** (D11) — deliberate social
  mechanic: check someone's badge to see if they're safe to approach.
- **Night truce 22:00–08:00** (D7), host truce button, safe zones as printed rules
  (the badge has no positioning).

## Findings from reading the existing code

- **`parse_payload` ignores trailing bytes** (`ble_proximity.py:154`) — so a game block
  can be appended backward-compatibly. Became moot once backward compatibility was
  waived (D8), which allowed a single clean **HSNT v2** beacon (new `blocks` bitmask
  byte + optional 5-byte game block after the name) instead of time-multiplexing two
  adverts at 2 Hz. **That deleted the riskiest Phase 0 item.**
- 🐛 **`BLEProximity`'s `seen` table has no size cap.** Invisible with 3 badges;
  unbounded RAM growth plus a lengthening IRQ-path loop at 700. **Must be fixed
  regardless of Gotcha** (LRU, ~64 entries).
- **MENU is mapped nowhere** (`BTN_2024`/`BTN_2026_EXP` cover only a/b/y; MENU is
  GPIO 45 / expander idx 5, present only in `BTN_2024_DIAG`) — free for the attack
  gesture on both boards.
- `mpos.DownloadManager.post_url()`/`download_url()` are async and aiohttp-backed —
  no hand-rolled `urequests`, and no repeat of the blocking-`ntptime` hazard.
- `WifiService.is_connected()` returns **True in hotspot mode with no internet**, so a
  reachability check is necessary, not redundant. MicroPython has no ICMP — use a TCP
  connect.

## Power budget — the uncomfortable finding

**Both badge generations carry a 2000 mAh LiPo** (2024 per `fri3dbadge2024/BADGE.md`;
2026 confirmed identical this session). Datasheet arithmetic, **not measured**:

| Scenario | Draw | Runtime (~1700 mAh usable) |
|---|---|---|
| App as it exists today, no WiFi | ~150 mA | **~11 h** |
| App + Gotcha, WiFi always on, no power save | ~240 mA | **~7 h** |
| App + Gotcha, WiFi with DTIM power save | ~175 mA | ~9.5 h |

**The app already does not last a 16-hour waking day** — that is a pre-existing
property, not something Gotcha introduces. Three roughly equal consumers: CPU ~40 mA,
BLE scan at 50 % duty ~50 mA, display/backlight ~50 mA.

Two levers identified, both now Phase 0 spikes:
- **Scan duty.** `DESIGN.md` §3's load-bearing part is *passing explicit
  `interval_us`/`window_us` at all* (that is what disables NimBLE's duplicate filter),
  **not** the 50 % ratio. Dropping to ~12.5 % should save ~37 mA.
- **Screen blanking on the 2024**, which has no backlight API — nobody has tried a
  GC9307 sleep command directly. Highest-value power fix in the project if it works.

Charging is assumed (D20); the design does not depend on either lever succeeding.

## One app, not two (D19)

Gotcha is **integrated into !Fri3d Friends**, not a separate app. NimBLE gives one adv
set, one IRQ, and `gatts_register_services` is **one-shot per power-on** — two apps
cannot share the radio, and `beacon_service.py` already runs a `screen_stack` watchdog
to arbitrate ownership with the Activity; a second app's boot service would be a third
claimant. Structurally decisive: the game block lives *inside* the HSNT beacon, and one
31-byte advert cannot be owned by two applications. Isolation is achieved with **lazy
imports** (`gotcha.py` loaded only when a live game is detected) and try/except-wrapped
entry points, so a Gotcha fault degrades to "no game", never "no nametag". A second
Activity in the same package was considered and rejected.

## Transport: plain HTTP with signed requests (D21)

The badge speaks **plain HTTP, signing every request and response with HMAC-SHA256**,
except for a **single HTTPS call at enrollment** to bootstrap the 32-byte `player_key`.
No bearer token; nothing replayable crosses the link.

Rationale: the game needs **authenticity, not secrecy**. Kill proofs are
self-authenticating (a soul is worthless to anyone but the killer), scores are public,
and the hit list is published. Certificate verification is likely **off** on this
build, so TLS would have delivered encryption without authenticity — the property that
actually matters on a hacker-camp network, where an unverified session is trivially
intercepted and rewritten. **Responses are signed too**, or a MITM could inject "truce
off" or a fake target.

Side benefit: the per-sync 20–45 KB mbedTLS allocation disappears. `DownloadManager`
uses per-request aiohttp sessions, so there was no connection reuse to amortise it, and
MicroPython's GC frees without compacting — the textbook route to fragmentation
`ENOMEM` after days of uptime. One handshake early in uptime replaces ~1000.

MicroPython has no `hmac` module; implement it over `hashlib.sha256` (~10 lines) and
test against RFC 4231 vectors.

⚠️ **Deployment consequence:** **Tailscale Funnel is HTTPS-only** and is therefore
ruled out for the sync path. Preference order is now (1) LAN route from the badge VLAN
— plain HTTP end to end, **now strongly preferred rather than merely nice**;
(2) Cloudflare Tunnel with "Always Use HTTPS" disabled. Plain Tailscale was never
usable — badges cannot run a WireGuard client. Load is trivial (700 ÷ 300 s ≈
**2.3 req/s**).

## Deployment

Fri3d confirmed they **pre-load the `fri3d-badge` SSID onto badges**, so the app
manages **no WiFi credentials at all** — it only checks connectivity and reports it.
No credential in the repo, the `.mpk`, or any config file.

## Known risks carried into implementation

| Risk | Severity |
|---|---|
| WiFi/BLE coexistence degrading the load-bearing scan | High — Phase 0 gates everything |
| ~~TLS heap fragmentation over a 4-day run~~ | **Removed by D21** — one handshake instead of ~1000 |
| Background GATT + radio handoff (`beacon_service` must host the victim side) | High — most fragile area |
| Unbounded `seen` table at 700 badges | High — fix regardless |
| Battery (above) | High |
| Group exclusion makes targets unfindable | Medium — watch median time-to-first-kill |

## Privacy stance

**Location tracking is explicitly out of scope** (D17). AP-association and
witness-graph location hints were both designed, costed, and **rejected** — they would
work, and they are location tracking of children. Stalled hunts get a "last seen by
anyone: N min ago" freshness figure plus a 6 h auto-reassign, using only data already
collected. On-by-default enrollment (D2) is paired with a mandatory first-run consent
screen and a three-second badge-side exit (MENU long-press).

## Repository housekeeping

- **Restored `changelog.md`.** The working tree held only the v0.9.0 entry (94 lines);
  1031 lines of history (v0.8.1 back to the 2026-07-07 plan-phasing entry) had been
  truncated in a previous session and never committed. Recovered with
  `git show HEAD:changelog.md` and re-appended below the v0.9.0 entry. No content lost
  in either direction.
- **Committed the v0.9.0 work from a previous session** (13 modified files +
  `identity.py`, `test_identity.py`, `tools/deploy.sh`, `tools/serialcap.py`) as its
  own commit rather than folding it into the design commits — it is a different piece
  of work and deserved a message recording the `Groups`-truncation bug and the fact
  that **none of it is hardware-verified yet**.
- Session commits, all on `feat/contact-swap-splash-portal`:

  | Commit | Contents |
  |---|---|
  | `2c48439` | Gotcha plan (first draft) + `changelog.md` history restore |
  | `3999c87` | Signed-HTTP transport (D21), gameplay intro, rule tuning |
  | `c621ce4` | v0.9.0 application work (previous session's code) |
  | `da63e48` | Three-day camp timing (§2.4), streak grace back to 3 h |

## Open items

- **A2 (only blocking question left):** can Fri3d route the badge VLAN to the on-site
  laptop? **Upgraded from "nice" to "strongly preferred" by D21**, which needs a path
  carrying plain HTTP — that is the LAN route, or Cloudflare Tunnel with HTTPS
  enforcement off. Still non-blocking by design: the endpoint logic tries a LAN address
  first and falls back to the public URL, so it can be answered on arrival.
- **A4:** measure all five power scenarios on both boards with an inline USB meter.
- v0.9.0 remains **not hardware-verified**; 118/118 host tests pass.

# !Fri3d Friends — v0.9.0: on-badge onboarding (auto-nickname, group adoption, on-badge editor) — 2026-07-22

Answers **GitHub issue #4** (ThomasFarstrike): the app *required* an
internet-connected smartphone. A fresh badge showed a blocking "Configure me" QR
screen pointing at GitHub Pages and — worse — **never started the proximity
beacon**, so its owner couldn't even be seen by friends who were set up. At Fri3d
Camp most kids don't have a data plan. Three independent routes now remove that
gate; none needs a phone. Also closed **issue #1** (BadgeHub icon) earlier the
same day.

## 1. Auto-nickname (`identity.py`, new)

`auto_nickname(machine.unique_id())` -> `"Otter 42"` (64 animals x 100, FNV-1a
fold of the fused chip id). **Derived, never persisted**: pure and deterministic,
so it's stable across reboots without a flash write, can't fight a phone-side
save, and survives wiping `config.json`.

Deliberately *unlike* the Bluetooth `Fri3d-XXXX` id. That one comes from the BLE
MAC, readable only once the radio is active — and a group-less badge never powers
the radio. `machine.unique_id()` needs no radio but returns the *base* MAC, which
differs by a small fixed offset; two nearly-equal ids that disagree reads as a
bug, so the nickname is a different *kind* of name instead.

**The gate split:** `_unconfigured` was `(not name) or (not ids)`; it is now
**groups only**. Groups are never auto-assigned — a shared default would make
every badge match every other badge and turn the arrival buzzer into camp-wide
noise. A new persisted `setup_skipped` flag drives `_show_setup_screen()`.

## 2. Adopting a friend's group from a Y-swap

The swap envelope already carried group names in cleartext (`_outgoing_contact`
injects `"Groups"`). Now the receiver offers to join them — the easiest *and* most
reliable way into a group, since names are matched exactly and a typo means you
silently never match anyone.

**Bug found and fixed while wiring it:** `setdefault` put `Groups` at the end of
the dict, and `build_contact_envelope` pops from the end on overflow — so `Groups`
was the **first** field sacrificed, silently breaking adoption for anyone with a
full contact card. And MicroPython doesn't guarantee dict ordering, so *which*
field died wasn't even deterministic. Now protected **by name**.

Multi-select, because a friend can be in several groups: all offered groups start
ticked (single-group case = one `Y`), **A: next / B: tick / Y: join**. Rows are
pre-built hidden labels, `set_text`-only; the tick is `[x]`/`[ ]` text rather than
`lv.checkbox` because the app registers no LVGL indev. The prompt is **deferred**
out of `_do_exchange` — `_exchanging` is still True there and `_handle_buttons`
swallows every edge while busy, so an inline prompt would have been unanswerable.

## 3. On-badge settings editor (START)

Built on MicroPythonOS `SettingsActivity`, so **one code path covers both boards**:
the OS supplies touch on 2026 and button-navigated focus + the LVGL keyboard on
2024 (its focus helper explicitly supports "keyboard, hardware buttons, or a
rotary encoder"). Entry is **START** — otherwise unused and plain GPIO 0 on *both*
boards, so `_held` special-cases it ahead of the 2026 expander map.

`config.json` stays the single source of truth; `SharedPreferences` is only a
transfer buffer, harvested back through the *same* `sanitize_config` the phone
page uses. `settings_to_config()` covers the two mappings it can't do: the
radiobutton `"on"`/`"off"` string (`bool("off")` is `True` — a real trap) and
banner seconds -> ms. **Alert range is a dropdown of the DESIGN section 5.1 presets**
rather than a raw dBm slider.

## 4. New radio teardown path

`BLEProximity.end()` early-returns when proximity never held the radio, so once a
group-less badge could Y-swap there was nothing to power BLE down afterwards.
Added `ContactExchange.radio_off()`, called from `_teardown_ble()` and from "skip
for now".

## Files

`identity.py` (new) | `fri3d_friends.py` (gate split, adopt prompt + overlay,
START, editor launch/harvest, Configure-me hints) | `ble_proximity.py`
(`parse_groups_field`, `new_groups_from`, `merge_groups`) | `contact_exchange.py`
(`PROTECTED_FIELDS`, `radio_off`) | `ble_setup.py` (`config_to_settings`,
`settings_to_config`, `range_label`, `RANGE_PRESETS`) | `beacon_service.py`
(nickname fallback) | `MANIFEST.JSON` -> 0.9.0 | README + DESIGN section 13.

## Verification

- **Host: 118 tests pass** (was 83). New: `test_identity.py` (determinism,
  stability, junk input, render-safe wordlist); `merge_groups`/`new_groups_from`
  (dedup via `normalize_group`, multi-group peers, 5-cap + `dropped`); `Groups`
  surviving envelope truncation; the full settings<->config mapping. One existing
  beacon test was **updated, not deleted** — it asserted the old "blank name =
  unconfigured" rule, which is exactly what changed.
- **Not yet on hardware.** Every path below still needs a badge:
  fresh-badge skip -> nametag + nickname stable across reboot; two-badge adoption
  with a **multi-group** peer; the editor round-trip on **both** a 2024 and a 2026
  badge (2024 is the button-navigated-focus path and the one at risk); that START
  isn't claimed by the OS; and that the sub-Activity round-trip doesn't reboot the
  badge. Phone-setup and swap regressions too.

# !Fri3d Friends — v0.8.1: fix occasional GATT drops (reconnect/resume + no flash I/O in the BLE IRQ) — 2026-07-19

Occasional **"GATT server disconnected"** while loading the stored friends list
over the phone-setup page (and during first-time setup). Root-caused it as a
fragile BLE session with **no recovery**, and shipped a layered fix. Also bumped
to **0.8.1**, reflashed all three dev badges, deployed the web page to GitHub
Pages, and built + staged the BadgeHub package.

## Root cause

The setup/contacts BLE session had zero timing margin and no self-healing: the
badge advertises/accepts at the phone's default connection parameters (short
supervision timeout, no peripheral param-update API in stock MicroPython), and a
few things can stall the badge past that timeout. When a drop happened, nothing
recovered — the paged read just threw. Contributing badge-side item: the contacts
page was served by reading `contacts.json` **from flash inside the BLE IRQ**,
which stalls the main task, and the "synchronous in the IRQ" serve was not
actually synchronous with the write-ACK (scheduled IRQ) → a fast client could
read a stale page.

## The fix (A/B/C)

| # | Change | Where |
|---|--------|-------|
| A | Phone reconnects + silently re-auths (cached code) + **resumes** the paged read / config save on a transient drop (`withGatt`, 6 attempts, growing backoff to 2.5 s); `onDisconnected` no longer tears down the UI mid-recovery | `docs/setup/index.html` |
| B | Snapshot `contacts.json` **once at auth on the loop** (`_handle_auth`); the BLE IRQ (`_serve_contacts`) now only slices that in-memory blob — **zero flash I/O in the IRQ**. +30 ms settle before each page read closes the scheduled-IRQ race | `app/.../ble_setup.py`, `docs/setup/index.html` |
| C | Contacts page **400 → 490** (fits one ATT read at MTU 515; fewer round-trips) | `app/.../ble_setup.py` |

The read/save are idempotent, so a reconnect restart-from-zero is always safe.
The new web page is **backward-compatible** — it uses whatever page size the badge
advertises — so it fixes the visible error even against an un-flashed badge.

## Commits (branch `feat/contact-swap-splash-portal`)

- `443d306` Fix occasional GATT drops (A/B/C)
- `f519e83` Bump version to 0.8.1 (`MANIFEST.JSON`)
- `a0d228d` Web setup: more patient reconnect (4→6 attempts, backoff to 2.5 s)
- `b55be5b` (on **`main`**) Deploy setup page to GitHub Pages (cherry-pick of the
  page fixes only; Pages builds from `main`/`docs`)

## Verification

- **Off-device:** 83 unit tests pass, incl. 3 new asserting B — auth snapshots
  contacts once, `_serve_contacts` does **zero** flash reads across every offset,
  pre-auth is denied. `docs/setup/index.html` validated with `node --check`.
- **On-device (live over BLE):** ran the real `SetupService` on a badge and drove
  it with `bleak` — the GATT read returned `header {"page":490}`, confirming
  **change C live** and that the auth→paging path (B) runs on hardware.
- **Web deploy:** confirmed the live Pages page now serves change A (6 `withGatt`
  matches after the ~45 s rebuild).
- **Blocked:** the full multi-page + disconnect/resume live assertion — this
  host's BlueZ can't sustain LE connects (see Notes).

## Badge fleet (2026 dev badges)

Reflashed all three with the full core set + `MANIFEST.JSON`, every file
sha-verified against the repo, rebooted, all advertising `Fri3d-XXXX`:

| Serial-id | Badge | Version |
|-----------|-------|---------|
| `348518acfab80000` | Fri3d-FABA | 0.8.1 |
| `348518abdf0c0000` | Fri3d-DF0E | 0.8.1 |
| `1cdbd49d9de40000` | Fri3d-9DE6 | 0.8.1 |

Files: `ble_setup.py`, `fri3d_friends.py`, `contact_exchange.py`,
`ble_proximity.py`, `beacon_service.py`, `MANIFEST.JSON`.

## BadgeHub package

- Built `dist/com.fri3dcamp.fri3dfriends_0.8.1.mpk` (deterministic recipe; icon +
  0.8.1 manifest verified; core files sha-match the flashed badges).
- Bumped `dist/metadata.json` 0.8.0 → 0.8.1 (`version` + `application[].executable`).
- **Staged for publish** in `/storage/fileshare/com.fri3dcamp.fri3dfriends/`
  (deleted stale leftovers first): the `.mpk`, `metadata.json`, `icon_64x64.png`
  — cross-checked consistent. This staging is now a **standing task** on any
  "publish to BadgeHub" request (see memory `badgehub-publish-fileshare`).

## Notes / gotchas

- **Publishing 0.8.1:** re-uploading the `.mpk` over the existing BadgeHub project
  does NOT refresh metadata/icon — **delete + recreate** the project from the
  fresh `.mpk` (or manually re-upload icon + corrected `metadata.json`).
- **David2024 badge** (not connected here) still runs old `ble_setup.py`; change A
  (now live) stops the visible error against it, but reflashing gets the drop
  reduction (B/C).
- **Host BLE limitation:** bleak scans fine but *connecting* fails deterministically
  (`device not found` / connect-timeout); `bluetoothctl` fails the same → a BlueZ
  policy on this host, not the badge/code (one early connect succeeded and returned
  `page:490`). USB-reset of the BT dongle + `systemctl restart bluetooth` didn't
  help; likely needs a host reboot / `main.conf` change.
- **USB-CDC wedge:** cycling the harness while BLE is up wedges the badge CDC;
  recover host-side with `USBDEVFS_RESET` (ioctl `0x5514`, needs sudo). Don't
  over-reset — it can push a firmware-hung device into an enumeration fault that
  needs a physical power-cycle. Prefer fire-and-forget launches (close serial
  before the radio comes up). Captured in memory `badge-ble-testing`.

# !Fri3d Friends — v0.8.0: phone setup over Bluetooth (Web Bluetooth); WiFi portal removed — 2026-07-16

At Fri3d Camp badges and phones sit on **different SSIDs/subnets**, so the old
PIN'd WiFi portal was unreachable by IP in practice. v0.8.0 replaces it with a
**Web-Bluetooth setup page** (`docs/setup/index.html`, GitHub Pages) that talks
GATT straight to the badge — **zero network**. iOS Safari has no Web Bluetooth, so
iPhone users use the free **Bluefy** browser (the page detects iOS and links it).

## What changed
- **New `ble_setup.py`** — a connectable setup GATT service (`SETUP_SVC 6e400020-…`):
  `AUTH`(4-digit code) · `INFO`(pre/post-auth JSON) · `CFG`(chunked config) ·
  `STATUS`(read+notify) · `CONTACTS`(paged read) · `CTLOFF`(page offset). Pure,
  host-tested halves: `sanitize_config` (the BLE `form_to_config`), `ChunkAssembler`
  (`seq|total|payload`, 2048-byte cap → `too_large`), `contacts_response` (0xFFFF
  header + 400-byte slices), `AuthState` (4-digit + 60 s lockout/rotation),
  `badge_id`/`build_info`/`build_setup_adv`. 25 new tests (`tests/test_ble_setup.py`).
- **One radio, one registration.** NimBLE accepts `gatts_register_services` once per
  power-on, so the setup service is registered **in the same call** as the contact-
  exchange service. `ContactExchange.ensure_radio()`/`_ensure_services()` build both
  and hand the setup handles to `SetupService.bind_handles()`; `ensure_radio` is the
  single BLE-up + MTU-once + register-once site used by both swap and setup.
- **Badge identity `Fri3d-XXXX`** (last 2 bytes of the BLE MAC). The QR encodes
  `…/setup/?badge=XXXX` so the browser chooser shows exactly this badge.
- **App wiring:** unconfigured badge runs the setup service on the Configure-me
  screen (new QR + on-screen code); a configured badge opens a **2-min window with
  a long press of B** (short B still mutes; A/Y close early), with a create-once
  overlay (QR + code + countdown), suspending/resuming proximity like the Y-swap.
  Y-swap and LED writes are gated off while a setup session runs.
- **Removed** `web_portal.py` + `tests/test_web_portal.py`; README/DESIGN §10 rewritten.
- **New `tools/setup_client.py`** (bleak) — the same protocol, headless, for testing.

## On-hardware verification (2024 badge #1, this session) + two bugs fixed
Deployed (sha-verified) and driven end-to-end from the dev host over BLE (`bleak`):
- unconfigured → phone-configured over BLE → badge **switches to the nametag live
  and goes on the air, NO reboot** (config `"BLE Test ✓ José"` round-tripped —
  UTF-8 preserved through chunked GATT + `sanitize_config` + atomic write);
- **contacts paging** exact (4 pages / 1395 bytes / 6 contacts byte-identical);
- **wrong-code lockout** (5th → `locked`, code rotated) matches the old portal;
- **setup window** on a configured badge opens, **suspends proximity, advertises,
  shows the overlay, and resumes proximity on close**; exchange service still
  registered (`svc_ready`) alongside setup.
- **2026 board** re-verified end-to-end (configure → nametag → on air, no reboot).
- **Merged registration proven on-device:** the exchange service (handles 16/18)
  and the setup service (handles 21–32) both live in one `gatts` table and are
  both `gatts_read`-able — registered together in a single call, exchange first.
- **Two-badge Y-swap verified working** (owner test) — the shared single
  registration does not disturb the contact exchange.
- **Bug fixed — the phone setup session tore itself down 3 s after a save,**
  breaking the web UX: reloading received contacts failed, a follow-up config
  save failed with *"GATT Server is disconnected"*, and (racing the teardown) a
  badge could stay on the QR/Configure-me screen instead of switching to the
  nametag. Root cause: the session force-disconnected the phone `SAVE_GRACE_MS`
  (3 s) after a save. Now the session **stays alive after a save** — the phone
  keeps its connection so it can reload contacts / make more edits — and only
  ends when the **phone disconnects** (then it hands the radio to the proximity
  beacon), with a 60 s safety cap if the phone vanishes without a clean
  disconnect. The unconfigured→nametag UI swap still happens immediately on save.
  Verified on both boards: configure → nametag live, contacts reloaded twice
  while connected, no premature disconnect, on air after the phone leaves.
- **Bug fixed — swap stopped working until reboot after an app pause:**
  `proximity.end()` (called from `_teardown_ble` on every onPause/onStop) issues
  `BLE.active(False)`, which — verified on-device — **clears NimBLE's whole gatts
  table and MTU**. Our `_svc_ready` flag persisted, so the next swap reused now-
  dead handles and `gatts_write` raised `OSError(22)` (EINVAL) → the swap failed
  silently (`write-exc` in `exch.log`) forever until reboot. `ContactExchange.
  ensure_radio` now self-heals: it probes the cached handle with a **write** (a
  *read* spuriously succeeds on a stale handle on this build — only writes EINVAL)
  and, if dead, resets `_svc_ready`/`_mtu_set` and re-registers. Re-registration
  and re-`config(mtu=)` ARE allowed after an `active(False)`/`active(True)` cycle
  (also verified on-device), even though they EINVAL without one. Confirmed by
  reproducing the exact failure and then a clean two-badge swap after forcing the
  active cycle on both.
- **Bug fixed — session went invisible after the first phone left:** NimBLE stops
  advertising on connect and doesn't auto-resume; the setup session now
  **re-advertises on disconnect** (verified: badge reappears after a client drops).
- **Bug fixed — setup task handle clobbered:** the splash→main `setContentView`
  re-fires `onPause`/`onResume`, cancelling+restarting the configure session; the
  cancelled task's `finally` blindly nulled `_setup_task`, wiping the live task's
  handle (breaking teardown-on-pause + the LED/Y gates + the deferred proximity
  begin). Both wrappers now identity-guard (`asyncio.current_task()`) before clearing.
- **Web page now requires a name AND at least one group before saving.** A badge
  only leaves setup once it has both (groups drive proximity matching), but the
  page let you save a name with no groups — the badge accepted the config yet
  stayed "unconfigured" and sat on the QR screen with no explanation. The page
  now validates before writing and shows a clear inline message; the form marks
  both fields required. (`docs/setup/index.html`.)
- **Bug fixed — web page "retrieve contacts" returned corrupt JSON** (*"expected
  double-quoted property name…"*). The contacts pager served each page on the asyncio
  loop (`_process`), but a `writeValueWithResponse(offset)` resolves the instant NimBLE
  ACKs the write, so a fast client (a browser) read the contacts characteristic **before**
  the loop updated it and got the **previous** page — the reassembled byte stream was
  misaligned and failed `JSON.parse`. (The headless `bleak` test passed because Python's
  round-trip latency hid the race.) The page is now written **synchronously in the IRQ**
  (`_serve_contacts`, same pattern already used to capture chunks), cached per paging
  session, so the read buffer is fresh before the phone reads it.
- **Setup window is now an *idle* timeout, not a fixed 2-min wall clock.** The
  configured-badge window (`SETUP_WINDOW_MS`, 2 min) previously counted down from
  the moment you long-pressed B and ignored activity, so a longer friends-list
  transfer got cut off mid-flight. Now **any GATT activity (auth, config write,
  contacts-page request) resets the window**, with a 10-min absolute backstop
  (`SETUP_ABS_CAP_MS`) so a forgotten-open window still returns the radio to the
  beacon. The on-screen "closes in Ns" countdown reads the session's true
  remaining time (`SetupService.window_secs_left()`) so it no longer falsely
  hits 0 during an active transfer.

## Phone + fleet verification (2026-07-17)
Real-phone testing over Web Bluetooth on the actual badges (the last untethered gap):
- **Setup via QR → Web Bluetooth page worked**: badges configured live and switched
  to the nametag. The `require name + ≥1 group` and idle-window fixes above came out
  of this round (a name-only save silently stuck on the QR screen; a long contacts
  transfer timed out mid-flight).
- **Contacts retrieval over the phone surfaced the paging race** (corrupt JSON, fixed
  above with IRQ-synchronous serving).
- **Deploy: flashed all 3 Fri3d 2026 badges** (Espressif native-USB) to the current
  code, sha-verified. Recipe: quiet the radio via serial **paste-mode** blank-config +
  reset (paste is safe with BLE active; `mpremote` raw-REPL wedges), re-resolve the
  port by `/dev/serial/by-id` after the native-USB re-enumeration, `mpremote fs cp` +
  `sha256sum`, restore config, reset.
- **Bug fixed — app crashed on start after a *partial* deploy.** One badge had only
  `ble_setup.py` + `fri3d_friends.py` updated, leaving an **old `contact_exchange.py`
  (24631 vs 27532 bytes)** lacking `attach_setup`/`ensure_radio` that the new app
  calls → AttributeError on the setup path. Fix: always push the **full core set**
  (`ble_setup`, `fri3d_friends`, `contact_exchange`, `ble_proximity`, `beacon_service`);
  verify on-device by importing with the app dir on `sys.path` and checking the methods.
- **Note:** the two CH340 (`1a86:55d4`) USB devices on the dev host are **not badges** —
  they run `rdzTTGOsonde` (radiosonde trackers) and must never be flashed.
- **Published artifact:** built `dist/com.fri3dcamp.fri3dfriends_0.8.0.mpk` (deterministic
  ZIP, single top-level `fullname` folder, default `config.json`, no runtime junk) for
  upload to BadgeHub (slug `com.fri3dcamp.fri3dfriends`, badge `mpos_api_0`).

---

# !Fri3d Friends — v0.7.2: first-time portal save now switches to the nametag live — 2026-07-15

## Deploy/ops notes (learned 2026-07-15/16, all three badges on 0.7.2)
- **USB copies wedge the CDC far more often since the background beacon (v0.7.0)**
  keeps BLE advertising during transfers — the known "stressed mid-copy while BLE
  runs" failure. An interrupted `mpremote fs cp` leaves a **truncated file on
  flash**: always `fs sha256sum` after deploying, and re-copy until it matches.
- **Proven deploy recipe for a badge running the beacon service:** back up
  `config.json` on-badge → write a blank `{"name":"","groups":[]}` (the service
  then holds the radio OFF — unconfigured badges stay silent; a plain
  `BLE().active(False)` is NOT enough, the watchdog re-asserts within ~30 s) →
  copy + checksum → restore config → reboot.
- A hard-wedged CDC (raw REPL never engages, console silent) needs a physical
  RESET or USB replug; `mpremote reset` can't reach it. The two 2024 badges look
  identical — identify by unplug-watching `/dev/serial/by-id/`.
- Debugging: `time.sleep()` inside one `mpremote exec` starves the whole OS
  asyncio loop — sample app state in a separate exec.

Field feedback: after first-time setup via the portal, the badge stayed on "Configure
me" (v0.6.3 only started BLE + showed a "reopen app" banner, avoiding the known
screen-rebuild crash). Now the swap happens **in place on the same live screen** —
the safe middle path between "do nothing" and the crashing rebuild: the setup widgets
(title, subtitle, QR tile) are **hidden, never deleted**, the nametag widgets (name,
pills, friends line, battery, detail panel) are **created** next to them (creation is
safe; deletion/`setContentView` re-entry are the crash classes), and the banner is
re-raised to the top (`move_foreground`). `_build_idle` was split into
`_build_setup` / `_build_nametag` + shared widgets (clock, portal footer, controls,
banner) built exactly once. Verified on the 2026 badge by replaying the portal save:
Configure-me → nametag with pills, BLE live, and an immediate "X, Y nearby" arrival
banner from the other badges — no crash.

---

# !Fri3d Friends — v0.7.1: QR code + clearer text on the Configure-me screen — 2026-07-15

The unconfigured screen now says **"open this app's setup portal"** (was "open the WiFi
setup portal") and shows a **QR code of the portal URL** — scan it with a phone instead
of typing the IP. The QR sits on a white 136 px tile (the margin doubles as the QR quiet
zone; `lv.qrcode` is built into the OS's LVGL), appears once WiFi is up and hides when
it drops, fed by the existing 2 s `_refresh_portal` throttle. Falls back to the text URL
if `lv.qrcode` is missing. Verified on-device (2024 badge): QR visible and encoding the
live portal URL. Debugging gotcha rediscovered: `time.sleep()` inside an `mpremote exec`
blocks the OS's single asyncio loop, so the app under test gets zero CPU — sample state
in a *separate* exec instead.

---

# !Fri3d Friends — v0.6.2–v0.7.0: splash-crash hotfix, portal-save feedback, background beacon — 2026-07-15

Three releases in one session, all **verified on real hardware** (2×2024 + 1×2026 badge,
deployed over `mpremote` by stable `/dev/serial/by-id` path, `config.json` preserved).
**64 off-device tests green** (60 + 4 new for the beacon service).

## v0.6.2 — hotfix: v0.6.1 crashed the OS + rebooted the badge on every app start
The F-19 "cleanup" (`self._splash_scr.delete()` after `setContentView`) was a
use-after-free: `setContentView` starts a **non-blocking 500 ms LVGL slide animation**
(`lv.screen_load_anim(..., auto_del=False)`) and returns immediately, so deleting the
outgoing splash screen right after leaves the animation timer pointing at freed memory
→ hard crash + reboot on the next tick, on both badge generations. This is the same
landmine DESIGN.md already documented for the config-reload path; v0.6.1 shipped
unflashed. Reverted to the field-verified leak-the-splash behaviour with a loud
warning comment. Verified: all 3 badges survive the splash→main transition.

## v0.6.3 — portal save on an unconfigured badge looked dead
Field bug: first-time setup via the portal saved fine but the badge stayed silently on
"Configure me" — `_build_idle`'s unconfigured branch returned **before the banner
widgets were built**, so the "Config saved ✓" feedback was a silent no-op, and BLE only
ever started from `onResume`. Now: the banner exists on the Configure-me screen too;
`_apply_reload` detects the unconfigured→configured transition, **starts BLE live**
(the F-5 Y-gate reads `_unconfigured` live, so it would have opened onto a dead radio)
and shows "Saved! Reopen app for nametag". Deliberately does **not** re-submit the
screen: `mpos.ui.view.setContentView` always pushes the stack and re-fires this same
Activity's onPause/onResume — a subtler cousin of the v0.6.2 crash. Verified end-to-end
on the 2026 badge by replaying the exact portal save path.

## v0.7.0 — background beacon: visible to friends with the app closed
New `beacon_service.py`, a manifest-declared `boot_completed` service (OS support
verified on both generations): while the app is **not** on the screen stack, it
advertises the identical non-connectable proximity beacon (advertise-only — no alerts,
no swaps in the background); while the app is open it never touches the radio, so all
existing swap/suspend logic is untouched. No app-code changes needed — the app's
`begin()` replaces the service's adv on open, and the service reclaims the radio ≤5 s
after exit. Unconfigured badges stay silent in the background too. Re-asserts the adv
every ~30 s (self-heals radio trampling); watchdog survives USB-console
`KeyboardInterrupt`. Verified 2024↔2026 both directions incl. open/close handoffs.
**Activates on the next reboot after install.**

---

# !Fri3d Friends — v0.6.1: Phase 5 code-review fixes (portal input, swap/teardown robustness) — 2026-07-15

Applied **every finding** from the Phase 5 code review
(`Code_Review_Phase5_20260715_0731.md`, verdict *PASS WITH NOTES*): 5 MAJOR, 9 MINOR
and 6 INFO. No redesign — the BLE exchange, re-entrancy fix, starvation fix and
suspend/resume were already sound; these harden the edges (especially the portal, the
recommended text-entry path). Bumped to **v0.6.1**; **60 off-device tests green**
(57 + 3 new for the portal input fixes).

## Portal input handling (MAJOR — corrupted real data through the recommended path)
- **UTF-8 percent-decoding (F-1):** `_url_unquote` decodes `%XX` into a byte buffer and
  UTF-8-decodes once, so accented names/groups (José, Noël, café) survive the portal
  instead of turning into Latin-1 mojibake. Also fixes silent group **mismatch** — a
  portal-saved group now hashes identically to the same name typed into `config.json`.
- **Apostrophe escaping (F-2):** `_esc` now escapes `'` (every form attribute is
  single-quoted), so O'Brien / L'Atelier no longer terminate the attribute early and
  truncate the field on re-save.
- **Full-body read (F-3):** POST bodies are read in a loop until `Content-Length` (was a
  single short-read-prone `read()`), so a large save can't silently drop fields.

## Contact swap + lifecycle (MAJOR)
- **Cancel swap on exit (F-4):** the exchange task is tracked (`_exch_task`) and
  cancelled in `_stop_task`; `run_window` and `_do_exchange` re-raise `CancelledError`
  through their `finally`, so a swap can no longer outlive the Activity by up to 5 s and
  touch freed LVGL widgets / BLE.
- **Unconfigured Y-press (F-5):** **Y** is gated on `_unconfigured`, matching the README
  ("unconfigured badges don't advertise/scan") — no more activating a radio no teardown
  path deactivates.

## Robustness (MINOR)
- **Atomic writes (F-8):** `config.json` and `contacts.json` are written via temp file +
  `os.rename` (atomic on LittleFS/FAT), so a power-off mid-write can't wipe the camp's
  collected contacts.
- **Banner coalescing (F-6):** arrivals only coalesce into a live *arrival* banner (not a
  "Swapped ✓" / "Config saved ✓" one), and `_hide_banner` clears the stale name list —
  fixes an arrival silently rewriting an unrelated banner with no LED flash / sting.
- **Buttons paused mid-swap (F-7):** A/B actions are deferred while `_exchanging` (edges
  still tracked), so a stray B-press can't fire the IRQ-disabling LED write that starves
  the GATT link.
- **Write-ack before disconnect (F-11):** the client waits for `_IRQ_GATTC_WRITE_DONE`
  (bounded by the window deadline) instead of a fixed 150 ms nap, fixing rare one-sided
  swaps on a congested radio.
- **Portal hardening (F-9, F-14):** bind retries on `EADDRINUSE`; `url()` / footer only
  advertise a genuinely-listening portal; open connections close on `stop()`; the request
  read phase has a 10 s timeout and the header loop is capped.
- **NTP + banner clamp (F-10, F-12):** a failed NTP dispatch clears `_ntp_busy` (no longer
  wedges resync for the session); `banner_ms` is clamped ≥500 on load *and* save so a
  0/negative value can't hide every banner.
- **`onDestroy` stops the portal (F-13).**

## Cleanup (INFO)
- **Company id checked (F-15):** both beacon parsers now verify the 2-byte company field
  (`0xFFFF`) alongside the magic, matching the documented wire format.
- **Splash freed (F-19):** the splash screen + its ~8.7 KB PNG are deleted once the
  nametag appears (a Python-side reference to the PNG bytes is kept while the image lives).
- **Portal refresh throttled (F-20):** the footer URL query (hits the WiFi stack) is gated
  to ~2 s like the other refreshers, not every 30 ms frame.
- **Dead code removed (F-18):** `_finishing`, `notified`, `_disc`/`_chars`.
- **Documented (F-16, F-17):** the 3-badge rendezvous ambiguity and the connectable-window
  exposure are now written up in DESIGN.md §9.

## Tests
- Added host tests for `_url_unquote` (multibyte UTF-8), `_esc` (single-quote escaping)
  and the `banner_ms` clamp. **60/60 green.**

## Docs
- DESIGN.md §3/§9/§10 updated with the review-fix notes; README refreshed (international
  names now safe via the portal, atomic contact storage, portal robustness).

## Packaging
- Built the deterministic release package `dist/com.fri3dcamp.fri3dfriends_0.6.1.mpk`
  (single top-level `fullname/` folder, stored/uncompressed, fixed `2025-01-01`
  timestamps, 10 files, no `__pycache__`/`exch.log`/`contacts.json` cruft). Verified the
  in-package manifest reads version 0.6.1. **Not yet flashed** — to be published via
  BadgeHub → on-badge AppStore (badges auto-offered the 0.6.0 → 0.6.1 update).

---

# !Fri3d Friends — v0.6.0: BadgeHub packaging, repo rename, MIT license, icon polish — 2026-07-14

Prepared the app for publishing on **BadgeHub.eu** and cleaned up release details.
Bumped to **v0.6.0**; deployed to all three badges.

## Publishing prep
- Confirmed the BadgeHub flow (community appstore, `.mpk` packages, `mpos_api_0`
  badge tag). Slug = the app `fullname` `com.fri3dcamp.fri3dfriends` (verified
  against how every MicroPythonOS app on BadgeHub is slugged via its public API).
- Build a deterministic `.mpk` (single top-level `fullname/` folder, stored,
  fixed timestamps, dirs-before-files) → `dist/com.fri3dcamp.fri3dfriends_0.6.0.mpk`.
  `dist/` is gitignored (artifact, reproducible from `app/`).
- `MANIFEST.publisher` → **David Steeman** (was "Fri3d Camp").

## Repo + license
- **Renamed the GitHub repo** `fri3dbadge-group-nametag` → **`fri3d-friends`**
  (github.com/steemandavid/fri3d-friends; old URL 301-redirects). Local `origin`
  updated.
- Added the **MIT LICENSE** (© 2026 David Steeman / Makerspace Baasrode).

## Launcher icon
- The icon's black tile was full-bleed and crowded the app-name label in the OS
  menu. Shrunk the **whole tile** (~80%) with transparent padding, weighted to the
  bottom, so the icon graphic clears the label. Redeployed to all badges.

## Docs
- README rounded out: AppStore-first install, friend-LED breathing, build/publish
  (`.mpk` → BadgeHub) section, tests, MIT license, credits. Added a ready-to-post
  Fri3d Discord announcement at `docs/announcement.md`.

---

# !Fri3d Friends — rebrand, bigger name font, per-swap contacts, UI/portal fixes — 2026-07-14

Renamed the app **!friends nearby → !Fri3d Friends** and did a full rebrand, plus
a batch of UX changes. Deployed + verified on all three badges (2× 2024, 1× 2026);
57 off-device tests green. Bumped to **v0.5.0**.

## Rebrand
- Display name → **!Fri3d Friends** everywhere user-facing (MANIFEST, splash,
  portal header, docs). Functional labels (`Friends nearby:`, detail header) kept.
- **Package id renamed** (app unpublished, so safe): dir/fullname
  `com.fri3dcamp.groupnametag → com.fri3dcamp.fri3dfriends`, module
  `group_nametag.py → fri3d_friends.py`, class `GroupNametag → Fri3dFriends`.
  On-badge deploy: single-session `mpremote fs cp -r` into the new dir, then a
  script to **migrate each badge's config + contacts.json**, remove the old dir,
  and reboot (far less USB-CDC churn than many small copies).
- **New logo** — a hybrid of two proposals (badge-bump × pixel-people): two badges
  bumping (the swap) each with a pixel friend + a spark. New `icon_64x64.png`
  (tiled) + `fri3dfriends.png` (96px, tileless, splash). Old `makerspace.png`/
  `logo.png` removed (the "Makerspace Baasrode" *text* attribution stays).
  Generators: `tools/make_logos.py` (10 candidates) + `tools/make_hybrid_logo.py`.
- **Splash relaid out** with explicit y-positions so "by David Steeman" no longer
  overlaps the logo and the logo clears the "Makerspace Baasrode" line.

## Name font + friends line
- **Name at 42px** (1.5× the built-in `montserrat_28`) from a bundled ~15KB subset
  Montserrat **TTF** via `FontManager.getFont(size, ttf=…)` → `tiny_ttf`. A fixed
  font, not transform-scaled. (`lv.binfont_create` on an `lv_font_conv` `.bin` did
  **not** load on this lvgl 9.4 build — the TTF path is what works.)
- **Friends line** inset + `LONG_MODE.WRAP` so long peer names wrap instead of
  being clipped by the curved corner.

## Contacts / swap
- **One entry per swap** (`merge_received` → `add_received`, append-only, no dedup;
  cap 200, oldest-first). Kept a `merge_received = add_received` alias for
  partial-deploy safety.
- **Default contact fields** in the template: Email, Phone, Website, Discord.
- **Removed the `handle` field entirely** (config, `_load_config`,
  `ble_proximity.begin` signature + name-with-handle display, portal form,
  `_outgoing_contact`, docs, tests). Swap sends **name + groups + contact fields**.

## Portal fix
- **Fixed badge reboot on config save**: the old reload rebuilt the whole LVGL
  screen + cycled BLE (hard-crash + memory leak on this build). Now a safe
  in-place reload; added save feedback — "Config saved ✓" banner on the badge and
  a green note in the portal. Group changes apply on next app start.

---

# !friends nearby — contact-swap bug fixes (re-entrancy + LED starvation) — 2026-07-13

Fixed two bugs that made the Y-button contact swap fail in the field, found via
on-device trace logging (`ContactExchange.dbg` → `/apps/.../exch.log`). Both
confirmed fixed on hardware: repeated swaps now work, incl. cross-model 2024↔2026.

## Bug 1 — re-entrancy (`OSError(22)` on the 2nd+ swap)
The swap worked exactly once per power-on, then every later attempt threw
`OSError(22)` (EINVAL) early in BLE setup until reboot. This *looked* like a
2024-vs-2026 problem (the first test pair happened to be the first swap) but
wasn't. Cause: NimBLE one-time-only stack ops (`config(mtu=…)`,
`gatts_register_services`) were re-issued every window. Fix: `run_window` setup is
now idempotent + fully guarded — MTU set once (`_mtu_set`), services once
(`_svc_ready`), `active()` only if needed, and every setup call wrapped so none
can abort the window.

## Bug 2 — GATT connection starved by the LED loop
After bug 1, the swap set up fine but the connection was unstable
(`cli conn=None`, or connect-then-drop `read-exc NoneType`). Cause: the app's main
loop ran concurrently with the exchange task and called `_update_leds()` →
`lights.write()` (WS2812, IRQ-disabling) every 60 ms, starving the short GATT
link. (This is why headless `run_window` tests passed — no main loop — but the
live app failed.) Fix: while `self._exchanging`, the main loop only reads buttons
and yields (no LED/BLE/refresh work), so the exchange owns the CPU + radio.

## Ops notes
- Heavy on-device BLE debugging repeatedly wedged the badges' USB-CDC (documented
  failure mode — physical RESET is the only reliable recovery). Deploy right after
  a reset (fresh CDC) before the app fully loads and contends the REPL.
- The diagnostic trace (`dbg` + `exch.log`) is left in for now; trim once fully
  proven in the field.

---

# !friends nearby — friend LEDs, clock inset, 2026 verified on hardware — 2026-07-12

Follow-up to the splash/swap/portal work below. Added **per-friend breathing
LEDs**, nudged the clock clear of the curved corner, deferred the launch-time NTP
sync, and **verified the app end-to-end on a Fri3d 2026 badge** (first on-hardware
2026 run). Also fixed the live-save group-pill refresh (see prior commit).

## Friend LEDs (per-friend breathing)
- One RGB LED per nearby friend, slowly + dimly breathing that friend's **group
  colour** (friend 1 → LED 0, …). `_update_leds` in the loop, `LED_UPDATE_MS=60`,
  breathe `LED_DIM_MIN..MAX 0.015..0.18` over `3800 ms`, per-LED phase stagger,
  frame-cached writes. LED count is board-keyed: **4 on 2024, 5 on 2026** (fw
  `get_led_count()` over-reports 5 on 2024). Arrival/exchange flashes set a short
  override, then breathing resumes.

## Clock + NTP
- Clock inset to `CLOCK_X=24` (2 chars right) so the curved screen corner no longer
  clips it. First app-driven NTP resync deferred one interval (OS already syncs at
  WiFi connect) so the blocking `ntptime.settime()` doesn't hitch launch.

## Fri3d 2026 — on-hardware verification (badge serial 1cdbd49d9de4)
- Fresh install on the 2026; **works**: splash → nametag (320×240), board detected
  `fri3d_2026`, BLE proximity detected both 2024 badges, clock/pills/portal footer/
  controls render, io_expander buttons (A/B/Y) read cleanly, and **friend LEDs
  breathed** (2 friends → LEDs 0+1 dim-green, animated + staggered). No 2026 bugs
  found — worked on first deploy.

## Meta
- Added a shared cross-project USB device reference at
  `/home/john/claudecode/fri3d-usb-devices.md` (serials/by-id paths for both 2024
  badges, the 2026, and the 2 TTGOs, + 2024-vs-2026 identify recipe + wedge
  recovery). The 2026 badge is now an active dev/test target.

---

# !friends nearby — splash, contact swap (Y), WiFi setup portal + clock — 2026-07-12

Added a startup splash, a **contact-exchange** feature on the **Y** button, a
configurable free-form **`contact`** object, on-badge storage of received
contacts with timestamps, a **PIN-gated WiFi web portal** to edit config /
view+export contacts, and a live **NTP-synced clock**. Bumped to **v0.4.0**.
Off-device tests: **56 passing** (30 BLE + 20 contact-exchange + 6 portal). On the
2024 badge: splash → nametag verified, clock showed real time, portal footer
rendered, clean exit (no wedge). Radio round-trip for the swap + the browser
portal round-trip need a two-badge / on-WiFi setup — not yet run.

## New: splash + clock (group_nametag.py, makerspace.png)
- 3-second splash (app name, `v0.4.0`, "by David Steeman", Makerspace Baasrode
  logo + name), mirroring `org.fri3d.hwtest`'s `_build_splash` — the **in-memory
  `lv.image_dsc_t` decode** (reliable) with a text fallback; asset copied from the
  hwtest project. `_splash_then_enter` swaps to the nametag after 3 s.
- **Live clock** top-left, same font/colour as the battery %. RTC kept accurate by
  NTP: MicroPythonOS syncs on WiFi connect, and `_resync_time` re-syncs ~every
  10 min (`ntptime.settime()` in a task, guarded by `WifiService.is_connected()`).

## New: contact exchange — Y button (contact_exchange.py)
- Overlapping 5 s **press-triggered windows** (no synced clocks). Y opens a window
  advertising a connectable `HXCG` beacon + scanning for peers doing the same.
- **`decide_role`**: lower MAC = GATT server, higher = client → exactly one
  connection. Bidirectional swap over one link (server's readable `MYINFO` char +
  writable `THEIRS` char); MTU raised to 515; envelope `{"n":…,"c":{…}}` capped to
  500 B (fields dropped last-first).
- Coexists with proximity via new `BLEProximity.suspend()/resume()` (stop/restore
  scan+adv + IRQ **without** `active(False)`, to avoid CDC-wedging churn).
- **Storage:** `merge_received` → `contacts.json`, deduped by MAC (refresh + bump
  `count`, keep `first_received`), capped at 200, each with `received_at`.

## New: WiFi setup portal (web_portal.py)
- Always-on `asyncio.start_server` HTTP portal (assumes the OS is already on WiFi;
  no STA/hotspot management). Routes: `/` (config + dynamic `contact` editor),
  `/save`, `/contacts`, `/contacts.json`. Pure `parse_form`/`form_to_config`
  unit-tested.
- **Auth:** random 5-digit PIN per boot shown on the badge as a login challenge,
  session cookie after entry, lockout + PIN rotation after 5 wrong tries. Footer on
  the nametag shows `⚙ http://<ip>:8080` / the PIN. Plain HTTP → gates access, not
  traffic (camp-LAN trust model). BLE phone-companion + notification mirroring were
  considered and **dropped** (Android would need a native app; Web-Bluetooth
  excludes iOS Safari).

## Config / manifest
- `config.json`: new `contact` object (free-form `field: value`). `MANIFEST.JSON`:
  version → `0.4.0`, description updated. `_load_config` reads `contact`;
  `_apply_reload` (deferred to the main loop) reloads config + re-applies the beacon
  after a portal save.

---

# !friends nearby — UI redesign + Fri3d 2026 support + button/perf fixes — 2026-07-11

Renamed the app to **"!friends nearby"** and redesigned the screen; added Fri3d
2026 badge support; fixed button handling and a CPU-starvation bug. No BLE /
protocol / test changes (`ble_proximity.py` untouched, 30/30 pytest still green).

## UI redesign (group_nametag.py, MANIFEST, README, DESIGN)
- Renamed (`MANIFEST.name`) to "!friends nearby" (the `!` sorts it to the top of
  the launcher).
- Layout: **name** (`font_montserrat_28`, single line, marquee-scrolls when too
  long) at the top; **group(s)** as full-width coloured pills (per-group signature
  colour, stacked vertically, each scrolls if its name is too long); a
  **friends line** (`Friends nearby: <names>` or `looking for friends…`); battery
  (inset from the rounded corner); controls at the bottom. The group **logo**
  (decode broken on this build) and the earlier breathing avatar disc were dropped.
- **A** opens a friends-nearby panel (cards: colour dot · name · shared group ·
  signal bars · dBm · age). **B** = mute/unmute (persisted to config; the controls
  label reflects the state). **X** = OS quit. **START** unused.
- New config keys: `sound` (bool), `banner_ms` (ms, default 5000), `board`
  (optional "2024"/"2026" override).

## Fri3d 2026 badge support
- Board autodetect (`mpos.DeviceInfo.get_hardware_id()` → `"fri3d_2026"`, fallback
  `mpos.io_expander.version`); 2026 reads A/B via the **CH32X035 I²O expander**
  (`mpos.io_expander.digital` idx A=7, B=6), uses **320×240**, buzzer **GPIO38**,
  and re-enables the backlight via `io_expander.lcd_brightness`. LEDs/battery via
  `mpos` (portable). Screen size comes from `mpos.DisplayMetrics`. (2026 runtime
  not yet verified — the 2026 badge was in active use / off-limits.)

## Hard-won bugs found & fixed
- **lvgl long-mode enum** is `lv.label.LONG_MODE.SCROLL_CIRCULAR` — **not**
  `lv.label.LONG.*` (which doesn't exist on this build). The wrong name silently
  no-op'd, so long names wrapped to a second line.
- This build has **`add_flag`/`remove_flag` but no `clear_flag`** (already in
  DESIGN §1 — I re-tripped it): using `clear_flag` to show the A-panel silently
  raised + was swallowed by `try/except`, so the panel never appeared.
- **Buttons** (2024): A=GPIO39, B=GPIO40 (raw GPIO, active-low; **no** LVGL key
  events on 2024), X = OS "back"/quit. Confirmed with a throwaway on-screen
  input-test app. 2026 equivalents via the expander (see DESIGN §7).
- **CPU starvation**: a **2× transform-scale on the scrolling name** made lvgl
  re-render + re-scale it every animation frame, swamping the CPU → asyncio loop
  starved (button polls missed, arrival chime audibly stretched) and eventually the
  USB-REPL locked up. Fixed by rendering the name at `font_montserrat_28` (no
  transform scale). Also reduced per-tick lvgl re-renders to "only when the text
  actually changes".

## Verification
- 30/30 `pytest tests/` (untouched).
- On-device (2024 badge): name scrolls on one line, 2 group pills show in full,
  A expands/closes the panel, B mutes+persists (label flips), X quits, chime is
  crisp, and the USB-REPL stays responsive under load.

---

# Group Nametag + Proximity Finder — screenshot-capture investigation — 2026-07-10

Attempted to capture a still screenshot of the running app on a configured badge
for documentation. No app/code changes; **findings only**, folded into `DESIGN.md`
§1/§4.

## `capture_screenshot()` is not usable for a full-frame capture on this build
- `mpos.capture_screenshot('/data/shot.bin')` does **not** deadlock from raw REPL
  (`mpremote run`/`exec`) — only from paste, where it deadlocks lvgl (DESIGN §1).
  But the 153,600-byte file it writes (320×240×2 RGB565) is a **scrambled partial
  lvgl draw buffer, not a composited frame**: brute-forcing the row stride from
  120–512 yields **zero empty columns for every width** (no text columns or screen
  margins ever line up), so no byte-order/stride/dimension reinterpretation
  produces a readable image. lvgl `snapshot`/`snapshot_create` are **not compiled
  in**, so there is no on-device path to a true pixel screenshot without a firmware
  change (enable `LV_USE_SNAPSHOT`) or SPI panel-GRAM readback.
- **Reliable alternative for "what's on screen":** `mpos.get_all_widgets_with_text(lv.screen_active())`
  returns the label widgets; `w.get_text()` gives each label's text. `print_screen_labels(scr)`
  takes the screen object as one positional arg. Used to confirm the live idle
  screen (name, own-group, battery %, the `nearby:` line, the controls hint) and a
  live arrival banner.

## Other verified facts (for next time)
- Display framebuffer is **320×240 RGB565 little-endian** (153,600 B); visible area
  **296×240** (`mpos.DisplayMetrics.width()/height()`). App background `0x0862`.
- `mpos.get_foreground_app()` returns the **fullname string**; `AppManager.start_app(fullname)`
  works from raw REPL (paste mode not required to launch).
- File transfer: `mpremote fs cp` works on a **freshly-booted** badge; it hangs/wedges
  on a stressed one, and large exec-output (>~a few KB) stalls the CDC TX. The bundled
  `tools/pull_file.py` (chunked base64) is the fallback puller.
- **Wedged badge** recovery: physical RESET, or `esptool --before usb_reset --after hard_reset run`
  (esptool wasn't installed on the host and pip is PEP-668-locked, so RESET was used).

## Device identification (2024 vs 2026 badge)
With multiple Espressif boards on USB, the **Fri3d 2024 and 2026 badges enumerate
identically** (`303a:4001`, same CDC descriptors) — distinguishable only by the USB
**`iSerial`** (`ID_SERIAL_SHORT`), never by `/dev/ttyACMx` (unstable) or VID:PID
(ambiguous). The Lilygo TTGOs are trivially separate (`1a86:55d4`). Always address
the target badge via `/dev/serial/by-id/…<serial>…`.

## Observed app behaviour (live hardware)
On a configured badge, the proximity finder detected a real co-located peer over BLE
and raised the arrival banner — the end-to-end advertise → scan → intersect → alert
flow works on live hardware. The logo still does not render on this build (blank
middle; the known D-12 silent-decode issue). No pixel screenshot was obtainable, so
the display was photographed with a phone for the record.

---

# Group Nametag + Proximity Finder — review-fix implementation, on-device test, UI tweaks — 2026-07-08

Implemented the fixes from the Phase 0–4 code review, completed the DESIGN.md doc
TODOs, ran the full on-device test suite on 3 badges, and made a couple of UI
tweaks. Fixes/results captured in `Code_Review_Fixes_20260708.md`.

## Code-review fixes (`ble_proximity.py`, `group_nametag.py`, `config.json`)
All findings from `Code_Review_Phase0-4_20260708_0800.md`:
- **D-1** UI loop `try/except` moved *inside* the `while` (a per-frame error no
  longer permanently freezes the render/input loop); added a `_finishing` flag so
  `B`/`START` breaks the loop before touching torn-down widgets.
- **D-2** BLE scan IRQ↔loop race on `_seen`: the IRQ now only enqueues raw results
  into a bounded `_pending` list; all parse/intersect/`_seen` mutation moved to
  `_process_pending()`/`_process_result()` on the loop thread (also fixes **D-9**).
- **D-3** logo now scaled-to-fit (`_read_png_size` + fit-to-box); `_logo_base_scale`
  is live; **D-4** alert coalescing accumulates across the banner window (one cue).
- **D-5** `B` exits like `START`; **D-6** shipped `config.json` is now an empty
  template (fresh badge shows the hint + stays BLE-silent); **D-7** wrap-safe
  `ticks_diff`/`ticks_add` in the scan re-arm + battery throttles; **D-8** `begin()`
  coerces name/handle to str and returns truthful advertise success.
- **D-12** (was deferred) logo placeholder now shown for a missing/empty/non-PNG
  file via a deterministic file gate — confirmed on-device that lvgl fails silently
  (no exception) and `image_decoder_get_info` is not exposed on this build.
- Bonus: `_process_result` now refreshes a re-seen peer's **name** (a rename was
  previously invisible for up to the 30 s eviction window).
- Host `pytest tests/` stays **30/30**; added a host-level exercise of the
  refactored radio wrapper (deferred IRQ→tick, notify-once, eviction, disjoint, etc.).

## DESIGN.md doc TODOs completed
- **§5** filled in: the `rssi_floor` dBm→range guidance table (−120 full-range …
  −70 next-to-me) and the open-field link-budget estimate (Friis ≈93 dB budget →
  ~435 m ideal LoS, derated to a realistic ~50–100 m LoS / ~10–30 m through
  bodies/tents).
- **§4** re-verification note added after the on-device run.

## On-device full test — 3 badges (ACM0/1/2), no badge wedged
Deployed the fixed code with **`mpremote fs cp`**, launched via
`AppManager.start_app` in **paste mode**, verified with a **passive host BLE scan**
(`bleak`) plus **lvgl label introspection** — deliberately avoiding the REPL BLE
begin/end cycling that wedged badges in a prior session. All passed:
- Single + 3-badge concurrent advertise (HSNT payload correct: `ver 1`, `gid 0xa07b`).
- Real multi-peer round-trip detection; **coalesced** banner for two arrivals.
- Disjoint group ignored; unconfigured → "Configure me" hint **and absent from the
  air**; advertising **stops on exit** (`restart_launcher`); detail view content
  (name · shared group · smoothed RSSI · age); live battery/own-group/help UI.

Method gotchas (for next time):
- Paste-based file upload **hangs on large files** (paste-mode echo never goes
  quiet) → use `mpremote fs cp` for transfers; paste mode only for launch/read.
- `mpos.get_foreground_app()` returns the **fullname string**, not the instance;
  the live Activity is `activity_navigator.screen_stack[i][0]`.
- Avoid `mpos.capture_screenshot()` from paste (deadlocks lvgl) — read UI via
  `screen_active()` label-walking or `mpos.get_all_widgets_with_text`.

## UI tweaks (`group_nametag.py`)
- **Name enlarged 1.5×** and **moved to the top**: rendered at `font_montserrat_28`
  (the largest built-in) then `transform_scale(384)` (=1.5×) pivoted on the label's
  horizontal centre so it stays centred; `NAME_TOP=6`. Logo relocated below it
  (`LOGO_TOP 14→74`, `LOGO_BOX_H 104→74`); own-group line moved under the logo.
- Removed the callsign handle from the reference config; updated the on-badge peer
  display names.

## Privacy note
The on-device test output re-introduced the maintainer's real name + callsign into
`DESIGN.md` and `Code_Review_Fixes_20260708.md`. Since the GitHub repo is **public**
and was previously scrubbed of that identity, these were re-scrubbed to the same
generic `Alex`/`YOURCALL` before commit. (The makerspace group name and badge MACs
remain in-repo — still flagged for the owner to decide, unchanged this session.)

---

# Group Nametag + Proximity Finder — published to GitHub + privacy scrub — 2026-07-08

- Published the project as a **public** GitHub repo under the owner's account
  (`fri3dbadge-group-nametag`), initial commit + push.
- **Sensitive-info audit** of all tracked files: clean — no emails, passwords, API
  keys/tokens (the GitHub PAT used for the push was never written to any file), IPs,
  WiFi creds, host paths, or real names/phones. Image metadata is benign (only an
  editor version + DPI); generated PNGs are fully stripped.
- **Privacy scrub + history rewrite**: removed the maintainer's personal name and
  callsign from all file contents (→ generic `Alex`/`YOURCALL` examples; `config.json`
  is now a `Your Name`/`YOURCALL` template) and from the commit author/committer
  identity. Because the repo was already public, this was done as a commit **amend +
  force-push** (`dc50c10` → `9611146`) so the names leave `main`'s history, not just
  the tip. `git grep` against the remote tree confirms `main` is clean.
  - Caveat: the orphaned commit may remain reachable by SHA / in caches for a time;
    delete-and-recreate the repo for a guaranteed purge.
  - Still in the repo (outside the name+callsign scrub scope, flagged for the owner):
    the makerspace group name (17×), its logo image, and badge MAC addresses (3×).
- **Phase 0–4 code review** (`Code_Review_Phase0-4_20260708_0800.md`): independent
  review verdict **PASS WITH NOTES** — no critical defects; the scan-stability fix and
  platform adaptation endorsed.

---

# Group Nametag + Proximity Finder — SCAN STABILITY FIX — 2026-07-07

Fixed the **presence flapping** the user observed with 3 co-located badges (each
showed random 0/1/2 peers, losing and re-detecting the others).

## Root cause
`gap_scan()` with **default args** enables NimBLE's **duplicate filter** → each peer
reported only ~once → `last_seen` ages out → peer evicted at 30 s → disappears, then
re-detected (re-alert) next time heard. Compounded by the PLAN's sparse 1.5 s-on / 4 s
duty cycle and 3-badge advertising collisions, so most short scan windows caught nothing.
Measured: default `gap_scan(12000)` = **2 hits/12 s** (≈1 per peer); the app's
`gap_scan(1500)` re-armed every 4 s detected only **1 peer once in 60 s**.

## Fix (`ble_proximity.py`)
Continuous dense scan with **explicit `interval_us`/`window_us`** — that disables the
duplicate filter so every advertisement is reported:
`gap_scan(0, SCAN_INTERVAL_US=120000, SCAN_WINDOW_US=60000)` = 50% duty, re-armed every
`SCAN_REARM_MS=30 s` as insurance. Replaced `SCAN_ON_MS`/`SCAN_CYCLE_MS` duty cycling;
`tick()` now just evicts + re-arms.
- Measured: 50% duty = **44 hits/12 s**, peer age **0–1 s over 60 s** with 3 badges
  advertising → stable presence, no flapping, no spurious evictions. 100% duty = 93 hits,
  age 0 (chosen 50% for the power/stability tradeoff).
- Verified on-device: fixed `BLEProximity` held both peers at age ≤1 s for the full 60 s.

## Deployed
Fix deployed + apps relaunched on Alex (ACM0) and Bob (ACM2). Alice (ACM1) USB-wedged
(app still running old code) — needs a physical RESET, then deploy + relaunch to get it.

## Note
Discovered along the way: a USB-serial hang does **not** stop the app — the activity +
BLE keep running (Alice's app kept advertising while her USB was unresponsive). Recovery
of a truly wedged badge is still `esptool --before usb_reset --after hard_reset run`, or a
physical RESET. Repeated REPL BLE begin/end cycling is what wedges badges — avoided now by
testing the fix via the running apps rather than more REPL cycling.

---

# Group Nametag + Proximity Finder — IMPLEMENTED (Phase 0–4) — 2026-07-07

Implemented and verified the app from `PLAN.md`, **adapted to the badge actually
on the bench** (see `DESIGN.md` §1). The connected badge is 2024 hardware but
runs **MicroPythonOS 0.11.1**, not the `fri3d.application` firmware the plan was
written against — so the behavioural design (BLE protocol, multi-group matching,
proximity state machine, per-group signature, alerts, idle UI) was kept verbatim
and only the framework shell moved to a MicroPythonOS `Activity`.

## Built
- `app/com.fri3dcamp.groupnametag/` — a full MicroPythonOS app:
  `MANIFEST.JSON` (launcher intent), `group_nametag.py` (the Activity),
  `ble_proximity.py` (BLE advertise/scan + group-aware state machine),
  `config.json`, `logo.png`, `icon_64x64.png`.
- `tests/test_ble_proximity.py` + `conftest.py` — off-device pytest.
- `tools/host_advertise.py` (BlueZ D-Bus LE advertiser = a 2nd-badge test stand-in),
  `tools/pull_file.py`.
- `DESIGN.md` (platform adaptation, verified facts, protocol, verification
  status, TODOs), `README.md` (group quick-start).

## Verified autonomously (real hardware)
- **30/30 host pytest** (`pytest tests/`) — protocol round-trip, fnv1a_16, dedup/sort,
  UTF-8 truncation, version rejection, malformed-packet dropping, intersection.
- **17/17 on-device BLE state-machine checks** — shared-group arrival, disjoint
  ignored, dedup, multi-group, per-group signature, eviction, re-alert-after-return,
  lifecycle — through the real `parse_payload → intersect → seen → arrivals` path.
- **Real BLE advertising** — host bleak scanner received the badge's beacon:
  `34:85:18:AB:DF:0E rssi −75 ver 1 gids [0xa07b] name "Alex YOURCALL"` (§10 single-badge smoke).
- **Real BLE scan RX** — `gap_scan` IRQ fires on real adverts; non-HSNT ignored.
- **UI build** — all idle labels present; banner + coalescing ("Alice, Bob nearby
  (Makerspace Baasrode)"); unconfigured hint; **main loop integration** (breathing
  animation oscillates 244–269, battery → "100%", no exceptions over 3 s).
- **App discovery** — `AppManager.refresh_apps()` finds `com.fri3dcamp.groupnametag`.
- **Stable public BLE address** confirmed (`ble.config("mac")` → type 0).

## Platform findings folded in (`DESIGN.md` §1)
- `mpos.fs_driver` registers LV_FS `"S:"` → logo decode by path (no in-memory spike).
- `mpos.lights` (set_all(r,g,b)/set_led/clear), `machine.PWM(Pin(46))` buzzer, raw
  `machine.Pin` buttons, `mpos.BatteryManager.get_battery_percentage()`.
- lvgl: `add_flag`/`remove_flag` (no `clear_flag`), `lv.display_get_default()`.
- **Backlight/brightness API absent → dim feature dropped + noted.**
- Recovery: a wedged badge is reset with `esptool --before usb_reset --after hard_reset run`;
  `usbreset` alone re-enumerates USB but not the core; avoid `mpos.capture_screenshot()`
  from raw paste probes (deadlocks lvgl).

## Live lifecycle checks (after physical badge reset)
- **App launches in the real OS lifecycle** — `AppManager.start_app("com.fri3dcamp.groupnametag")`
  (via paste mode, which coexists with the OS asyncio loop); host scan then sees the live
  beacon `name "Alex YOURCALL"` → real `onCreate`/`onResume` → `BLE.begin` → advertise works
  from within the Activity (not just the REPL).
- **Runs stably** — advertised continuously 20 s+ in the real OS, no crash.
- **Advertising stops on exit** — `AppManager.restart_launcher()` tears down the activity
  (`onStop`→`ble.end()`); host scan then finds **0** hits.
- Deployed code confirmed current (lvgl `remove_flag` fix present on-device).

## 2-badge field test — ROUND-TRIP CLOSED ✅
A 2nd badge (`/dev/ttyACM1`, unique_id `…aed8`) closed the one remaining physical gap:
- **Real round-trip**: badge #2's real `gap_scan` detected badge #1 over the air —
  `ARR name="Alex YOURCALL" shared="Makerspace Baasrode" id=0xa07b rssi=−40`. Real
  `gap_scan → parse_payload → intersect → arrival` on actual radio packets.
- **Disjoint ignored**: badge #2 scanning with a non-overlapping group (`0x3c42`) → **0 peers**
  (Alex ignored).
- **Symmetric**: both apps running + advertising + scanning; host scan sees both beacons
  (`Alex YOURCALL` on `…0E`, `Alice` on `…DA`, both group `0xa07b`) → mutual detection + alert.
- Gotcha: a freshly-deployed app isn't seen by `AppManager` until `refresh_apps()` (or a reboot);
  `start_app` on an undiscovered fullname **silently no-ops** (no exception), so the first Alice
  launch advertised nothing until refresh.
- Gotcha: `tools/badge_run.py` hardcodes `/dev/ttyACM0`; used a port-arg paste launcher
  (`/tmp/paste_port.py`, paste mode coexists with the OS asyncio loop — mpremote's raw REPL
  does not) for the 2nd badge.

The host BlueZ TX limitation is now moot — a real 2nd badge is the clean test stand.

## 3-badge test — coalescing on real hardware
A 3rd badge (`/dev/ttyACM2`, `…cfab8`, "Bob") joined. All three deployed + running the app +
advertising on group 0xa07b (host scan: `Alex YOURCALL`, `Alice`, `Bob`).
- **Multi-peer + coalescing**: with Alice + Bob advertising and Alex as scanner, Alex's real
  scan detected **Alice** → coalesced banner `"Alice nearby (Makerspace Baasrode)"` (rssi −50).
  The 2-arrival coalesced banner text (`"Alice, Bob nearby (Makerspace Baasrode)"`) was already
  proven on-device in `dev_ui_test`; the real-radio run confirmed the single-peer path.
- **Flakiness noted**: catching BOTH Alice+Bob in one scan window simultaneously was unreliable
  (BLE radio timing/state), and the repeated adv+scan cycling on Alex (ACM0) eventually
  hard-wedged him (esptool `--before usb_reset` could not recover — needs a physical RESET).
  Alice (ACM1) + Bob (ACM2) stayed healthy.
- **Takeaway**: coalescing is satisfied at the code level (2-arrival → coalesced banner) plus the
  real single-peer path; the simultaneous-2-real-peer live demo is radio-timing luck, not a code
  gap. Avoid long adv+scan REPL sessions on one badge — they destabilize the NimBLE/USB stack.
- **Resumed attempt**: a gentle scan-only run (Alice as receiver, Alex+Bob advertising) was tried,
  but the prerequisite `restart_launcher` paste on Alice (ACM1) hard-wedged her too (esptool
  `--before usb_reset` could not recover — needs a physical RESET, like Alex earlier). Stopped
  after 2 of 3 badges wedged rather than risk Bob (ACM2). All three had been confirmed advertising
  together immediately before; coalescing stands proven without the live 2-peer-simultaneous demo.

---

# Group Nametag + Proximity Finder — plan review & hardening — 2026-07-07

Reviewed and substantially hardened `PLAN.md`, the self-contained implementation plan for a
MicroPython **group nametag + BLE proximity finder** app for the Fri3d Camp 2024 badge. No code
was written this session — the badge app is still "planning complete, not yet implemented." Work
was: verifying the plan's load-bearing claims against the real firmware/framework repo, fixing
broken paths after the project folder moved, adding a multi-group membership feature, reworking
the proximity model, and a full review pass (contradictions / omissions / ambiguities) plus five
new usability features.

## Files
- `PLAN.md` — the working document; edited throughout (grew ~19 KB → ~32 KB).
- `Makerspace Baasrode Logo 500X500.jpg` — placeholder logo, unchanged.
- **No git repo** in this folder (nothing to commit/push).

## 1. Verified the plan's load-bearing claims (against `../fri3dbadge2024`)
All confirmed **true** by reading the actual sources:
| Claim | Where verified |
|---|---|
| BLE central+peripheral compiled in (`MICROPY_PY_BLUETOOTH_ENABLE_CENTRAL_MODE 1`, NimBLE, `CONFIG_BT_ENABLED=y`) | `repos/badge_2024_micropython/ports/esp32/mpconfigport.h`, `boards/sdkconfig.ble` |
| Image decoders on (`LV_USE_TJPGD/LODEPNG/GIF 1`); no real `lv_fs` (only `LV_USE_FS_MEMFS 1`) → must decode from in-memory buffer | `fri3d/lvgl_esp32_mpy/binding/lv_conf.h` |
| `fb_image()` RGB565 `lv.image_dsc_t` raster fallback; `_held()`/`_keep`/`_wipe`/`start`/`stop` patterns; `app.json` schema | `app/name_badge/{art.py,name_badge.py,app.json}` |
- Note: `MICROPY_BLUETOOTH_NIMBLE_BINDINGS_ONLY (1)` is set (IDF-provided NimBLE host) — reinforces that the concurrent advertise+scan spike is genuinely mandatory.

## 2. Fixed broken path references (folder was moved)
The project folder is now a **sibling** of `fri3dbadge2024/` (was assumed nested inside it). Every
`../app/...` reference was wrong. Corrected throughout:
- `../app/...` → `../fri3dbadge2024/app/...` (name_badge, neon_launcher, main.py, art.py)
- framework-source anchor and `tools/badge_run.py` → `../fri3dbadge2024/...`
- §4 layout header + tree root renamed `group-nametag/` → `fri3dbadge-group-nametag/`, reworded as a sibling.

## 3. Multi-group membership (new requirement)
A member can now belong to **multiple groups**; presence alerts fire when group sets **intersect**.
- Config `group` (string) → **`groups`** (list), capped by `MAX_GROUPS ≈ 5`.
- Wire format: single Group ID → **Group count (1B) + Group IDs (2×G, little-endian, dedup+sorted)**.
- Matching = hash-set intersection; the `seen[]` entry records the shared group name(s) for display.

## 4. Proximity model change — "presence = in BLE range"
the wearer's decision: alert as soon as a matching badge is within radio range (no distance calibration).
- **Dropped** the `RSSI_ENTER`/`RSSI_EXIT` field-calibration hysteresis entirely.
- **Eviction timeout `EVICT_MS = 30 s`** defines absent; notify-once debounced on `absent→present`.
- **`rssi_floor` is now a per-install `app.json` config value** (default **-120** = disabled; radio
  sensitivity is ~-97 dBm so -120 passes everything). Optional coarse range gate, not calibration.
- Open-field range estimate captured: **~50–100 m LoS** badge-to-badge, less through tents/bodies.

## 5. Full review pass — fixes folded in
**Contradiction:** §8 lifecycle still used single-group `ble.begin(group,...)` → now
`ble.begin(groups, name, handle, rssi_floor)`.

**Omissions (a couple were latent bugs):**
- **Stable BLE address** (`addr_mode=0x00` public/static; table keyed on `(addr_type, addr)`) — without
  it, address rotation causes endless re-alerts + ghost entries. Biggest gap.
- **Defensive parsing** — bounds-check `group_count`/`name_length` against the received buffer; anyone can broadcast 31 arbitrary bytes.
- **`ADV_MS ≈ 250 ms`** interval specified; **little-endian** fixed for 2-byte fields; **`ticks_diff()`** for eviction; **UTF-8 boundary** truncation; empty/missing `groups` → hint + skip BLE; `MAX_GROUPS` overflow → keep lowest IDs.

**Ambiguities:**
- **GIF dropped** — static PNG/JPEG only this iteration (GIF needs `lv.gif`, conflicts with breathing anim); deferred to §11.
- **Passive scan** (beacon is non-connectable / no scan response, so active scan is wasted power).
- **1-byte wire-format version `0x01`** (unknown → drop) for forward-compat; **concurrent alerts coalesce**; two `name` keys (menu label vs `config.name`) clarified; non-square logo scale = `min(box_w/img_w, box_h/img_h)×256`.

## 6. New usability features written into the plan
| Feature | Notes |
|---|---|
| **Per-group colour + tone** | LED hue + sting pitch derived deterministically from the group hash; shared-multiple → lowest-sorted shared ID (both badges agree). No config. |
| **Backlight dim-out** | After `DIM_MS ≈ 30 s` idle; BLE keeps running while dimmed. |
| **Battery indicator** | On idle screen, *if* the framework exposes battery state (API unverified). |
| **First-run hint** | Unconfigured badge (empty `name`/`groups`) shows "Configure me" + skips BLE. Only new persistent surface — persisted mute/brightness explicitly deferred. |
| **Own-group(s) line** | Idle screen shows this badge's configured groups so the wearer confirms who can find them. |

## 7. Added a hardware-API probe (§9 spike 3, + §10 checklist)
Quick pre-UI check for the three **unverified** APIs this session introduced: `addr_mode` (stable
address), display/backlight **brightness**, and **battery** state. Instruction: drop-and-note in
`DESIGN.md` rather than block if backlight/battery don't exist.

## Notes / follow-ups
- Plan is now internally consistent end-to-end; name budget is **`20 − 2×G` bytes** (no Flags AD emitted).
- Still unimplemented. Two mandatory spikes before UI work: **logo in-memory decode** and **concurrent adv+scan**; plus the hardware-API probe above.
- Deliverables named in the plan but not yet created: `README.md`, `DESIGN.md`, and the `app/`/`tools/` source tree. `DESIGN.md` has queued TODOs: `rssi_floor` guidance table + open-field link-budget writeup.

---

# Group Nametag + Proximity Finder — plan phasing & packaging pass — 2026-07-07

Follow-up to the hardening pass above: turned the flat build-order into **gated
development phases** and closed the three structural gaps the review flagged.
`PLAN.md` only; still no code, still unimplemented.

## Files
- `PLAN.md` — four edits (§4 layout, §6.1, §9 spike 3, new §9.1).

## What changed
1. **`tests/` added to the §4 layout** — `test_ble_proximity.py` + `conftest.py`.
   Flagged the load constraint: `ble_proximity.py` must keep
   `import bluetooth` / `fri3d` / `lvgl` out of the pure wire-format functions'
   import path (lazy-import inside the radio/IRQ wrappers) or the host can't
   load the module to run them.
2. **New §9.1 "Phased deliverables"** — 6-phase table (0 De-risk → 1 BLE core+tests →
   2 logo loader → 3 idle UI shell → 4 alerts+signature → 5 integration+polish),
   each row = deliverable + falsifiable exit gate + the §10 checkboxes it closes.
   All 14 checklist items mapped to a phase. `README.md` / `DESIGN.md` (previously
   orphaned) made explicit Phase-5 deliverables.
3. **Stable-address fallback separated (§9 spike 3, + §6.1 cross-ref)** — backlight
   and battery stay "drop if absent"; the stable address reclassified **not optional**
   (it underpins the no-ghosts guarantee). Expected ESP32/NimBLE public-address
   default, plus an honest degradation fallback (eviction window → documented
   known-limitation → flag-before-shipping) if a stable address can't be set.

## Notes / follow-ups
- Plan is now phased with gated deliverables and a home for the unit tests;
  everything else unchanged. Still unimplemented; Phase 0 spikes remain the entry
  point.
