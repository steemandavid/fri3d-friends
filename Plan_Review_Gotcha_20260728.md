# Review — Implementation_Plan_Gotcha_20260726.md (2026-07-28)

Full readiness review of the Gotcha plan (working-tree rev. 4, uncommitted) before
handing it to a fresh implementation session. Method: complete read of the plan,
then a claim-by-claim cross-check against the repo (`ble_proximity.py`,
`contact_exchange.py`, `ble_setup.py`, `beacon_service.py`, `fri3d_friends.py`,
`DESIGN.md`, `Code_Review_Phase5_20260715_0731.md`, `docs/setup/index.html`,
MicroPythonOS API docs) plus an internal-consistency sweep. Host test suite:
**118 passed**.

**Verdict: not yet ready to hand off.** The engineering core (BLE wire format,
kill handshake, soul crypto, radio arbitration, backend contract, phasing) is
sound, internally consistent, and its code claims are overwhelmingly accurate.
But there are four blockers — one plan-vs-plan conflict and three factual gaps a
fresh session would hit mid-implementation — plus stale sections that would
mis-scope Phase 2.

---

## Verified correct (spot-list)

Everything below was checked against the repo and is accurate as claimed:
`fnv1a_16`/`normalize_group`/`MAX_GROUPS=5`/`parse_payload` (returns
`{version, group_ids, name}`, gates on company id AND magic, drops unknown
versions), `a = 0.3` at `ble_proximity.py:521`, 60/120 ms = 50 % scan duty, the
name-budget arithmetic (31−19=12 with game block, 18 today), UUID blocks
`6e4000_1x_` (exchange) and `_2x_` (setup) leaving `_3x_` free,
`WINDOW_MS = 5000`, `SETUP_ABS_CAP_MS = 600000`, `SetupService.bind_handles()`
(`ble_setup.py:552`, invoked from `contact_exchange.py:451`),
`beacon_service.py` advertises-only (no scan, no GATT server), the
`_adopt_open`-no-timeout invulnerability (still present; consulted at
`fri3d_friends.py:1897`), `BTN_2024`/`BTN_2026_EXP`/`BTN_2024_DIAG` values and
MENU=GPIO 45 only in DIAG, buzzer pins 46/38 and the rising `_sting()`
(freq → ×3/2), all LED constants (`LED_UPDATE_MS=60`, `LED_DIM_MIN/MAX`,
`LED_BREATHE_MS=3800`, `LED_FLASH_MS=900`), `_led_override_until`/`_led_last`/
`_flash_leds`/`_led_count`/`_hsv`, `_dimmed`/`_set_brightness`/`_wake`
scaffolding, atomic `.tmp` + `os.rename` writes, review items F-4 and F-15,
`identity.auto_nickname`, `MANIFEST.JSON` at 0.9.0, DESIGN.md facts (no
`clear_flag`, `capture_screenshot` unusable, `gatts_register_services` once per
power-on, `active(False)` wipes registration, `lights.write()` disables IRQs,
−70 dBm ≈ a few metres), `DownloadManager.download_url`/`post_url` +
`TaskManager.wait_for` existence and per-request aiohttp sessions, timing/power
arithmetic (37 h, 2.3 req/s, runtime table).

---

## Blockers

### B1 — Direct conflict with `Implementation_Plan_Menu_20260728.md` (same target version)
The menu plan (agreed 2026-07-28, two days after this plan) **replaces the input
layer this plan builds on**:
- It deletes the raw-poll dispatch (`_handle_buttons`, `_edge`, long-press-B) and
  possibly the `BTN_2024*`/`BTN_2026_EXP` maps — the exact maps §8.4 says to add
  MENU to.
- §8.4's "Existing A / B / Y / START — Unchanged" is false under the menu plan:
  A opens the menu, X exits, Y/B/START lose their roles (swap, mute, editor
  become menu items).
- The menu plan records that **MENU emits an OS-special key code** on 2024
  (like START); under the new LVGL-focus-group input model it is not obvious
  MENU presses reach the app at all unless raw polling of GPIO 45 / expander
  idx 5 is deliberately retained.
- §5.7's "one button, escalating with distance" ladder, rule 15's MENU-long
  opt-out, §5.9.1's "Y is taken by the contact swap and MENU by the escalation
  ladder", and the §8.9.3 hint strings (`MENU: onthullen`) all assume the old
  model.
