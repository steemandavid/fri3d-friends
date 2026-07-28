# Implementation Plan — Gotcha (Assassin) game for !Fri3d Friends

**Date:** 2026-07-26 · **rev. 5, 2026-07-28** · **Status:** ready for implementation · **Target version:** v0.11.0 (v0.10.0 shipped 2026-07-28 as the joystick-navigation release)
**Camp:** **Friday 14 – Sunday 16 August 2026**, badges handed out Friday morning.
Roughly **37 hours of playable time** once the 22:00–08:00 truce is excluded (§2.4).
Everything must ship before then.

## Start here (for the implementing session)

*Rev. 5, 2026-07-28. The readiness review (`Plan_Review_Gotcha_20260728.md`) is
fully folded into this document — the review file is history and rationale, not
an override. This plan is self-contained.*

1. **Read, in order:** this preamble → "The game, in plain language" → §0 and
   the D1–D31 table → `DESIGN.md` §1, §3, §9, §10, §12 → `README.md` "Controls"
   and `changelog.md` (2026-07-28, v0.10.0) → the code
   (`app/com.fri3dcamp.fri3dfriends/`).
2. **The base app is v0.10.0** (commit `5df769b`): input is the LVGL
   focus-group model — joystick moves focus, **A** activates the focused row,
   **X** = `onBackPressed`. There is **no raw button polling** anywhere; all
   Gotcha input is specified against this model (D29, §5.7, §8.4). Use the
   existing helpers (`_make_focusable`, `_set_focus`, `_establish_focus`,
   `_release_focus`, `_bind_event`) and mind the firmware API gaps recorded in
   the changelog: `mpos.ui.add_focus_border` (not `add_focus_highlight`), and
   top-level `lv.group_remove_obj` / `lv.group_focus_obj` (the group object has
   no such methods on this build).
3. **Do not relitigate D1–D31.** Phase order is §11. Do §14.2 **A5** (the
   AppStore-update wipe test — the cheapest high-value test in this document)
   and the Phase 0 spikes first.
4. **Open inputs that do not block Phases 0–4:** register the DNS name and
   confirm the DNS host supports API-driven DNS-01 issuance (needed by Phase 5,
   §6.1); the arrival-day check that badges resolve the name with the uplink
   down (§6.1); measurements A4/A6 (§14.2); the ceremony slot (§14.4).
5. Where prose and a table disagree on a number, **the table wins**. Code
   references were verified 2026-07-28 against v0.10.0; trust symbol names over
   line numbers.

---

This plan is written to be handed to an implementer who has *not* been part of the
design conversation. It assumes familiarity with `DESIGN.md` (especially §3 BLE
protocol, §9 contact exchange, §10 BLE phone setup, §12 background beacon service)
and `README.md`. Where this plan contradicts an existing pattern, it says so
explicitly.

> **Revision 2** folds in ideas from an independent functional specification of the
> same game (*Gotcha Badge Game Functionele Specificatie v1.0*), written in parallel by
> another Fri3d participant. Adopted from it: **Reveal** (§5.7, D22), the **LED colour
> language** (§8.8, D23), **join/spawn protection** (§5.8, D24), **demo mode** (§8.4),
> the **battery warning ladder** (§8.7), **badge rebind** (§9.4), the **live dashboard
> metrics** and **multi-host admin** (§9.4), and a reworked **state model** (§9.6).
> Explicitly *not* adopted: shields (redundant with dodges), badge-off and
> flat-battery elimination (see §1.1, rule 8), and server-authoritative-only play
> (see D6). Added independently of that spec: **training mode** (§5.9, D28) and the
> **version/hotfix path** (§8.10, D27). Its **separate child/adult target chains** were considered and replaced by
> **personal quiet hours** (§10.4a, D25), which solve the same real problem without
> recording anyone's age. Its **"finale mode"** remains open and is not designed here.

> **Revision 5 (2026-07-28)** integrates the full readiness review
> (`Plan_Review_Gotcha_20260728.md`) and rebases the plan on the **v0.10.0
> joystick/focus-navigation release** (commit `5df769b`), which shipped while this
> plan was under review: all input is LVGL-focus-group driven (joystick + **A** +
> **X**), the raw button layer this plan previously extended no longer exists, and
> the base-app Dutch translation has shipped. New decisions **D29–D31** (input
> model; no `witnesses[]`; on-site server + low-TTL DNS, backend-served pages).
> Response signing moved into a body envelope (§6.2); the peer-table admission
> filter and LRU pinning specified (§4); backend fixed to FastAPI+SQLite in
> `server/` (§9); `DORMANT_H` settled at 12 h (§2.4).

**Read the next section first.** Everything after it is engineering; none of it makes
sense until you know what the game feels like to play.

---

## The game, in plain language

*No technology in this section. It describes what a player experiences, nothing else.*

You are at a three-day camp with several hundred other people wearing badges. One
morning your badge tells you: **you have a target.** It shows you their name. It does
not tell you where they are, and it never tells you who is hunting *you* — because
someone is.

Your target is almost always a stranger. That is deliberate: the game does not want to
hand you the friend sitting next to you.

### Finding them

Your badge is a radar. When your target is somewhere near, a bar on your screen starts
to fill — stronger as you get closer, fading as you drift away. It cannot point you in
a direction. It only ever tells you *warmer* or *colder*, which means finding someone
is a matter of walking around, watching the bar, and paying attention to faces.

The badge also tells you which way you are going: the ping bends upward while you are
getting closer and downward while you are losing them, so you can course-correct on the
move without stopping to look.

You do not have to stare at the screen for this. The row of lights on the front of your
badge *is* the radar: dark when there is nothing, then one blue light when your target
is somewhere around, then two, then three — quickening and turning amber as you close —
until the whole row is solid red and they are within arm's reach. You can hunt with the
screen off, in a pocket, by glancing down.

Most of the time the lights are dark and your target is somewhere else entirely on the
site. So you carry on with your day, and every so often one of them flickers blue, and
you look up.

And once you are genuinely close, the badge starts to **ping** — a short, dry sonar
note, in time with the lights. It is slow at first, one every second or so, and it
quickens and rises as you close, until it is going four times a second and the row is
solid red and the person is standing right in front of you. You can hunt by ear, badge
in your pocket, without looking at anything.

It also means the people around you can hear it. A badge pinging faster and faster in a
crowd is not a subtle object, and if your target knows the sound, they know something is
coming before they know it is you.

### Picking them out of a crowd

The radar gets you to a group of thirty people around a fire. Then it stops helping:
your badge knows your target is *here*, within a few metres, and cannot tell you which
of the thirty they are. Names are on badges, but you are not going to read thirty
badges without it being obvious what you are doing.

So you press **A**, and their badge — and only theirs — **lights up bright gold for
a couple of seconds and chirps.**

Now you know. And so do they, because it is their badge that just went off in their
hand, and they can see you looking. Revealing is not free: you have spent your surprise
to buy their location, and they get a couple of seconds' head start on deciding whether
to walk away. You can only do it every couple of minutes, so you cannot stand in a
crowd flashing people until something happens.

That is the shape of a hunt. Wander until the light goes blue, close until it goes
amber, reveal to find the face, then close the last few metres knowing they are already
watching you.

### The kill

When you are close enough — a few metres, near enough to touch them — you press
**A** again. It is the same button that revealed them; once you are near enough to
kill, that is what it does, and your badge says so before you press it.

Their badge immediately starts **screaming.** Red screen, siren, `UNDER ATTACK — RUN!`
Everyone nearby turns round. Your target now knows, with total clarity, that they are
being killed and that it is one of the people in front of them.

They have **five seconds** to get away from you. Not out of the building — just far
enough, about ten metres, and broken away. If they manage it, they have dodged, and
your badge tells you they escaped. You have to wait a minute before you can try again.

But they only get away **once.** The second time you press A on the same person,
there is no escape and no timer — their badge says **NO ESCAPE**, and they are gone. So
a dodge is a reprieve, a moment of pure adrenaline in the middle of a crowd, and not a
strategy. Nobody outruns this game.

When they die, their badge hands you **their** target, and the hunt continues without
pausing. Kill someone standing in a group of friends and you may find your next target
is standing right there. There is nothing stopping you taking all of them.

### Dying

You will be killed. Everyone is killed, repeatedly.

Your badge shows who did it and a countdown: **thirty minutes.** Then you are back,
with a new target and a clean slate. You are never out of the game, never sitting on
the sidelines for a day because your battery died at breakfast. Your total kills are
yours forever — dying never takes them away.

You come back with **ninety seconds of grace** — nobody can touch you while your badge
glows white. It exists so that dying next to the person who killed you does not mean
dying again the moment you return, and it is exactly as long as it takes to walk away.
It ends the instant you attack someone, so it is a breath, not a bunker. New players
get the same grace when they first join.

### Getting famous, and the trouble that brings

There are two things worth being good at.

**Total kills** is your permanent record — every kill you ever land, all camp.

**Your streak** is how many you have killed since you last died, and it is the
dangerous one, because your streak is **public**. Get to three and your name goes on
the **hit list** — and now *anyone* may hunt you, not just the one person assigned to
you. Including your own friends. You are worth double points to whoever gets you.

So the leaderboard is also a target list. The better you do, the more of the camp is
looking for you, and everyone can see exactly how well you are doing by glancing at
their own badge.

The obvious response — hide the badge in a tent and protect your lead — does not work.
**A streak goes stale.** Three hours after your last kill it starts bleeding away, one
point every two hours, until there is nothing left. The crown belongs to whoever is
still out there hunting, in public, right now. Your total kills are never touched by
this; only the crown is.

### Reading the room

Alive or dead is written on the front of every badge. You can glance at someone's
badge — or your own, which lists who is nearby — and know whether they are currently in
play. It is a small thing that changes how people move around each other: you learn to
check before you walk up to someone.

### Sleep, and not being a nuisance

**Nobody can be killed between 22:00 and 08:00.** Badges do not scream at night, and
sleeping costs you nothing — the streak clock stops too. The people running the game
can also call an immediate truce across the whole camp if something needs to stop.

If you go to bed earlier than that, tell your badge. You can set your own quiet hours,
from eight in the evening at the earliest, and inside them nobody can touch you. It
works both ways — you cannot hunt during your own quiet hours either — and your streak
carries on decaying, so an early night is rest rather than armour. This is how a
nine-year-old and a night-owl adult can play the same game without either of them being
woken up by it.

Some places are simply off limits by agreement, not because the badge enforces it: the
main stage during a show, the toilets and showers, a workshop while it is running, and
first aid. And nobody runs indoors, near the fire, or through a crowd. It is a game
about walking up to someone, not about sprinting.

### Groups

Whatever groups you have set on your badge — your hackerspace, your village, your
crew — score together. There are two group boards: **total kills**, which rewards
getting your people playing, and **kills per member**, which rewards a small sharp
crew. Being in several groups is fine; you count for all of them.

### If you would rather not

Open the badge menu and choose **Stoppen** — three presses, a few seconds, no phone
and no explanation needed. Rejoin the same way whenever you like — your total is
waiting for you.

---

## 0. Summary

