# Physical Tests Runbook — 3 tests to run before camp

Clear, concise, copy-pasteable. Do these at the bench with the badges.
Today is 2026-08-11; camp is 14–16 Aug. WiFi at the bench is **LIMEHOME**
(password in the badges already). Backend is live at `100.64.72.86:8080`.

**Badges & ports** (Espressif by-id; CH340 ports are *trackers — never touch*):
```
9de4  pid 1004  /dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_1cdbd49d9de40000-if00
lijn  pid 1007  /dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_348518acfac00000-if00   ← has battery
bac8  pid 1003  /dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_90706901bac80000-if00   ← NO battery
```
`MP="sudo /tmp/ff-venv/bin/mpremote connect <port>"`. If a command hangs the USB
console (CDC wedge), recover without replug:
`sudo /tmp/ff-venv/bin/python` → `fcntl.ioctl(open('/dev/bus/usb/<bus>/<dev>','w'),21780)`
(bus/dev from `ls /sys/bus/usb/devices`). This does **not** reboot the badge.

---

## TEST 1 — Worn-on-worn threshold walk  *(~30 min, 2 people, 2 battery badges)*

**Goal:** set `KILL_RSSI` for real body-shadow, so a kill only fires when the
assassin is genuinely close. Use **lijn + one other battery badge** (bac8 has no
battery — can't be worn).

1. On the **walker**, write the target name filter and launch the activity:
   ```
   $MP exec "import json;json.dump({'name':'<target-name>'},open('/rssi_cfg.json','w'))"
   ```
   Then on the badge: launch **RSSI Walk** from the launcher.
2. Walk the prompted course **twice**: (a) face each other on approach,
   (b) target facing **away** (worst body-shadow). Press A at each prompt.
3. Pull + analyse:
   ```
   tools/pull_walks.sh <walker-port>
   /tmp/ff-venv/bin/python tools/analyze_shadow.py probes/logs
   ```
4. Read the **median RSSI at 1 m** the script prints, then set `KILL_RSSI` on the
   **admin page** (live-tunable, no rebuild):
   - 0 to −4 dB shadow → `KILL_RSSI = -65` (unchanged)
   - −8 → `-68` · −12 → `-71` · −16 → `-77`
   - worse than −16 → also cut `KILL_HOLD_MS` to `2500`.

**If you can't do this test:** ship `KILL_RSSI = -68` and treat the first real
playtest as the measurement. Don't let it block anything.

---

## TEST 2 — Real two-badge kill over the live flush path  *(~15 min)*

**Goal:** prove a genuine duel scores end-to-end: A-press → 5 s hold → KILLED →
soul disclosed → badge flushes → server `total_kills`/`score` increment.

**Preconditions:** both badges enrolled & on LIMEHOME; one hunts the other; **not
in truce** (truce is 22:00–08:00 — do this in daytime); victim not protected.

1. **Set the target** so 9de4 hunts lijn (do this on the server):
   ```
   ssh john@100.64.72.86 "sudo python3 -c \"
   import sqlite3; d=sqlite3.connect('/var/lib/gotcha/gotcha.sqlite3')
   d.execute('UPDATE players SET target_pid=1007 WHERE pid=1004'); d.commit(); print('ok')\""
   ```
2. On **9de4**, open the Gotcha app. Wait for the radar to show the target.
   Press **A = AANVALLEN** while within ~1 m of lijn.
3. **Hold 5 seconds** (screen shows ENGAGED countdown). On success: **KILLED**,
   soul disclosed on 9de4; lijn shows the death/respawn screen.
4. Confirm it scored on the server (sync runs within 5 min, or force it now):
   ```
   ssh john@100.64.72.86 "sudo python3 -c \"
   import sqlite3; d=sqlite3.connect('/var/lib/gotcha/gotcha.sqlite3');d.row_factory=sqlite3.Row
   r=dict(d.execute('SELECT total_kills,score FROM players WHERE pid=1004').fetchone());print(r)\""
   ```
   → `total_kills` went up by 1. (A kill's soul is verified against the victim's
   commitment, so only a real duel scores — that's the proof.)

**If the A-press does nothing:** victim likely in truce/protected, or the target
wasn't reassigned. Re-check step 1 and the clock. Host-BLE hunting does **not**
work from this laptop (−95 dBm) — it must be badge-to-badge.

---

## TEST 3 — Flags AD + full-screen UPDATE smoke  *(~10 min, after a redeploy)*

**Precondition:** redeploy current repo code to the badge and bump `MANIFEST.json`
to **0.11.30** first (the on-badge `contact_exchange.py` is stale at 0.11.29).
Deploy recipe: reset to launcher, then ONE chained `cp` session. Verify a loaded
symbol afterwards, not just the MANIFEST number.

### 3a — Flags AD (connectable advert)
```
$MP exec "import contact_exchange as ce;print(ce.build_exchange_adv(1)[:3]==bytes([0x02,0x01,0x06]))"
```
→ must print **`True`**. (If `False`, the stale module is still loaded — redeploy again.)

### 3b — full-screen UPDATE NODIG overlay
1. Force the nudge by raising the floor above the badge's version:
   ```
   ssh john@100.64.72.86 "sudo python3 -c \"
   import sqlite3; d=sqlite3.connect('/var/lib/gotcha/gotcha.sqlite3')
   d.execute('UPDATE games SET min_version=99.0 WHERE id=1'); d.commit(); print('ok')\""
   ```
2. On the badge, open/refresh the Gotcha app so it syncs. **Expect:** a full-screen
   **"UPDATE NODIG"** panel (Dutch: *alles opgeslagen…* once the queue is empty, or
   *even synchroniseren…* while events are pending).
3. Press **A or X** → panel dismisses. While it was shown, hunting (AANVALLEN)
   should be **refused**; after dismiss the badge returns to normal.
4. **Reset the floor** so it doesn't fire at camp:
   ```
   ssh john@100.64.72.86 "sudo python3 -c \"
   import sqlite3; d=sqlite3.connect('/var/lib/gotcha/gotcha.sqlite3')
   d.execute('UPDATE games SET min_version=NULL WHERE id=1'); d.commit(); print('reset')\""
   ```

---

### When all three pass
- `KILL_RSSI` set from the walk (or defaulted to −68).
- A real kill incremented the hunter's `total_kills` on the server.
- `build_exchange_adv(...)[:3]` == Flags AD → `True`, and the UPDATE panel
  showed/dismissed correctly.

Then the only things left before camp are the admin-page housekeeping
(`min_version`/`latest_version`/`end_at` — see `PreCamp_Runbook_20260811.md` step 4)
and the Phase 6 dry run with real players.