- Both plans target **v0.10.0**, and DESIGN.md §11a.1 already labels the shipped
  translation "the v0.10.0 translation pass". Three work streams share one
  version number, while §8.10.3 makes the version string load-bearing.

**Author's resolution (2026-07-28): DEFERRED**, then **RESOLVED the same day.**
The control-scheme rewrite shipped as **v0.10.0** (commit `5df769b`): the raw
button layer is deleted and all input rides the LVGL focus-group model (joystick
moves focus, A activates, X = `onBackPressed`), which also fixed the 2026
OS-drawer bug. The Gotcha plan was rebased onto it as **rev. 5 / D29**: the MENU
ladder became the A-action of a focusable **hunt strip** on the nametag; opt-out,
training and demo mode became rows on a Gotcha screen behind a new `Gotcha` main-
menu row (`MENU_MAX` 5 → 6); first-run consent became a Configure-me-style
mini-menu; duel screens consume X. Target version moved to **v0.11.0**
(v0.10.0 is taken). B1 closed.

### B2 — §6.2 response verification cannot be implemented with `DownloadManager`
§6.2/§9.1 put the response signature in an **`X-Sig` response header** and bind
the HTTP **STATUS** into it. But `DownloadManager.post_url()` returns **body
bytes only** (`None` on failure) and `download_url()` likewise — the badge can
read **neither response headers nor the status code**. §8.3 simultaneously
forbids hand-rolling `urequests`. As written, the badge cannot verify any
response, which §6.2 itself calls "not optional".

**Fix (forced, no user decision needed):** move signatures into a JSON envelope
in the **body** for responses — e.g. `{"sig": "<hex>", "payload": {...}}` with
`sig = HMAC(player_key, X-Ts || request-nonce || canonical(payload))` — and drop
STATUS from the signed material (an unverifiable status carries no authority
anyway; the payload is what the badge acts on). Request headers can stay as
specified (`headers=` is supported). §6.2, §9.1 and §9.2 need rewording.

### B3 — The peer table never admits the target: the group filter, and LRU pinning
`ble_proximity._process_result()` **drops any advert that shares no group**
(`if not shared: return`) before it reaches `seen`. A Gotcha target is by design
almost never in your group (D9), so under the current pipeline **the radar would
never see the target at all**. §4 says "add the game fields to the existing
`seen` entries" without mentioning this. The plan must specify:
1. The v2 parse path admits beacons carrying a game block even with no shared
   group (at minimum: your current target's pid, bounty players, and anything
   needed for the D11 alive/dead display of nearby players).
2. Widening the filter is what *creates* the unbounded-growth risk at 700
   badges, so the LRU cap lands in the same change — **and the LRU must pin the
   current target's entry** (and arguably bounty entries): with 64 slots in a
   crowd of 100+, plain lowest-`last_seen` eviction can evict the one peer the
   game is about.
3. Nit: the plan's bug note says the table grows "in an IRQ path" — stale. The
   IRQ only appends to `_pending` (bounded at 256); `_seen`, `_evict()` and
   `current_peers()` run on the loop thread via `tick()`. The concern is real
   but the description should be corrected.

### B4 — Web pages: hosting, mixed content, CORS unaddressed
§8.5 puts `docs/gotcha/index.html` and `docs/gotcha/admin/` in the repo's
`docs/` folder, which is **GitHub Pages** (per the setup page header). But:
- A page served over HTTPS **cannot fetch a plain-HTTP API** (mixed-content
  blocking) — and D21 makes the API plain HTTP. It also cannot reach a
  LAN-only backend (A2 route) from the public internet.
- Nothing specifies **CORS**, and §9.1's "session login on `/admin` over HTTPS"
  implies backend-served pages while §8.5 implies static Pages.

**Author's resolution (2026-07-28): DEFERRED** — under discussion with the
Fri3d network admin (Ward) to establish what is technically possible. Treat this
as a new blocking input alongside §14.1 A2. Phase 5 (web pages) cannot be
finalized until it resolves; Phases 0–4 are unaffected.

**Update (2026-07-28, later):** Fri3d confirms **badges will reach the
internet**, and **the game server can be given a fixed public IP.** This
supersedes most of §6.1's analysis:
- **Cloudflare Tunnel and the Tailscale discussion are moot** — with an inbound
  public IP there is no NAT problem to tunnel around. The server simply listens
  on :80 (plain HTTP, signed — D21 unchanged) and :443 (enrollment; and the web
  pages if hosting resolves that way).
