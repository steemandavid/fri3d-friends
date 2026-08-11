# !Fri3d Friends — nametag, friend finder & contact swap

A MicroPythonOS app for the **Fri3d Camp 2024 & 2026 badges** that does three
things:

1. **Animated nametag** — shows your name large (it scrolls if too long), with
   your group(s) as coloured pills (the colour is unique to each group), a live
   NTP-synced clock (top-left) and battery % (top-right).
2. **Proximity finder** — over Bluetooth Low Energy, it detects other badges
   running this app that share **at least one group** with you, and alerts you
   when one comes within radio range ("someone from my groups is nearby").
3. **Contact swap (Y button)** — press **Y** near another badge whose owner also
   presses **Y** within ~5 s (they need *not* be a friend or in your group), and
   the two badges exchange contact info over a short Bluetooth connection. You
   send your **name** and **group(s)**, plus a free-form set of fields you choose
   (Email, Phone, Website, Discord, bitcoin wallet…). What you receive is stored
   on the badge with the date/time — **one entry per swap**.

A **phone setup page over Bluetooth** (Web Bluetooth) lets you edit your name /
groups / contact fields and view/export received contacts from a phone or laptop
— the badge keyboard is too cumbersome for lots of text. It needs **no WiFi or
network**: the phone talks Bluetooth straight to the badge. Scan the QR the badge
shows to open the page; a 4-digit code on the badge gates access.

**No phone? No internet? The badge works on its own.** A brand-new badge names
itself (something like *Otter 42*) and goes straight to a working nametag — pick
**Overslaan** on the first screen to skip setup. From there you can join a
friend's group just by swapping with them (**Contact ruilen** in the menu, no
typing), or edit everything on the badge via the menu's **Instellingen**. The
phone page is the comfortable option, never a requirement.

It's **generic and redistributable**: any hackerspace/makerspace can flash it and
set their own group name(s) and member name by editing one file (no code changes)
— and it finds *their* people.

> **Language: the app's interface is in Dutch.** Fri3d is a Dutch-language event
> with a lot of children in the audience, so every string the player sees — the
> badge UI, the on-badge editor and the phone setup page — is Dutch. Code,
> comments, docstrings, log output and this README stay English.
>
> **UI copy must be pure ASCII.** The badge renders its chrome in lvgl's built-in
> `font_montserrat_*`, which carry ASCII only — a `ë` or `é` becomes a
> missing-glyph box with no warning at build time. Write `een`, not `één`.
> **Player names are the exception**: the big name label uses the bundled
> Latin-1 subset TTF, so `Zoë` renders correctly. Never strip accents from names.

## Install

### From the AppStore (recommended)

On your badge, open the **AppStore** app (BadgeHub backend), find **!Fri3d
Friends**, and install. It shows up at the top of the launcher afterwards (the
`!` sorts it first). Updates are offered automatically when a newer version is
published.

### From source (development)