Add an optional camp-wide game of **Assassin/Gotcha**
([rules](https://en.wikipedia.org/wiki/Assassin_(game))) to the !Fri3d Friends app.

Each enrolled player is assigned one **target**. You hunt your target physically,
using your badge as a **radar** (BLE RSSI). In a crowd you press **A** to
**reveal** — their badge flashes gold, which tells you which person they are and tells
them they have been found. Closer still, **A attacks**: the victim's badge
**screams** and they get a few seconds to **run out of range**. Kill your target and
you inherit theirs. Death is a 30-minute respawn, not an elimination.

Three tiers:

| Tier | Role | Transport |
|---|---|---|
| **Backend** (new) | Authority: roster, ring, kills, scoring, game state, anti-cheat | Signed HTTP |
| **Badge** (`gotcha.py`, new) | Radar, kill handshake, alarm, local event queue | BLE (peer↔peer) + signed HTTP (badge↔backend, §6.2) |
| **Web pages** (new, static) | Player status + leaderboards + host admin console | HTTPS |

**The badge does the physical game; the backend does the bookkeeping.** BLE is used
*only* for what it is genuinely good at — "is that specific person within a few
metres of me right now" — and never for gossiping global state.

### Design decisions already taken (do not relitigate)

| # | Decision | Rationale |
|---|---|---|
| D1 | **A real backend, not BLE gossip** | A camp site produces hot pockets, dead zones and connectivity islands. An epidemic gossip protocol demos beautifully with 3 badges and disintegrates at 700. All badges are expected on the `fri3d-badge` SSID. |
| D2 | **Enrolled ON by default**, prominent opt-out | At 700 badges a sparse player base makes the hunt boring. Consent obligations are handled in §13. |
| D3 | **Killable while the app is closed** | Otherwise "close the app" is perfect invincibility, and every kid finds that on day one. `beacon_service.py` must host the victim side of the handshake. |
| D4 | **Respawn + streak + perishable bounty** (§2) | Nobody is ever locked out; the stay-alive tension survives; leaders get hunted; hiding your badge does not preserve a lead. |
| D5 | **Kill proof = commitment–disclosure ("the soul")** | Cryptographic proof of a genuine physical handshake, using only sha256, with no key distribution to 700 badges. |
| D6 | **Offline = keep playing, queue events** | Dead zones must not become invincibility zones. |
| D7 | **Night truce 22:00–08:00 + host truce button** | Camp safety and sleep. Safe *zones* are printed rules, not code — the badge has no positioning. |
| D8 | **No backward compatibility required** | The app has not been formally released and badges are handed out on 14 Aug 2026 with the current build. This permits a clean **HSNT v2** beacon (§4) and removes the riskiest item from Phase 0. |
| D9 | **Group-aware target assignment** (§3.2) | Same-group pairs find each other trivially. Assignment avoids them where the constraint graph allows. |
| D10 | **Target inheritance rides the kill handshake** | The victim hands over its own target in the same payload as the soul, so inheritance works fully offline. |
| D11 | **Alive/dead is visible on the nametag *and* on air** (§8.4) | Deliberate social mechanic: you can check whether someone is safe to walk up to. |
| D12 | **One camp-wide game** | Simplest to run; at 700 players the scale *is* the spectacle. `game_id` stays in the schema so a second game needs no migration. |
| D13 | **Fixed 5-minute sync** | Prioritises the BLE scan, which `DESIGN.md` §3 calls load-bearing. Everything gameplay-critical already works offline. |
| D14 | **Dead players get a countdown only** | No ghost mode in v1. Revisit if playtesting shows people putting the badge down. |
| D15 | **Group scoreboard: two boards** (§2.3) | Total kills *and* mean kills per member (min 3 members), so neither big nor small groups own the format. |
| D16 | **No kill-rate cooldown** | A player who sweeps a table of six earns the story. Streak decay and the audit tools carry the anti-abuse load instead. |
| D17 | **Stalled hunts: freshness + reassign, no location hints** (§10.1) | Uses only data already collected. No AP-based or witness-graph location tracking of minors. |
| D18 | **The app manages no WiFi credentials at all** (§7) | Fri3d pre-loads the `fri3d-badge` SSID onto the badge (confirmed 2026-07-26), so `auto_connect()` handles it on boot. The app only *checks* connectivity and reports it. No credential in the repo, the `.mpk`, or any config file. |
| D19 | **Integrated into !Fri3d Friends, not a separate app** (§8.6) | One BLE stack, one adv set, one one-shot `gatts_register_services`, one IRQ. Two apps cannot share the radio, and the game block lives *inside* the HSNT beacon. Isolation is achieved with lazy imports and a hard interface instead (§8.6). |
| D20 | **Charging is assumed** (§8.7, §14.3) | The app cannot last a 16-hour waking day in any configuration, and power banks are ubiquitous at a hacker camp. Battery-aware degradation below 20 % is still built; the design does not depend on the power levers succeeding. |
| D21 | **Plain HTTP with HMAC-signed requests and responses** (§6.2) | The game needs authenticity, not secrecy — kill proofs are self-authenticating and scores are published. Certificate verification is likely off on this build, so TLS would have given encryption without authenticity. One HTTPS call at enrollment bootstraps the key; everything after is signed plain HTTP. Removes the per-sync 40 KB allocation. Deployment fit is settled by D31: the server exposes :80 and :443 directly. |
| D22 | **Reveal — the last ten metres** (§5.7) | RSSI walks you into a crowd and then stops helping. Reveal makes your target's badge flash, at the cost of telling them they have been found. Pure BLE, works offline, and it is the mechanic that stops the endgame of every hunt being "squint at thirty lanyards". |
| D23 | **The whole LED strip becomes the hunt radar; the friend LEDs are removed** (§8.8) | The badge must be readable at a glance with the screen dark — which is what makes §8.7's biggest power lever (blanking the display) survivable. A **bar** (length + colour) is legible at several metres in a way a single colour-coded dot is not. No information is lost: the friends panel and group pills still show everyone nearby. Average LED draw *falls*, because the bar is dark whenever the target is out of range. |
| D24 | **Spawn and join protection** (§5.8) | Respawning next to your killer, or joining into the middle of a scrum, should not mean dying instantly. 90 s, forfeited the moment you attack. |
| D25 | **Personal quiet hours, and no age data anywhere** (§10.4a) | Children go to bed before 22:00. The obvious fix — separate child and adult games — requires recording which badges belong to minors, and would not even deliver the safety it implies (bounties and inheritance cross cohorts). A self-serve personal truce window solves the actual problem, serves early-sleeping adults equally, and keeps **one ring, one game, no age flag, no cohort field**. |
| D26 | **All user-facing text is Dutch** (§8.9) | Fri3d Camp is a Belgian/Dutch-language event and much of the audience is children, for whom English rules text is a real barrier at exactly the moment the game needs to be understood instantly. This covers the existing app, not just Gotcha: the whole UI is translated. **ASCII-only** — the built-in lvgl fonts do not carry accented glyphs (§8.9). |
| D27 | **No OTA. Server-side hotfixes first, an AppStore nudge as the escape hatch** (§8.10) | D8's "no backward compatibility required" expires the moment badges are handed out on Friday morning; after that every change is a live migration across a population you cannot fully reach. Every tunable is already server-pushed (§5.4), so most fixes need no app update at all. Writing a self-updater for 700 badges in three weeks, with brick risk, is a bad trade. |
| D28 | **Training mode: mutual opt-in, everything real except the consequences** (§5.9) | Rule 5 gives one dodge per assassin per life, so without practice every player's first escape is also their only one. Both sides opt in HXCG-style, so reveal and dodging are both genuinely rehearsable and no covert-probe capability is created. Isolated from real state by a target *override*, a disposable soul and presentation-only death. **Exempt from truce and quiet hours** — both parties consented, social responsibility, as with rule 14. Late phase, droppable. |
| D29 | **All Gotcha input rides the v0.10.0 focus-navigation model** (§5.7, §8.4) | v0.10.0 (shipped 2026-07-28) deleted raw button polling and moved the app to LVGL focus-group navigation: joystick + **A** (activate) + **X** (back via `onBackPressed`). The hunt is a focusable **hunt strip** whose A-action escalates with proximity; everything else is menu rows. No new input mechanisms, no raw pins, no chords. |
| D30 | **No `witnesses[]` in v1** (§9.5, §13) | It was the only telemetry field whose plaintext exposure (D21) revealed anything the game does not already publish, and the soul proof plus rate/graph heuristics carry anti-cheat without it. The event schema tolerates the key, so it can be revived by an app update if farming actually appears. |
| D31 | **On-site server behind a fixed public IP, addressed by a low-TTL DNS name; the backend serves the web pages** (§6.1, §9.1) | Fri3d routes a public IP to the game laptop on site; the IP is not known in advance, so the `.mpk` ships **hostnames only** and the A record is repointed on arrival (Ward, 2026-07-28: *"werk bij voorkeur met een DNS met lage TTL"*; ports 80/443 open internally and externally). Pages are served by the backend over Let's Encrypt HTTPS (**DNS-01**), same origin as the API — no CORS, no mixed content. Tunnels (Cloudflare/Tailscale) are moot. |

---

## 1. Rules of the game (player-facing)

These are the rules as they should appear on the rules card and the web page.
Everything here is enforced by the backend unless marked *social*.

1. **You have one target.** Your badge shows their name and how close they are. It
   never tells you who is hunting *you*. Your target is **almost never** someone from
   one of your own groups.
2. **To find them in a crowd — Reveal.** When your target is near but you cannot tell
   *which* person they are, press **A**: their badge flashes gold and chirps for
   two seconds. It also tells them they have been found. One reveal every **2
   minutes**, and none during a truce.
3. **To kill:** get within a few metres of your target and press **A** again. Hold
   the proximity for **5 seconds**. Their badge will scream — that is the point.
4. **To survive:** if your badge screams, **run.** Break line of sight and get
   ~10 metres away within 5 seconds and you have dodged. *No running indoors, near
   the stage, near the fire, or in food queues.* (social)
5. **You cannot dodge forever.** After **1 successful dodge from the same
   assassin**, their next attack lands **instantly**. Dodge counters reset an hour
   after that assassin last attacked you.
6. **Attack cooldown:** an assassin must wait **60 seconds** between attempts on the
   same victim.
7. **When you kill, you inherit** your victim's target and keep going. There is no
   cooldown — if you can take a whole table, take a whole table.
8. **When you die**, you are out for **30 minutes**, then you respawn with a new
   target and a **streak of zero**. Your total kills are never lost. You return with
   **90 seconds of protection** — you cannot be attacked, your badge glows white, and
   it ends the moment you attack someone. New players get the same grace when they
   join.
9. **Four leaderboards:** individual *Total kills* and *Longest streak*; group
   *Total kills* and *Kills per member*.
10. **Bounties:** anyone on a live streak of **3 or more** is fair game for
    **everybody**, not just their assigned hunter — including people from their own
    group. Their name and streak are on the public hit list. Bounty kills score double.
11. **Streaks perish.** Your streak holds for **3 hours** after your last kill, then
    decays by **1 every 2 hours** until it reaches zero. Hiding your badge in a tent does
    not protect a lead — it forfeits it. (Total kills never decay.)
12. **Night truce: no kills between 22:00 and 08:00.** Truce hours are excluded from
    the streak-decay clock, so sleeping costs you nothing. The game host can call a
    camp-wide truce at any other time.
13. **Your own quiet hours.** If you go to bed earlier than the camp does, set your own
    window on your badge — from 20:00 at the earliest, until 10:00 at the latest. Inside
    it nobody can attack or reveal you. **You also cannot attack or reveal anyone**, and
    **your streak still decays** outside the camp truce — going to bed early is rest,
    not a shield. Anyone's badge shows they are asleep rather than refusing mysteriously.
14. **Safe zones (social):** main stage during shows, toilets and showers, workshop
    tents while a workshop is running, and first aid. Not enforced by the badge —
    enforced by not being a jerk. **Training (§5.9) is exempt from the truce** because
    you both agreed to it — so at night, practise away from the tents and mute your badge.
15. **Opting out:** open the badge menu → **Gotcha** → **Stoppen met Gotcha**, or use
    the web page. A few seconds, no phone needed. You can rejoin the same way later;
    your total is preserved.

**What the lights mean** (§8.8) — the whole LED strip is the radar, readable with the
screen off. *Rules-card wording is Dutch (§8.9); English gloss in italics.*

| Lampjes | Betekenis |
|---|---|
| uit | *dark* — doelwit niet in de buurt |
| **1 blauw**, traag | *1 blue, slow* — doelwit ergens in de buurt |
| **2–3 blauw/oranje**, sneller | *2–3 blue/amber, quickening* — je komt dichterbij |
| **bijna vol, oranje** | *nearly full, amber* — heel dichtbij: nu onthullen |
| **alles rood, vast** | *all red, steady* — aanvalsafstand: nu aanvallen |
| **alles goud + piep** | *all gold + chirp* — jij bent zojuist onthuld |
| **alles rood** (met sirene) | *all red + siren* — je wordt aangevallen: rennen |
| **alles groen** | *all green* — je hebt hem te pakken |
| **rood, trage puls** | *red, slow pulse* — je bent uit, wacht op herstart |
| **alles wit** | *all white* — beschermd (net herstart of net begonnen) |
| laatste lampje oranje | *last LED orange* — batterij bijna leeg |

### 1.1 Why these rules

- **Rule 2 (Reveal) answers "which of these thirty people is Otter 42?"** RSSI is a
  scalar: it walks you to within a few metres and then goes flat, and the last ten
  metres are the part the radar cannot do. Without Reveal the endgame of every hunt is
  squinting at lanyards, which is slow, conspicuous and faintly creepy. **The cost is
  what makes it a mechanic rather than a cheat:** revealing hands your target the
  single piece of information they most want — that they are being hunted, right now,
  by someone standing near them. That cost is self-limiting, so the cooldown is a
  backstop against crowd-spamming rather than the primary brake.
- **Rule 8's protection window answers spawn-camping.** You die where you were killed,
  and 30 minutes later you reappear in the same place, quite possibly next to the
  person who did it — who, if you were on a streak, may have friends waiting. Ninety
  seconds is enough to walk away and not enough to do anything with. Forfeiting it on
  attack is what stops it becoming a free first strike.
- **Rule 11 answers "just hide your badge."** A raw bounty on the leader creates an
  obvious dominant strategy: get a streak, then put the badge in a locker until
  Sunday. Making the streak perishable inverts that — the only way to *stay* on the
  crown is to keep hunting, in public, where bounty hunters can reach you. Decay is
  computed **server-side on wall-clock time**, so a powered-off badge decays fastest
  of all: it cannot even dodge.
- **Rule 5 answers "run away forever."** Without it a fast player is invulnerable.
  One dodge is a **single reprieve, not a chase**: escape once and your assassin's
  next attempt lands regardless of how fast you are. Combined with the 60 s attack
  cooldown, an encounter resolves in about a minute rather than dragging on. The 1 h
  `DODGE_DECAY_MS` reset matters more at this setting than it would at three — it is
  what stops a single unlucky encounter from marking you as un-dodgeable by that
  assassin for the rest of the camp.
- **Rule 8 (respawn, not elimination)** answers a three-day camp: eliminating a
  9-year-old at 09:30 on Friday because their badge battery died would put them out
  for a third of the entire event, for a reason that is not their fault. That is not a
  game, it is a punishment for logistics.
- **Rule 1 says "almost never" on purpose.** Group exclusion is a *preference the
  assignment tries to satisfy*, not an invariant. Three paths legitimately produce a
  same-group pair: an unsatisfiable constraint graph (§3.2 step 4 — the game must
  still start), inheritance after a kill (§3.2), and bounty kills, which are open to
  everyone including your own group (rule 10). Promising "never" in the rules would be
  a promise the system does not keep.
- **Rule 1's group exclusion has a cost — read §3.3.** It makes almost every target a
  stranger, which is thematically right but makes targets *harder to find*. The
  freshness/reassign machinery in §10.1 is what makes it survivable, not optional
  polish.

---

## 2. Scoring model

### 2.1 Individual

| Quantity | Decays? | Notes |
|---|---|---|
| `total_kills` | No | Permanent record. Board 1. |
| `streak` | **Yes** (rule 11) | Kills since last death. Board 2 ranks `best_streak` (high-water mark, never decays); the *live* `streak` carries the bounty. |
| `deaths` | No | Displayed, not ranked. |

**Points per kill:**

| Situation | Score |
|---|---|
| Your assigned target | 1 |
| A bounty player (live streak ≥ 3) who is not your target | 2 |
| Repeat kill of the same victim within 6 h | **0** (anti-farming; still counts as a death for the victim) |
| Any kill during a truce | **rejected** — the handshake never completes |

`best_streak = max(best_streak, streak)` on every kill. Decay lowers `streak` only;
it never touches `best_streak` or `total_kills`.

### 2.2 Streak decay (server-side, idempotent)

```
active_seconds = wall_seconds_since(last_kill_at) minus overlapping CAMP truce intervals
                 # camp-wide only: the 22:00-08:00 window and host-called truces.
                 # Personal quiet hours (§10.4a) are NOT excluded -- see the note below.
if active_seconds > STREAK_GRACE_S (default 3 h):
    decayed = floor((active_seconds - STREAK_GRACE_S) / STREAK_DECAY_S)   # default 2 h
    streak  = max(0, streak_at_last_kill - decayed)
```

Deriving from `last_kill_at` rather than mutating a counter makes it idempotent and
correct regardless of when the timer actually runs — important, because the backend
may be unreachable for hours (§6).

> ⚠️ **Only the camp-wide truce pauses decay — never a player's personal quiet hours.**
> If personal windows paused the clock, a player could declare quiet hours from 20:00
> to 10:00, become both unkillable and undecaying for fourteen hours a day, and hold
> the crown by sleeping. Rule 11's whole purpose is that hiding forfeits a lead, and a
> personal truce is a form of hiding. **Going to bed at 20:00 is rest, and it costs you
> two hours of streak decay.** See §10.4a for the rest of the abuse analysis.

### 2.3 Group scoreboard (D15)

Groups come from the **existing** `groups` config key — the same list already used
for the nametag pills and proximity matching, normalised with
`ble_proximity.normalize_group()` and identified by `fnv1a_16()`. Players may be in
up to `MAX_GROUPS = 5`. Group membership is uploaded at enrollment and on change.

| Board | Metric | Guard |
|---|---|---|
| **Group total** | Σ member `total_kills` | none — rewards recruiting |
| **Group per-member** | Σ member `total_kills` / member count | **minimum 3 members** to appear |

Rules:
- A player in 5 groups contributes their kills to **all 5** totals. This is
  deliberate: groups overlap in real life and the boards are for bragging, not for
  awarding a prize per capita.
- **Membership is snapshotted at kill time.** A kill is attributed to the groups the
  player held when the kill happened, so joining the winning group on Saturday night
  does not retroactively claim Friday's kills.
- Membership for the *member count* denominator is the **current** roster, so a group
  that inflates its membership dilutes its own per-member average. That is the
  anti-stuffing mechanism, and it needs no lock-in date.
- **Unverified by design.** Anyone can type any group name. Treat the group boards as
  entertainment, not as an award with a trophy attached, and say so on the page.

### 2.4 Timing against a three-day camp

The game is short. Excluding the 22:00–08:00 truce, the whole event is about
**37 hours of playable time**:

| Day | Playable |
|---|---|
| Friday (badges handed out in the morning) | ~14 h |
| Saturday | ~14 h |
| Sunday (ends late afternoon) | ~9 h |
| **Total** | **~37 h** |

Every duration constant should be read against that budget, not against a vague
"multi-day event":

| Constant | Value | Share of the game | Verdict |
|---|---|---|---|
| `RESPAWN_S` | 30 min | 1.4 % | Fine — a real cost, never a write-off. |
| `STREAK_GRACE_S` | 3 h | 8 % | Fine. A leader must produce roughly every three hours to hold the crown. |
| `STREAK_DECAY_S` | 2 h | — | A streak of 7 survives 3 + 14 = **17 playable hours**, about half the camp. Deliberate: the crown should be losable but not evaporate overnight. |
| `TARGET_STALE_H` | 6 h | 16 % | Acceptable, but consider 4 h — six hours of hunting a ghost is a big slice of a 37-hour game. |
| `DORMANT_H` | **12 h** (settled at rev. 5; was 24 h) | 32 % | At 24 h a badge switched off on Friday night would not be spliced out of the ring until Sunday, stranding its hunter for most of the event. 12 h splices it out within an evening-plus-night while surviving any realistic charging break. |

`TARGET_STALE_H` stays 6 h for v1. All of these are server-pushed (§5.4), so they
can be retuned on Friday afternoon once real behaviour is visible.

---

## 3. Identity, targeting and proof

### 3.1 Player identity

- `pid` — **u24, assigned by the backend** at enrollment (16.7 M ids; 3 bytes on the
  wire). The backend owns the space so it can revoke and re-issue.
- `badge_key` — the badge's stable BLE public MAC (`ble.config("mac")`, already the
  peer-table key, `DESIGN.md` §3). Used **only** to recognise a returning badge at
  enrollment. Never sent on air as the game id — that would leak the MAC in a form
  trivially correlated with the HSNT beacon.
- `display_name` — the app's existing name (config `name`, or the `identity.py`
  auto-nickname). Two players with the same name are disambiguated in the UI by a
  `#pid` suffix.

### 3.2 The ring

The backend maintains a **single global ring** over alive, non-dormant players.

**Initial assignment (group-aware, D9).** This is a Hamiltonian cycle on the graph
whose edges are pairs *not* sharing a group. At camp scale that graph is extremely
dense — groups are tens of people out of hundreds — so a randomised construction with
local repair converges immediately:

```
1. players := shuffle(all enrolled)
2. arrange as a ring: players[i].target = players[i+1], last -> first
3. repeat up to MAX_REPAIR_PASSES (default 20):
       V := [i for i in ring if shares_group(players[i], players[i].target)]
       if V is empty: done
       for each i in V:
           pick random j not in {i-1, i, i+1}
           if swapping players[i+1] and players[j+1] removes a conflict
              without creating a new one: swap them
4. if conflicts remain: assign them anyway, log a warning, and surface the count
   on the admin page.
```

Step 4 matters: if half the camp declares one group, the constraint is genuinely
unsatisfiable and the game must still start. **Never let the constraint block a game
from starting.**

**Maintenance:**

| Event | Ring action |
|---|---|
| New enrollment mid-game | Splice in: pick random alive `P`; `new.target = P.target; P.target = new`. Retry up to 10 picks for a non-group-conflicting `P`. Joins `protected` (§5.8). |
| Kill | `assassin.target = victim.target` (classic inheritance). If that creates a group conflict, try **one** re-splice; otherwise accept it and log. If it yields the assassin themselves, or a dead player, walk forward to the next alive player. |
| Respawn | Splice in by the same rule, with `SPAWN_PROTECT_S` protection (§5.8). |
| Opt-out | Splice out immediately; the hunter is reassigned on their next sync. |
| Target unseen by anyone for `TARGET_STALE_H` (6 h) | Splice out, hunter reassigned. Score preserved; spliced back on return. |
| No sync for `DORMANT_H` (12 h, truce hours excluded) | Splice out as dormant (§2.4). |
| Ring down to 2 | They hunt each other. Fine. |
| Ring down to 1 | `target = null`, badge shows "waiting for players". |

Badges never compute the ring; it only has to be self-consistent server-side.

### 3.3 The cost of group exclusion

Preferring non-same-group pairs means your target is, in the overwhelming majority of
cases, someone you do not already hang around with (the exceptions are enumerated in
§1.1). That is the point — but it directly increases the chance
that you and your target simply never occupy the same field. Combined with D16 (no
kill cooldown, so sweeps are legal), the game's failure mode is not "too fast", it is
**"I wandered for four hours and never found anyone."** The mitigations are §10.1
(freshness display + 6 h reassign) and the bounty layer, which always gives you
*someone* killable nearby. Treat "median time-to-first-kill" as the metric to watch
in the Phase 6 soak test.

### 3.4 Kill proof — commitment and disclosure ("the soul")

> **Naming.** This was called "commitment–reveal" in rev. 1, after the standard
> cryptographic term. Since rev. 2 added a **Reveal** *game mechanic* (§5.7) that has
> nothing to do with it, this document says **disclosure** for the crypto and
> **Reveal** for the gold flash. Do not mix them up in code either:
> `disclose_soul()`, not `reveal_soul()`.

The problem: an assassin could simply POST "I killed Otter 42" from a tent. We need
proof that two badges were physically within a few metres of each other.

1. On enrollment **and on every respawn**, the badge generates a fresh 16-byte random
   secret — the **soul** (`os.urandom(16)`).
2. It uploads only `commitment = sha256(soul)`. **The backend never learns the soul.**
3. The badge releases the soul **only** over a completed kill handshake (§5).
4. The assassin reports `{victim_pid, soul}`. The backend accepts iff
   `sha256(soul) == victim.commitment` **for the victim's current life**.

Properties:
- Holding the preimage means you got it from the victim's badge over a BLE link at
  close range. Verifiable with nothing but sha256.
- **No key distribution.** Nothing secret ever has to reach 700 badges.
- A fresh soul per life binds each proof to one specific death; a replayed soul fails
  because the commitment has rotated.
- The badge receives its **target's commitment** in the sync response, so it can
  verify a disclosed soul **locally and offline** before believing a kill.

**What it does not stop** (documented honestly):
- **Collusion.** Handing a friend your soul is *giving away your own life*, and it is
  visible on the audit page (all kills mutual, nothing else).
- **Sybil farming.** See §9.3.
- **Sniffing.** The soul crosses an unencrypted GATT link; an attacker would have to
  be metres away at the exact moment of someone else's kill. Accepted — and the
  hacker crowd will consider it a feature. Put it in the rules.

---

## 4. BLE wire format — HSNT v2

D8 removes the need for backward compatibility, so there is **one beacon**, not two
time-multiplexed ones. This deletes the riskiest item from the original Phase 0
(re-setting `adv_data` twice a second on this NimBLE build was unproven).

```
[AD len][0xFF][0xFFFF][ "HSNT" ][ver=2][blocks][gcount][gid_le × G][namelen][name_utf8]
                                                                              └─ optional game block, appended ─┐
                                       [pid_le(3)][gflags(1)][streak(1)]  ←────────────────────────────────────┘
```

- `ver = 2`. Receivers **drop unknown versions** (unchanged rule).
- `blocks` — new bitmask byte. **bit0 = a game block is appended after the name.**
  Bits 1–7 reserved, must be 0. When no game is running the bit is clear and the
  name budget is **exactly what it is today** — the game costs nothing when idle.
- Game block = `pid` (3 B) + `gflags` (1 B) + `streak` (1 B) = **5 bytes**.
- `gflags`: bit0 `ALIVE`, bit1 `UNDER_ATTACK`, bit2 `BOUNTY` (streak ≥ 3), bit3
  `TRUCE`, bit4 `PROTECTED` (§5.8), bit5 `SEEKING_TRAINING` (§5.9.1, set only during a
  ~10 s rendezvous window), bits 6–7 reserved.
- `PROTECTED` is on air deliberately: a hunter's badge can then say
  *"Otter 42 — protected, 43 s"* instead of offering an attack that will be refused,
  and the white protection LED on the victim's badge has a matching signal on the
  attacker's screen. It costs nothing — the byte already exists.
- `streak` u8, saturating at 255 — lets a nearby badge render "BOUNTY: streak 7"
  and the alive/dead chip (D11) with no backend round-trip.

**Name budget:** `OVERHEAD` grows by 1 (the `blocks` byte) plus 5 when the game block
is present. With one group that is 31 − 19 = **12 bytes of name during a game**,
versus 18 today. Update `name_budget()` to take the block presence into account and
update the truncation tests. Long names already scroll (`DESIGN.md` §11a), so the
visible cost is on the *beacon* name others see, not the nametag.

**Parsing:** extend `parse_payload` to return `game` (dict or `None`) alongside
`version`/`group_ids`/`name`. Keep gating on **company id AND magic** (review item
F-15). Keep it defensive and non-raising. All of this is pure and host-testable.

**Peer table:** the existing scanner already delivers every advert. Add the game
fields to the existing `seen` entries rather than opening a second scanner or a
second table — one scan, one IRQ, no new radio contention. **But the admission
filter must widen:** today `_process_result()` drops any advert that shares no
group *before* it reaches `_seen` — and a Gotcha target is by design almost never
in your group (D9), so without this change **the radar never sees the target at
all**. During a live game, additionally admit beacons carrying a game block when
they are (a) your current target's `pid`, (b) a bounty player, or (c) wanted for
the D11 alive/dead display of nearby players. Game-block-admitted peers get the
same entry shape plus the game fields; the friend-matching logic is unchanged.

> 🐛 **Pre-existing weakness the widened filter will expose.** `BLEProximity`'s
> `_seen` table has **no size cap**. Today the shared-group filter keeps it small
> by accident; once game-block peers are admitted, 700 badges mean unbounded RAM
> growth plus ever-lengthening `_evict`/`current_peers` loops. (These run on the
> loop thread via `tick()` — the IRQ itself only appends to the bounded
> `_pending` queue — so this is a memory/latency problem, not an IRQ one.)
> **Cap it with an LRU — suggest 64 entries, evict lowest `last_seen` — and pin
> the current target's entry (and bounty entries) so a dense crowd can never
> evict the one peer the game is about.** The cap is worth having regardless of
> Gotcha.

---

## 5. The kill handshake

### 5.1 Rendezvous

Do **not** reuse the `HXCG` overlapping-window rendezvous from the contact swap. A
kill is deliberately **one-sided** — the victim must not have to press anything. The
assassin already knows the target's `pid` and sees its advert, so it connects directly.

### 5.2 GATT service

**Critical constraint:** NimBLE accepts `gatts_register_services` **once per
power-on** (`DESIGN.md` §10). The Gotcha characteristics **must** be built and
registered in the same `ContactExchange._ensure_services()` call as the exchange and
setup services, with handles handed over via a `bind_handles()` method — exactly the
pattern `SetupService.bind_handles()` already uses.