- The fixed IP can ship in `config.json` defaults (`gotcha.api = http://<ip>/`,
  `gotcha.enroll = https://<ip>/v1/enroll`). Keep §6.3's two-URL + LAN-first
  fallback mechanism anyway — it costs nothing and keeps options open until
  arrival.
- B4 becomes solvable cleanly if a **DNS name** can point at the IP: the backend
  then serves the player/admin pages over Let's Encrypt HTTPS, same origin as
  the API — no CORS, no mixed content. A bare IP is not enough for
  browser-trusted TLS without extra ceremony, so the domain question is now the
  crux of B4.
- **Still to confirm with Ward:** (a) is the public IP routed to a machine
  *on site*, and does badge→server traffic stay internal if the camp uplink
  drops (this is what §14.1 A2 was really about); (b) can a DNS name / own
  domain point at the IP; (c) inbound 80 + 443 both open; (d) the IP known far
  enough in advance to ship in the `.mpk` defaults.

**Resolved (2026-07-28, Ward's reply + author): B4 is now decided.**
Ward: the IP may not be known much in advance — *"werk bij voorkeur met een DNS
met lage TTL"* — and ports 80/443 are open, *"zeker intern, maar ook extern"*.
The public IP is routed to a machine physically on site (a freshly imaged
Ubuntu laptop). Consequences:

- **The `.mpk` ships hostnames, never IPs.** Register/point a DNS name under an
  own domain (low TTL, e.g. 60–300 s) at the server; repoint the A record on
  arrival day when the camp IP is known. The HMAC scheme signs `METHOD || PATH`,
  not the host, so repointing breaks nothing.
- **B4 decision: the backend serves the player and admin pages itself** over
  HTTPS at that DNS name, same origin as the API — no CORS, no mixed content.
  `docs/gotcha/` in the repo is source only.
- **Certificates: use Let's Encrypt DNS-01, not HTTP-01.** During development
  the server sits on the author's home LAN behind a Fritz!Box that cannot
  forward external ports 80/443, and HTTP-01 requires inbound :80 specifically.
  DNS-01 issues certs regardless of reachability and keeps one workflow for
  home and camp.
- **Development networking:** externally the Fritz!Box forwards **:8066 → :80**
  and **:8446 → :443** on the game server's LAN IP. Dev badges on the same LAN
  simply use the server's LAN address on :80/:443 directly — §6.3's LAN-first +
  public-fallback mechanism covers this case as designed. Off-LAN test access
  (phones, remote checks) uses `http://<name>:8066` / `https://<name>:8446`.
- **Release checklist item:** shipped `.mpk` defaults are the camp URLs
  (`http://<name>/` and `https://<name>/v1/enroll`, implicit :80/:443); the
  :8066/:8446 dev ports must never appear in a release build.
- **§14.1 A2 is effectively answered:** server on site + ports open internally
  means badge→server traffic has an internal path. Residual (cheap, arrival-day)
  check: confirm badges still resolve the DNS name and reach the server if the
  camp uplink drops — if camp DNS forwards upstream only, consider a hosts-style
  fallback of trying the last-known IP, which the §6.3 two-URL mechanism can
  carry.
- A public plain-HTTP endpoint will be scanned by the whole internet: the HMAC
  scheme already carries integrity, but rate-limit the unsigned `/v1/enroll` by
  IP and `badge_key` (§9.2 already says so) and expect background noise in the
  logs.

---

## Major

### M1 — §8.9 describes translation work that has already shipped
Commit `fa7b644` + DESIGN.md §11a.1 record the Dutch translation of the app UI
**and** `docs/setup/index.html` (verified: the page body is Dutch; the app's
strings are largely Dutch). §8.9.4's "a real pass over ~50 user-visible strings
… `docs/setup/index.html` … currently English throughout" is stale and would
cause a fresh session to re-plan done work. Remaining reality: a handful of
English remnants in `fri3d_friends.py` (`"join my friend's group"`,
`"Skip for now"`, `"no group yet"`, `"the button does nothing"`), the hint
string `"Later instellen: hou B, of START"` (doubly stale — those buttons go
away under the menu plan), and all *new* Gotcha strings (§8.9.3/§8.9.5 remain
fully valid). Note: DESIGN.md §1 lists built-in fonts 12–28 **including 18**
(the app uses `font_montserrat_18`); §8.9.1's list omits 18 — cosmetic.

### M2 — Backend has no home
§8.5's files-touched table contains no backend files, no backend tests, and no
simulator, yet Phase 1 is "fully testable with a simulator". Stack is
"unspecified" by design, but the plan should at least fix: where the server code
lives (suggest `server/` in this repo), where its tests live, how it runs
(systemd, per §6.1), and what the Phase 1 simulator is (suggest: a pytest
fixture driving the HTTP API with N fake badges).

### M3 — `witnesses[]`: build it or drop it (undecided tension)
§9.5's anti-cheat detection #1 depends on `witnesses[]`; §13 calls it "the
strongest argument for dropping" and says drop it if not earning its keep. A
fresh session cannot resolve this. **Decision needed** (see open questions).

### M4 — Plan header/version metadata stale
Header says "rev. 2, same day"; the file is at rev. 4 (rev. 3 committed
`12aab97`, rev. 4 uncommitted in the working tree). The rev-2 note block is the
only revision history. Update the header, and note the v0.10.0 collision (B1).

### M5 — Small schema gaps
- **Heartbeat cadence unspecified** — §9.3 defines the event; nothing says when
  it is queued (presumably once per `SYNC_S`; say so).
- **`life_id`** appears once (§10.3 dedupe "`(victim_pid, life_id)`") and is
  never defined in any schema. Define it (e.g. server-side death counter per
  pid) or restate the dedupe key.
- **Enroll payload mismatch**: §6.2 lists `{badge_key, display_name, groups,
  commitment}`; §9.2 adds `app_version, board`. Align on §9.2.
- **Player-page QR** (§9.1): nothing says where the QR is rendered (on-badge
  screen? printed card?). The setup flow has an on-badge QR window precedent —
  specify.

---

## Minor / nits

1. **Battery-warning level mismatch**: §8.7 ladder starts the orange LED hint at
   20 %; §8.8.3's LED table says "Battery ≤ 10 %". Harmonize (suggest: notice at
   20 %, persistent last-LED double-blink from 10 %, and say so in both).
