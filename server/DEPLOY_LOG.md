# Deployment log — Gotcha backend

**Everything this project changes on a host is listed here, with the command that
undoes it.** The camp is 14–16 August 2026; after it, the game server should leave
no trace on the laptop it ran on beyond what someone deliberately decides to keep.

`deploy/uninstall.sh` performs the whole reversal in one go. This file is the
audit trail behind it — read it if you want to undo something by hand, or to
check that nothing was left behind.

---

## DECOMMISSIONED 2026-08-14 — no instance is running anywhere

Gotcha development was stopped, and the staging instance below was removed from
`john-ThinkPad-E15` the same day. **Every row in the table was reverted and
verified**; the host is back to its pre-deploy state. See "Decommission" at the
end of the session record for exactly what was run and what was checked. The
sections below are kept as the audit trail (and as the recipe, should the game
ever be revived).

---

## Host: 192.168.1.57 (`john-ThinkPad-E15`, Ubuntu 26.04, Python 3.14.4)

Development/staging instance for Phase 1. Deployed **2026-07-30** by
`deploy/install.sh`. Not the camp machine — the camp server is a freshly imaged
laptop (§6.1) and will be deployed with the same script.

| # | Change | Path / name | Undo |
|---|---|---|---|
| 1 | System user created (no login shell, no home content) | `gotcha` | `sudo userdel gotcha` |
| 2 | Application directory + virtualenv (~50 MB: fastapi, uvicorn, python-multipart, pip) | `/opt/gotcha/` | `sudo rm -rf /opt/gotcha` |
| 3 | Database directory, owned by `gotcha`, mode 0750 (`StateDirectoryMode`) | `/var/lib/gotcha/` | `sudo rm -rf /var/lib/gotcha` |
| 4 | SQLite database, mode 0640 (`UMask=0027`) — **holds one `player_key` per badge** | `/var/lib/gotcha/gotcha.sqlite3` | delete the file, or the directory above |
| 5 | Config directory, mode 0750 root:gotcha | `/etc/gotcha/` | `sudo rm -rf /etc/gotcha` |
| 6 | **Environment file containing the admin password** | `/etc/gotcha/gotcha.env` | deleted with #5 |
| 7 | systemd unit, enabled and started | `/etc/systemd/system/gotcha.service` | `sudo systemctl disable --now gotcha; sudo rm /etc/systemd/system/gotcha.service; sudo systemctl daemon-reload` |
| 8 | systemd state directory (created by `StateDirectory=`) | `/var/lib/gotcha` (same as #3) | as #3 |
| 9 | Source staged for the installer | `/tmp/gotcha-src/` | `rm -rf /tmp/gotcha-src` (or reboot) |
| 10 | **Tailscale Funnel** exposing `:8080` to the public internet over HTTPS at `https://john-thinkpad-e15.tail44c8ab.ts.net` (added 2026-08-09) | Tailscale serve/funnel config | `sudo tailscale funnel --https=443 off` |

**Not changed on this host:** no firewall rules (ufw was and remains inactive),
no ports 80/443 bound (the service listens on **:8080** only; the Funnel in row 10
terminates TLS in the Tailscale daemon, not in this service), no changes to
DNS, `/etc/hosts`, timezone, packages outside the virtualenv, or any other
systemd unit. `python3-venv` was already installed. No cron or timer units
were created — this server has no scheduled work by design (see `README.md`,
"Derive, don't schedule").

### Session record

| Date | Action | Notes |
|---|---|---|
| 2026-07-30 | `install.sh` run 6× | Initial deploy, then re-deploys for `/v1/admin/truce_schedule`, the `protect seconds: 0` fix, the admin-page rendering fix, and the `UMask=0027` / `StateDirectoryMode=0750` hardening. Idempotent; each run replaced `/opt/gotcha/server` and restarted the unit. |
| 2026-07-30 | Database deleted 5× | After each smoke run, so the deployed instance holds no fake players. **Current state: empty database, game in `lobby`.** |
| 2026-07-30 | Permissions tightened | systemd created `/var/lib/gotcha` 0755 and SQLite the database 0644, leaving every badge's `player_key` readable by any user on the laptop. Now 0750/0640 via the unit. |
| 2026-07-30 | Admin password set | Stored in `/etc/gotcha/gotcha.env` on the host, mode 0640 root:gotcha. **Not recorded here — this repo is public.** Read it with `sudo grep GOTCHA_ADMIN_PASSWORD /etc/gotcha/gotcha.env`; change it by editing that file and `systemctl restart gotcha`. A development value was used during this session and has since been rotated; **the camp machine must get a fresh one.** |
| 2026-08-10 | **Admin password ROTATED (incident)** | The value in use since 2026-07-30 was committed to `changelog.md` on 2026-08-02 and pushed to this **public** repo, while `/admin` was reachable from the internet through the Tailscale Funnel — so it must be treated as compromised for that window. Rotated 2026-08-10, old value now rejected (401), new value verified (303). Working tree scrubbed; **git history still contains the dead value** and was deliberately not rewritten (the repo is public and already cloneable, so a rewrite buys nothing). Undo: restore `/etc/gotcha/gotcha.env.bak-*` and `systemctl restart gotcha`. **Do not record the new value in this repo.** |
| 2026-07-30 | Smoke test run 4× | `tools/smoke.py` over the LAN. Last run: enroll → signed sync → replay refused → ring built (6 players, 0 conflicts) → kill scored → dashboard. All checks passed. |
| 2026-07-30 | 1000-sync soak run | `tools/smoke.py --soak 1000` over the LAN. Median 5.5 ms, no latency drift, service RSS flat at 35 MB. Database wiped afterwards. |
| 2026-07-30 | Truce window moved and restored | By `smoke.py`, because the run happened at 06:00 inside the 22:00–08:00 truce. Restored to `22:00–08:00` in the same run; verified in the database afterwards. |
| 2026-08-09 | Truce reset to 22:00–08:00 | The DB still held the `00:00–00:01` dev override from commit `7d9cef3`. Reset via `POST /v1/admin/truce_schedule` over localhost (the server is now on this machine, on casarural WiFi at `192.168.1.177`). |
| 2026-08-09 | Tailscale Funnel enabled (row 10) | Exposes `:8080` publicly at `https://john-thinkpad-e15.tail44c8ab.ts.net`. Reason: casarural WiFi isolates clients, so badges cannot reach the server over the LAN. Verified end-to-end — a badge's signed `/v1/sync` over the funnel returned `200` and `synced_15m` went `0→1`. |
| 2026-08-09 | Badges pointed at the funnel | All 3 dev badges (9de4, fac0/Badge2024lijn, bac8) on casarural WiFi, `config.json gotcha.api`/`enroll` set to the funnel URL, on app `0.11.16` (HTTPS sync support). |
| **2026-08-14** | **DECOMMISSIONED — all 10 rows reverted** | See below. |

### Decommission (2026-08-14)

Gotcha development was stopped, so the instance was torn down by hand rather than
via `deploy/uninstall.sh` (the script was not used; the manual steps below are the
same reversals the table prescribes, run in a safe order). Order mattered: the
**Funnel was closed first** so the public exposure ended before anything else, and
the service was stopped **before** archiving so SQLite checkpointed its WAL into a
consistent file.

```bash
sudo tailscale funnel --https=443 off && sudo tailscale serve reset   # row 10
sudo systemctl stop gotcha                                            # row 7
# ... archive taken here (see below) ...
sudo systemctl disable gotcha && sudo rm -f /etc/systemd/system/gotcha.service
sudo systemctl daemon-reload && sudo systemctl reset-failed           # row 7
sudo rm -rf /opt/gotcha /var/lib/gotcha /etc/gotcha                   # rows 2,3,4,5,6,8
sudo userdel gotcha                                                   # row 1
```

Verified afterwards: `tailscale funnel status` → `No serve config`; the public
URL no longer answers; no `gotcha` unit, user or group exists; all three
directories gone; nothing listening on `:8080`; Tailscale itself still up. Row 9
(`/tmp/gotcha-src/`) was already absent. `ufw` was inactive throughout, as the
"Not changed on this host" note says, so no firewall state needed undoing.

**Archive:** `/home/john/gotcha-backend-decommissioned-20260814.tar.gz`, mode
`0600`, owned by `john` — the WAL-checkpointed database (`integrity_check: ok`;
7 players, 7 `badge_keys`, 1 kill, 1397 events), `gotcha.env` + its `.bak`, and
`gotcha.service`. This is the `--keep-backup` idea done by hand, so it sits in
`/home/john` rather than the script's `/root/gotcha-final-<timestamp>.sqlite3`.
**It contains credentials** — a `player_key` per badge (row 4) and the admin
password (row 6) — hence `0600`, and deliberately **outside this repo**, which is
public and Syncthing-synced.

Two things deliberately left in place, neither of which is host state this
project created: the Funnel's Let's Encrypt certificate in
`/var/lib/tailscale/certs` (Tailscale-managed, self-expiring), and the tailnet's
Funnel **ACL grant**, which lives in the Tailscale admin console rather than on
this machine and must be revoked there if it is no longer wanted.

Two observations from the teardown, recorded because they are the kind of thing
this log exists for. A dev badge was **still syncing** at shutdown (`POST
/v1/events`, `GET /v1/sync` at 15:25) — harmless, since the badge protocol treats
an absent server as "keep playing, queue events" (D6), and the app now published
(0.12.1, pre-Gotcha) does not sync at all. And the Funnel was being **scanned from
the open internet**: an open-proxy probe (`CONNECT httpbin.org:443` from
45.135.193.193) hit it minutes before shutdown, answered `404`. That is the
predicted "a public URL attracts bot scans" behaviour, and a reminder of why the
admin password rotation above mattered.

### Operating notes

**Resetting to an empty database** (a dev action — at camp, start a new game with
`POST /v1/admin/game` instead, which keeps the record):

```bash
sudo systemctl stop gotcha
sudo sh -c 'rm -f /var/lib/gotcha/gotcha.sqlite3*'    # note: root expands the glob
sudo systemctl start gotcha
```

The `sh -c` matters. `/var/lib/gotcha` is 0750, so `sudo rm /var/lib/gotcha/*`
lets your *own* shell expand the glob, which cannot read the directory — the glob
silently fails to match and `rm -f` succeeds having deleted nothing. It looks like
it worked. Almost all of the database lives in the `-wal` file, so deleting only
`gotcha.sqlite3` also leaves the data intact.

**Where the state is:** the SQLite file is the only state. There is no cache, no
queue, no cron and no second process, so backing it up is `cp` and restoring it is
`cp` back with the service stopped.

**Logs** go to the journal: `journalctl -u gotcha -f`. Nothing is written to disk
outside `/var/lib/gotcha`.

### After camp

```bash
# keep the game record (scores, kills, audit log), remove everything else
sudo server/deploy/uninstall.sh

# or take a copy of the record and leave nothing at all
sudo server/deploy/uninstall.sh --purge --keep-backup
```

The database is worth keeping until the leaderboards have been published and any
disputes settled: it holds every kill, every admin action and the full audit
trail. `--keep-backup` copies it to `/root/gotcha-final-<timestamp>.sqlite3`
before deleting the live one.

---

## Reversibility of the game itself

Separate from host changes, and worth stating because it is the part that
involves other people:

- **The badge stores nothing new outside its own app directory.** Gotcha state
  lives in `gotcha.json` in the app folder, which an AppStore update already
  wipes (verified, §14.2 A5). Deleting the app removes it.
- **No credential is ever transmitted to the badge except `player_key`**, once, at
  enrollment, and it never leaves the badge afterwards.
- **The server holds no age or cohort field** (D25) and no location data of any
  kind (D17) — there is nothing sensitive to purge beyond names and scores that
  were public by design.
- **Export before deleting:** `GET /v1/admin/export` (JSON) or `?fmt=csv` produces
  the full dump. `player_key` is deliberately excluded from it.