```
GOTCHA_SVC   6e400030-b5a3-f393-e0a9-e50e24dcca9e
  ATTACK     6e400031-…   WRITE        attacker -> victim
  DUEL       6e400032-…   READ+NOTIFY  victim -> attacker: live duel state
  SPOILS     6e400033-…   READ         victim -> attacker: soul + inherited target
  REVEAL     6e400034-…   WRITE        hunter  -> target: "light yourself up" (§5.7)
```

`ATTACK` payload: `{g, a_pid, v_pid, as: "target"|"bounty", nonce}`
`SPOILS` payload: `{soul: hex, tgt: {pid, name, commitment}}` — **D10: the inherited
target rides the handshake**, so inheritance works with no network at all.

### 5.3 Flow

```
ASSASSIN                                  VICTIM
--------                                  ------
target in peer table, rssi_ewma >= KILL_RSSI
press A on the hunt strip
  gap_connect(victim addr)
  write ATTACK{...}                    ->  validate: game running, not truce,
                                           v_pid == me, alive, not already duelling,
                                           cooldown elapsed for a_pid,
                                           if as=="bounty": my streak >= BOUNTY_STREAK
                                       <-  NOTIFY DUEL{ENGAGED, hold_ms, dodges_left}
  show "ATTACKING <name>" + hold bar       *** ALARM *** siren + red LEDs +
                                           full-screen "UNDER ATTACK — RUN!"
  ... both sides sample RSSI every 100 ms ...
                                           if dodges_left == 0:
                                               hold_ms = INSTANT_KILL_MS
                                               RSSI escape disabled
  (a) escape:                              rssi < FLEE_RSSI for FLEE_MS
                                           OR link drops before hold elapses
                                       <-  NOTIFY DUEL{DODGED}
      queue "dodge"; start cooldown         dodges_left -= 1; queue "dodged"
                                           "YOU GOT AWAY!" + relief chime
  (b) hold completes:                  <-  NOTIFY DUEL{KILLED}
      read SPOILS                      <-  {soul, tgt}
      verify sha256(soul) == commitment      mark dead, rotate soul + commitment,
      adopt tgt as new target (offline!)     queue "killed_by", show death screen
      queue "kill"; "GOTCHA!"                + respawn countdown
```

### 5.4 Tunables (all server-pushed via `/v1/sync`)

| Constant | Default | Meaning |
|---|---|---|
| `KILL_RSSI` | −65 dBm | Arm's length. `DESIGN.md` §5.1 puts −70 at "a few metres". |
| `KILL_HOLD_MS` | 5000 | Sustained proximity required. |
| `FLEE_RSSI` | −78 dBm | Escape threshold (hysteresis vs `KILL_RSSI`). |
| `FLEE_MS` | 1500 | Time below `FLEE_RSSI` that counts as escaped. |
| `REVEAL_RSSI` | −80 dBm | Must be at least this close to reveal (§5.7). Deliberately looser than `KILL_RSSI` — reveal is the approach, not the strike. |
| `REVEAL_COOLDOWN_S` | 120 | Per hunter, not per target. Backstop against crowd-spamming. |
| `REVEAL_FLASH_MS` | 2500 | How long the target's badge flashes gold. |
| `PING_ENABLED` | true | Server-side kill switch for the hunt ping (§8.8.6). |
| `PING_FROM_SEG` | 3 | First radar-bar segment at which sound starts; below this the bar is silent. Compared against the shared RSSI→fraction mapping (§8.8.2), not a raw LED index, so it means the same proximity on the 4-LED 2024 and the 5-LED 2026. |
| `PING_MS` | 40 | Length of one ping burst. |
| `PING_FREQ_FAR` / `PING_FREQ_NEAR` | 1400 / 2400 Hz | Base pitch at `PING_FROM_SEG` and at kill range. |
| `PING_INTERVAL_NEAR` | 350 | Ping interval at kill range; wider intervals track the LED breathe period. |
| `PING_BEND_PCT` | 12 % | How far a ping bends up/down to signal the trend (§8.8.2a). |
| `TREND_ALPHA_FAST` | 0.30 | Fast RSSI EWMA — today's hardcoded `a` in `ble_proximity.py`, now named and tunable. |
| `TREND_ALPHA_SLOW` | 0.06 | Slow EWMA; `fast − slow` is the trend. |
| `TREND_DEADBAND_DB` | 1.5 | Below this, report "steady" — without it the arrow and pitch flap while standing still. |
| `DODGE_LIMIT` | 1 | Dodges per (attacker, victim) pair per life. One reprieve, then the next attempt lands. |
| `DODGE_DECAY_MS` | 3600000 | Dodge counter reset after 1 h with no attack from that attacker. |
| `INSTANT_KILL_MS` | 1000 | Hold time once `dodges_left == 0`. |
| `ATTACK_COOLDOWN_MS` | 60000 | Between attempts on the same victim. |
| `RESPAWN_S` | 1800 | 30 minutes. |
| `SPAWN_PROTECT_S` | 90 | Un-attackable after a respawn or a first join (§5.8). Forfeited on attacking. |
| `BOUNTY_STREAK` | 3 | Streak at which you become fair game for everyone. |
| `STREAK_GRACE_S` | 10800 | 3 h before decay starts. |
| `STREAK_DECAY_S` | 7200 | −1 streak every 2 h thereafter. |
| `QUIET_EARLIEST` | 20:00 | Earliest a personal quiet window may start (§10.4a). |
| `QUIET_LATEST` | 10:00 | Latest a personal quiet window may end. |
| `TRAINING_WINDOW_S` | 10 | Rendezvous window; both players must opt in within it (§5.9.1). |
| `TRAINING_SESSION_S` | 300 | Maximum length of a training session. |
| `TRAINING_REENTRY_S` | 600 | Cooldown before the same badge may train again. |
| `SYNC_S` | 300 | D13. Jittered ±20% (§10.3). |

Retuning `KILL_RSSI` and `KILL_HOLD_MS` **live from the admin page** is worth a lot:
RSSI at a real camp will not behave like RSSI on a bench, and you will want to adjust
on Friday afternoon without reflashing 700 badges.

### 5.5 Radio arbitration

Gotcha is a fourth consumer of a radio with **one adv set, one connection slot, one
IRQ handler**. Extending `DESIGN.md` §9/§10:

