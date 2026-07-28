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
