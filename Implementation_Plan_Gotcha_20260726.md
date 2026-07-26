# Implementation Plan — Gotcha (Assassin) game for !Fri3d Friends

**Date:** 2026-07-26 (rev. 2, same day) · **Status:** design agreed, not implemented · **Target version:** v0.10.0
**Camp:** **Friday 14 – Sunday 16 August 2026**, badges handed out Friday morning.
Roughly **37 hours of playable time** once the 22:00–08:00 truce is excluded (§2.4).
Everything must ship before then.

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
> (see D6). Its **separate child/adult target chains** were considered and replaced by
> **personal quiet hours** (§10.4a, D25), which solve the same real problem without
> recording anyone's age. Its **"finale mode"** remains open and is not designed here.

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

You do not have to stare at the screen for this. The row of lights on the front of your
badge *is* the radar: dark when there is nothing, then one blue light when your target
is somewhere around, then two, then three — quickening and turning amber as you close —
until the whole row is solid red and they are within arm's reach. You can hunt with the
screen off, in a pocket, by glancing down.

Most of the time the lights are dark and your target is somewhere else entirely on the
site. So you carry on with your day, and every so often one of them flickers blue, and
you look up.

### Picking them out of a crowd

The radar gets you to a group of thirty people around a fire. Then it stops helping:
your badge knows your target is *here*, within a few metres, and cannot tell you which
of the thirty they are. Names are on badges, but you are not going to read thirty
badges without it being obvious what you are doing.

So you press **MENU**, and their badge — and only theirs — **lights up bright gold for
two seconds and chirps.**

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
**MENU** again. It is the same button that revealed them; once you are near enough to
kill, that is what it does, and your badge says so before you press it.

Their badge immediately starts **screaming.** Red screen, siren, `UNDER ATTACK — RUN!`
Everyone nearby turns round. Your target now knows, with total clarity, that they are
being killed and that it is one of the people in front of them.

They have **five seconds** to get away from you. Not out of the building — just far
enough, about ten metres, and broken away. If they manage it, they have dodged, and
your badge tells you they escaped. You have to wait a minute before you can try again.

But they only get away **once.** The second time you press MENU on the same person,
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

Hold **MENU** and you are out, in about three seconds, no phone and no explanation
needed. Rejoin whenever you like — your total is waiting for you.

---

## 0. Summary