The app folder is `app/com.fri3dcamp.fri3dfriends/`. Copy the whole folder to
`/apps/` on the badge with [`mpremote`](https://docs.micropython.org/en/latest/reference/mpremote.html),
then reset:

```bash
mpremote connect /dev/ttyACM0 cp -r app/com.fri3dcamp.fri3dfriends :/apps/
mpremote connect /dev/ttyACM0 reset
```

(If you added it without rebooting, run `AppManager.refresh_apps()` in the REPL,
or just reboot.)

## Configure (no code edits)

Edit **`/apps/com.fri3dcamp.fri3dfriends/config.json`**:

```json
{
  "groups": ["Makerspace Baasrode"],
  "name": "Alex",
  "rssi_floor": -120,
  "sound": true,
  "banner_ms": 5000,
  "contact": {
    "Email": "alex@example.org",
    "Phone": "+32 0000 000",
    "Website": "example.org",
    "Discord": "alex#1234"
  }
}
```

- **`groups`** — one or more group names you belong to. Two badges alert on each
  other when their group lists **overlap** (any shared group). Each name is
  hashed before broadcast (never sent as text), so type it the same way on every
  member's badge (case/whitespace are ignored). Up to ~5 groups. Easiest to join
  by **swapping with someone already in the group** (see below) — that copies the
  name exactly and can't be typo'd.
- **`name`** — your display name (shown large across the top of the screen). Leave
  it empty and the badge picks a stable **auto-nickname** for itself (*Otter 42*,
  *Badger 7*, …), derived from the chip's own id, so a fresh badge is usable
  immediately. It's the same name every boot and is never written to the file, so
  clearing `name` always brings it back.
- **`rssi_floor`** — optional coarse range gate in dBm. Default **`-120`** =
  detect anything the radio can hear (full range). Raise it to only alert on
  badges that are close, e.g. `-80` (≈ same tent / ~10 m) or `-70` (≈ next to me).
  It's a noise/range filter, *not* fine calibration. See **DESIGN.md §5** for a
  fuller dBm→range guidance table and the open-field link-budget estimate.
- **`sound`** — `true`/`false`, whether the arrival buzzer sting plays. Toggled
  with **B** and **persisted** across reboots. Default `true`.
- **`banner_ms`** — how long the "friend arrived" banner stays on screen, in ms.
  Default `5000` (5 s). Values below `500` are ignored (a `0`/negative would hide
  every banner) and fall back to the default.
- **`board`** — optional, `"2024"` or `"2026"` to force the hardware profile
  (otherwise auto-detected). Only needed if autodetection fails.
- **`contact`** — your "my contact info": a free-form object of `"field":
  "value"` pairs (Discord, website, phone, bitcoin wallet, anything). This is the
  data sent to another badge when you both press **Y**. Easiest to edit from the
  **phone setup page** (below) rather than by hand.

## Setup on the badge itself (no phone, no internet)

Open the menu → **Instellingen** to open the on-badge editor. It uses
MicroPythonOS's own settings UI, so it works on **both badges** — tap-and-type on
the 2026 badge's touchscreen, and button-navigated focus plus the on-screen
keyboard on the button-only 2024 badge.

| Setting | How you edit it |
|---|---|
| **Je naam** | text |
| **Groepen** | text, comma-separated |
| **Geluid** | Aan / Uit |
| **Bereik** | pick from *Volledig bereik · Ruime omgeving · Zelfde tent of ruimte · Vlak naast me · Tegen elkaar* |
| **Banner (sec)** | slider, 1–15 s |

Saving writes straight to `config.json` through the same validation the phone page
uses, and applies immediately. Contact fields (Email, Discord, …) are **not** in
the on-badge editor — there are arbitrarily many of them and they're long, so
that's what the phone page is for.

## Setup / contacts from your phone (over Bluetooth, no keyboard, no WiFi)

The badge runs a small **Web-Bluetooth setup service** so you can edit everything
above (name, groups, and the free-form `contact` fields) and view/export the
contacts you've received — from a **phone or laptop browser**, over Bluetooth.
No network is involved: the page talks GATT straight to the badge, which is ideal
at Fri3d Camp where badges and phones sit on different SSIDs/subnets.

- **Open the page.** Scan the **QR code** the badge shows (on the first-run
  "Stel me in" screen, or in the setup window on a configured badge). It points
  at a static page on GitHub Pages:
  `https://steemandavid.github.io/fri3d-friends/setup/?badge=XXXX`. `XXXX` is the
  badge's unique id, also printed on screen (`Fri3d-XXXX`).
- **Connect.** Tap **Connect** and pick the badge from the Bluetooth chooser. The
  `?badge=XXXX` filter means the chooser shows exactly **your** badge.
- **Unlock.** The badge shows a **4-digit code**. Type it in (prove you can see
  the screen — the Bluetooth-pairing trust model). Five wrong tries lock the badge
  out briefly and rotate the code.
- **Edit & save.** Change your name / groups / runtime settings and add/remove
  free-form contact fields, then **Save** — the badge applies name + contact +
  runtime settings live, and group pills refresh live too. Switch to the
  **Contacts** tab to view received contacts and **download** them as JSON.
- **Opening setup on a configured badge:** pick **Telefoon-setup** in the menu.
  This opens a **2-minute** setup window (QR + code + a countdown); pick
  **Sluiten** (or press **X**) to close it early. Proximity pauses during the
  window and resumes when it closes.
- **Browsers:** works in **Chrome/Edge** (Android + desktop). **iPhone/iPad**:
  Safari has no Web Bluetooth — the page detects this and points you at the free
  **Bluefy** browser (the same page works there unchanged).
- **International names work:** accented and non-ASCII names/groups (José, Noël,
  L'Atelier, …) are handled correctly. Edits are written **atomically**, so a
  battery dying mid-save won't corrupt your config or wipe your received contacts.
- There is also a headless CLI client, `tools/setup_client.py` (needs
  `pip install bleak`), that speaks the same protocol for testing/scripting.

## Swapping contacts (Y button)

Press **Y** and, within ~5 s, have a nearby badge's owner press **Y** too. The
two badges find each other over Bluetooth and swap their `contact` info in both
directions — **no shared group or friendship required**, just radio range. The
banner confirms `Geruild met <name>`; the received fields are stored on your
badge with the date & time and are visible in the phone setup page's **Contacts**
tab. (If nobody else is swapping in the window you get `niemand aan het ruilen`.)

### Joining a friend's group by swapping

The swap also carries the sender's **group name(s)**. If your friend is in a group
you're not in, the badge asks right after the swap:

```
      Alice is in 3 groups
      Join which?

   >  [x] Makerspace Baasrode
      [x] Fri3d Volunteers
      [ ] Lockpicking Village

   A: next   B: tick   Y: join
```

Everything offered starts ticked, so the usual case — a friend with one group — is
a single **Y**. This is the easiest way to join a group and the most reliable:
group names are matched exactly (after ignoring case and spacing), so a typo means
you silently never match anyone. Swapping copies the name across character for
character. It needs no phone, no internet and no typing, and it works on a badge
that has never been set up at all.

Your groups fill up at **5 maximum**; if more are ticked than fit, the badge joins
what it can and says how many didn't. Newly joined groups go on the air right
away, but the coloured **pills** only re-lay-out on the next app start.

> Note: the screen shows your group(s) as **coloured pills** (colour derived from
> the group name). The **!Fri3d Friends logo** (`fri3dfriends.png`) appears on the
> startup splash. The app runs on **both the Fri3d 2024 and 2026 badges**
> (auto-detected; force with the `board` key above).

> **First-run:** with no `groups` set, the badge shows a **"Stel me in" screen
> with a QR code** of its Bluetooth setup page and **does not run the proximity
> beacon/scan** — safer than beeping as a blank badge. It *does* advertise as
> `Fri3d-XXXX` so a phone can connect and configure it. Three ways forward, and
> only the first needs a phone:
>
> - **Scan the QR**, connect, enter the on-screen code, fill in your name and
>   group(s), and save: the badge **switches to the nametag and goes on the air
>   immediately** — no reboot needed.
> The first-run screen is a 3-row menu: pick **Op badge instellen** to open the
> on-badge editor (no phone), **Telefoon-setup** for the QR, or **Overslaan** to
> drop straight to a working nametag under the badge's **auto-nickname**
> (remembered, so you're not asked again). You can still join a group later by
> swapping with a friend, or set up via the menu.

## Controls

Everything is reached from one **on-badge menu** (joystick to move, **A** to
choose, **X** to close). On the nametag, press **A** (or tap **Menu** on the 2026
touchscreen) to open it:

| Menu item | Action |
|---|---|
| **Vrienden dichtbij** | Toggle the friends-nearby panel (cards: name · shared group · signal bars · dBm · age) |
| **Contact ruilen** | Swap contacts with a nearby badge (they pick it too, within ~5 s) |
| **Geluid: aan/uit** | Mute / unmute the alert buzzer (saved; the label reflects the state) |
| **Telefoon-setup** | Open the phone-setup window (Bluetooth QR + code) |
| **Instellingen** | Open the on-badge settings editor (name, groups, sound, range, banner) |

Three more rows appear **only once a Gotcha game has ever been joined**:

| Menu item | Action |
|---|---|
| **Mijn kaart (QR)** | Show the player-card QR — scan it with a phone for your score, rank, target and the leaderboards |
| **Gotcha demo** | Walk through the game screens without a live game |
| **Stoppen met Gotcha** / **Meedoen met Gotcha** | Opt out of / back into the game (always reachable in a couple of seconds) |

| Input | Action |
|---|---|
| Joystick ↑ / ↓ | move the highlight |
| **A** (ENTER) | activate the highlighted row (or open the menu from the nametag) |
| **X** (back) | close the current overlay; if nothing is open, quit to the launcher |

This menu model also fixes a 2026-badge bug where a button press could pop the OS
top-bar/drawer: the keypad drives our menu rows (the focus group's only members
while the app is foregrounded), never the OS bar. After a swap, the "join a
group?" prompt is the same kind of list — tick the group(s) you want, then
**Meedoen** (groups start **unchecked**, so nothing is joined by accident; **X**
cancels).

At launch a **3-second splash** shows the app name, version, "by David Steeman"
and the Makerspace Baasrode logo, then the nametag appears.

The idle screen shows: your **name** large across the top (it scrolls if too
long), your **group(s)** as coloured pills directly under it, battery %
(top-right, inset from the rounded corner), and a **friends line** —
`Vrienden dichtbij: Alice, Bob` when peers are in range, or `vrienden zoeken...`
when none. On a new arrival, a banner appears for ~5 s (`banner_ms`), the LEDs
flash, and a short buzzer sting plays — with a **colour + tone unique to the
shared group** (derived from the group hash, so you can recognise *which* group
just arrived without reading the screen). Several arrivals in one window coalesce
into one banner ("Alice + 2 more nearby"). Adding a group (via a swap or the
editor) makes its pill appear immediately — no reboot.

**Friend LEDs:** each nearby friend also gets their own badge LED, slowly and
dimly **breathing that friend's group colour** (friend 1 → LED 1, friend 2 →
LED 2, …) — a quiet, glanceable "who's around" without looking at the screen.
The name is rendered in a bundled 42px font; long friend names wrap.

## How matching works (short version)

Each badge broadcasts a small BLE manufacturer-data beacon containing a fixed
magic (`HSNT`), a version byte, the hashed IDs of its groups, and its (truncated)
name. A receiving badge decodes the beacon, ignores it unless the group sets
**intersect**, and otherwise adds the peer to a "nearby" table. A peer counts as
present the moment its first matching beacon is heard, and absent once it hasn't
been heard for ~30 s — that 30 s window also debounces the edge-of-range
dropouts. You're alerted **once** per encounter, and again once if they leave and
come back.

The group hash is a 16-bit convenience filter, **not** authentication — anyone
can broadcast a matching payload. That's fine for "who from my groups is around?"
at a camp.

## Background beacon (visible even with the app closed)

A small boot service (`beacon_service.py`, declared in the manifest, started by
the OS at boot) keeps **advertising your beacon while the app is closed**, so
friends' badges still spot you when you're in another app or on the launcher.
Background is **advertise-only**: you don't get alerts, LEDs, or contact swaps
until you open the app — but *they* see *you*.

- The service stays completely off the radio while the app is open (the app owns
  BLE exactly as before, including during contact swaps).
- An unconfigured badge stays silent in the background too.
- It activates on the **next reboot** after installing/updating the app.
- If another app uses Bluetooth while Fri3d Friends is closed, the two may fight
  over the radio; the beacon re-asserts itself within ~30 s.

## Project layout

```
app/com.fri3dcamp.fri3dfriends/   → the app (deploy to /apps/…)
  MANIFEST.JSON, fri3d_friends.py, ble_proximity.py (proximity beacon),
  beacon_service.py (background beacon boot service),
  contact_exchange.py (Y-button GATT swap), ble_setup.py (Web-Bluetooth setup GATT
  service + on-badge editor mapping), identity.py (auto-nickname),
  config.json, fri3dfriends.png (splash logo), icon_64x64.png (launcher icon),
  montserrat_name.ttf (42px name font)
server/       the Gotcha game backend (FastAPI + SQLite, one process, no build step)
  gotcha_server/  API, ring, scoring, state model, admin console, served pages
  deploy/         install.sh / uninstall.sh / gotcha.service (systemd)
  tools/smoke.py  stdlib-only smoke + soak test against a deployed instance
  README.md, DEPLOY_LOG.md (every host-level change, with its undo command)
docs/setup/index.html   → the Web-Bluetooth setup page (served via GitHub Pages)
tests/        off-device pytest: BLE wire format + contact exchange + setup protocol,
              plus the Gotcha backend (badge_sim.py drives the API as N fake badges)
tools/        setup_client.py (bleak GATT client), host_advertise.py, pull_file.py, make_logos.py
              deploy.sh (sha-verified code push), recover_badge_port.py (USBDEVFS_RESET
              unwedge for a badge whose USB-CDC has gone silent)
probes/       throwaway on-badge measurement apps (deployed, run, then removed) +
              probes/logs/ raw data. RSSI walks (rssi_walk_pkg), the BLE/WiFi
              coexistence probe (coex_pkg), and the §11 item-2 signed-sync heap
              soak (soak_pkg — driven from the host by tools/run_soak.sh;
              result in probes/logs/soak_result.json).
              Analysis: tools/analyze_rssi.py (RSSI-trend scoring),
              analyze_coex.py (coexistence + scan duty), analyze_shadow.py
              (body-shadow headroom for the kill thresholds)
DESIGN.md     protocol spec, verified hardware facts, verification status, open items
PLAN.md       the original full design document
```

**Gotcha (Assassin) game — planning and hardware spikes.**
`Implementation_Plan_Gotcha_20260726.md` is the live plan. Phase 0's hardware spikes
are **closed** (2026-07-30); their results are in
`Phase0_RSSI_Trend_Spike_20260729.md` (the "warmer/colder" RSSI-trend promise was
measured and **retracted** — the radar shows absolute proximity only) and
`Phase0_Coex_GATT_Duty_Display_20260730.md` (WiFi/BLE coexistence, a third GATT
service, scan-duty reduction, 2024 screen blanking). Read those before touching the
radar or the power levers — several plan assumptions did not survive contact.

**Phase 1 — the backend — is done** (2026-07-30) and lives in `server/`: FastAPI +
SQLite, the whole §9 API, scoring, the target ring, the admin dashboard, and the
badge-simulator test harness. It runs under systemd; `server/README.md` covers
running it, the two design choices that shape it, the interpretation calls it had to
make (two of which are contracts the badge side must match), and what is measured.
`server/DEPLOY_LOG.md` records every change made to the host it was deployed on,
each with the command that undoes it, so the machine can be returned to its prior
state after camp.

```bash
python3 -m pytest tests/ -q                                   # 442 tests, no badge needed
python3 server/tools/smoke.py http://<host>:8080 --badges 6    # check a deployment
```

See **DESIGN.md** for the full BLE protocol, the platform adaptation notes
(this badge runs MicroPythonOS, not the `fri3d.application` firmware), and the
detailed verification status.

## Build & publish (`.mpk` → BadgeHub)

**Automated (preferred):** `python3 tools/publish_badgehub.py` builds the
`.mpk`, uploads it + the icon, syncs `metadata.json` from `MANIFEST.JSON`, and
publishes a new BadgeHub revision — all via the BadgeHub API v3
(`https://badgehub.eu/api-docs/`). Use `--dry-run` to build + preview without
publishing. Requires a project API token in `~/.claude/secrets/badgehub.env`
(not in this repo — see `BADGEHUB_API_TOKEN`, created via
`POST /api/v3/projects/{slug}/token` while authenticated as the project owner).
Note: it shells out to `curl` for the HTTP calls — Python's `urllib` gets a
Cloudflare 403 (bot-management) on POST to badgehub.eu even with a custom
User-Agent, `curl` is unaffected.

The manual steps below are what the script automates, useful if you need to
publish without the stored token or want to inspect the process:

Apps are distributed as `.mpk` packages (a ZIP whose single top-level folder is
the app's `fullname`). Build a deterministic one:

```bash
cd app
FN=com.fri3dcamp.fri3dfriends
rm -rf $FN/__pycache__ $FN/.pytest_cache
find $FN -exec touch -t 202501010000.00 {} \;
# NEVER bundle config.json (or any runtime state) in the .mpk: install_mpk
# extracts it over the player's real config on every AppStore update, and the
# bare template it ships reads as "the update wiped my badge" (§8.10.4). The app
# bootstraps a missing config from defaults; gotcha.json/contacts.json are
# runtime-only and never in the repo.
(find $FN -type d; find $FN -type f ! -name config.json) | sort | TZ=CET zip -X -r -0 ../dist/${FN}_$(python3 -c "import json;print(json.load(open('$FN/MANIFEST.JSON'))['version'])").mpk -@
```

To publish, log in at **[badgehub.eu](https://badgehub.eu)** → **Create Project**
(App Identifier / slug = the `fullname` `com.fri3dcamp.fri3dfriends`; under
**Badge** select **`mpos_api_0`**) → upload the `.mpk`. Badges see the new release
on the next AppStore refresh. See the MicroPythonOS
[Bundling Apps](https://docs.micropythonos.com/apps/bundling-apps/) and
[BadgeHub](https://docs.micropythonos.com/apps/badgehub/) docs.

> **BadgeHub gotcha (learned the hard way).** On **Create Project**, BadgeHub
> extracts `metadata.json` and `icon_64x64.png` from the `.mpk` and stores them as
> separate project files. Re-uploading a newer `.mpk` to an existing project does
> **not** regenerate them, so `metadata.json`/icon stay frozen at the version you
> first created the project with. **Do not manually delete a project's files** —
> deleting the extracted `icon_64x64.png` leaves the app with no icon, and a
> BadgeHub app with no icon does not render in the on-badge AppStore (it stays in
> the `project-summaries` index but the card is dropped). To ship a new version
> cleanly, prefer deleting + recreating the project from the fresh `.mpk` (it
> re-extracts a matching `metadata.json` + icon), or manually re-upload both the
> icon and a corrected `metadata.json`.
>
> **Mind the icon filename — hyphen, not underscore.** Inside the `.mpk` the
> launcher icon is `icon_64x64.png` (underscore) and must stay that way. But
> BadgeHub stores the *project-level* icon as **`icon-64x64.png`** (hyphen), and
> it builds the AppStore icon URL verbatim from the `icon_map` value — so
> `metadata.json` needs `"icon_map": {"64x64": "icon-64x64.png"}`. Pointing it at
> the underscore name yields a 404 icon URL: the app lists in the AppStore with a
> broken/absent icon, yet looks fine once installed (the badge reads the icon from
> inside the package). That was
> [issue #1](https://github.com/steemandavid/fri3d-friends/issues/1).
>
> Sanity-check the live state via `https://badgehub.eu/api/v3/project-summaries`
> and `.../api/v3/projects/<slug>` — and actually fetch the advertised icon URL,
> confirming it returns **200** and not a 404 JSON body.

The logo/icon are generated by `tools/make_hybrid_logo.py`; the 42px name font is
a subset Montserrat TTF (`montserrat_name.ttf`).

## Tests

Off-device unit tests (pure wire-format / storage / setup-protocol logic, no
badge needed):

```bash
pytest tests/
```

Against a real badge in setup mode, the full GATT protocol can be exercised
headlessly with `python3 tools/setup_client.py` (needs `pip install bleak`) —
see its `--help`.

The Web-Bluetooth page (`docs/setup/`) is published via **GitHub Pages** (repo
**Settings → Pages → Deploy from branch → `main` / `/docs`**); its URL is what the
badge's QR encodes.

## License

[MIT](LICENSE) © 2026 David Steeman / Makerspace Baasrode.

## Credits

Made by **David Steeman** / **Makerspace Baasrode** for the Fri3d Camp badge.
Feedback and PRs welcome.