- **Hunter side.** A kill handshake **or a reveal** (§5.7) **cannot** start while
  `_exchanging` (contact swap), while a setup session/window is open, or while an adopt
  prompt is up. The hunt strip's A-action is ignored with a brief "busy" toast. This is
  input arbitration and costs only the hunter, so it can stay broad. (v0.10.0's
  `_open_menu` already suppresses on this exact list — extend that guard with "duel
  live" rather than inventing a parallel one.)
- ⚠️ **Victim side: gate on "a GATT connection is actually live", never on "a window is
  open."** The two are not the same, and conflating them is an invulnerability exploit:

  | State | Can an attack be served? |
  |---|---|
  | Y-swap in flight (`WINDOW_MS` = 5 s) | **No** — a link is genuinely up. True hardware necessity, and 5 s is not exploitable. |
  | Setup window open, **phone connected** | **No** — the single connection slot is taken. Necessity, for as long as the phone actually talks. |
  | Setup window open, **nobody connected** | **Yes.** The slot is free. Refusing here is policy, and it hands out up to `SETUP_ABS_CAP_MS` of invulnerability for nothing. |
  | **Adopt prompt up** | **Yes.** It is a local lvgl overlay that touches no radio at all. |

  > 🐛 **The adopt prompt is the worst invulnerability in the app today, and it is
  > reachable by accident.** `_adopt_open` still has **no timeout** in v0.10.0 (X
  > can now dismiss it via `onBackPressed`, but an unattended badge sits on it
  > indefinitely) — swap with someone, get the "join their group?" panel, never
  > answer, and you are un-attackable with no phone and no setup session. Two
  > fixes, both worth doing regardless of Gotcha: **(a)** the responder must not
  > consult `_adopt_open` at all, and **(b)** the prompt gets a **30 s
  > auto-dismiss** that declines without joining (the groups are re-offered on the
  > next swap). An unbounded modal is a bug on its own terms.
- Y-swap and the setup window are **refused while a duel is live**.
- **You cannot be attacked while you are attacking.** The single connection slot makes
  simultaneous client+server roles impractical here; the responder answers `BUSY`.
  This loses some drama ("killed mid-kill") and is a deliberate simplicity trade.
- The main loop already pauses periodic work during a swap, because a WS2812
  `lights.write()` disables interrupts and starves a short GATT link (field bug 2,
  `DESIGN.md` §9). **The duel needs the same treatment — except the alarm**, which is
  the entire point of the mechanic. Implement the alarm as buzzer PWM (does not
  disable IRQs) plus **one** LED write at duel start and one at duel end. Do not
  animate LEDs during a duel.
- On app exit, cancel any duel task through a `finally` that re-raises
  `CancelledError`, as `run_window` does (review item F-4).

### 5.6 Background participation (D3)

`beacon_service.py` today only advertises; it never scans and never serves GATT. It
must additionally:

- advertise the HSNT v2 beacon **with the game block**,
- bring up the GATT server and accept `ATTACK` writes,
- run the **victim half only** — alarm (buzzer + LEDs, no UI), hold timer, dodge
  accounting, soul release, target handover, **the reveal flash + chirp (§5.7)** and
  **protection state (§5.8)**,
- queue events and sync on the same cadence.

It must **not** scan and **not** attack: hunting requires the app to be open.

Structure `gotcha.py` so the victim-side responder is a class with **no lvgl and no
Activity dependency**, constructed by both `fri3d_friends.py` and `beacon_service.py`,
with UI delivered through injected callbacks (`on_attack_begin`, `on_duel_end`, …)
that the service implements with buzzer/LED only.

> ⚠️ The service taking the radio means it now calls `ensure_radio()` and registers
> services. App and service never run simultaneously (the service backs off when the
> Activity is on `screen_stack` — `DESIGN.md` §12), and `active(False)` wipes the
> registration, so each owner re-registers on taking the radio; `ensure_radio()`'s
> write-probe self-heal already covers stale handles. **This is the single most
> fragile area of the feature — budget real hardware time.**

### 5.7 Reveal — the last ten metres (D22)

**The problem Reveal exists to solve.** RSSI is a scalar. It gets you from "somewhere
on site" to "within a few metres" and then it goes flat: standing in a group of thirty
people around a fire, `rssi_ewma` says your target is *here* and cannot say *which
one*. Names are on the badges, but reading thirty chest-height screens is slow,
conspicuous, and not a thing anyone should be doing at a camp with children at it.

**The mechanic.** With your target inside `REVEAL_RSSI`, press **A**: their badge
flashes **bright gold on every LED for `REVEAL_FLASH_MS` and chirps**, and shows
`SPOTTED — someone has found you`. You see which badge lit up. They see that they have
been found.

**Why it is balanced without much tuning.** The cost is paid in the same instant as the
benefit: you buy their location by handing them the one fact they most want, which is
that a hunter is standing within a few metres of them *right now*. A cautious player
reveals once, at the right moment; a spammer just warns the whole field.
`REVEAL_COOLDOWN_S` is a backstop against crowd-spamming, not the primary brake.

**Transport: GATT write, not a beacon flag.** The obvious cheap implementation — set a
"revealing pid X" field in your own advert and let X's badge notice while scanning — is
wrong here, because **the victim side must work with the app closed** (D3), and
`beacon_service.py` advertises but deliberately does not scan (§5.6). A connectionless
reveal would therefore silently fail against exactly the players who are hardest to
find. Reveal uses the same short GATT connection as the attack, so the background
responder answers it for free.

```
HUNTER                                    TARGET
------                                    ------
target in peer table, rssi_ewma >= REVEAL_RSSI
cooldown elapsed
press A on the hunt strip
  gap_connect(target addr)
  write REVEAL{g, h_pid, t_pid, nonce}  ->  validate: game running, not truce,
                                            t_pid == me, alive
                                        <-  (ack, then disconnect)
  "REVEALING — look for the gold badge"     *** GOLD FLASH, all LEDs ***
  start REVEAL_COOLDOWN_S                   + chirp + "SPOTTED" screen
  queue "reveal"                            queue "revealed"
```

**Rules and arbitration:**

- **Suppressed during a truce**, unconditionally and on both sides — a badge flashing
  and chirping in a tent at 03:00 is precisely the nuisance §10.4 exists to prevent.
- Subject to the same radio arbitration as an attack (§5.5): no reveal while
  `_exchanging`, while a setup window is open, or while either party is in a duel. The
  responder answers `BUSY`.
- **Works fully offline.** No backend involvement; the hunter already holds the
  target's `pid` and sees its advert.
- Legal against **bounty players** as well as your assigned target, on the same terms.
- Legal against a **protected** player (§5.8) — knowing where someone is does them no
  harm, and it is often *how* you decide to wait out their 90 seconds.
- Reported as a `reveal` / `revealed` event pair (§9.3) so the audit page can see
  someone standing in a crowd flashing strangers.

**Action semantics — one press, escalating with distance (D29).** The nametag's
**hunt strip** is a focusable row (§8.4); pressing **A** on it does the strongest
thing currently available, which is unambiguous because the ladder is monotonic in
proximity:

| Target state | A on the hunt strip |
|---|---|
| within `KILL_RSSI` | **Attack** |
| within `REVEAL_RSSI`, cooldown clear | **Reveal** |
| within `REVEAL_RSSI`, cooling down | Radar detail (shows the cooldown) |
| not detected | Radar detail / Gotcha screen |
| own attack in progress | **Abort** the attack (§10.2 — a real tactical choice) |

The strip's label and the hunt LED always name the action *before* it is pressed —
`A: onthullen` or `A: AANVALLEN`, red LED — so the boundary case (you meant to
reveal, you were already in kill range) resolves to "you attacked someone you were
standing next to", which is what you wanted anyway. **Do not add a confirmation
step**: the whole mechanic is a single press in a crowd. Focus policy and the X
button are specified in §8.4.

### 5.8 Spawn and join protection (D24)

For `SPAWN_PROTECT_S` (90 s) after a respawn, and after a first enrollment, a player
**cannot be attacked**.

- `gflags` bit4 `PROTECTED` is set on air (§4), so a hunter's badge shows
  *"protected — 43 s"* rather than offering an attack that will bounce.
- The responder refuses `ATTACK` with `PROTECTED`. The attacker **pays no cooldown**
  for a refused attempt.
- **Protection ends immediately when the protected player sends an `ATTACK`.** It is a
  breath, not a bunker, and it must never become a free first strike.
- Reveal is still allowed against a protected player (§5.7).
- The badge shows a white protection LED (§8.8) and a countdown chip; the backend
  tracks `protected_until` and re-checks it on ingest, so a badge that lies about
  protection gains nothing.
- Protection is **not** paused by a truce — it is a 90-second wall-clock window and
  interacting with truce arithmetic would buy nothing.

### 5.9 Training mode (D28)

**Both sides opt in, and then everything is real except the consequences.**

The prize is not learning to hunt — a first real kill teaches that perfectly well. It is
**learning to dodge**. Rule 5 gives you exactly *one* dodge per assassin per life, so
without training every player's first escape attempt is also their only one, spent while
they are still working out what the siren means. Training is the only way to feel a
successful break-away before it costs something. Reveal is the second beneficiary: it
can only be practised against a partner whose badge is genuinely willing to flash.

#### 5.9.1 Rendezvous — mutual opt-in, HXCG-style

Both players choose `Oefenmodus` from the radar-detail screen within
`TRAINING_WINDOW_S` of each other. Each badge sets **`gflags` bit5
`SEEKING_TRAINING`** (§4) for the duration of its window and watches the scan it is
already running for another badge with the same bit set; first match pairs, and both
drop the bit.

This is deliberately the **overlapping-window pattern from the contact swap**
(`contact_exchange.py`, HXCG). §5.1 rejected that pattern for *kills* because a kill
must be one-sided — but mutual consent is exactly what it was built for, it is already
field-proven, and reusing it avoids inventing a second rendezvous. Signalling through a
reserved `gflags` bit rather than a second beacon means no new advertising set and no
new scan.

Under the v0.10.0 input model there are no button chords at all (D29), so training is
entered from a menu row — `Oefenmodus` on the Gotcha screen (§8.4). That is fine: you
are standing next to your partner agreeing to do this, so it is not time-critical.

#### 5.9.2 What runs during a session

The **whole cycle, for real**, in both directions — within a session each badge treats
the other as its training target, so both players get to hunt *and* to be hunted:

```
radar closes  ->  reveal (a real gold flash on the partner's badge)
              ->  attack, real siren, real hold bar
              ->  a real dodge attempt, or a "kill"
              ->  and again, as often as you like, until the session ends
```

A session ends on whichever comes first: `TRAINING_SESSION_S` expires, either player
exits, or the partner is out of range for 60 s. Re-entry is blocked for
`TRAINING_REENTRY_S`.

#### 5.9.3 Isolation from the real game — the three rules that matter

Training touches **no** persisted game state. Three specific disciplines, each closing a
concrete exploit:

1. **Override the target; never swap it.** `GotchaHunter` gets a `training_target` that
   overrides display and attack logic while set. The persisted `target` in
   `gotcha.json` is **never modified and never rewritten** during a session.
   > 🐛 **Why not a temp variable.** If the badge resets mid-session — flat battery,
   > crash, USB unplug — a saved-and-restored field leaves the badge believing the
   > training partner *is* its real target, and if that ever reached flash it survives
   > the reboot and the player hunts the wrong person for real, silently. An override
   > fails correctly: a crash simply loses it.
2. **A disposable soul.** The partner generates a **throwaway secret for the session**
   and discloses that, never its real one.
   > 🐛 **Why.** A real kill ends in soul disclosure, and the backend credits a kill on
   > nothing but `sha256(soul) == commitment` (§3.4). Handing over the live soul would
   > let the trainee bank a genuine kill afterwards — and let two friends farm each
   > other by "training". The training soul verifies against nothing.
3. **Presentation-only death.** The partner's badge plays the full alarm, the death
   screen and the countdown, but does **not** set `alive = false`, start `respawn_at`,
   touch `streak`/`total_kills`, decrement the dodge ledger, queue `killed_by`, or hand
   over its real target in `SPOILS` (which would both leak who it is hunting and
   corrupt the trainee's real target). `SPOILS` carries a dummy.
   > 🐛 **Why.** Otherwise "let's train" is a way to take someone out of the game for
   > thirty minutes, and silently burning a victim's single dodge (rule 5) sets them up
   > for an instant real kill by a confederate.

Nothing is queued and nothing is uploaded: the production scoring path never sees a
training event, so no bug can credit one.

#### 5.9.4 Training is not a shield

- **A real attack always wins.** Training does not hold a connection open — it is a
  series of short duels, so the BUSY windows are the same few seconds a real duel
  already creates. A real `ATTACK` arriving between training duels is honoured
  normally, and if it kills you, **training aborts and the real death screen takes
  over.**
- **The beacon stays honest.** A training session sets no `gflags` that make you look
  unattackable: `ALIVE` and `BOUNTY` keep their real values and `TRUCE` is not set.
- `TRAINING_SESSION_S` and `TRAINING_REENTRY_S` are belt-and-braces. They mostly guard
  against *social* abuse ("I'm training, don't kill me") and against an implementation
  that accidentally holds the link, rather than against a real invulnerability exploit.

#### 5.9.5 Truce and quiet hours do **not** apply — and there is no code for this

Training carries **no truce logic and no quiet-hours logic at all.** Do not add any.

Both people opted in seconds earlier and are standing next to each other; where and
when they practise is their own responsibility, exactly as it is for their phones. The
plan already handles this class of thing socially rather than in code — rule 14's safe
zones are explicitly *not* enforced by the badge — and this is the same call.

**This is the simpler implementation, not the more permissive one.** A gate would mean
carrying the truce schedule, `clock_offset_s` and each player's personal window into the
training path and keeping them in sync with §10.4a. Skipping it removes that code
entirely.

Nothing special is needed to make a badge quiet, either: training uses the same alert
path as everything else, so the existing mute already applies with no extra work. The
rules card just tells people to use it.

**The real game's truce behaviour is unchanged** (§10.4): a genuine attack still cannot
happen during a truce, and the genuine siren is still suppressed unconditionally. Only
consenting training is exempt.

#### 5.9.6 Scope — late, and explicitly droppable

Sequenced in **Phase 6 and droppable** (§11). It is a real feature — rendezvous,
overridden targeting, disposable souls, suppressed state transitions on both sides,
session cap, re-entry cooldown, abort paths — landing against 14 August with Phases 0–5
ahead of it.

**Crucially, development does not depend on it.** Two dev badges enrolled in a
throwaway backend game exercise the real duel, the real handshake and the real soul
disclosure, which is a *better* protocol test than training mode will ever be. Training
mode's value is player-facing (learn to dodge before it counts) and for field-tuning
`KILL_RSSI`/`FLEE_RSSI` with a willing partner. If time runs out, cut it.

---

## 6. Deployment and networking

### 6.1 Where the server runs

**Settled (D31, 2026-07-28, confirmed with Fri3d infra):** a freshly imaged
**Ubuntu laptop physically on site**, with a **fixed public IP routed to it** by
the camp network. Ports **80 and 443 are open, internally and externally**
(Ward). The tunnel options from earlier revisions (Cloudflare Tunnel, Tailscale
Funnel) are moot and deleted — there is no NAT problem to tunnel around (see
rev. 4 in git history if that analysis is ever needed again).

- **Address by DNS name, never by IP.** The IP may not be known until arrival;
  Ward's guidance is *"werk bij voorkeur met een DNS met lage TTL"*. Register a
  name under an own domain with a **low TTL (60–300 s)** and repoint the A
  record on arrival day. The `.mpk` ships **hostnames only** (§6.3). The HMAC
  scheme signs `METHOD || PATH`, not the host, so repointing breaks nothing.
- **Uplink independence:** the server is on site and the ports are open
  *internally*, so badge → server traffic has an internal path even if the camp
  uplink fails. **Arrival-day check:** confirm badges still *resolve the DNS
  name* with the uplink down (if camp DNS only forwards upstream, resolution can
  fail while routing works); if needed, put the assigned IP literal in the §6.3
  fallback URL slot once known.
- **Development environment:** during development the server runs on the
  author's home LAN behind a Fritz!Box that cannot forward external ports
  80/443. External forwards **:8066 → :80** and **:8446 → :443** are configured
  instead. Dev badges on the same LAN use the server's LAN address on :80/:443
  directly — exactly the §6.3 LAN-first mechanism. Off-LAN access (a phone on
  mobile data) uses `http://<name>:8066` / `https://<name>:8446`.
  **Release-checklist item: the dev ports must never appear in a shipped
  build's defaults.**
- **TLS: Let's Encrypt via DNS-01, not HTTP-01.** HTTP-01 needs inbound :80,
  which the dev Fritz!Box cannot provide; DNS-01 issues regardless of
  reachability and keeps one workflow for home and camp. Confirm the DNS host
  offers an API certbot can drive — a blocking prerequisite for Phase 5 (§14.1).
- Load is negligible: 700 badges ÷ 300 s = **2.3 req/s**, a few KB each. SQLite
  and a single process are ample. Run it under systemd with restart-on-failure.

### 6.2 Transport: plain HTTP with signed requests (D21)

**Decision: the badge speaks plain HTTP and signs every request and response with
HMAC-SHA256, except for a single HTTPS call at enrollment to bootstrap the key.**

#### Why this is not a downgrade

This game barely needs confidentiality. Kill proofs are self-authenticating (§3.4 — a
soul is worthless to anyone but the killer), scores are public by design, and the hit
list is *published*. What the game actually needs is **integrity and authenticity**:
that a kill report really came from that badge, and that a "truce is on" or "your
target is X" response really came from the server.

TLS as this badge would have used it — very likely with certificate verification off
(§6.2.1) — provides encryption but **not** authenticity against an active attacker.
A signed-payload scheme provides authenticity but not encryption. On a hacker-camp
network, **authenticity is the property that matters**: an unverified TLS session can be
trivially intercepted and rewritten, whereas a signed payload cannot be forged without
the key. So this is stronger than the realistic HTTPS alternative, not weaker.

#### The scheme

```
enrollment (ONCE per badge, over HTTPS):
    badge -> POST https://…/v1/enroll
             { badge_key, display_name, groups, commitment, app_version, board }
    server -> { pid, player_key (32 B, hex), game_id }
    Exactly one TLS handshake in the badge's entire life, made early in uptime
    while the heap is clean. Cost is irrelevant; it closes the key-delivery hole.

every request thereafter (plain HTTP):
    X-Pid:   <pid>
    X-Ts:    <unix seconds, corrected by clock_offset_s>
    X-Nonce: <16 random hex chars>
    X-Sig:   HMAC_SHA256(player_key, METHOD || PATH || X-Ts || X-Nonce || BODY)

every response (a JSON envelope in the BODY -- see the note below):
    { "ts": <unix seconds>, "nonce": "<the request's X-Nonce>", "sig": "<hex>",
      "payload": { ... } }
    sig = HMAC_SHA256(player_key, ts || nonce || canonical_json(payload))
    The badge MUST verify `sig` and that `nonce` matches the nonce it just
    sent, and discard anything unsigned, mis-signed or nonce-mismatched.
```

- **Responses must be signed too.** Without it, a MITM could inject "truce off",
  "you are dead", or a fake target. This is not optional.
- **Why the response signature lives in the body, not a header:** the badge's
  HTTP client is `mpos.DownloadManager` (§8.3), whose `post_url`/`download_url`
  return **the response body only** — no headers, no status code. A header-based
  response signature would be unverifiable on the badge. The HTTP status is
  likewise invisible and carries no authority: the badge acts only on the signed
  payload. Requests keep their `X-*` headers (`headers=` is supported on send).
  `canonical_json` = keys sorted, no whitespace — a few lines next to the HMAC
  helper, unit-tested with it.
- **Replay defence:** server rejects `X-Ts` outside ±10 minutes (generous — badge RTCs
  drift, see `clock_offset_s`, §8.3) and caches seen nonces for that window. The badge
  rejects a response whose signature does not bind the nonce it just sent.
- **Nothing replayable ever crosses the link.** The `player_key` is transmitted exactly
  once, over TLS, at enrollment.
- **MicroPython has no `hmac` module.** Implement HMAC-SHA256 by hand over
  `hashlib.sha256` — it is about ten lines (key padding to 64 B, inner/outer digest).
  Put it in `gotcha.py`'s pure half and **unit-test it against RFC 4231 vectors**.

#### What this costs

- **Loses:** eavesdroppers on the camp network can see who killed whom and when. The
  leaderboard publishes that anyway. Record it in §13 and on the player page.
- **Gains:** the entire TLS RAM/fragmentation risk (§6.2.1) drops from a Phase 0
  blocker to a single handshake at enrollment. No cert pinning, no cert-verification
  question, no per-sync 40 KB allocation on a heap shared with lvgl.

#### Deployment fit — resolved by D31

The server exposes **both** faces directly on its public IP: HTTPS on :443
(`/v1/enroll` and the web pages) and plain HTTP on :80 (everything the badge
calls, signed). With a real Let's Encrypt certificate (DNS-01, §6.1) the
enrollment handshake verifies even on clients that do check certificates; the
badge, which likely does not, loses nothing.

### 6.2.1 Background: what HTTPS would have cost

`DownloadManager` is aiohttp-backed, so HTTPS works out of the box. The question is
what it costs. Taking the three resources separately, because they have very different
answers:

**Battery: a non-issue.** A TLS handshake is 1–3 s of CPU and radio. At a 5-minute sync
that is under 1 % duty, i.e. **well under 1 mA averaged** against a ~150 mA baseline
(§8.7). HTTPS is nowhere near the battery conversation; the BLE scan and the backlight
are each ~50 mA and dwarf it by two orders of magnitude. **Do not optimise TLS for
power.**

**Time: a non-issue.** 1–3 s every 5 minutes, in a `TaskManager` task with a timeout,
never on the main tick (§8.3). Nothing in the game is latency-sensitive — the only
instant thing, the attack alarm, is BLE-local and never touches the network.

**RAM: the entire risk, and it hinges on one unknown.** An mbedTLS session on ESP32
needs roughly **20–45 KB**, dominated by the TLS record buffers
(`MBEDTLS_SSL_IN_CONTENT_LEN`/`OUT_CONTENT_LEN`, up to 16 KB each unless the firmware
was built smaller) plus certificate-chain parsing. That allocation is requested **every
sync**, because `DownloadManager` uses **per-request aiohttp sessions** — there is no
connection reuse to amortise it.

That matters because MicroPython's GC **frees but does not compact**. A repeated
30–40 KB contiguous allocation on a heap shared with lvgl's display buffers, fonts and
widget trees is the textbook recipe for **fragmentation-induced `ENOMEM` after days of
uptime** — total free memory looks fine, but no single block is big enough. This is the
classic long-run failure mode for MicroPython-on-ESP32 network code.

**But: the badge is an ESP32-S3-WROOM-1 N16R8V with 8 MB PSRAM.** If MicroPythonOS
places the MicroPython heap in PSRAM — which is usual on PSRAM-equipped boards — then
40 KB is a rounding error and fragmentation pressure is negligible. **If the heap is
internal-only (~100–200 KB), a 40 KB TLS session is a third of everything and the risk
is severe.** These are not close calls; they are opposite conclusions.

**Resolve it with one line on the badge before designing around it:**

```python
import gc; gc.collect(); print(gc.mem_free())
# megabytes  -> heap is in PSRAM  -> fragmentation pressure negligible
# ~100-200 KB -> heap is internal -> a 40 KB TLS session is a third of everything
```

**D21 resolves this by removing the recurring allocation entirely**: one TLS handshake
at enrollment, made early in uptime while the heap is clean, then plain HTTP forever.
The check above is still worth running once — it tells you how much headroom the *rest*
of the app has, which matters for the peer-table LRU (§4) and for lvgl — but it no
longer gates the transport design.

**Certificate verification** may be **off by default** on this build. That was the
decisive argument for D21: unverified TLS is encrypted but freely MITM-able, so it
would have bought secrecy the game does not need while failing to provide the
authenticity it does.

**Phase 0 item 2 is therefore reduced** from "1000 consecutive HTTPS syncs without OOM"
to: run the `gc.mem_free()` check, confirm one enrollment handshake succeeds, and soak
**1000 consecutive signed plain-HTTP syncs** for heap stability.

### 6.3 Endpoint configuration

Two base URLs ship in `config.json`, both changeable from the phone page or the
on-badge editor without reflashing. **They carry hostnames, never IPs (D31).**

| Key | Scheme | Used for | Camp default | Dev value |
|---|---|---|---|---|
| `gotcha.enroll` | **https://** | `/v1/enroll` only — once per badge, to bootstrap `player_key` (§6.2) | `https://<name>/` | `https://<lan-ip>/` or `https://<name>:8446/` |
| `gotcha.api` | **http://** | Everything else, signed | `http://<name>/` | `http://<lan-ip>/` or `http://<name>:8066/` |

The badge tries a configured LAN/fallback address first, then the primary URL —
this is how dev badges reach the home-LAN server, and how an arrival-day IP
literal can bypass a broken DNS path (§6.1). **The shipped `.mpk` defaults are
the camp URLs (implicit :80/:443); the :8066/:8446 dev ports must never ship.**

---

## 7. Connectivity check (D18)

**Fri3d pre-loads the `fri3d-badge` SSID onto the badge** (confirmed 2026-07-26), so
`WifiService.auto_connect()` brings the link up on every boot with no involvement from
this app. **The app therefore provisions nothing and stores no credentials.**

> **This app must never call `WifiService.save_network()`, `forget_network()`, or
> `disconnect()`.** It is a consumer of connectivity, not a manager of it. There is no
> credential anywhere in this repo, in the `.mpk`, or in any config file — and there
> must never be one.

What the app *does* do is verify connectivity and tell the player the truth about it:

```
1. WifiService.is_connected()
   NOTE: this returns True in HOTSPOT mode with no internet at all,
   so it is necessary but NOT sufficient.
2. Reachability test: MicroPython has NO ICMP. Use a TCP connect with a short
   timeout to the game API host (falling back to 1.1.1.1:80).
   Run it in a TaskManager task — socket connect BLOCKS.
3. Surface the result in the UI. Never fail silently.
```

**Rules:**
- Run the check once at startup and on a `ConnectivityManager` change event — not on
  a poll loop.
- **A badge with no connectivity must say so, and say what to do about it.** The
  Gotcha strip shows `no network — check WiFi in Settings` rather than simply being
  absent, otherwise a player whose badge never joined has no way to tell the game is
  broken rather than merely quiet. This is the single most likely support question at
  camp.
- Everything gameplay-critical works offline anyway (D6, §10.3), so a failed check
  degrades the game to "scores sync later", never to "you cannot play".

---

## 8. Badge implementation

### 8.1 New file: `app/com.fri3dcamp.fri3dfriends/gotcha.py`

Follow the established **pure/radio split** (`ble_proximity.py`,
`contact_exchange.py`): everything pure is host-testable with pytest.

**Pure (unit-tested):**
```
make_soul() -> bytes                        # os.urandom(16)
commitment(soul) -> str                     # sha256 hex
verify_soul(soul, commitment) -> bool
EventQueue                                  # bounded, atomically persisted, dedup by uuid
DuelState                                   # the §5.3 state machine, tick(now, rssi)
DodgeLedger                                 # per-attacker counters + DODGE_DECAY_MS
GameConfig.from_sync(dict)                  # defensive parse of server tunables
truce_active(now, cfg, quiet)               # camp truce OR personal quiet hours (§10.4a),
                                            # server-clock corrected. Returns which one,
                                            # since only the camp truce pauses decay (§2.2).
clamp_quiet(window, cfg)                    # QUIET_EARLIEST/LATEST bounds, never raises
version_lt(a, b)                            # "0.10.0" < "0.9.0" is False -- compare
                                            # numerically per component, never as strings
TrainingSession                             # §5.9 pairing, session cap, re-entry cooldown;
                                            # holds training_target as an OVERRIDE, never
                                            # touching the persisted target
score_preview(...)                          # mirror of §2, optimistic UI only
hunt_action(target, rssi, now, cfg, duel)   # the §5.7 A-ladder -> attack|reveal|detail|abort
reveal_ready(now, last_reveal_at, cfg)      # REVEAL_COOLDOWN_S
protected(now, protected_until)             # §5.8
hunt_bar(state, rssi, now, cfg, n_leds)     # -> [(r,g,b)] * n_leds, the §8.8 radar bar
rssi_trend(fast, slow, cfg)                 # -> -1 / 0 / +1, §8.8.2a. The single most
                                            # load-bearing untested assumption in the
                                            # design -- Phase 0 gates it.
hunt_ping(state, rssi, trend, now, cfg)     # -> (freq_hz, ms, taps) or None, §8.8.6. Pure and
                                            # host-testable: same proximity clock as the
                                            # bar, so the two stay in phase by construction
```
Beacon build/parse lives in `ble_proximity.py` with the rest of the wire format (§4).

**Radio / IO:**
```
class GotchaResponder:   # VICTIM side — used by app AND background service
class GotchaHunter:      # ASSASSIN side — app only
class GotchaSync:        # signed HTTP client: enroll(), sync(), flush_events()
```

### 8.2 Persistence

New file `/apps/com.fri3dcamp.fri3dfriends/gotcha.json`, written with the **same
atomic temp-file + `os.rename`** pattern as `contacts.json` (`DESIGN.md` §9) — a queue
corrupted by a power-off loses a kid's kills.

```json
{
  "enrolled": true, "pid": 4711, "player_key": "…32B hex…", "game_id": "fri3d2026",
  "soul": "…hex…", "commitment": "…hex…",
  "target": {"pid": 8123, "name": "Otter 42", "commitment": "…", "seen_ago_s": 240},
  "state": {"alive": true, "streak": 2, "total": 5, "respawn_at": null,
            "protected_until": null},
  "dodges": {"6301": 1},
  "last_reveal_at": 0,
  "clock_offset_s": -3,
  "queue": [ {"uuid": "…", "type": "kill", …} ],
  "synced_at": "2026-08-14T15:22:07"
}
```

Opt-out and personal quiet hours live in `config.json` as
`"gotcha": {"enrolled": false, "quiet": {"from": "20:30", "to": "08:00"}}` so they flow
through the **existing** `sanitize_config` (used by both the phone page and the on-badge
editor) and cannot be clobbered by a partial save. `sanitize_config` must clamp `quiet`
to `QUIET_EARLIEST`/`QUIET_LATEST` (§10.4a) and fall back to the camp truce on anything
it cannot parse — never raise, never store a half-valid window.

Queue bounded at `MAX_QUEUE = 40`; on overflow drop the **oldest non-kill** event
first, never a `kill` or `killed_by`.

### 8.3 Networking

Use `mpos.DownloadManager` — `download_url()` / `post_url(url, data, headers)`, both
async and aiohttp-backed. **Do not hand-roll `urequests`.** Gate on
`WifiService.is_connected()` (already wrapped by `_wifi_connected()`) and wrap every
call in `TaskManager.wait_for(..., timeout=10)`.

> ⚠️ **Every** Gotcha HTTP call must be a `TaskManager` task with a timeout, never
> called from the main tick — the same reason `ntptime.settime()` already runs in a
> thread (see `_resync_time`/`_ntp_blocking`).

Sync failures are non-events: log, keep the queue, retry with backoff (5 → 10 → 20 min,
capped), and keep playing on cached state (D6).

**Clock:** store `clock_offset_s = server_time − local_time` at every sync and apply
it to all truce and decay checks. A badge whose RTC never got NTP would otherwise
compute the truce window wrongly, which at 22:00 is the difference between a sleeping
child and a screaming badge.

### 8.4 UI

| Screen | Content |
|---|---|
| **Nametag (extended)** | A status chip — `ALIVE · streak 3 · 11 kills` or `DEAD · back 14:32` — plus one target strip: `🎯 Otter 42` and a 5-segment radar bar from `rssi_ewma`. Hidden entirely when not enrolled or no game is running. |
| **Gotcha screen / radar detail** (A on the hunt strip when no target is near, or Menu → `Gotcha`) | Target name, dBm, **last seen by anyone: 12 min ago** (§10.1), your ranks, nearby bounty players, reveal cooldown remaining — plus the focusable rows: `Oefenmodus` (§5.9), demo mode, and `Stoppen met Gotcha` / `Meedoen met Gotcha` (rule 15). |
| **Revealing** (hunter, §5.7) | `REVEALING — look for the gold badge`, 2.5 s, then back to the radar with the cooldown running. |
| **Spotted** (target, §5.7) | Gold full-screen, chirp, `SPOTTED — someone has found you`. Deliberately *not* the attack alarm: no siren, no red, no "RUN". It is a warning, and it must not be mistakable for a kill in progress. |
| **Protected** (§5.8) | White chip `PROTECTED — 43 s`, on the nametag. Shown on the *hunter's* radar strip too, from `gflags` bit4. |
| Attacking | Target name, hold progress bar, live RSSI, "KEEP CLOSE!" |
| **Under attack** | Full-screen red, siren, `⚠ UNDER ATTACK — RUN! ⚠`, countdown, and either `you can still get away` or **`NO ESCAPE — they have you`** when `dodges_left == 0`. At `DODGE_LIMIT = 1` this is a binary state, so render it as words, not a counter. Must be unmistakable from across a field. |
| Dodged | "YOU GOT AWAY!" + relief chime + **"they will catch you next time"** (at limit 1, the next attempt always lands). |
| Killed | "GOTCHA — killed by \<name\>" + respawn countdown. **Countdown only (D14)** — no ghost mode in v1. |
| Bounty nearby | Banner `BOUNTY: Otter 42 (streak 7) is near`, reusing the existing arrival-banner widget. |

**D11 — the social mechanic.** Alive/dead is on the nametag *and* in `gflags` on air,
so you can both (a) peer at someone's badge to see if they are safe to walk up to, and
(b) see the status of anyone in range on your own friends panel. Add an alive/dead dot
to the existing friends-panel cards.

**Input (D29) — everything rides the v0.10.0 focus-navigation model.** The raw
button layer is gone; the joystick moves LVGL focus, **A** fires `CLICKED` on the
focused row, **X** invokes `onBackPressed`. Gotcha adds focusables and menu rows
to the existing machinery — no new input mechanism of any kind:

- **The hunt strip is a focusable row** on the nametag (build it with
  `_make_focusable`, like the `Menu` pill). Its label always names its A-action
  (§5.7): `A: radar`, `A: onthullen`, `A: AANVALLEN`, `A: afbreken` during your
  own attack. **Focus policy:** when the strip is visible (enrolled, game
  running) it is the *default* focused object on the nametag; the joystick moves
  between it and the `Menu` pill. Escalation changes the **label** under your
  thumb, never the focus — the accepted boundary case stays "you attacked
  someone you were standing next to" (§5.7).
- **The main menu grows one row: `Gotcha`** (`MENU_MAX` 5 → 6), opening the
  Gotcha screen (table above), whose rows are focusables in the adopt-prompt
  pattern. Opt-out lives there (`Stoppen met Gotcha` + one confirm) — a few
  seconds, no phone (§13).
- **First-run consent (§13) is a mini-menu** in the Configure-me pattern
  (`_do_cfg_action`): `Meedoen` / `Niet meedoen` / `Laat zien wat de badge doet`.
- **`_establish_focus()` gains the Gotcha states** ahead of the existing ladder:
  duel screens (no focusables — see next point) → Gotcha screen rows → first-run
  consent rows → the existing menu/adopt/setup/cfg/nametag ladder. Every
  open/close routes through `_set_focus`, exactly as v0.10.0 does.
- **`onBackPressed` ordering:** duel screens (attacking, under attack, killed,
  dodged, spotted) **consume X and do nothing** — a victim cannot dismiss the
  alarm, and an assassin aborts with A, deliberately (one button, one meaning,
  §10.2). Then: Gotcha screen closes → the existing chain (menu → adopt → setup
  → detail) → quit.
- **`_open_menu`'s suppression list gains "duel live"**; the hunt strip's
  A-action is suppressed by the same list (§5.5).
- Use `_bind_event` (never raw `add_event_cb`) and the changelog-noted firmware
  APIs: `mpos.ui.add_focus_border`, top-level `lv.group_remove_obj` /
  `lv.group_focus_obj`. The 2026 touch screen gets tap support on all of this
  for free (rows are `lv.button`s).

**Demo mode.** A `Show me what the badge does` entry on the first-run screen (§13) and
in the radar detail screen: it walks the whole colour language and every sound — blue,
amber, red, the gold reveal flash and chirp, the attack siren, the green kill flash,
the dead pulse, and **the hunt ping at all three rates** (§8.8.6, the sound players most
need to recognise and otherwise first hear while it matters) — with a one-line caption
each, in about twenty seconds. Borrowed
straight from the other proposal, and it is the cheapest thing in this document: it
runs entirely off `_flash_leds` and the existing buzzer, needs no game, no network and
no enrollment, and it means the first time a nine-year-old hears the siren is not the
first time it matters. **Run it during a truce with the buzzer suppressed.**

Follow the **pre-built hidden widgets, `set_text` only** rule from the adopt prompt
(`DESIGN.md` §13.3, landmine #1): never create or delete lvgl widgets per duel. Build
every Gotcha widget once in `onCreate` and toggle `add_flag`/`remove_flag(lv.obj.FLAG.HIDDEN)`.
**There is no `clear_flag`** on this build (`DESIGN.md` §1).

### 8.5 Files touched

| File | Change |
|---|---|
| `gotcha.py` | **new** — incl. `TrainingSession` (§5.9) and `version_lt` (§8.10) |
| `fri3d_friends.py` | The focusable **hunt strip** + §5.7 A-ladder handler, the `Gotcha` menu row (`MENU_MAX` 6) + Gotcha screen, focus/`onBackPressed` extensions (§8.4), Gotcha widgets, duel + reveal + spotted + protected UI, status chip, demo mode, first-run consent mini-menu, **`_update_leds()` rewritten as the §8.8 radar bar — friend LEDs removed**, the §8.8.6 hunt ping + sound priority ladder, main-loop tick, sync task, connectivity check (§7), arbitration guards |
| `ble_proximity.py` | **HSNT v2** build/parse + name budget; game fields on peer entries; **LRU cap on `seen`** |
| `contact_exchange.py` | Register the Gotcha service in `_ensure_services()`; hand handles to `GotchaResponder` |
| `beacon_service.py` | Victim-side responder (attack **and** reveal) + protection state + sync in the background (D3); v2 beacon; LED-only rendering of §8.8 |
| `ble_setup.py` | `sanitize_config` accepts `gotcha` (incl. `quiet`, clamped per §10.4a); expose enroll state over the setup GATT |
| `MANIFEST.JSON` | → 0.11.0 (0.10.0 is the shipped navigation release). **The version string is now load-bearing** (§8.10.3) — bump it on every release or the fleet histogram and the update nudge both lie. |
| `server/` | **new** — FastAPI + SQLite backend (D31, §9): API, scoring, ring, admin console, **and the player/admin pages it serves itself** (templates or static files under `server/`; `docs/` is *not* the deployment path — it is GitHub Pages, whose HTTPS origin cannot call a plain-HTTP API). Runs under systemd. |
| `tests/test_gotcha.py` | **new** — badge pure half (§8.1) |
| `tests/test_server.py` | **new** — backend + the Phase 1 badge-simulator fixture (§11) |
| `tests/test_ble_proximity.py` | v2 format, name budget, block presence |
| `DESIGN.md` | new Gotcha section; **§11 (friend LEDs) rewritten as the radar bar**; the §8.4 focus-ladder additions noted in the v0.10.0 input section |
| `README.md` | Gotcha section + the network caveat (§13) |

### 8.6 Why this is one app, not two (D19)

**The radio decides it.** NimBLE on this build gives one BLE stack, **one advertising
set**, **one `gatts_register_services` call per power-on** (`DESIGN.md` §10) and one
IRQ handler. Two MicroPythonOS apps cannot share that. Worse than the foreground case
is the background one: `beacon_service.py` already runs an elaborate
`screen_stack`-watchdog dance to decide whether the Activity or the service owns the
radio (`DESIGN.md` §12). A second app with its own boot service would be a third
independent claimant, and the failure modes — a silently dead beacon, a wedged NimBLE,
`OSError(22)` on a stale handle — are exactly the bugs this project has already paid
for once.

Beyond that, **the game block lives inside the HSNT beacon** (§4). A single 31-byte
advert cannot be split across two applications. And Gotcha reuses, rather than
reimplements: the dense scan and peer table with RSSI EWMA, `name`/`groups` from
`config.json` (the group scoreboard is built on them), the setup GATT service and its
web page, the button chokepoint, LEDs, buzzer, the atomic-write pattern, and the
arrival-banner widget.

Operationally: 700 badges, one AppStore entry, one install, one update.

**The benefits of a separate app, obtained without splitting:**

| Concern | How it is addressed inside one app |
|---|---|
| Memory / bytecode size (`fri3d_friends.py` is already 87 KB) | **Lazy import**: `gotcha.py` is imported only once a live game is detected, so a badge that never plays pays nothing. Precompile to `.mpy` if flash-to-RAM compile time becomes a problem. The board has 8 MB PSRAM, so heap is unlikely to be the binding constraint — but confirm in Phase 6. |
| Blast radius of a Gotcha bug | Hard interface, every entry point wrapped in `try/except`, exactly as `SettingsActivity` is lazily imported inside a `try/except` today (`DESIGN.md` §13.4). **A Gotcha fault must degrade to "no game", never to "no nametag".** |
| The offline purity of the base app | The game is opt-out-able and fully dormant when no game is running — the beacon's game-block bit is not even set (§4), and no HTTP is attempted. |
| Independent release cadence | Not achievable, and not worth the radio complexity. Accept it. |

**Rejected middle path:** a second *Activity* inside the same package (the manifest's
`activities[]` is an array, so it is structurally possible). Two Activities still
cannot run simultaneously and would have to hand the radio to each other across
`onPause`/`onResume` — added lifecycle complexity for no gain. **One Activity, Gotcha
as modules, plus the existing service extended per §5.6.**

---

### 8.7 Power budget — this is a headline problem, not a footnote

**Both badge generations carry a 2000 mAh LiPo** — the 2024 per `fri3dbadge2024/BADGE.md`
(TP4056 charger), the 2026 confirmed identical by the author (2026-07-26). Assume
~1700 mAh usable after derating. The runtimes below therefore apply to both boards;
the only power-relevant difference is that **the 2026 has a working backlight API and
the 2024 does not** (lever 1).

Estimates below are from ESP32-S3 datasheet figures, **not measurements.** They are
good enough to make decisions and not good enough to quote. Measure in Phase 6.

| Consumer | Avg current | Note |
|---|---|---|
| CPU active @240 MHz, radio off | ~40 mA | The app never sleeps. |
| **BLE scan @50 % duty** (`SCAN_WINDOW_US`/`SCAN_INTERVAL_US`) | **~50 mA** | Receiver on half the time. Co-equal largest draw. |
| BLE advertise @250 ms | ~1 mA | Negligible. |
| **Display + backlight** | **~50 mA** | Co-equal largest draw. |
| 5× WS2812 at the app's dim breathe | ~5–10 mA | Plus ~1 mA each quiescent. |
| **WiFi associated, no power save** | **~90 mA** | The Gotcha tax, if done naively. |
| WiFi associated, DTIM power save | ~25 mA | Same connectivity, ~65 mA cheaper. |
| WiFi TX burst | 240–350 mA peak | Momentary; irrelevant to the average. |

| Scenario | Draw | Runtime on 1700 mAh |
|---|---|---|
| App closed, background beacon, screen on at launcher | ~90 mA | ~19 h |
| **App open today** (nametag + scan + LEDs), no WiFi | **~150 mA** | **~11 h** |
| App open + Gotcha, WiFi always on, **no** power save | ~240 mA | **~7 h** |
| App open + Gotcha, WiFi with DTIM power save | ~175 mA | ~9.5 h |
| App open + Gotcha, WiFi raised only to sync (1.7 % duty) | ~152 mA | ~11 h |

**The uncomfortable conclusion: the app does not already last a camp day.** A waking
day of 08:00–24:00 is 16 h; the current app gets ~11 h and Gotcha done naively gets
~7 h. Charging is therefore assumed, not optional — but the difference between 11 h
and 7 h is the difference between "charge overnight" and "charge at lunchtime too."

**Levers, in order of impact:**

1. **Screen (~50 mA, a third of the budget).** On **2026** `mpos.io_expander.lcd_brightness`
   exists — an aggressive blank-after-inactivity is the single biggest win available,
   and the app already has `_dimmed`/`_set_brightness`/`_wake()` scaffolding for it.
   On **2024 there is no backlight API** (`DESIGN.md` §1), so this lever does not
   exist. **Worth one spike:** try a display-driver sleep/`DISPOFF` command on the
   GC9307 directly. If that works it is the highest-value power fix in the project.
2. **BLE scan duty (~50 mA).** `DESIGN.md` §3 warns that the scan config is
   load-bearing — but read it carefully: the load-bearing part is **passing explicit
   `interval_us`/`window_us` at all**, because that is what disables NimBLE's
   duplicate filter. The specific 50 % ratio is not what fixes the flapping. Dropping
   to ~12.5 % (30 ms window / 240 ms interval) should keep the filter off and save
   ~37 mA, at the cost of slower radar updates and more missed adverts in a crowd.
   **Test this explicitly in Phase 0** — it is cheap and worth a lot.
3. **WiFi power save (~65 mA).** Verify whether `WifiService` sets
   `wlan.config(pm=...)`. If it does not, setting DTIM power save is nearly free.
   Prefer this over connect-per-sync: raising the link every 5 minutes costs a DHCP
   round-trip and fights the shared OS service.
4. **Battery-aware degradation, on an announced ladder.** Borrowed from the other
   proposal's §15 — but **without** its "empty battery = elimination" rule, which at
   ~11 h of runtime on a 16 h waking day would eliminate a large fraction of the camp
   for a logistics failure (§1.1, rule 8). Warn, degrade, and keep playing:

   | Level | Behaviour |
   |---|---|
   | **20 %** | On-screen notice + a one-off orange blink on the last LED. Drop scan duty, stretch `SYNC_S` to 600 s, drop the hunt ping. |
   | **10 %** | Second notice, explicitly worded: *"find a power bank — you can still be killed while charging."* The last-LED orange double-blink becomes persistent (once a minute, §8.8.3). Blank the screen harder (2026 only, §8.7 lever 1). |
   | **5 %** | Final notice. Sync once immediately to flush the event queue **before** the badge dies, so a kill landed at 4 % is not lost. Then minimum everything. |
   | **0 %** | The badge stops. The player keeps their score, keeps their streak (it decays on wall-clock like anyone else's, rule 11), and returns as `dormant` → `protected` (§9.6) when charged. |

   Announce each step on screen so a suddenly-sluggish radar is never mysterious.
   **Flushing the queue at 5 % is the load-bearing part of this ladder** — everything
   else is comfort.
5. CPU frequency reduction (240 → 160 MHz) saves ~10–20 mA but risks lvgl smoothness
   and GATT timing. Not recommended.

**Add to Phase 6:** a real measurement of all five scenarios above with an inline
USB meter, on both board generations.

---

### 8.8 Reading the badge without the screen — LEDs and sound (D23)

**This is not decoration, it is the power budget.** §8.7 lever 1 says the single
biggest saving available is blanking the screen — but the radar currently *lives* on
the screen, so blanking it blinds the hunter and the lever cannot be pulled. Moving the
hunt onto the LEDs is what makes an aggressive blank-after-inactivity compatible with
playing the game. Treat this section as a prerequisite for lever 1, not as polish.

§8.8.1–8.8.5 cover the LED radar bar; **§8.8.6 covers the hunt ping**, the sound that
rides the same proximity clock. Together they are the whole no-screen interface.

#### 8.8.1 The whole strip becomes the radar (replaces the friend LEDs)

**Decision: the friend-LED feature is removed. Gotcha owns all `n` LEDs.**

`DESIGN.md` §11 currently gives one RGB LED per nearby friend, dimly breathing that
friend's group colour, driven by `_update_leds(now)` every `LED_UPDATE_MS = 60`
(`LED_DIM_MIN = 0.015` … `LED_DIM_MAX = 0.18`, `LED_BREATHE_MS = 3800`, phase-staggered,
frame-cached). **That feature goes away**, and `_update_leds()` is rewritten around the
hunt. `DESIGN.md` §11 must be marked superseded when this ships.

**Why this is the right call rather than sharing:** one LED can only express the hunt as
a *colour*, which asks a nine-year-old to distinguish blue from amber from red on a
single 5 mm dot, at night, at a glance. The whole strip can express it as a **bar** —
a length, which is pre-attentive and legible from several metres — *and* still carry
the colour ramp on top. The upgrade from one LED to four or five is not incremental; it
turns the LEDs from a hint into the primary radar, which is exactly what §8.7 lever 1
needs.

**What is lost, honestly:** the ambient pleasure of seeing your friends' group colours
breathing on your chest. **No information is lost** — the on-screen friends panel and
the group pills still show everyone nearby, with names, dBm and age. It is a
deliberate trade of ambience for legibility, made on the assumption that during a live
game the hunt is what you actually want the LEDs to be telling you.

**A side benefit: this is cheaper.** The friend LEDs breathe continuously whenever
anyone is nearby; the hunt bar is **completely dark whenever your target is not in
range**, which is most of the time (§3.3). Average LED draw goes *down*, which helps the
§8.7 budget rather than hurting it.

#### 8.8.2 The radar bar

`n` = 4 on the 2024, 5 on the 2026 (`_led_count()`, unchanged). LEDs fill from index 0
upward. Both **length and colour** encode the same proximity axis, so the bar is
readable whether you catch the count or the hue:

| `rssi_ewma` | Lit LEDs | Colour | Brightness | Animation |
|---|---|---|---|---|
| target not detected | 0 | — | — | dark |
| detected, far | 1 | blue | 0.20 | breathe, 3800 ms |
| closing | 2 | blue | 0.25 | breathe, 2400 ms |
| closing | 3 | **amber** | 0.35 | breathe, 1400 ms |
| ≥ `REVEAL_RSSI` (reveal range) | n−1 | **amber** | 0.45 | breathe, 700 ms |
| ≥ `KILL_RSSI` (attack range) | **all n** | **red** | 0.55 | steady |

The lit count is `lit = clamp(1, n, ceil(n * fraction))` where `fraction` comes from the
same RSSI→bucket mapping that drives the on-screen 5-segment bar, so the two readouts
always agree and teach each other. **On the 2024 the bar has one fewer segment; nothing
else changes.**

The breathe *period* shortening as you close is the second redundant cue — quickening is
noticeable in peripheral vision in a way that a colour change is not. A player who
learns *"solid red, all of them, means press A"* has learned the whole hunt.

#### 8.8.2a Warmer or colder — the trend signal ⚠️ *test this first*

**The plan promises this and does not currently deliver it.** The narrative says the
badge *"only ever tells you warmer or colder"*, but everything specified so far reports
**absolute** level. In a crowd, absolute RSSI is close to useless for navigation — it is
dominated by bodies, orientation and multipath. **The derivative is what a hunter
actually steers on:** did the last three steps help?

**Mechanism — two EWMAs at different time constants.**

```
fast = (1-af)*fast + af*rssi        # af ~ 0.30  -- this is today's rssi_ewma
slow = (1-as)*slow + as*rssi        # as ~ 0.06
trend_db = fast - slow              # > 0 closing, < 0 losing
```

The fast filter already exists — `ble_proximity.py` line ~521 hardcodes `a = 0.3`. That
magic number becomes a named, server-tunable constant alongside its new slow twin, and
the peer entry grows one float (note the interaction with §4's LRU cap).

| `trend_db` | Meaning | Ping | Strip |
|---|---|---|---|
| > `TREND_DEADBAND_DB` | closing | each ping **bends up** ~`PING_BEND_PCT` | ▲ |
| within the deadband | steady | flat ping | · |
| < −`TREND_DEADBAND_DB` | losing | each ping **bends down** | ▼ |

**The sound version is the one that matters** — a hunter with the badge in a pocket gets
warmer/colder by ear, which is the whole point of §8.8 and of §8.7 lever 1. Bending a
PWM tone is free: it is the same two-step frequency write `_sting()` already does.

The deadband is not optional. Without it the arrow and the pitch flap continuously while
standing still, which is worse than no signal because it reads as movement.

> ⚠️ **A subtlety the live test must settle: these EWMAs are driven per-advert, not per
> second.** Their time constants are measured in *adverts received*, so when the advert
> rate drops — distance, a crowded channel, a body in the way — the effective time
> constant silently stretches and the trend goes sluggish exactly when it is needed
> most. Either scale `a` by elapsed time per sample, or accept it knowingly. **Do not
> decide this from a bench.**

##### ⚠️ Phase 0 blocking spike — the whole hunt rests on this

This is the most load-bearing untested assumption in the design: if trend does not track
real movement, the "warmer or colder" promise fails and the hunt degrades to wandering
until the bar happens to fill. **It is therefore a Phase 0 item with a go/no-go, not a
Phase 2 implementation detail** (§11).

**Protocol.** One badge advertising, one logging `rssi`, `fast`, `slow` and `trend_db`
at ~10 Hz to a file; pull it off and plot on the host. Walk a scripted path:

```
approach 40 m -> 1 m at a normal pace  |  stand still 30 s  |  retreat 1 m -> 40 m
cross laterally at 5 m                 |  step behind a tent / container / vehicle
```

Repeat in **four conditions**, because they fail differently: open field; inside a tent;
**with people standing between the badges** (2.4 GHz is absorbed by bodies — this is the
realistic camp case); and with the badge **in a trouser pocket**.

**Success criteria, stated in advance:**

| Test | Pass |
|---|---|
| Steady approach / retreat | `trend_db` sign correct in **≥ 80 %** of 2 s windows |
| Standing still 30 s | **no** sign flips outside the deadband |
| Body between badges | trend still usable, or the failure is understood and documented |
| Time constants | a `(af, as, deadband)` triple that satisfies the above in **all four** conditions |

**If it fails**, say so plainly and fall back to the absolute bar alone — and then fix
the narrative, because §"Finding them" would be describing a game the badge cannot play.

#### 8.8.3 Whole-strip states

These override the bar entirely:

| State | Strip | Brightness | Duration |
|---|---|---|---|
| **Under attack** | all red, **steady** (not animated — §8.8.4) | 1.0 | until the duel resolves |
| **You have been revealed** (§5.7) | all **gold** + chirp | 1.0 | `REVEAL_FLASH_MS` (2500) |
| **You killed someone** | all green | 1.0 | `LED_FLASH_MS` (900) |
| **You dodged** | green, two blinks | 0.8 | ~900 ms |
| **You are dead** | all red, slow pulse 2000 ms | 0.20 | until respawn |
| **You are protected** (§5.8) | all white, steady | 0.30 | 90 s |
| **Battery low** (§8.7: hint at 20 %, persistent from 10 %) | last LED only, orange, double-blink once a minute | 0.30 | — |
| **Truce, or either side in quiet hours** | **dark** (§10.4 — detection halts, not just attacks) | — | — |
| **Contact lost** (§8.8.7) | two amber blinks, then dark | 0.4 | ~600 ms |
| **No game / not enrolled / opted out** | **dark** | — | — |

Low battery deliberately claims only the **last** LED, so it can coexist with a radar
bar that has not yet filled that far — a dying badge should still be able to hunt.

The existing `_flash_leds()` whole-strip override (Y-swap success, mute toggle) stays
exactly as it is and keeps priority over the bar; those flashes are ~900 ms and do not
meaningfully interrupt hunting.

#### 8.8.4 The IRQ constraint — the part that will bite

`lights.write()` **disables interrupts** and has already starved a short GATT link once
in this project (field bug 2, `DESIGN.md` §9; §5.5 above). Therefore:

- **During a duel: exactly two LED writes** — one when the alarm starts, one when it
  ends. The "under attack" state is **steady red, not pulsing**, for this reason and no
  other. Do not be tempted to animate it; the siren carries the urgency.
- **The reveal flash happens after the link is closed.** Reveal is
  write → ack → disconnect (§5.7); the victim's badge starts flashing on
  *disconnect*, not on receipt of the write. Same rule on the hunter's side.
- The bar animates freely **only when no GATT link is up** — which is the normal
  hunting state, since the radar is pure passive scanning.
- Reuse the existing `_led_override_until` deadline for the whole-strip states; it
  already implements exactly this priority.
- Keep the `_led_last` frame cache. It matters *more* now, not less: the two commonest
  states are **dark** (no target) and **steady red** (kill range), and both must cost
  **zero** `lights.write()` calls per tick. Cache the whole frame, not a per-LED colour.

#### 8.8.5 Removing the friend LEDs — sequencing

**Do not delete the friend-LED code before the hunt bar exists.** Deleting it early
leaves the badge with a dark, dead LED strip and no replacement, which is a visible
regression for zero benefit. `_update_leds()` is **replaced in Phase 2** (§11), in the
same change that introduces the bar, and `DESIGN.md` §11 is rewritten at that point.

The group-colour helper that the friend LEDs used (`_hsv()` and the group→hue
derivation) is **still needed** — the on-screen group pills use it. Do not remove it
along with the LED code.

---

#### 8.8.6 The hunt ping — sound on the same clock as the bar

The LED bar already encodes proximity as a **breathe period** (3800 → 700 ms, §8.8.2).
The ping rides that same clock: **one ping per breathe cycle, in phase with the light.**
That is the whole trick — the two channels pulse together instead of competing, and a
player only has to learn one rhythm. (At kill range the strip goes steady red —
§8.8.4 forbids animating it — so the proximity clock keeps ticking at
`PING_INTERVAL_NEAR` and only the light stops following it; the double-tap carries
the rhythm alone.)

Rate is the primary cue, exactly as in real sonar and in a parking sensor: **repetition
rate is read pre-attentively and pitch is not.** Pitch rises alongside it purely as
redundancy, the same length-plus-colour argument the bar makes.

| Bar state | Ping interval | Base pitch |
|---|---|---|
| segments 1–2 | **silent** (see below) | — |
| segment 3 (amber) | 1400 ms, in phase with the breathe | 1400 Hz |
| segment n−1 (amber, fast) | 700 ms | 1800 Hz |
| all n (red, kill range) | **350 ms**, as a **double-tap** | 2400 Hz |

At kill range the ping becomes a **double-tap** rather than a single note — two bursts
~70 ms apart. It is the audible "the attack is live now" cue, so a hunter knows they can
strike without looking at anything.

**Every ping also carries the trend as a pitch bend** (§8.8.2a): bending up while you
are closing, down while you are losing, flat inside the deadband. Rate says *how close*,
bend says *getting warmer or colder* — two independent facts on one channel, which is
the most a single PWM buzzer can carry and exactly the two a hunter needs.

Each ping is a **short falling chirp** — ~40 ms, stepping down from `f` to about
`0.75 f` — because the existing arrival sting **rises** (`_sting()` goes `freq` then
`freq × 3/2`). Falling versus rising is distinguishable by ear with no thought at all,
which matters when both can happen within a second of each other.

**There is a silent floor, and it is the important design decision.** Sound starts only
at `PING_FROM_SEG` (default 3 of n), not at first detection. §3.3 says the common state
is a target somewhere on site and nothing to do about it; a badge that pinged for every
faint detection would ping for hours, 700 of them would build a camp-wide noise floor,
and the narrative promise that you "carry on with your day" would be a lie. Keeping the
first two segments silent means **the sound starting is itself information**: it means
*they are here, now, close.*

**It gives you away, deliberately.** A badge pinging faster and faster in a crowd is
audible to everyone around it, including the target once they learn the sound. This is
flavour worth keeping — it is the audible equivalent of the Reveal trade in §5.7, where
information costs information — but it is a second reason the silent floor matters, and
a reason `PING_ENABLED` exists as a server-side kill switch (§8.10.1).

**Only the hunter hears it.** The target's badge makes no sound at all; they do not know
they are hunted (rule 1). The ping is generated entirely from the hunter's own
`rssi_ewma`, so it needs no radio traffic and works offline.

##### Sound priority — the buzzer is one PWM channel

`_setup_buzzer()` creates a **single `machine.PWM`** (GPIO 46 on 2024, GPIO 38 on 2026).
There is exactly one tone at a time and **no mixing is possible**, so every sound in the
game is strictly serialised and needs a stated order:

| Priority | Sound | Behaviour on conflict |
|---|---|---|
| 1 | **Attack siren** (you are under attack) | Pre-empts everything; nothing else sounds until the duel resolves |
| 2 | **Reveal chirp** (you have been spotted) | Pre-empts 3–5 |
| 3 | Kill / dodge confirmation | Pre-empts 4–5 |
| 4 | Friend-arrival sting (existing) | Pre-empts the ping |
| 5 | **Hunt ping** | Lowest. **Skips the beat rather than queueing** — a late ping is worse than no ping, because the whole signal is its rhythm |

Rule for the implementer: the ping must be **droppable**, never buffered. If the buzzer
is busy when a ping is due, that ping is lost and the next one lands on schedule.

**Other gates**, all of which come free by routing through the existing helper:

- The existing `sound` config key (the menu's `Geluid` toggle) mutes it, like
  everything else.
- **Suppressed during a truce and during personal quiet hours** — a badge pinging in a
  tent at 03:00 is precisely what §10.4 exists to prevent. (Training, per §5.9.5, has no
  such logic; this is the *real* game's hunt ping.)
- Silent while dead, while protected, and during a duel (the siren owns the buzzer).
- Below 20 % battery the ping is the first sound dropped (§8.7 lever 4).

##### Cost: not a power concern, and say so

A 40 ms burst at the fastest rate (350 ms) is ~11 % duty on a PWM buzzer that draws a
few mA when sounding — **well under 1 mA averaged**, against a ~150 mA baseline (§8.7).
Buzzer PWM also **does not disable interrupts**, unlike a WS2812 `lights.write()`, so
unlike the LED bar it is safe to run during a GATT link (§5.5). **Do not optimise the
ping for power**; if it needs to be dropped, drop it for noise reasons, never for
battery.

⚠️ One real hazard: `_sting()` is an asyncio coroutine, and `DESIGN.md` §1 records that
a starved CPU produces "a stretched asyncio buzzer chime". A ping whose timing wanders
stops reading as a rate at all. Keep the ping task trivial, and treat audible stretching
as a symptom of a main-loop problem elsewhere rather than something to paper over.

#### 8.8.7 Losing contact

The bar emptying and the ping slowing already say "they are getting away" — that comes
free from the proximity mapping and needs nothing. What is missing is the *moment*:
dropping from three metres to nothing reads identically to drifting apart at forty.

**One explicit cue, cheap:** if the bar falls from **≥ `PING_FROM_SEG` to zero** and
stays there for 3 s, show `KWIJT` on the strip, blink the bar amber twice, and play a
**falling two-note** (the ping's chirp, twice, dropping). Then dark.

The only state this needs is the highest segment reached in the last few seconds, so it
costs one integer and a timestamp. **Do not fire it from higher up the bar** — losing a
faint contact at segment 1 is the normal condition of the game (§3.3) and announcing it
would make the badge chatter constantly.

### 8.9 Language — everything the player sees is Dutch (D26)

**Scope: the whole app, not just Gotcha.** Fri3d is a Dutch-language event with a lot
of children in the audience, and English rules text fails hardest at the moment this
game most needs to be understood — a red screaming screen you have three seconds to
read. The existing nametag, setup, swap and onboarding strings are translated in the
same pass (§11, Phase 2).

#### 8.9.1 The font constraint — read before writing any copy

The UI chrome renders in **built-in lvgl fonts** (`font_montserrat_12/14/16/24/28`,
used throughout `fri3d_friends.py`). In a stock lvgl build these carry **ASCII only**;
a `ë` or `é` renders as a missing-glyph box, and nothing warns you at build time.

> **Rule: all UI copy must be pure ASCII.** This costs nothing in Dutch — write
> `een` not `één`, `overgenomen` not `geërfd`, `Prive` not `Privé`. Where a diacritic
> is unavoidable in meaning, rephrase.

**Player names are the exception and are safe.** The big name label uses the bundled
`montserrat_name.ttf`, a **Latin-1 subset** TTF (`DESIGN.md` §11a), so a player called
`Zoë` or `Renée` renders correctly. Do not "fix" names by stripping accents.

**Verify once on hardware in Phase 0** (both badges are on the bench): render a label
containing `ë é ï` in `font_montserrat_16` and read it back with
`get_all_widgets_with_text()`. If the glyphs are present the ASCII rule can be relaxed;
until then, assume they are not. Screenshots are not available for this check
(`DESIGN.md` §1 — `capture_screenshot()` returns a scrambled buffer).

#### 8.9.2 Register and conventions

- **Address the player as `je`**, never `u`. This is a game at a hacker camp, and half
  the players are nine.
- **Short imperatives on urgent screens.** `RENNEN!` beats `Je wordt aangevallen, loop
  weg`. The under-attack screen must be readable at a glance, from across a field, by a
  child.
- **Keep the English loanwords the audience actually uses**: `badge`, `groep`, `swap`,
  `bluetooth`, `wifi`, `reset`. Translating `badge` to `naamkaartje` would be more
  correct and less clear.
- **Keep it short.** Dutch runs ~15 % longer than English, and this is a 296×240 screen
  with fixed fonts and no reflow. Every translated string must be checked against its
  widget width; several existing labels are already near the limit. Where a phrase
  will not fit, cut it rather than shrinking the font.
  > 🐛 **This already bit once.** The v0.9.0 adopt prompt's title became two lines in
  > Dutch and overlapped the group rows below it, which are positioned with hand-computed
  > `set_pos` offsets (`DESIGN.md` §13.3, fixed 2026-07-28). **Any label that gains a line
  > breaks every hand-positioned widget under it, and only hardware catches it.** Budget a
  > screen-by-screen pass on a real badge, not just a read-through.
- **Numbers, times and units stay as they are** (`22:00`, `-65 dBm`, `30 min`).

#### 8.9.3 The Gotcha strings

The screens in §8.4, in the wording that should ship:

| Screen | Dutch | *(English gloss)* |
|---|---|---|
| Status chip, alive | `LEEFT · reeks 3 · 11 kills` | *ALIVE · streak 3 · 11 kills* |
| Status chip, dead | `UIT · terug om 14:32` | *DEAD · back at 14:32* |
| Target strip | `DOELWIT: Otter 42` | *TARGET* |
| Hunt strip, no action | `A: radar` | *A: radar detail* |
| Hunt strip, reveal | `A: onthullen` | *A: reveal* |
| Hunt strip, attack | `A: AANVALLEN` | *A: ATTACK* |
| Hunt strip, abort own attack | `A: afbreken` | *A: abort* |
| Menu row | `Gotcha` | — |
| Last seen | `laatst gezien: 12 min geleden` | *last seen 12 min ago* |
| Contact lost (§8.8.7) | `KWIJT` | *lost them* |
| Target asleep / truce (§10.4) | `WAPENSTILSTAND` | *truce* |
| Revealing | `ONTHULLEN — zoek de gouden badge` | *look for the gold badge* |
| Spotted (victim) | `GEZIEN! — iemand heeft je gevonden` | *SPOTTED* |
| Attacking | `AANVAL OP Otter 42 — BLIJF DICHTBIJ!` | *KEEP CLOSE* |
| **Under attack** | `JE WORDT AANGEVALLEN — RENNEN!` | *UNDER ATTACK — RUN!* |
| Under attack, can escape | `je kan nog ontsnappen` | *you can still get away* |
| Under attack, at limit | `GEEN ONTSNAPPEN — hij heeft je` | *NO ESCAPE* |
| Dodged | `ONTSNAPT! — de volgende keer pakt hij je` | *YOU GOT AWAY! …next time* |
| Killed | `GOTCHA — uitgeschakeld door <naam>` | *killed by* |
| Respawn countdown | `terug over 28:14` | *back in* |
| Protected | `BESCHERMD — 43 s` | *PROTECTED* |
| Target protected | `Otter 42 — beschermd, 43 s` | *…protected* |
| Target asleep (§10.4a) | `Otter 42 — slaapt` | *…asleep* |
| Bounty banner | `PREMIE: Otter 42 (reeks 7) is dichtbij` | *BOUNTY … is near* |
| Truce | `WAPENSTILSTAND — geen aanvallen` | *TRUCE* |
| No network (§7) | `geen netwerk — check wifi bij Instellingen` | *no network* |
| Demo mode entry | `Laat zien wat de badge doet` | *Show me what the badge does* |
| First-run consent | `Meedoen met Gotcha? Andere spelers zien wanneer je in de buurt bent, en kunnen je opjagen.` | *…will see when you are nearby, and hunt you* |
| Leave the game | `Stoppen met Gotcha?` | *Leave Gotcha?* |

**Terminology, fixed once and used everywhere** — inconsistency here is what makes a
translated UI feel broken:

| English | Dutch | Note |
|---|---|---|
| target | **doelwit** | never `doel` |
| kill (noun) | **kill** | the loanword is what players will say out loud |
| to kill / eliminate | **uitschakelen** | |
| streak | **reeks** | |
| bounty / hit list | **premie** / **premielijst** | |
| reveal | **onthullen** | |
| dodge / escape | **ontsnappen** | |
| respawn | **terugkomen** | avoid `respawnen` |
| truce | **wapenstilstand** | |
| quiet hours | **stiltetijd** | |
| protected | **beschermd** | |
| leaderboard | **klassement** | |
| group | **groep** | matches the existing UI |

#### 8.9.4 Existing strings — the base-app translation has SHIPPED

**The v0.10.0 translation pass is done** (commit `fa7b644` + the v0.10.0 release;
recorded in DESIGN.md §11a.1): `fri3d_friends.py`, `ble_setup.py` and
`docs/setup/index.html` are Dutch. Do **not** re-plan that work. What remains:

- A handful of English remnants in `fri3d_friends.py` — at rev. 5:
  `"join my friend's group"`, `"Skip for now"`, `"no group yet"`,
  `"the button does nothing"`. Grep for stragglers and fix them in passing.
- All **new** Gotcha strings (§8.9.3, §8.9.5) ship in Dutch from the start.
- Anything the player reads counts; log messages, exception text and code
  comments stay English.

#### 8.9.5 Training and update strings

| Screen | Dutch | *(English gloss)* |
|---|---|---|
| Training entry | `Oefenmodus` | *Training mode* |
| Looking for a partner | `Zoek een oefenpartner...` | *looking for a training partner* |
| Partner found | `Oefenpartner: Otter 42` | *training partner* |
| No partner found | `Geen oefenpartner gevonden` | *no partner found* |
| Training chip (permanent) | `OEFENMODUS — 2:14` | *TRAINING — 2:14 left* |
| Practice attack (both sides) | `OEFENING — dit telt niet` | *practice — this does not count* |
| Session over | `Oefenmodus voorbij` | *training over* |
| Re-entry cooldown | `Nog even wachten voor je opnieuw kan oefenen` | *wait before training again* |
| Night courtesy (rules card) | `Oefen 's nachts weg van de tenten, en zet je badge op stil` | *train away from the tents at night, and mute your badge* |
| Soft update hint | `Nieuwe versie beschikbaar — update in de AppStore` | *new version available* |
| Required update | `UPDATE NODIG — open de AppStore en werk de app bij` | *UPDATE REQUIRED* |
| Update, syncing first | `Even synchroniseren voor je update...` | *syncing before you update* |
| Update, safe to go | `Alles opgeslagen — je kan nu updaten` | *all saved — safe to update now* |
| Host broadcast banner | *(server-supplied text, shown verbatim)* | — |

---

### 8.10 Versions, hotfixes and surviving an app update (D27)

**D8 says "no backward compatibility required." That expires on Friday morning.** It is
true only up to the moment badges are handed out; from then on there are ~700 units in
the field, most of which will never be updated during the event, and every change is a
live migration across a population you cannot reach.

#### 8.10.1 The hotfix mechanism you already have is the config push

Before reaching for an app update, note how much is already retunable from the admin
page with **no badge change at all** (§5.4, §9.4): every RSSI threshold, every timer,
`DODGE_LIMIT`, `BOUNTY_STREAK`, streak grace and decay, `SYNC_S`, the truce, scoring
modifiers, and per-player kick/revive/void.

**Add one thing to complete it: per-feature kill switches** in the sync `config` block —
`reveal_enabled`, `bounty_enabled`, `training_enabled`, `alarm_enabled`. If Reveal turns
out to be a nuisance at 14:00 on Saturday, it is switched off camp-wide in one click
and every badge honours it within `SYNC_S`. The badge must treat an absent switch as
`true` so an older backend does not disable features by omission.

**An app update is the escape hatch, not the mechanism.** It is for code bugs that no
config value can route around.

#### 8.10.2 Wire-format discipline during camp

This is the rule that actually preserves compatibility, and it is a *discipline*, not a
feature:

- **Never bump HSNT `ver` during the camp.** Receivers drop unknown versions (§4), so a
  `ver = 3` hotfix partitions the camp into two populations that cannot see each other
  at all. Extend using the **reserved `blocks` bits 1–7 and `gflags` bits 5–7** instead;
  both were reserved for exactly this. (`gflags` bit5 is now spoken for by
  `SEEKING_TRAINING`, §5.9.1 — bits 6–7 remain.)
- **GATT payloads are JSON: additive keys only.** Responders must ignore unknown keys
  rather than rejecting the message — an updated hunter must still be able to kill a
  non-updated victim.
- **Sync responses: the badge ignores unknown keys** (`GameConfig.from_sync` is already
  specified as a defensive parse, §8.1) and treats absent keys as defaults.
- **The backend accepts events from old app versions indefinitely.** Never gate event
  ingest on a version.

#### 8.10.3 Seeing the fleet, and nudging it

- **Report the version.** `app_version` already rides `/v1/enroll` (§9.2); add it to
  `heartbeat` (§9.3) so it is refreshed continuously. The admin dashboard gets a
  **version histogram** (§9.4) — you cannot manage an update you cannot see.
- **Sync response gains** `min_app_version`, `latest_app_version`, and a free-text
  `broadcast` (§9.2).

| Badge version | Behaviour |
|---|---|
| ≥ `latest_app_version` | nothing |
| ≥ `min_app_version` | one dismissible line: `Nieuwe versie beschikbaar — update in de AppStore` |
| < `min_app_version` | prominent `UPDATE NODIG` screen with instructions |

> ⚠️ **An out-of-date badge must stay killable.** If falling behind removed you from the
> game, then *not updating* becomes perfect invulnerability — the identical failure mode
> that D3 exists to prevent ("close the app" must not be a shield). So a badge below
> `min_app_version` stops **hunting** (no attack, no reveal) but its **victim-side
> responder keeps running**. If the incompatibility is severe enough that the responder
> cannot work either, the badge simply looks unreachable and the existing dormancy
> machinery (§3.2) splices it out — which is correct, not a special case.

**`broadcast` is worth more than the version nudge alone.** A free-text line the host
can push to every badge within `SYNC_S` covers "update de app", "spel gepauzeerd", and
"prijsuitreiking om 17:00 op het hoofdpodium" with one mechanism. Render it in the
existing arrival-banner widget. Cap it hard (say 120 chars) and never let it be
interpreted as anything but text.

#### 8.10.4 ⚠️ Data survival across an update — this is broken *today*

**Every persistent file lives inside the app directory**, which is what an AppStore
update replaces:

```
/apps/com.fri3dcamp.fri3dfriends/config.json     name, groups, sound, rssi_floor, quiet hours
/apps/com.fri3dcamp.fri3dfriends/contacts.json   every contact ever swapped
/apps/com.fri3dcamp.fri3dfriends/gotcha.json     pid, player_key, soul, score, event queue  (§8.2)
```

**Whether a MicroPythonOS AppStore update preserves or wipes that directory is not
known.** It has never been tested, and the answer changes what has to be built. **This
is now the single highest-value thing to verify on the bench** — see §14.2.

If it wipes, the damage is very unevenly distributed:

| File | Recoverable? |
|---|---|
| `config.json` | Painful but survivable — the player retypes their name and groups, or re-adopts a group with a Y-swap. **They land back on the "Stel me in" screen**, which will read as "the update broke my badge". |
| **`contacts.json`** | ❌ **Not recoverable. There is no server copy, and there never will be — the contact swap is deliberately offline-only.** Every contact a player collected is gone. |
| `gotcha.json` | Mostly fine: `badge_key` (the BLE MAC) is stable, and §10.5 already specifies re-enroll → **same `pid`, score intact**. The genuine loss is the **unsent event queue** — kills landed since the last sync. |

> 🐛 **This is a pre-existing bug in the shipping v0.9.0 app, not a Gotcha problem.**
> `contacts.json` is irreplaceable user data sitting in a directory an update may
> replace. It is worth fixing regardless of whether Gotcha ever ships.

**What to build:**

1. **Verify the behaviour first** (§14.2). If updates preserve the directory, most of
   the rest of this is unnecessary and should not be built.
2. **If they wipe: move persistent state out of the app directory** — or, if
   MicroPythonOS offers no per-app data location outside it, write a copy of
   `config.json` + `contacts.json` somewhere the installer does not touch and restore
   on first run after an update. Keep the atomic temp-file + `os.rename` pattern.
3. **Flush before updating, always.** The `UPDATE NODIG` screen must sync first, show
   `Even synchroniseren voor je update...`, and only then say
   `Alles opgeslagen — je kan nu updaten`. This is what turns the one genuinely
   unrecoverable Gotcha loss (the queue) into no loss at all, and it is cheap.
4. **Handle the soul rotation.** Re-enrolling after a wipe issues a fresh soul and
   commitment, so a hunter still holding the old commitment cannot verify a kill for up
   to `SYNC_S`. The backend must **accept the previous commitment for a grace window**
   (15 min) rather than voiding an otherwise legitimate kill.

#### 8.10.5 Why not an OTA updater

Rejected deliberately. MicroPythonOS already has a sanctioned install path and badges
already have the AppStore on them. Writing a self-updater that runs on 700 devices,
three weeks before the event, with the failure mode "badge no longer boots", is a bad
trade against a nudge screen and a config push that cover the realistic cases. The
`.mpk` build and BadgeHub publish flow in `README.md` stays the release mechanism.

---

## 9. Backend contract

**Stack (settled at rev. 5): Python / FastAPI + SQLite, in `server/` in this
repo**, run under systemd (§6.1), tested in the existing pytest suite with a
**badge-simulator fixture** that drives the HTTP API as N fake badges (the
Phase 1 harness, §11). Requirements: **HTTPS on `/v1/enroll` and on the web
pages, plain HTTP on everything else** (§6.2, D31), ~2.3 req/s sustained, and
something operable from a phone at a muddy campsite.

### 9.1 Auth

- **Badge:** **HMAC-SHA256 request and response signing** with `player_key` (§6.2) —
  headers `X-Pid`, `X-Ts`, `X-Nonce`, `X-Sig`. There is **no bearer token**; nothing
  replayable crosses the link. `player_key` is issued once over HTTPS at enrollment,
  stored in `gotcha.json`, and never displayed or re-transmitted.
  - Server rejects `X-Ts` outside ±10 min and replays a nonce cache for that window.
  - Server **signs every response**, binding the request nonce. The badge discards
    unsigned or mis-signed responses — without this, a MITM could inject "truce off"
    or a fake target over plain HTTP.
- **Player web page:** public data only; the QR encodes
  `…/gotcha/?badge=XXXX&t=<short-lived read token>` for the private view (your
  target). The QR is rendered **on the badge**, in the Gotcha screen, exactly as
  the setup window already renders its setup QR (`_update_setup_qr` is the
  pattern); the token rides the sync response.
  The pages are **served by the backend itself** (D31) over Let's Encrypt HTTPS,
  same origin as the API — D21 governs the *badge* path only.
- **Host:** session login on `/admin` over HTTPS, reachable from a phone.

### 9.2 Player endpoints

```
POST /v1/enroll                                    *** HTTPS — the only TLS call ***
  { badge_key, display_name, groups[], commitment, app_version, board }
  -> { pid, player_key (32 B hex), game_id }
  Idempotent on badge_key: re-enrolling returns the existing pid and a fresh key.
  Unsigned (the badge has no key yet); rate-limit by IP and badge_key.

--- everything below: plain HTTP, signed both ways (§6.2, §9.1) ---

GET /v1/sync
  -> { server_time,
       game:   { id, state, truce_active, truce_until, truce_schedule, modifiers },
       me:     { pid, alive, respawn_at, protected_until, streak, best_streak,
                 total_kills, rank_total, rank_streak, dodges: {attacker_pid: left} },
       target: { pid, name, commitment, last_seen_ago_s } | null,
       hitlist:[ { pid, name, streak } ],          # capped at 16
       app:    { min_version, latest_version },    # §8.10.3, the update nudge
       broadcast: "<=120 chars of host text" | null,   # §8.10.3, shown as a banner
       config: { KILL_RSSI, KILL_HOLD_MS, ...,     # §5.4, live-tunable
                 reveal_enabled, bounty_enabled,   # §8.10.1 kill switches;
                 training_enabled, alarm_enabled } }  # absent == true
  Every SYNC_S (300 s), jittered. The ONLY thing the badge polls.

POST /v1/events   { events: [ Event, ... ] }   # batched from the offline queue
  -> { accepted: [uuid], rejected: [{uuid, reason}] }
  Idempotent on Event.uuid.

GET  /v1/leaderboard?board=total|streak|group_total|group_per_member&limit=50
```

### 9.3 Event types

Every event carries `uuid`, `pid`, `at` (badge clock, offset-corrected), and `ticks`.

| `type` | Payload | Backend action |
|---|---|---|
| `kill` | `victim_pid`, `soul`, `as`, `rssi` | Verify `sha256(soul)`; score §2; repair ring. (**No `witnesses[]` in v1** — D30. The parser tolerates the key so an app update can revive it.) |
| `killed_by` | `attacker_pid`, `new_commitment` | Confirm death, rotate commitment |
| `dodge` | counterpart pid, `rssi_at_escape` | Decrement `dodges_left`, log |
| `attack_started` | `victim_pid` | Cooldown bookkeeping, abuse detection |
| `reveal` | `target_pid`, `rssi` | Log only. Feeds the audit page (§9.5) — someone standing in a crowd flashing strangers shows up here. |
| `revealed` | `hunter_pid` | Log only. Also a **liveness signal for §10.1**: being revealed proves you were physically near someone, so it refreshes `last_seen`. |
| `heartbeat` | `alive`, `target_seen_ago_s`, `peers_seen`, `battery`, `groups[]`, `quiet{from,to}`, `app_version` | Liveness, stale-target detection, group snapshot, personal quiet window (§10.4a) so the server can re-check it on ingest. **Cadence: queued once per `SYNC_S`**, immediately before the sync flush, so every sync carries exactly one. |
| `optout` / `optin` | — | Splice out of / into the ring |

### 9.4 Admin endpoints

```
POST /v1/admin/game            create (name, start, end, tunables)
POST /v1/admin/game/<id>/state {state: lobby|running|paused|ended}
POST /v1/admin/truce           {active, until, reason}      # instant camp-wide
POST /v1/admin/broadcast       {text|null}                  # §8.10.3, <=120 chars
POST /v1/admin/appversion      {min_version, latest_version}
POST /v1/admin/modifier        {type: double_points|amnesty, from, to}
POST /v1/admin/player/<pid>    {action: kick|revive|void_kill|adjust|reassign|protect}
POST /v1/admin/player/<pid>/rebind  {new_badge_key}    # badge broke — see below
GET  /v1/admin/dashboard       the live numbers below
GET  /v1/admin/audit           suspicious-pattern report
GET  /v1/admin/export          full CSV/JSON dump
```

Admin actions land on every badge within `SYNC_S`. Nothing needs a push channel: the
one thing that must be instant — the attack alarm — is BLE-local.

**Badge replacement (`/rebind`).** A badge will break, get lost, or go in a puddle, and
"you have lost 11 kills and your streak" is not an acceptable answer at a camp. Rebind
points an existing `pid` at a **new `badge_key`**, preserving score, streak, ring
position and target. The old `badge_key` is tombstoned so the dead badge cannot
re-enroll into the same identity. The new badge enrolls normally, gets a **fresh
`player_key` and a fresh soul/commitment** (its old life's soul is gone with the old
badge), and lands with `SPAWN_PROTECT_S` of protection so the swap is not itself a
death sentence. This is distinct from the existing "`gotcha.json` wiped, same badge"
path (§10.5), which needs no admin action at all.

**The live dashboard.** Endpoints are not a screen; this is the screen. A host at a
muddy campsite needs to answer "is the game alive?" in one glance, on a phone:

| Group | Numbers |
|---|---|
| Population | enrolled · alive · dead-awaiting-respawn · protected · opted out · **dormant** |
| Tempo | kills total · **kills last hour** · **kills last 10 minutes** · reveals last 10 minutes |
| Health | badges synced in the last 15 min · **badges not seen for > 1 h** · queued-event backlog · ring conflicts (§3.2 step 4) |
| Fleet | battery histogram · **count below 20 %** · app-open vs background-service split · **app-version histogram** (§8.10.3) |
| Leaders | top 5 individual, top 3 per group board, current hit list |

**Kills in the last 10 minutes is the single most important number on the page** — it
is the only one that distinguishes "the game is running quietly" from "the game has
silently stopped working", which §3.3 names as the most likely failure mode. Put it
first and make it big.

**Multiple hosts, concurrently.** Several volunteers with several phones is how a camp
actually gets run, so admin state lives server-side with no local session assumptions,
and the dashboard polls (5 s) rather than holding a socket. No SignalR, no websockets,
no realtime framework: at 700 players the dashboard is a few KB of JSON and a `setInterval`.
Admin actions are logged with **which** host performed them.

### 9.5 Anti-cheat

**Cryptographically enforced:** a kill requires the victim's soul (§3.4). No soul, no
kill.

**Rule-enforced server-side:** truce windows, respawn timers, attack cooldowns,
repeat-kill scoring, dodge limits, streak decay, target validity. **Never trust
badge-side enforcement** — the badge enforces the same rules only so the offline UX is
correct; the backend re-checks everything on ingest.

**Detected, not prevented.** Sybil farming is the real hole, and D16 (no kill
cooldown) removes the natural rate limiter, so the detection side has to carry it:

1. **Rate limits — flag, do not block.** Legitimate table sweeps are explicitly legal
   (D16), so `MAX_KILLS_PER_HOUR` (default 10) marks kills for review rather than
   refusing them. Refusing a real sweep would break the best moment in the game.
2. **Graph shape.** Mutual-only kill pairs, players who only ever interact with each
   other, enrollments clustered in time from one IP, `heartbeat.peers_seen`
   persistently near zero around a player's kills (a farm in a tent sees nobody).

*(Rev. 1–4 also specified **witness overlap** — both parties reporting up to 8
nearby `pid`s per kill. **Dropped for v1 by D30**: it was the only field whose
plaintext exposure revealed anything the game does not already publish. The event
parser tolerates a `witnesses` key so an app update can revive it if farming
actually appears.)*

The host can void kills, revive victims, adjust scores and kick. **This is the correct
posture for a hacker camp:** make cheating possible, visible and socially expensive
rather than pretending an open flashable badge is tamper-proof.

### 9.6 The state model

Adapted from the other proposal's §13, which listed *Registered, Waiting,
JoinProtection, Active, Shielded, Eliminated, Offline, Updating, Defective*. That list
is a useful checklist but not a usable state machine, because it mixes **exclusive
states** (Active, Eliminated) with **orthogonal conditions** (Offline, Shielded) and
with **operational facts about hardware** (Defective, Updating). A badge can be Active
*and* Offline; it cannot be Active *and* Eliminated. Split accordingly.

**A. Server-side player status — exclusive, one per player, drives the ring.**

| Status | In the ring? | Attackable? | Enters when | Leaves when |
|---|---|---|---|---|
| `active` | yes | yes | Enrolled and past protection | Dies, opts out, goes dormant/stale |
| `protected` | yes | **no** | Enroll or respawn (§5.8) | 90 s elapse, or they attack |
| `dead` | **spliced out** | no | Killed | `respawn_at` passes → `protected` |
| `opted_out` | spliced out | no | Rule 15 (Gotcha screen / web) | Opts back in → `protected` |
| `dormant` | spliced out | no | No sync for `DORMANT_H`, truce-adjusted (§2.4 — use 12 h) | Any sync → `protected` |
| `stale` | **hunts, is not hunted** | no | Not seen by *anyone* for `TARGET_STALE_H` (§10.1) | Seen again by anyone |
| `kicked` | spliced out | no | Host action | Host action |
| `retired` | spliced out | no | `badge_key` tombstoned by `/rebind` | never |

`stale` is the one genuinely asymmetric status and it is worth the complexity: a player
whose badge is in a tent should stop *stranding their hunter* without also being told
they are out of the game when they pick it up ten minutes later.

**B. Badge-local state — what the badge believes between syncs.**

Exclusive: `NOT_ENROLLED` → `ENROLLING` → `HUNTING` ⇄ `REVEALING` / `ATTACKING` /
`UNDER_ATTACK` / `SPOTTED` → `DEAD` → `HUNTING`. Plus `NO_TARGET` (ring of one) and
`OPTED_OUT`.

Orthogonal flags, any combination: `PROTECTED`, `TRUCE`, `OFFLINE` (queue non-empty or
last sync failed), `LOW_BATTERY`.

**The badge is authoritative for exactly one thing: its own death** (§10.2). Everything
else it holds is a cache of the server's status, and the server re-derives all of it on
ingest.

**Deliberately not modelled:**
- **`Shielded`** — we have no shield item (§5.8 protection is a timed status, not a
  consumable), and adding both a shield and a dodge would give the game two overlapping
  defensive systems.
- **`Updating`** — there is no OTA path (D27, §8.10.5); badges are updated by hand
  from the AppStore. An out-of-date badge is not a distinct status: it keeps its normal
  status and simply stops hunting (§8.10.3), because a version that removed you from
  the game would make *not updating* a shield.
- **`Defective`** — not a player status. A broken badge is a *reason* for `/rebind`
  (§9.4), after which the player is `protected` on new hardware and the old
  `badge_key` is `retired`. Modelling hardware faults as game states would put a
  soldering-iron problem into the scoring engine.

---

## 10. Edge cases and real-camp dynamics

### 10.1 The hunt stalls (D17)

- The badge shows **"last seen by anyone: N min ago"**, from other players'
  heartbeats. That single number is the difference between "keep looking" and "this
  person's badge is in a tent" — and it needs no new telemetry.
- After `TARGET_STALE_H` (6 h) with no sighting **by anyone**, the backend reassigns.
- The bounty layer is the safety valve: even with an unreachable assigned target,
  there is usually *someone* killable in range.
- **Explicitly rejected:** AP-based coarse location and witness-graph social hints.
  Both would work; both are location tracking of children. Not built.

### 10.2 Duel edge cases

| Situation | Behaviour |
|---|---|
| Victim powers off mid-duel | Link drops → counted as a dodge. **A known exploit**: pull the battery to survive. Accepted — it costs them all their own play time, and it is not worth the complexity to close. |
| Both parties attack each other at once | Single connection slot; first `ATTACK` write to land wins, the other gets `BUSY`. |
| Attacked while attacking | Refused (`BUSY`) — §5.5. |
| Victim already dead but hasn't synced | Responder answers `ALREADY_DEAD`; assassin gets nothing and pays no cooldown. |
| Assassin's target changed since last sync | The **victim's badge is the authority for its own death** — if it accepted the duel it dies. The backend then reconciles: an invalid pairing is voided **and the victim is revived** with streak restored. A stale assassin must never be able to permanently cost someone their streak. |
| Truce begins mid-duel | The duel completes. The truce gates *new* attacks only. |
| Either party's **personal quiet hours** begin mid-duel | Same rule — the duel completes (§10.4a). |
| Attack or reveal attempted into someone's personal quiet hours | Refused by the responder; the hunter's badge should not have offered it, since `gflags` bit3 is set on air. **No cooldown charged.** |
| Player tries to attack *during their own* quiet hours | Blocked badge-side before the connection is attempted, and re-checked server-side on ingest. Symmetry is what stops quiet hours being an invulnerability exploit (§10.4a). |
| Two assassins on one bounty player | Single slot; second gets `BUSY`. |
| Victim sitting in a setup window or swap | Refused **only while a GATT link is actually live** (§5.5) — not merely because a window is open. That shrinks the exposure from `SETUP_ABS_CAP_MS` (10 min) to the seconds a phone is really talking. While a game is running, also shorten the absolute cap to **3 min**. |
| Victim sitting on an adopt prompt | **Attack proceeds normally.** The prompt touches no radio, so the responder ignores it. The prompt additionally auto-dismisses after 30 s (§5.5). |
| RSSI spike causes a false dodge | Use the smoothed `rssi_ewma` and require `FLEE_MS` sustained, never a single sample. |
| Rapid re-attack after a dodge | `ATTACK_COOLDOWN_MS` (60 s) per pair. |
| **Assassin aborts a live attack** | **Allowed, and treated as a skill.** Press A again during the hold (`A: afbreken`, §5.7): the duel ends, the victim's alarm stops, **no cooldown is charged and the victim's dodge is not consumed.** It is a real tactical choice rather than a free escape — letting a failing attack run to a dodge *burns* the victim's single dodge (rule 5) and makes your next attempt an instant kill, so aborting trades that away to keep attacking now. |
| Reveal lands while the target is in a duel with someone else | Responder answers `BUSY`; **no cooldown charged** to the hunter. |
| Target walks out of range between reveal and attack | Nothing special — the reveal already did its job, and the cooldown runs. This is the normal case. |
| Reveal fires but the target is not wearing the badge visibly | The reveal is spent and the hunter learns nothing. Accepted: it is the same information asymmetry as looking for a face. |
| Reveal during truce | Refused on **both** sides — the hunter's badge does not attempt the connection, and the responder refuses if it somehow arrives. Same defence-in-depth as the siren (§10.4). |
| Attack against a `PROTECTED` player | Refused with `PROTECTED`; **no cooldown charged**. The hunter's badge shows the remaining seconds from `gflags` bit4, so this should rarely be attempted. |
| Protected player attacks someone | Protection drops **at the moment the `ATTACK` write is sent**, not when the duel resolves — a failed or dodged attack still forfeits it. |
| Protected player is killed by a stale assassin who had not synced | The **victim's badge refuses the duel outright** (it knows it is protected), so this resolves at the responder, not by later reconciliation. |

### 10.3 Sync, offline and clock

| Situation | Behaviour |
|---|---|
| Badge RTC never NTP-synced | Server receive time is authoritative; `clock_offset_s` corrects local truce/decay checks (§8.3). |
| Queue overflow | Drop oldest non-kill first; never drop a `kill`/`killed_by`. |
| Duplicate upload | Idempotent on `Event.uuid`. |
| Only the assassin reports | Accept on soul proof alone; apply the death when the victim returns. |
| Only the victim reports | `killed_by` names the attacker — credit the kill immediately, dedupe by `(victim_pid, life_id)` when the assassin's copy arrives. `life_id` is a **server-side per-player death counter** (0 at enrollment, +1 per confirmed death); it never crosses the wire — the server derives it from whichever report lands first. |
| Backend down for hours | Everyone queues. **Dormancy must pause when global sync volume collapses**, or a server outage would mass-dormant the entire camp and shred the ring. |
| 08:00, everyone powers on at once | **Jitter the sync schedule ±20%** — 700 simultaneous syncs is a self-inflicted DDoS. |

### 10.4 Night, sleep and powered-off badges (D7)

- **Truce 22:00–08:00.** Checked on the badge from cached config + corrected clock, so
  it holds with no network, and re-checked server-side on ingest.
- **The siren is suppressed during a truce unconditionally**, even if a duel somehow
  starts. Defence in depth: the failure mode is a screaming badge in a tent full of
  sleeping children.
- **The hunt ping is suppressed too** (§8.8.6), during both the camp truce and personal
  quiet hours. A badge pinging steadily at 03:00 is a quieter version of the same
  failure. (Training mode is the deliberate exception — §5.9.5.)
- ⚠️ **A truce halts *detection*, not just attacks.** The radar bar goes **dark** and the
  ping goes silent; the Gotcha strip says `WAPENSTILSTAND` instead of showing range. A
  halt that still let you watch your target's distance would not be a halt — it would be
  a scouting window, and the obvious play becomes parking outside someone's tent at
  07:55 with perfect information. **This is a UI suppression, not a radio change:** the
  scan keeps running because the base app's friend finder depends on it (§8.6).
- **The halt is per-pair and evaluated locally.** Your radar for a given target goes dark
  if **either** side is in a truce or in personal quiet hours. The target's `gflags` bit3
  `TRUCE` is already on air (§4), so the hunter's badge decides this with no server
  round-trip and no extra traffic. The strip reads `Otter 42 — slaapt`: you learn *that*
  they are unavailable, never *where* they are. Bounty banners are suppressed on the
  same rule.
- **Streak decay excludes truce hours** — sleeping costs you nothing.
- **Dormancy accounting pauses during truce plus a 1 h grace**, so a badge switched
  off overnight is not spliced out of the ring by morning.
- **Respawn timers keep running during truce** — dying at 21:50 means you wake up
  alive. Deliberately kind.
- On power-on the badge does not need a sync to know the truce; the cached schedule
  is enough.

### 10.4a Personal quiet hours (D25)

**The problem.** The camp truce starts at 22:00. A lot of the children at Fri3d are
asleep well before that, and a badge that screams at 20:45 in a family tent is exactly
the outcome §10.4 exists to prevent.

**Why not separate child and adult games** (the other proposal's §4/§19): it would
require the system to record **which badges belong to minors**, which is a category of
data this design has otherwise gone out of its way not to hold (D17, §13). It would not
even deliver the safety it implies, because bounties (rule 10) and target inheritance
(rule 7) both cross cohorts — making it a real guarantee means two fully disjoint
games, two hit lists, eight leaderboards and two ceremonies. And it would delete the
best story the game can produce, which is a ten-year-old taking out an adult.

**The mechanic instead.** Any player may set a personal quiet window on their own
badge. It is not age-gated, nothing records why it was set, and it serves an adult who
wants to sleep at 21:00 identically.

| Property | Rule |
|---|---|
| Bounds | Start no earlier than `QUIET_EARLIEST` (20:00); end no later than `QUIET_LATEST` (10:00). The camp truce is always contained within it. |
| Default | Exactly the camp truce, 22:00–08:00 — i.e. setting nothing changes nothing. |
| Effect inbound | You cannot be attacked or revealed. |
| **Effect outbound** | **You cannot attack or reveal either.** Non-negotiable — see below. |
| Streak decay | **Not** paused (§2.2). Only the camp truce pauses decay. |
| Visibility | Sets `gflags` bit3 `TRUCE` on air, so a hunter's badge reads *"Otter 42 — asleep"* instead of refusing without explanation. |
| Where it lives | `config.json` under `gotcha.quiet`, through the existing `sanitize_config` — so it is settable from **both** the phone setup page and the on-badge editor, and cannot be clobbered by a partial save. |
| Enforcement | Badge-local (cached schedule + `clock_offset_s`, so it works with no network), re-checked server-side on ingest. |
| Dormancy | Dormancy accounting pauses through the player's **personal** window plus the existing 1 h grace, not just the camp truce — a badge switched off at 20:00 must not be spliced out by morning. |

**The two ways this could be abused, and why it isn't:**

1. **"I'll be unkillable all evening and keep hunting."** Closed by making the window
   symmetric. Quiet hours are a truce, not a shield; if you cannot be attacked you
   cannot attack. This is the single most important line in this section — an
   asymmetric version would be a straightforward invulnerability exploit and every kid
   would find it on Friday afternoon.
2. **"I'll declare 20:00–10:00 quiet hours and freeze my streak overnight."** Closed by
   §2.2: personal windows do not pause decay. Fourteen hours of personal quiet costs
   you the four hours outside the camp truce, at −1 streak per 2 h. Sleeping early is
   free in safety and paid for in crown.

**No age or cohort field is stored anywhere** — not in `config.json`, not in
`gotcha.json`, not in the backend schema. If a future version wants a children's
leaderboard, that is a display-layer opt-in and must not become a gameplay input.

### 10.5 Ring, identity and groups

| Situation | Behaviour |
|---|---|
| Inheritance yields yourself | Walk forward to the next alive player. |
| Inheritance yields a dead player | Walk forward. |
| Inheritance creates a group conflict | One re-splice attempt, then accept and log (§3.2). |
| Group constraint unsatisfiable | Start the game anyway; surface the conflict count on the admin page. |
| Player changes name mid-game | Pushed to their hunter on the next sync. |
| Player changes groups mid-game | Kills keep the snapshot they were scored with (§2.3). |
| `gotcha.json` wiped | Re-enroll by `badge_key` → same `pid`, score intact. |
| Two players, same display name | Disambiguate with `#pid` in the UI. |
| **Badge broken, drowned or lost** | Host runs `/v1/admin/player/<pid>/rebind` (§9.4): score, streak, ring position and target survive onto the new badge; fresh `player_key` and soul; lands `protected`; old `badge_key` `retired`. |
| Badge stolen, or a player caught cheating | Host kicks from the admin page. |
| Target opts out mid-hunt | Immediate reassign on next sync. |

---

## 11. Phasing

**Phase 0 — hardware spike (blocking).** Six questions, all cheap to answer and all
capable of invalidating downstream work. **Do §14.2 A5 (the AppStore-update wipe
test) first** — it is the cheapest high-value test in this document and it decides
whether §8.10.4 gets built at all.

1. **WiFi + BLE coexistence.** They share one 2.4 GHz radio and the dense 50 %-duty
   scan is load-bearing (`DESIGN.md` §3). Measure peer-detection rate and `last_seen`
   age with WiFi associated and syncing, versus WiFi off. *If coexistence badly
   degrades the scan, the architecture needs revisiting.*
2. **Sync durability (§6.2).** Run the `gc.mem_free()` heap check, confirm one
   enrollment HTTPS handshake succeeds, then soak **1000 consecutive signed
   plain-HTTP syncs** for heap stability. Verify the hand-rolled HMAC-SHA256 against
   RFC 4231 vectors on-device, not just on host.
3. **Third GATT service** fits alongside the existing two in one
   `gatts_register_services` call.
4. **Scan duty reduction** (§8.7 lever 2): does 30 ms/240 ms keep NimBLE's duplicate
   filter off and presence stable? Worth ~37 mA if it does.
5. ⚠️ **RSSI trend — "warmer or colder" (§8.8.2a).** **The single most load-bearing
   untested assumption in the design.** Run the four-condition walk protocol (open
   field, tent, bodies in between, badge in a pocket) against the stated success
   criteria, and come out with a `(TREND_ALPHA_FAST, TREND_ALPHA_SLOW,
   TREND_DEADBAND_DB)` triple that works in all four — or with the knowledge that it
   does not work. Everything the hunt feels like rests on this, and it is cheap to
   answer: two badges, a walk, and a plot.
6. **Screen blanking on 2024** (§8.7 lever 1): can the GC9307 be put to sleep
   directly, given there is no backlight API? Highest-value power fix if yes.

Deliverable: findings appended to `DESIGN.md`, and a go/no-go.

*(The original spike item "does 2 Hz `adv_data` swapping survive?" is gone — D8 let us
collapse to a single v2 beacon.)*

**Phase 1 — backend + admin.** FastAPI + SQLite in `server/` (§9): API, scoring
(§2), ring (§3.2), admin console, and the backend-served player/admin pages'
skeleton. Fully testable with the **badge-simulator pytest fixture** (N fake
badges driving enroll/sync/events over HTTP); no badge required.

**Phase 2 — badge: connectivity check, enrollment, sync, v2 beacon, radar.** No kills.
Includes the **widened peer admission + pinned LRU** (§4), the **LED radar bar
replacing the friend LEDs** (§8.8), the **hunt strip + `Gotcha` menu row + focus
integration** (§8.4, D29), and **demo mode** — all independent of the duel and
all of which make Phase 3 far easier to test in the field. Includes the **hunt
ping** (§8.8.6) — it shares the bar's proximity clock, so building it alongside
costs almost nothing and makes the radar testable by ear in a field. The base-app
translation has shipped (§8.9.4) — only the new Gotcha strings and the listed
English remnants are in scope. Training mode is **not** here — see Phase 6. Ends
with two badges enrolled, each showing the other as target with a live on-screen
radar bar *and* a live LED bar.

**Phase 3 — the duel and the Reveal.** Handshake, alarm, dodge, soul disclosure,
inheritance, reporting, plus **Reveal (§5.7)** and **spawn protection (§5.8)**. The core
fun. Ends with a real two-badge chase across a field. **Build Reveal first** — it is a
much simpler GATT interaction than the duel (write, ack, disconnect, flash), it
exercises the same connect path, and having it working makes every subsequent duel test
easier to set up.

**Phase 4 — background participation** (D3). The fragile one; see §5.6.

**Phase 5 — web pages, and the update path.** Player card, four leaderboards, hit
list, QR flow — **served by the backend** (D31), over Let's Encrypt HTTPS
(DNS-01; the DNS-host API check in §14.1 gates this). Plus §8.10: version
reporting, the `broadcast` banner, the feature kill switches, and whatever
§14.2's AppStore-update test turns out to require.

**Phase 6 — scale and soak.** As many badges as can be assembled, running for hours.
Watch RAM, the peer-table LRU, backend load, and **median time-to-first-kill**
(§3.3). **Measure all five power scenarios in §8.7 with an inline USB meter, on both
board generations.** Then a rules card, and a dry run with a dozen willing humans
before 14 August.

**Training mode (§5.9) lands here, last, and is explicitly droppable.** Nothing else
depends on it — two dev badges in a throwaway backend game are a better protocol test —
so if the schedule tightens, cut it without renegotiating anything else.

---

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **WiFi/BLE coexistence degrades the scan** | **High** | Phase 0 gates everything. 5-min sync (D13) already minimises exposure. |
| Signed plain HTTP: traffic is readable on the camp network | Low | Accepted (D21). Kill proofs are self-authenticating and scores are published; responses are signed so nothing can be injected. Noted in §13. |
| **Background GATT + radio handoff** (§5.6) | **High** | `ensure_radio` self-heal is the precedent; budget hardware time; be willing to ship Phase 4 late. |
| Unbounded `seen` table at 700 badges | High | LRU cap — fix regardless of Gotcha. |
| Camp uplink down → badges cannot resolve the game hostname | Low | Server is on site with internal routing (D31); the residual risk is DNS resolution — §14.1 A8's arrival-day check, with the IP-literal fallback in §6.3. D6 means play continues regardless. |
| Kids running into things | **High (real-world)** | Truce, safe-zone rules, "no running" on the card, host truce button. |
| **Battery: app already gets only ~11 h; Gotcha naively cuts it to ~7 h** | **High** | §8.7. WiFi DTIM power save, reduced scan duty, screen blanking, battery-aware degradation. Measure in Phase 6. |
| Group exclusion makes targets unfindable | Medium | §3.3, §10.1; watch time-to-first-kill in the soak. |
| **RSSI trend does not track real movement** | **High** | §8.8.2a. The hunt's core promise ("warmer or colder") is unimplemented today and unproven. **Phase 0 item 4b gates it**, with pass criteria fixed in advance. Fallback is the absolute bar alone — which works, but is a materially worse game and would require rewriting the narrative to stop promising something the badge cannot do. |
| RSSI at a real camp ≠ RSSI on a bench | Medium | Every threshold is server-tunable live (§5.4). |
| Sybil / collusion | Low | Detected not prevented (§9.5); host can void and revive. |
| Badge never joined WiFi; player cannot tell the game is broken | Medium | Explicit `no network — check WiFi in Settings` state (§7), never silent absence. |
| **Reveal is mistaken for an attack** and someone bolts through a crowd | Medium | The two are deliberately unmistakable: gold + single chirp + `SPOTTED` versus red + siren + `RUN`. **Demo mode (§8.4) exists largely to teach this difference before it matters.** Verify with real children in the Phase 6 dry run, not just with adults who read the rules card. |
| Reveal spam in a crowd | Low | Self-limiting (it warns your target), `REVEAL_COOLDOWN_S` on top, and `reveal` events land on the audit page (§9.5). |
| **An AppStore update wipes `contacts.json`** | **High** | §8.10.4. Irreplaceable user data with no server copy, in a directory an update may replace. **Affects the shipping v0.9.0 app already.** Verify on the bench (§14.2) before doing anything else about it. |
| A hotfix bumps HSNT `ver` mid-camp and splits the population | Medium | §8.10.2: never bump `ver` during the event; the reserved `blocks`/`gflags` bits exist for exactly this. Put it in the release checklist, not just the plan. |
| Nobody updates, and a needed fix never lands | Medium | Accept it. §8.10.1 is the real answer: make fixes server-side, and keep the version histogram (§9.4) honest about the fleet you actually have. |
| Training corrupts real game state | **High if built carelessly** | §5.9.3, three named disciplines: target **override** (never a save/restore, which corrupts on a mid-session crash), a **disposable soul** (a real one is a bankable kill), and **presentation-only death** (or "let's train" removes someone for 30 min and burns their dodge). Each closes a specific exploit — review them individually. |
| Training used as a shield | Low | §5.9.4: no connection held open, real attacks honoured between duels and abort the session, beacon flags stay honest, plus the session cap and re-entry cooldown. |
| Training siren wakes people at night | Low (social) | **Deliberately not coded against** (§5.9.5) — both parties consented, and gating it would mean dragging the truce schedule and personal quiet windows into the training path for no gain. A rules-card line, like rule 14's safe zones. |
| Removing the friend LEDs is felt as a loss | Low | §8.8.1: no *information* is lost (friends panel + pills are unchanged), the hunt bar is far more legible than one shared LED would have been, and average LED power falls. Revisit only if players actually complain. |
| **Abort-spam used to harass** (§10.2) | Medium | A free abort means a hunter can make a victim's badge scream repeatedly at no cost. Not prevented: every attempt is already logged as `attack_started` (§9.3) and lands on the audit page, and the behaviour is *extremely* public — your badge is making someone else's badge shriek, in front of people. Consistent with §9.5's stated posture. **If the dry run shows abuse, the fallback is a short (~20 s) cooldown on abort**, which keeps the tactical choice and kills the spam. |
| **The hunt ping becomes a camp-wide noise floor** | Medium | §8.8.6's silent floor (`PING_FROM_SEG`, default 3 of n) is the main defence — most of the time a target is detected but far, and that state stays silent. `PING_ENABLED` is a server-side kill switch if it is still too much on Friday afternoon. **Judge it in the Phase 6 dry run with a dozen badges in one tent, not on a bench with two.** |
| The 2024's 4-LED bar reads differently from the 2026's 5 | Low | §8.8.2: the bar is proportional, and colour carries the same signal redundantly. Check both boards in the Phase 6 dry run. |

---

## 13. Consent, privacy and safety

Gotcha is a **meaningfully bigger ask** than the rest of the app, and D2 makes it
on-by-default. Take that seriously:

- **The app's headline promise is "no WiFi or network needed."** Gotcha breaks it.
  The README must say plainly: *the nametag, friend finder and contact swap remain
  fully offline; Gotcha is an optional online mode.* Do not blur this.
- **First-run notice.** The first time a badge detects a live game it must show a
  screen saying what joining means — *"other players will be able to see when you are
  nearby, and hunt you"* — with joining as an explicit acknowledgement. On-by-default
  means enrolled once acknowledged, not before. **Offer demo mode (§8.4) from this
  screen**: a twenty-second walkthrough of every colour and every sound (§8.4). Informed
  consent for a game whose central mechanic is a badge screaming in your hand is much
  better served by *hearing it once, on purpose* than by a paragraph of text — and it
  is the same screen either way.
- **Exit on the badge itself** (Menu → `Gotcha` → `Stoppen met Gotcha` → confirm),
  not buried in a web page that needs a phone. A kid who wants out must get out in a
  few seconds without help.
- **No age, and no child/adult cohort, is recorded anywhere** (D25, §10.4a) — not in
  `config.json`, not in `gotcha.json`, not in the backend schema, not on the web pages.
  Children who go to bed early are served by **personal quiet hours**, which any player
  can set and which record only a time window. This was a deliberate choice over
  separate child and adult games: it solves the real problem (a badge screaming at
  20:45 in a family tent) without the system ever needing to know who the children are.
- **Location tracking is explicitly out of scope** (D17). No AP association, no
  witness-derived location hints, and — per D30 — **no `witnesses[]`**: no event
  reports who was near whom. The soul mechanism carries the anti-cheat weight on
  its own (§9.5).
- **Badge traffic is not encrypted** (D21, §6.2). Anyone on the camp network can read
  who killed whom and when — which the public leaderboard tells them anyway. With
  `witnesses[]` dropped (D30), no field crosses the link that the game does not
  already publish. Requests and responses are signed, so nothing can be forged or
  injected; the exposure is read-only. Say so plainly on the player page rather
  than letting people assume HTTPS.
- **Names.** Players choose their display name; `identity.py`'s auto-nickname is a
  good pseudonymous default. Never require real names.
- **Publish the retention and deletion policy** on the player web page, and actually
  delete the database after camp.

---

## 14. Open action items

These are **blocking inputs the implementer cannot resolve alone.** Each says what
changes depending on the answer, so Phase 1 can start while they are outstanding.

### 14.1 Ask the Fri3d infra crew (before Phase 2)

| # | Question | If YES | If NO |
|---|---|---|---|
| ~~A1~~ | ~~Will you pre-provision the camp SSID?~~ | **RESOLVED 2026-07-26: yes.** The `fri3d-badge` SSID is pre-loaded onto badges. §7 reduced to a connectivity *check*; the app manages no credentials and the repo contains none. | — |
| ~~A2~~ | ~~Route from the badge VLAN to a laptop on site?~~ | **RESOLVED 2026-07-28 (D31): yes, better** — a fixed public IP is routed to the on-site laptop; ports 80/443 open internally and externally; address by low-TTL DNS name (§6.1). | — |
| A7 | **DNS name + DNS-01.** Register the game hostname (low TTL) and confirm the DNS host offers an API certbot's DNS-01 plugin can drive (§6.1). | Phase 5's HTTPS pages are unblocked; one cert workflow for home and camp. | Pick a DNS host that does — this is a hard prerequisite for backend-served HTTPS pages. |
| A8 | **Arrival-day check:** with the camp uplink down, do badges still resolve the game hostname? (§6.1) | Nothing to do. | Put the assigned IP literal in the §6.3 fallback URL slot. |

Implement the endpoint logic to **try a configured fallback address first and fall
back to the primary URL** (§6.3) regardless — it serves the dev LAN today and the
A8 fallback at camp.

### 14.2 Measure (before Phase 6 sign-off)

| # | Item | Why it matters |
|---|---|---|
| ~~A3~~ | ~~2026 battery capacity~~ | **RESOLVED 2026-07-26: 2000 mAh, same cell as the 2024.** §8.7's runtimes apply to both boards. |
| A4 | **All five power scenarios in §8.7**, both boards, inline USB meter | The whole power section is datasheet arithmetic, not measurement. Good enough to choose levers, not good enough to quote. |
| **A5** | ⚠️ **Does an AppStore update preserve `/apps/com.fri3dcamp.fri3dfriends/`?** Publish a throwaway 0.9.1 to BadgeHub, put a sentinel `config.json` + `contacts.json` on a bench badge, update from the on-badge AppStore, and look at what survived. | **Decides whether §8.10.4 needs building at all.** If files survive, delete most of §8.10.4. If they do not, `contacts.json` is being silently destroyed by every update *today*, which is a v0.9.x bug independent of Gotcha. **Cheapest high-value test in this document — do it first.** |
| **A6** | Do this build's built-in `font_montserrat_*` carry Latin-1? (§8.9.1) | Decides whether the ASCII-only rule can be relaxed. Render `ë é ï` and read back with `get_all_widgets_with_text()`. |

### 14.3 Settled

- **Charging is assumed** (D20). Power banks are ubiquitous at a hacker camp. Keep the
  planned degradation below 20 % battery — cut scan duty, stretch `SYNC_S`, disable LED
  breathing, blank the screen harder — and put **"bring a power bank"** on the rules
  card. The §8.7 levers are still worth pursuing, but the design does not depend on
  them succeeding.
- **Group boards are entertainment, not an award** (§2.3). Membership is
  self-declared and unverifiable; say so on the page and do not attach a trophy.

### 14.4 Nice to confirm

- **Ceremony slot.** The format is built for a **Sunday late-afternoon** announcement of four winners
  (two individual, two group). The ceremony is a large part of why people play to the
  end — worth a stage slot if one can be had.