Add an optional camp-wide game of **Assassin/Gotcha**
([rules](https://en.wikipedia.org/wiki/Assassin_(game))) to the !Fri3d Friends app.

Each enrolled player is assigned one **target**. You hunt your target physically,
using your badge as a **radar** (BLE RSSI). In a crowd you press **MENU** to
**reveal** — their badge flashes gold, which tells you which person they are and tells
them they have been found. Closer still, MENU **attacks**: the victim's badge
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
| D21 | **Plain HTTP with HMAC-signed requests and responses** (§6.2) | The game needs authenticity, not secrecy — kill proofs are self-authenticating and scores are published. Certificate verification is likely off on this build, so TLS would have given encryption without authenticity. One HTTPS call at enrollment bootstraps the key; everything after is signed plain HTTP. Removes the per-sync 40 KB allocation. **Constrains deployment: Tailscale Funnel is HTTPS-only and is therefore ruled out for the sync path.** |
| D22 | **Reveal — the last ten metres** (§5.7) | RSSI walks you into a crowd and then stops helping. Reveal makes your target's badge flash, at the cost of telling them they have been found. Pure BLE, works offline, and it is the mechanic that stops the endgame of every hunt being "squint at thirty lanyards". |
| D23 | **The whole LED strip becomes the hunt radar; the friend LEDs are removed** (§8.8) | The badge must be readable at a glance with the screen dark — which is what makes §8.7's biggest power lever (blanking the display) survivable. A **bar** (length + colour) is legible at several metres in a way a single colour-coded dot is not. No information is lost: the friends panel and group pills still show everyone nearby. Average LED draw *falls*, because the bar is dark whenever the target is out of range. |
| D24 | **Spawn and join protection** (§5.8) | Respawning next to your killer, or joining into the middle of a scrum, should not mean dying instantly. 90 s, forfeited the moment you attack. |
| D25 | **Personal quiet hours, and no age data anywhere** (§10.4a) | Children go to bed before 22:00. The obvious fix — separate child and adult games — requires recording which badges belong to minors, and would not even deliver the safety it implies (bounties and inheritance cross cohorts). A self-serve personal truce window solves the actual problem, serves early-sleeping adults equally, and keeps **one ring, one game, no age flag, no cohort field**. |
| D26 | **All user-facing text is Dutch** (§8.9) | Fri3d Camp is a Belgian/Dutch-language event and much of the audience is children, for whom English rules text is a real barrier at exactly the moment the game needs to be understood instantly. This covers the existing app, not just Gotcha: the whole UI is translated. **ASCII-only** — the built-in lvgl fonts do not carry accented glyphs (§8.9). |

---

## 1. Rules of the game (player-facing)

These are the rules as they should appear on the rules card and the web page.
Everything here is enforced by the backend unless marked *social*.

1. **You have one target.** Your badge shows their name and how close they are. It
   never tells you who is hunting *you*. Your target is **almost never** someone from
   one of your own groups.
2. **To find them in a crowd — Reveal.** When your target is near but you cannot tell
   *which* person they are, press **MENU**: their badge flashes gold and chirps for
   two seconds. It also tells them they have been found. One reveal every **2
   minutes**, and none during a truce.
3. **To kill:** get within a few metres of your target and press **MENU** again. Hold
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
    enforced by not being a jerk.
15. **Opting out:** press and hold **MENU** on your badge, or use the web page. You
    can rejoin later; your total is preserved.

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
| `DORMANT_H` | 24 h | **65 %** | ⚠️ **Too long. Recommend 12 h.** With truce hours excluded, 24 h of *playable* time is nearly two real days — a badge switched off on Friday night would not be spliced out of the ring until Sunday, stranding its hunter for most of the event. |

`DORMANT_H` is the one that is actively wrong at this camp length; the rest merely
want a second look. All are server-pushed (§5.4), so they can be retuned on Friday
afternoon once real behaviour is visible.

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
| No sync for `DORMANT_H` (truce hours excluded) | Splice out as dormant. **See §2.4 — 24 h is too long for a three-day camp; use 12 h.** |
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
  `TRUCE`, bit4 `PROTECTED` (§5.8), bits 5–7 reserved.
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
second table — one scan, one IRQ, no new radio contention.

> 🐛 **Pre-existing bug this will expose.** `BLEProximity`'s `seen` table has **no size
> cap**. Invisible with three badges on a bench; with 700 badges it is unbounded RAM
> growth plus an ever-lengthening loop in `_evict` and `current_peers`, in an IRQ
> path. **Cap it with an LRU (suggest 64 entries, evict lowest `last_seen`) before the
> game ships.** This is worth fixing regardless of Gotcha.

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
press MENU
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
| `SYNC_S` | 300 | D13. Jittered ±20% (§10.3). |

Retuning `KILL_RSSI` and `KILL_HOLD_MS` **live from the admin page** is worth a lot:
RSSI at a real camp will not behave like RSSI on a bench, and you will want to adjust
on Friday afternoon without reflashing 700 badges.

### 5.5 Radio arbitration

Gotcha is a fourth consumer of a radio with **one adv set, one connection slot, one
IRQ handler**. Extending `DESIGN.md` §9/§10:

- A kill handshake **or a reveal** (§5.7) **cannot** start while `_exchanging` (contact
  swap), while a setup session/window is open, or while an adopt prompt is up. MENU is
  ignored with a brief "busy" toast.
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

**The mechanic.** With your target inside `REVEAL_RSSI`, press **MENU**: their badge
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
press MENU
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

**Button semantics — one button, escalating with distance.** MENU short-press does the
strongest thing currently available, which is unambiguous because the ladder is
monotonic in proximity:

| Target state | MENU short-press |
|---|---|
| within `KILL_RSSI` | **Attack** |
| within `REVEAL_RSSI`, cooldown clear | **Reveal** |
| within `REVEAL_RSSI`, cooling down | Radar detail (shows the cooldown) |
| not detected | Radar detail |

The screen and the hunt LED always name the action *before* it is pressed — the radar
strip reads `MENU: reveal` or `MENU: ATTACK`, red LED — so the boundary case (you meant
to reveal, you were already in kill range) resolves to "you attacked someone you were
standing next to", which is what you wanted anyway. **Do not add a confirmation
step**: the whole mechanic is a single press in a crowd.

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

---

## 6. Deployment and networking

### 6.1 Where the server runs

An **Ubuntu laptop brought to camp**. Preference order, driven by D21 (§6.2):

1. **LAN route from the badge VLAN (A2)** — plain HTTP end to end, no internet in the
   critical path. **Strongly preferred.** Ask the Fri3d infra crew; it is a
   five-minute firewall change on their side.
2. **Cloudflare Tunnel** — outbound-only, and it *can* serve plain HTTP on port 80 if
   "Always Use HTTPS" is disabled. Adds rate limiting and a custom domain.
3. ~~Tailscale Funnel~~ — **ruled out for the sync path.** Funnel is HTTPS-only
   (443/8443/10000, TLS terminated by Tailscale), which would force a TLS handshake
   back onto every sync and undo D21. Still fine for the *enrollment* endpoint.

- ⚠️ **Plain Tailscale is not usable by badges either** — they cannot run a WireGuard
  client. Only Funnel exposes a tailnet service to ordinary HTTP clients, and Funnel
  is HTTPS-only, hence the above.
- Options 1 and 2 are **outbound-only**, which is essential: behind camp NAT there is
  no port forward to be had, so DDNS alone cannot work.
- **Consequence of the subnet split:** badge → camp uplink → internet → back to camp →
  laptop 50 m away. If the camp uplink drops, an on-site server is unreachable — which
  is the second reason option 1 is preferred. Build the badge to try a configured LAN
  address first and fall back to the public URL (§6.3), so the choice can be made on
  arrival.
- Load is negligible: 700 badges ÷ 300 s = **2.3 req/s**, a few KB each. SQLite and a
  single process are ample. Run it under systemd with restart-on-failure.

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
    badge -> POST https://…/v1/enroll  { badge_key, display_name, groups, commitment }
    server -> { pid, player_key (32 B, hex), game_id }
    Exactly one TLS handshake in the badge's entire life, made early in uptime
    while the heap is clean. Cost is irrelevant; it closes the key-delivery hole.

every request thereafter (plain HTTP):
    X-Pid:   <pid>
    X-Ts:    <unix seconds, corrected by clock_offset_s>
    X-Nonce: <16 random hex chars>
    X-Sig:   HMAC_SHA256(player_key, METHOD || PATH || X-Ts || X-Nonce || BODY)

every response:
    X-Sig:   HMAC_SHA256(player_key, STATUS || X-Ts || REQUEST-NONCE || BODY)
    The badge MUST verify this and discard unsigned or mis-signed responses.
```

- **Responses must be signed too.** Without it, a MITM could inject "truce off",
  "you are dead", or a fake target. This is not optional.
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

#### ⚠️ Deployment consequence — this constrains §6.1

**Tailscale Funnel serves HTTPS only** (443/8443/10000, TLS terminated by Tailscale).
It **cannot** serve plain HTTP, so choosing D21 rules Funnel out for the sync path.
The viable combinations are:

| Path | Works with plain HTTP? |
|---|---|
| **LAN route (A2)** | ✅ Yes — the clean answer. Plain HTTP end to end. |
| **Cloudflare Tunnel** | ✅ Yes, if "Always Use HTTPS" is disabled and port 80 is served. |
| **Tailscale Funnel** | ❌ No — HTTPS only. Would force TLS back onto every sync. |

Enrollment still needs an HTTPS endpoint regardless, so **the server must expose both**
— HTTPS for `/v1/enroll`, plain HTTP for everything else. On the LAN path, enrollment
can use a self-signed cert with verification off; the key exchange is then protected
only against passive sniffing, which combined with a LAN-only route is acceptable.

**This raises the value of A2 (§14.1) from "nice" to "strongly preferred", and makes
Cloudflare Tunnel the better fallback over Tailscale Funnel.** Update §6.1 accordingly.

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
on-badge editor without reflashing:

| Key | Scheme | Used for |
|---|---|---|
| `gotcha.enroll` | **https://** | `/v1/enroll` only — once per badge, to bootstrap `player_key` (§6.2) |
| `gotcha.api` | **http://** | Everything else, signed |

The badge tries a configured LAN address first, then the public URL. Both must be
reachable; the server exposes HTTPS and plain HTTP side by side.

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
score_preview(...)                          # mirror of §2, optimistic UI only
menu_action(target, rssi, now, cfg)         # the §5.7 escalation ladder -> attack|reveal|detail
reveal_ready(now, last_reveal_at, cfg)      # REVEAL_COOLDOWN_S
protected(now, protected_until)             # §5.8
hunt_bar(state, rssi, now, cfg, n_leds)     # -> [(r,g,b)] * n_leds, the §8.8 radar bar
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
  "dodges": {"8123": 1},
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
`WifiService.is_connected()` (already used at `fri3d_friends.py:1483`) and wrap every
call in `TaskManager.wait_for(..., timeout=10)`.

> ⚠️ **Every** Gotcha HTTP call must be a `TaskManager` task with a timeout, never
> called from the main tick — the same reason `ntptime.settime()` already runs in a
> thread (`fri3d_friends.py:1454`).

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
| Radar detail (MENU short-press, target out of range) | Target name, dBm, **last seen by anyone: 12 min ago** (§10.1), your ranks, nearby bounty players, reveal cooldown remaining. |
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

**Buttons.** MENU is currently mapped nowhere (`BTN_2024 = {"a":39,"b":40,"y":41}`,
`BTN_2026_EXP = {"a":7,"b":6,"y":8}`; MENU is GPIO 45 / expander idx 5 and appears only
in `BTN_2024_DIAG`). Add it to both maps.

| Gesture | Action |
|---|---|
| MENU short | The §5.7 escalation ladder: **attack** in kill range · **reveal** in reveal range · else radar detail. The label on screen always names the action before it is pressed. |
| MENU long (≥1.5 s) | Leave / rejoin the game (confirm prompt) |
| Existing A / B / Y / START | Unchanged (A = detail panel, B = mute / long = setup window, Y = swap, START = exit) |

**Demo mode.** A `Show me what the badge does` entry on the first-run screen (§13) and
in the radar detail screen: it walks the whole colour language and both sounds — blue,
amber, red, the gold reveal flash and chirp, the attack siren, the green kill flash,
the dead pulse — with a one-line caption each, in about fifteen seconds. Borrowed
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
| `gotcha.py` | **new** |
| `fri3d_friends.py` | MENU map + the §5.7 escalation handler, Gotcha widgets, duel + reveal + spotted + protected UI, status chip, demo mode, **`_update_leds()` rewritten as the §8.8 radar bar — friend LEDs removed**, main-loop tick, sync task, connectivity check (§7), arbitration guards |
| `ble_proximity.py` | **HSNT v2** build/parse + name budget; game fields on peer entries; **LRU cap on `seen`** |
| `contact_exchange.py` | Register the Gotcha service in `_ensure_services()`; hand handles to `GotchaResponder` |
| `beacon_service.py` | Victim-side responder (attack **and** reveal) + protection state + sync in the background (D3); v2 beacon; LED-only rendering of §8.8 |
| `ble_setup.py` | `sanitize_config` accepts `gotcha` (incl. `quiet`, clamped per §10.4a); expose enroll state over the setup GATT |
| `MANIFEST.JSON` | → 0.10.0 |
| `docs/gotcha/index.html` | **new** — player card + 4 leaderboards |
| `docs/gotcha/admin/index.html` | **new** — host console |
| `tests/test_gotcha.py` | **new** |
| `tests/test_ble_proximity.py` | v2 format, name budget, block presence |
| `DESIGN.md` | new §14; **§11 (friend LEDs) rewritten as the radar bar**; note the Dutch-UI rule (§8.9) |
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
   | **20 %** | On-screen notice + orange LED hint. Drop scan duty, stretch `SYNC_S` to 600 s, stop the friend LED breathe (hunt LED stays — it is the game). |
   | **10 %** | Second notice, explicitly worded: *"find a power bank — you can still be killed while charging."* Blank the screen harder (2026 only, §8.7 lever 1). |
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

### 8.8 The LED colour language (D23)

**This is not decoration, it is the power budget.** §8.7 lever 1 says the single
biggest saving available is blanking the screen — but the radar currently *lives* on
the screen, so blanking it blinds the hunter and the lever cannot be pulled. Moving the
hunt onto the LEDs is what makes an aggressive blank-after-inactivity compatible with
playing the game. Treat this section as a prerequisite for lever 1, not as polish.

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
learns *"solid red, all of them, means press MENU"* has learned the whole hunt.

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
| **Battery ≤ 10 %** (§8.7) | LED n−1 only, orange, double-blink once a minute | 0.30 | — |
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
- **Numbers, times and units stay as they are** (`22:00`, `-65 dBm`, `30 min`).

#### 8.9.3 The Gotcha strings

The screens in §8.4, in the wording that should ship:

| Screen | Dutch | *(English gloss)* |
|---|---|---|
| Status chip, alive | `LEEFT · reeks 3 · 11 kills` | *ALIVE · streak 3 · 11 kills* |
| Status chip, dead | `UIT · terug om 14:32` | *DEAD · back at 14:32* |
| Target strip | `DOELWIT: Otter 42` | *TARGET* |
| Radar hint, reveal | `MENU: onthullen` | *MENU: reveal* |
| Radar hint, attack | `MENU: AANVALLEN` | *MENU: ATTACK* |
| Last seen | `laatst gezien: 12 min geleden` | *last seen 12 min ago* |
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

#### 8.9.4 Existing strings to translate

Not new work hidden in a footnote — this is a real pass over ~50 user-visible strings
in `fri3d_friends.py` (banners, prompts, the setup screen, the on-badge editor), plus
`ble_setup.py`'s field labels and helper text, plus **`docs/setup/index.html`**, which
is the phone-facing setup page and is currently English throughout. Anything the player
reads counts; log messages, exception text and code comments stay English.

Stack unspecified. Requirements: **HTTPS on `/v1/enroll` and plain HTTP on everything
else** (§6.2), ~2.3 req/s sustained, a small relational store, and something operable
from a phone at a muddy campsite.

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
  `…/gotcha/?badge=XXXX&t=<short-lived read token>` for the private view (your target).
  The web page is served over HTTPS as normal — D21 governs the *badge* path only.
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
       config: { KILL_RSSI, KILL_HOLD_MS, ... } }  # §5.4, live-tunable
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
| `kill` | `victim_pid`, `soul`, `as`, `rssi`, `witnesses[]` | Verify `sha256(soul)`; score §2; repair ring |
| `killed_by` | `attacker_pid`, `new_commitment` | Confirm death, rotate commitment |
| `dodge` | counterpart pid, `rssi_at_escape` | Decrement `dodges_left`, log |
| `attack_started` | `victim_pid` | Cooldown bookkeeping, abuse detection |
| `reveal` | `target_pid`, `rssi` | Log only. Feeds the audit page (§9.5) — someone standing in a crowd flashing strangers shows up here. |
| `revealed` | `hunter_pid` | Log only. Also a **liveness signal for §10.1**: being revealed proves you were physically near someone, so it refreshes `last_seen`. |
| `heartbeat` | `alive`, `target_seen_ago_s`, `peers_seen`, `battery`, `groups[]`, `quiet{from,to}` | Liveness, stale-target detection, group snapshot, personal quiet window (§10.4a) so the server can re-check it on ingest |
| `optout` / `optin` | — | Splice out of / into the ring |

### 9.4 Admin endpoints

```
POST /v1/admin/game            create (name, start, end, tunables)
POST /v1/admin/game/<id>/state {state: lobby|running|paused|ended}
POST /v1/admin/truce           {active, until, reason}      # instant camp-wide
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
| Fleet | battery histogram · **count below 20 %** · app-open vs background-service split |
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

1. **Witness overlap.** Both parties report up to 8 `pid`s seen in the last 60 s. A
   genuine kill in a crowd shares witnesses with other players' reports; a farm in a
   tent shares none. **A flag, never an automatic rejection.**
2. **Rate limits — flag, do not block.** Legitimate table sweeps are explicitly legal
   (D16), so `MAX_KILLS_PER_HOUR` (default 10) marks kills for review rather than
   refusing them. Refusing a real sweep would break the best moment in the game.
3. **Graph shape.** Mutual-only kill pairs, players who only ever interact with each
   other, enrollments clustered in time from one IP.

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
| `opted_out` | spliced out | no | Rule 15 (MENU long / web) | Opts back in → `protected` |
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
- **`Updating`** — there is no OTA path in scope; badges are updated by hand from the
  AppStore between games.
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
| Victim sitting in a setup window or swap | Attack refused. **Exploit:** camping in a setup window is temporary invulnerability, bounded by the existing 2-min idle / 10-min absolute caps (`DESIGN.md` §10). While a game is running, shorten the absolute cap to 3 min. |
| RSSI spike causes a false dodge | Use the smoothed `rssi_ewma` and require `FLEE_MS` sustained, never a single sample. |
| Rapid re-attack after a dodge | `ATTACK_COOLDOWN_MS` (60 s) per pair. |
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
| Only the victim reports | `killed_by` names the attacker — credit the kill immediately, dedupe by `(victim_pid, life_id)` when the assassin's copy arrives. |
| Backend down for hours | Everyone queues. **Dormancy must pause when global sync volume collapses**, or a server outage would mass-dormant the entire camp and shred the ring. |
| 08:00, everyone powers on at once | **Jitter the sync schedule ±20%** — 700 simultaneous syncs is a self-inflicted DDoS. |

### 10.4 Night, sleep and powered-off badges (D7)

- **Truce 22:00–08:00.** Checked on the badge from cached config + corrected clock, so
  it holds with no network, and re-checked server-side on ingest.
- **The siren is suppressed during a truce unconditionally**, even if a duel somehow
  starts. Defence in depth: the failure mode is a screaming badge in a tent full of
  sleeping children.
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

**Phase 0 — hardware spike (blocking).** Three questions, all cheap to answer and all
capable of invalidating downstream work:

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
5. **Screen blanking on 2024** (§8.7 lever 1): can the GC9307 be put to sleep
   directly, given there is no backlight API? Highest-value power fix if yes.

Deliverable: findings appended to `DESIGN.md`, and a go/no-go.

*(The original spike item "does 2 Hz `adv_data` swapping survive?" is gone — D8 let us
collapse to a single v2 beacon.)*

**Phase 1 — backend + admin.** API (§9), scoring (§2), ring (§3.2), admin console.
Fully testable with a simulator; no badge required.

**Phase 2 — badge: connectivity check, enrollment, sync, v2 beacon, radar.** No kills.
Includes the **LED radar bar replacing the friend LEDs** (§8.8) and **demo mode**, both
of which are independent of the duel and make Phase 3 far easier to test in the field.
**Also the Dutch translation pass (§8.9)** — do it before there are three new screens
of English to retranslate. Ends with two badges enrolled, each showing the other as
target with a live on-screen radar bar *and* a live LED bar.

**Phase 3 — the duel and the Reveal.** Handshake, alarm, dodge, soul disclosure,
inheritance, reporting, plus **Reveal (§5.7)** and **spawn protection (§5.8)**. The core
fun. Ends with a real two-badge chase across a field. **Build Reveal first** — it is a
much simpler GATT interaction than the duel (write, ack, disconnect, flash), it
exercises the same connect path, and having it working makes every subsequent duel test
easier to set up.

**Phase 4 — background participation** (D3). The fragile one; see §5.6.

**Phase 5 — web pages.** Player card, four leaderboards, hit list, QR flow.

**Phase 6 — scale and soak.** As many badges as can be assembled, running for hours.
Watch RAM, the peer-table LRU, backend load, and **median time-to-first-kill**
(§3.3). **Measure all five power scenarios in §8.7 with an inline USB meter, on both
board generations.** Then a rules card, and a dry run with a dozen willing humans
before 14 August.

---

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **WiFi/BLE coexistence degrades the scan** | **High** | Phase 0 gates everything. 5-min sync (D13) already minimises exposure. |
| Signed plain HTTP: traffic is readable on the camp network | Low | Accepted (D21). Kill proofs are self-authenticating and scores are published; responses are signed so nothing can be injected. Noted in §13. |
| **Background GATT + radio handoff** (§5.6) | **High** | `ensure_radio` self-heal is the precedent; budget hardware time; be willing to ship Phase 4 late. |
| Unbounded `seen` table at 700 badges | High | LRU cap — fix regardless of Gotcha. |
| Camp uplink down → on-site server unreachable | Medium | Ask for the badge-VLAN route (§6.1); D6 means play continues regardless. |
| Kids running into things | **High (real-world)** | Truce, safe-zone rules, "no running" on the card, host truce button. |
| **Battery: app already gets only ~11 h; Gotcha naively cuts it to ~7 h** | **High** | §8.7. WiFi DTIM power save, reduced scan duty, screen blanking, battery-aware degradation. Measure in Phase 6. |
| Group exclusion makes targets unfindable | Medium | §3.3, §10.1; watch time-to-first-kill in the soak. |
| RSSI at a real camp ≠ RSSI on a bench | Medium | Every threshold is server-tunable live (§5.4). |
| Sybil / collusion | Low | Detected not prevented (§9.5); host can void and revive. |
| Badge never joined WiFi; player cannot tell the game is broken | Medium | Explicit `no network — check WiFi in Settings` state (§7), never silent absence. |
| **Reveal is mistaken for an attack** and someone bolts through a crowd | Medium | The two are deliberately unmistakable: gold + single chirp + `SPOTTED` versus red + siren + `RUN`. **Demo mode (§8.4) exists largely to teach this difference before it matters.** Verify with real children in the Phase 6 dry run, not just with adults who read the rules card. |
| Reveal spam in a crowd | Low | Self-limiting (it warns your target), `REVEAL_COOLDOWN_S` on top, and `reveal` events land on the audit page (§9.5). |
| Removing the friend LEDs is felt as a loss | Low | §8.8.1: no *information* is lost (friends panel + pills are unchanged), the hunt bar is far more legible than one shared LED would have been, and average LED power falls. Revisit only if players actually complain. |
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
  screen**: a fifteen-second walkthrough of every colour and both sounds. Informed
  consent for a game whose central mechanic is a badge screaming in your hand is much
  better served by *hearing it once, on purpose* than by a paragraph of text — and it
  is the same screen either way.
- **One-press exit on the badge itself** (MENU long-press), not buried in a web page
  that needs a phone. A kid who wants out must get out in three seconds without help.
- **No age, and no child/adult cohort, is recorded anywhere** (D25, §10.4a) — not in
  `config.json`, not in `gotcha.json`, not in the backend schema, not on the web pages.
  Children who go to bed early are served by **personal quiet hours**, which any player
  can set and which record only a time window. This was a deliberate choice over
  separate child and adult games: it solves the real problem (a badge screaming at
  20:45 in a family tent) without the system ever needing to know who the children are.
- **Location tracking is explicitly out of scope** (D17). No AP association, no
  witness-derived location hints. The only proximity data collected is
  `witnesses[]` for anti-cheat (§9.5): store it salted-hashed, retain it for the
  duration of the game only, purge after camp, and **drop it entirely if it is not
  earning its keep** — the soul mechanism carries the cryptographic weight on its own.
- **Badge traffic is not encrypted** (D21, §6.2). Anyone on the camp network can read
  who killed whom and when — which the public leaderboard tells them anyway — and, if
  `witnesses[]` is kept, who was near whom. **This is the strongest argument for
  dropping `witnesses[]`:** it is the only field whose plaintext exposure reveals
  anything the game does not already publish. Requests and responses are signed, so
  nothing can be forged or injected; the exposure is read-only. Say so plainly on the
  player page rather than letting people assume HTTPS.
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
| A2 | **Can we have a route from the badge VLAN to a laptop on site?** (§6.1) **Now strongly preferred, not merely nice** — D21 needs a path that carries plain HTTP. | Badge talks to a LAN address over plain HTTP. **Internet leaves the critical path** and the camp uplink stops being a single point of failure. | **Cloudflare Tunnel**, with "Always Use HTTPS" disabled so port 80 is served. **Tailscale Funnel is ruled out** for the sync path — HTTPS-only (§6.1). |

Implement the endpoint logic to **try a configured LAN address first and fall back to
the public URL** (§6.3) regardless of the answer — that way A2 can be answered as late
as the day you arrive.

### 14.2 Measure (before Phase 6 sign-off)

| # | Item | Why it matters |
|---|---|---|
| ~~A3~~ | ~~2026 battery capacity~~ | **RESOLVED 2026-07-26: 2000 mAh, same cell as the 2024.** §8.7's runtimes apply to both boards. |
| A4 | **All five power scenarios in §8.7**, both boards, inline USB meter | The whole power section is datasheet arithmetic, not measurement. Good enough to choose levers, not good enough to quote. |

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