2. **Demo-mode drift**: §13 still says "fifteen-second walkthrough … both
   sounds"; rev. 4 updated §8.4 to "every sound … about twenty seconds".
3. **Narrative vs constants** (accepted prose rounding, but state it): "gold for
   two seconds" vs `REVEAL_FLASH_MS 2500`; "four times a second" vs 350 ms
   (~3/s); "Hold MENU … about three seconds" vs §8.4 "≥1.5 s + confirm prompt".
4. **Kill-range ping clock**: §8.8.6 says "one ping per breathe cycle, in phase
   with the light", but at kill range the strip is deliberately **steady** (no
   breathe) — state what drives the 350 ms double-tap there. Also `PING_FROM_SEG
   = 3 "of n"`: clarify scaling on the 4-LED 2024 (3 of 4 ≠ 3 of 5).
5. **Line-ref drift**: `fri3d_friends.py:1483` → now ~1497 (`WifiService.
   is_connected`), `:1454` → ~1466 (ntptime thread). Prefer symbol references
   over line numbers.
6. **`gotcha.json` example**: `dodges: {"8123": 1}` uses the same pid as the
   example *target*; dodges are keyed by *attacker* pid — pick a different
   number to avoid misreading.
7. **Phase 0 numbering**: items run 1, 2, 3, 4, 4b, 5 — renumber.
8. **Dual values, resolved here**: `DORMANT_H` — the plan argues for 12 h in
   three places while the table default says 24 h; make **12 h the normative
   default** everywhere (§2.4, §3.2, §9.6). `TARGET_STALE_H` — keep **6 h** as
   the shipped default; it is server-tunable and §2.4's "consider 4 h" is a
   Friday-afternoon retune, not a plan change.

---

## Decisions from the author (2026-07-28)

1. **Menu-plan conflict (B1): deferred.** Control scheme is being rewritten in a
   separate session; Gotcha's input bindings are provisional until it lands.
2. **Web-page hosting (B4): deferred**, pending discussion with the Fri3d
   network admin (Ward). New blocking input for Phase 5.
3. **`witnesses[]` (M3): dropped for v1.** Anti-cheat rests on the soul proof
   plus §9.5's rate and graph heuristics. Keep an optional schema slot so it can
   be added later if farming actually appears; §9.5 detection #1 and §13's
   witness bullets should be treated as removed.
4. **Backend (M2): Python / FastAPI + SQLite in a `server/` directory of this
   repo**, run under systemd (§6.1), tests in the existing pytest suite, with a
   badge-simulator fixture driving the HTTP API as the Phase 1 test harness.
