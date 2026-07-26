# Implementation Plan — Gotcha (Assassin) game for !Fri3d Friends

**Date:** 2026-07-26 · **Status:** design agreed, not implemented · **Target version:** v0.10.0
**Camp date:** badges are handed out **14 August 2026** — everything must ship before then.

This plan is written to be handed to an implementer who has *not* been part of the
design conversation. It assumes familiarity with `DESIGN.md` (especially §3 BLE
protocol, §9 contact exchange, §10 BLE phone setup, §12 background beacon service)
and `README.md`. Where this plan contradicts an existing pattern, it says so
explicitly.

---

## 0. Summary

Add an optional camp-wide game of **Assassin/Gotcha**
([rules](https://en.wikipedia.org/wiki/Assassin_(game))) to the !Fri3d Friends app.

Each enrolled player is assigned one **target**. You hunt your target physically,
using your badge as a **radar** (BLE RSSI). When you get close enough you press
**MENU** to attack; the victim's badge **screams** and they get a few seconds to
**run out of range**. Kill your target and you inherit theirs. Death is a 30-minute
respawn, not an elimination.

Three tiers:

| Tier | Role | Transport |
|---|---|---|
| **Backend** (new) | Authority: roster, ring, kills, scoring, game state, anti-cheat | HTTPS |
| **Badge** (`gotcha.py`, new) | Radar, kill handshake, alarm, local event queue | BLE (peer↔peer) + HTTPS (badge↔backend) |
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
| D5 | **Kill proof = commitment–reveal ("the soul")** | Cryptographic proof of a genuine physical handshake, using only sha256, with no key distribution to 700 badges. |
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

---

## 1. Rules of the game (player-facing)

These are the rules as they should appear on the rules card and the web page.
Everything here is enforced by the backend unless marked *social*.

1. **You have one target.** Your badge shows their name and how close they are. It
   never tells you who is hunting *you*. Your target is never someone from one of
   your own groups.
2. **To kill:** get within a few metres of your target and press **MENU**. Hold the
   proximity for **5 seconds**. Their badge will scream — that is the point.
3. **To survive:** if your badge screams, **run.** Break line of sight and get
   ~10 metres away within 5 seconds and you have dodged. *No running indoors, near
   the stage, near the fire, or in food queues.* (social)
4. **You cannot dodge forever.** After **3 successful dodges from the same
   assassin**, their next attack lands **instantly**. Dodge counters reset an hour
   after that assassin last attacked you.
5. **Attack cooldown:** an assassin must wait **60 seconds** between attempts on the
   same victim.
6. **When you kill, you inherit** your victim's target and keep going. There is no
   cooldown — if you can take a whole table, take a whole table.
7. **When you die**, you are out for **30 minutes**, then you respawn with a new
   target and a **streak of zero**. Your total kills are never lost.
8. **Four leaderboards:** individual *Total kills* and *Longest streak*; group
   *Total kills* and *Kills per member*.
9. **Bounties:** anyone on a live streak of **3 or more** is fair game for
   **everybody**, not just their assigned hunter — including people from their own
   group. Their name and streak are on the public hit list. Bounty kills score double.
10. **Streaks perish.** Your streak holds for **3 hours** after your last kill, then
    decays by **1 per hour** until it reaches zero. Hiding your badge in a tent does
    not protect a lead — it forfeits it. (Total kills never decay.)
11. **Night truce: no kills between 22:00 and 08:00.** Truce hours are excluded from
    the streak-decay clock, so sleeping costs you nothing. The game host can call a
    camp-wide truce at any other time.
12. **Safe zones (social):** main stage during shows, food queues, toilets and
    showers, workshop tents while a workshop is running, first aid, and anyone's
    sleeping tent. Not enforced by the badge — enforced by not being a jerk.
13. **Opting out:** press and hold **MENU** on your badge, or use the web page. You
    can rejoin later; your total is preserved.

### 1.1 Why these rules

- **Rule 10 answers "just hide your badge."** A raw bounty on the leader creates an
  obvious dominant strategy: get a streak, then put the badge in a locker until
  Sunday. Making the streak perishable inverts that — the only way to *stay* on the
  crown is to keep hunting, in public, where bounty hunters can reach you. Decay is
  computed **server-side on wall-clock time**, so a powered-off badge decays fastest
  of all: it cannot even dodge.
- **Rule 4 answers "run away forever."** Without it a fast player is invulnerable.
  Three dodges makes a real chase; the instant-kill fourth attempt guarantees it ends.
- **Rule 7 (respawn, not elimination)** answers a 4-day camp: eliminating a
  9-year-old at 09:30 on Friday because their badge battery died is not a game, it is
  a punishment for logistics.
- **Rule 1's group exclusion has a cost — read §3.3.** It makes every target a
  stranger, which is thematically right but makes targets *harder to find*. The
  freshness/reassign machinery in §10.1 is what makes it survivable, not optional
  polish.

---

## 2. Scoring model

### 2.1 Individual

| Quantity | Decays? | Notes |
|---|---|---|
| `total_kills` | No | Permanent record. Board 1. |
| `streak` | **Yes** (rule 10) | Kills since last death. Board 2 ranks `best_streak` (high-water mark, never decays); the *live* `streak` carries the bounty. |
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
active_seconds = wall_seconds_since(last_kill_at) minus overlapping truce intervals
if active_seconds > STREAK_GRACE_S (default 3 h):
    decayed = floor((active_seconds - STREAK_GRACE_S) / STREAK_DECAY_S)   # default 1 h
    streak  = max(0, streak_at_last_kill - decayed)
```

Deriving from `last_kill_at` rather than mutating a counter makes it idempotent and
correct regardless of when the timer actually runs — important, because the backend
may be unreachable for hours (§6).

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
| New enrollment mid-game | Splice in: pick random alive `P`; `new.target = P.target; P.target = new`. Retry up to 10 picks for a non-group-conflicting `P`. |
| Kill | `assassin.target = victim.target` (classic inheritance). If that creates a group conflict, try **one** re-splice; otherwise accept it and log. If it yields the assassin themselves, or a dead player, walk forward to the next alive player. |
| Respawn | Splice in by the same rule. |
| Opt-out | Splice out immediately; the hunter is reassigned on their next sync. |
| Target unseen by anyone for `TARGET_STALE_H` (6 h) | Splice out, hunter reassigned. Score preserved; spliced back on return. |
| No sync for `DORMANT_H` (24 h, truce hours excluded) | Splice out as dormant. |
| Ring down to 2 | They hunt each other. Fine. |
| Ring down to 1 | `target = null`, badge shows "waiting for players". |

Badges never compute the ring; it only has to be self-consistent server-side.

### 3.3 The cost of group exclusion

Excluding same-group pairs means your target is, by construction, someone you do not
already hang around with. That is the point — but it directly increases the chance
that you and your target simply never occupy the same field. Combined with D16 (no
kill cooldown, so sweeps are legal), the game's failure mode is not "too fast", it is
**"I wandered for four hours and never found anyone."** The mitigations are §10.1
(freshness display + 6 h reassign) and the bounty layer, which always gives you
*someone* killable nearby. Treat "median time-to-first-kill" as the metric to watch
in the Phase 6 soak test.

### 3.4 Kill proof — commitment and reveal ("the soul")

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
  verify a revealed soul **locally and offline** before believing a kill.

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
  `TRUCE`, bits 4–7 reserved.
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
| `DODGE_LIMIT` | 3 | Dodges per (attacker, victim) pair per life. |
| `DODGE_DECAY_MS` | 3600000 | Dodge counter reset after 1 h with no attack from that attacker. |
| `INSTANT_KILL_MS` | 1000 | Hold time once `dodges_left == 0`. |
| `ATTACK_COOLDOWN_MS` | 60000 | Between attempts on the same victim. |
| `RESPAWN_S` | 1800 | 30 minutes. |
| `BOUNTY_STREAK` | 3 | Streak at which you become fair game for everyone. |
| `STREAK_GRACE_S` | 10800 | 3 h before decay starts. |
| `STREAK_DECAY_S` | 3600 | −1 streak per hour thereafter. |
| `SYNC_S` | 300 | D13. Jittered ±20% (§10.3). |

Retuning `KILL_RSSI` and `KILL_HOLD_MS` **live from the admin page** is worth a lot:
RSSI at a real camp will not behave like RSSI on a bench, and you will want to adjust
on Friday afternoon without reflashing 700 badges.

### 5.5 Radio arbitration

Gotcha is a fourth consumer of a radio with **one adv set, one connection slot, one
IRQ handler**. Extending `DESIGN.md` §9/§10:

- A kill handshake **cannot** start while `_exchanging` (contact swap), while a setup
  session/window is open, or while an adopt prompt is up. MENU is ignored with a
  brief "busy" toast.
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
  accounting, soul release, target handover,
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

---

## 6. Deployment and networking

### 6.1 Where the server runs

An **Ubuntu laptop brought to camp**, published to the public internet via
**Tailscale Funnel** or **Cloudflare Tunnel**.

- ⚠️ **Plain Tailscale is not usable by badges** — they cannot run a WireGuard client.
  **Funnel** is the required feature: it publishes a tailnet service on a public
  HTTPS URL that any ordinary HTTP client can reach. Cloudflare Tunnel does the same
  and adds rate limiting and a custom domain.
- Both are **outbound-only**, which is essential: behind camp NAT there is no port
  forward to be had, so DDNS alone cannot work.
- **Consequence of the subnet split:** badge → camp uplink → internet → back to camp →
  laptop 50 m away. If the camp uplink drops, an on-site server is unreachable.
  **Ask the Fri3d infra crew for a route from the badge VLAN to the laptop** — a
  five-minute firewall change that removes the internet from the critical path.
  Plan for Funnel; take the route if offered, and make the badge try a LAN address
  first and fall back to the public URL.
- Load is negligible: 700 badges ÷ 300 s = **2.3 req/s**, a few KB each. SQLite and a
  single process are ample. Run it under systemd with restart-on-failure.

### 6.2 TLS on the badge — verify this early

`DownloadManager` is aiohttp-backed, so HTTPS works, but on ESP32-S3 MicroPython:
- a TLS handshake costs **tens of KB of RAM** and 1–3 s, and repeated handshakes are a
  classic source of **heap fragmentation → OOM** over a multi-day run;
- certificate verification may be **off by default** on this build. Unverified TLS is
  still encrypted but MITM-able — on a hacker-camp network, assume someone will try.

Decide explicitly and record it: (a) verify with a pinned CA/cert, (b) accept
unverified TLS and treat all badge→server data as public, or (c) plain HTTP if the
LAN route materialises. **Add "1000 consecutive HTTPS syncs without OOM" to Phase 0.**

### 6.3 Endpoint configuration

Base URL ships in `config.json` as `gotcha.api` with a compiled-in default, so it can
be changed from the phone page or the on-badge editor without reflashing. The badge
tries, in order: a configured LAN address (if set), then the public URL.

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
truce_active(now, cfg)                      # local truce check, server-clock corrected
score_preview(...)                          # mirror of §2, optimistic UI only
```
Beacon build/parse lives in `ble_proximity.py` with the rest of the wire format (§4).

**Radio / IO:**
```
class GotchaResponder:   # VICTIM side — used by app AND background service
class GotchaHunter:      # ASSASSIN side — app only
class GotchaSync:        # HTTP client: enroll(), sync(), flush_events()
```

### 8.2 Persistence

New file `/apps/com.fri3dcamp.fri3dfriends/gotcha.json`, written with the **same
atomic temp-file + `os.rename`** pattern as `contacts.json` (`DESIGN.md` §9) — a queue
corrupted by a power-off loses a kid's kills.

```json
{
  "enrolled": true, "pid": 4711, "token": "…", "game_id": "fri3d2026",
  "soul": "…hex…", "commitment": "…hex…",
  "target": {"pid": 8123, "name": "Otter 42", "commitment": "…", "seen_ago_s": 240},
  "state": {"alive": true, "streak": 2, "total": 5, "respawn_at": null},
  "dodges": {"8123": 2},
  "clock_offset_s": -3,
  "queue": [ {"uuid": "…", "type": "kill", …} ],
  "synced_at": "2026-08-14T15:22:07"
}
```

Opt-out lives in `config.json` as `"gotcha": {"enrolled": false}` so it flows through
the **existing** `sanitize_config` (used by both the phone page and the on-badge
editor) and cannot be clobbered by a partial save.

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
| Radar detail (MENU short-press, target out of range) | Target name, dBm, **last seen by anyone: 12 min ago** (§10.1), your ranks, nearby bounty players. |
| Attacking | Target name, hold progress bar, live RSSI, "KEEP CLOSE!" |
| **Under attack** | Full-screen red, siren, `⚠ UNDER ATTACK — RUN! ⚠`, countdown, `dodges left: 2`. Must be unmistakable from across a field. |
| Dodged | "YOU GOT AWAY!" + relief chime + dodges remaining. |
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
| MENU short | Attack (target/bounty in range) · else open radar detail |
| MENU long (≥1.5 s) | Leave / rejoin the game (confirm prompt) |
| Existing A / B / Y / START | Unchanged |

Follow the **pre-built hidden widgets, `set_text` only** rule from the adopt prompt
(`DESIGN.md` §13.3, landmine #1): never create or delete lvgl widgets per duel. Build
every Gotcha widget once in `onCreate` and toggle `add_flag`/`remove_flag(lv.obj.FLAG.HIDDEN)`.
**There is no `clear_flag`** on this build (`DESIGN.md` §1).

### 8.5 Files touched

| File | Change |
|---|---|
| `gotcha.py` | **new** |
| `fri3d_friends.py` | MENU map + handler, Gotcha widgets, duel UI, status chip, main-loop tick, sync task, connectivity check (§7), arbitration guards |
| `ble_proximity.py` | **HSNT v2** build/parse + name budget; game fields on peer entries; **LRU cap on `seen`** |
| `contact_exchange.py` | Register the Gotcha service in `_ensure_services()`; hand handles to `GotchaResponder` |
| `beacon_service.py` | Victim-side responder + sync in the background (D3); v2 beacon |
| `ble_setup.py` | `sanitize_config` accepts `gotcha`; expose enroll state over the setup GATT |
| `MANIFEST.JSON` | → 0.10.0 |
| `docs/gotcha/index.html` | **new** — player card + 4 leaderboards |
| `docs/gotcha/admin/index.html` | **new** — host console |
| `tests/test_gotcha.py` | **new** |
| `tests/test_ble_proximity.py` | v2 format, name budget, block presence |
| `DESIGN.md` | new §14 |
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
   round-trip plus a TLS handshake (§6.2 heap risk) and fights the shared OS service.
4. **Battery-aware degradation.** Below 20 %: drop scan duty, stretch `SYNC_S`,
   disable LED breathing, blank the screen harder. Announce it on screen so it is not
   mysterious.
5. CPU frequency reduction (240 → 160 MHz) saves ~10–20 mA but risks lvgl smoothness
   and GATT timing. Not recommended.

**Add to Phase 6:** a real measurement of all five scenarios above with an inline
USB meter, on both board generations.

---

## 9. Backend contract

Stack unspecified. Requirements: HTTPS, ~2.3 req/s sustained, a small relational
store, and something operable from a phone at a muddy campsite.

### 9.1 Auth

- **Badge:** `Authorization: Bearer <player_token>`, issued at enrollment, stored in
  `gotcha.json`. Never displayed.
- **Player web page:** public data only; the QR encodes
  `…/gotcha/?badge=XXXX&t=<short-lived read token>` for the private view (your target).
- **Host:** session login on `/admin`, reachable from a phone.

### 9.2 Player endpoints

```
POST /v1/enroll
  { badge_key, display_name, groups[], commitment, app_version, board }
  -> { pid, player_token, game_id }
  Idempotent on badge_key: re-enrolling returns the existing pid and a fresh token.

GET /v1/sync
  -> { server_time,
       game:   { id, state, truce_active, truce_until, truce_schedule, modifiers },
       me:     { pid, alive, respawn_at, streak, best_streak, total_kills,
                 rank_total, rank_streak, dodges: {attacker_pid: left} },
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
| `heartbeat` | `alive`, `target_seen_ago_s`, `peers_seen`, `battery`, `groups[]` | Liveness, stale-target detection, group snapshot |
| `optout` / `optin` | — | Splice out of / into the ring |

### 9.4 Admin endpoints

```
POST /v1/admin/game            create (name, start, end, tunables)
POST /v1/admin/game/<id>/state {state: lobby|running|paused|ended}
POST /v1/admin/truce           {active, until, reason}      # instant camp-wide
POST /v1/admin/modifier        {type: double_points|amnesty, from, to}
POST /v1/admin/player/<pid>    {action: kick|revive|void_kill|adjust|reassign}
GET  /v1/admin/audit           suspicious-pattern report
GET  /v1/admin/export          full CSV/JSON dump
```

Admin actions land on every badge within `SYNC_S`. Nothing needs a push channel: the
one thing that must be instant — the attack alarm — is BLE-local.

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
| Two assassins on one bounty player | Single slot; second gets `BUSY`. |
| Victim sitting in a setup window or swap | Attack refused. **Exploit:** camping in a setup window is temporary invulnerability, bounded by the existing 2-min idle / 10-min absolute caps (`DESIGN.md` §10). While a game is running, shorten the absolute cap to 3 min. |
| RSSI spike causes a false dodge | Use the smoothed `rssi_ewma` and require `FLEE_MS` sustained, never a single sample. |
| Rapid re-attack after a dodge | `ATTACK_COOLDOWN_MS` (60 s) per pair. |

### 10.3 Sync, offline and clock

| Situation | Behaviour |
|---|---|
| Badge RTC never NTP-synced | Server receive time is authoritative; `clock_offset_s` corrects local truce/decay checks (§8.3). |
| Queue overflow | Drop oldest non-kill first; never drop a `kill`/`killed_by`. |
| Duplicate upload | Idempotent on `Event.uuid`. |
| Only the assassin reports | Accept on soul proof alone; apply the death when the victim returns. |
| Only the victim reports | `killed_by` names the attacker — credit the kill immediately, dedupe by `(victim_pid, life_id)` when the assassin's copy arrives. |
| Backend down for hours | Everyone queues. **Dormancy must pause when global sync volume collapses**, or a server outage would mass-dormant the entire camp and shred the ring. |
| 08:00, everyone powers on at once | **Jitter the sync schedule ±20%** — 700 simultaneous TLS handshakes is a self-inflicted DDoS. |

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
| Badge lost, swapped or stolen | Host kicks or reassigns from the admin page. |
| Target opts out mid-hunt | Immediate reassign on next sync. |

---

## 11. Phasing

**Phase 0 — hardware spike (blocking).** Three questions, all cheap to answer and all
capable of invalidating downstream work:

1. **WiFi + BLE coexistence.** They share one 2.4 GHz radio and the dense 50 %-duty
   scan is load-bearing (`DESIGN.md` §3). Measure peer-detection rate and `last_seen`
   age with WiFi associated and syncing, versus WiFi off. *If coexistence badly
   degrades the scan, the architecture needs revisiting.*
2. **TLS durability (§6.2).** 1000 consecutive HTTPS syncs without OOM or heap
   fragmentation. Confirm whether certificates are verified on this build.
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
Ends with two badges enrolled, each showing the other as target with a live radar bar.

**Phase 3 — the duel.** Handshake, alarm, dodge, soul reveal, inheritance, reporting.
The core fun. Ends with a real two-badge chase across a field.

**Phase 4 — background participation** (D3). The fragile one; see §5.6.

**Phase 5 — web pages.** Player card, four leaderboards, hit list, QR flow.

**Phase 6 — scale and soak.** As many badges as can be assembled, running for hours.
Watch RAM, the peer-table LRU, TLS heap, backend load, and **median time-to-first-kill**
(§3.3). **Measure all five power scenarios in §8.7 with an inline USB meter, on both
board generations.** Then a rules card, and a dry run with a dozen willing humans
before 14 August.

---

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **WiFi/BLE coexistence degrades the scan** | **High** | Phase 0 gates everything. 5-min sync (D13) already minimises exposure. |
| **TLS heap fragmentation → OOM over 4 days** | **High** | Phase 0 soak; consider plain HTTP if the LAN route materialises. |
| **Background GATT + radio handoff** (§5.6) | **High** | `ensure_radio` self-heal is the precedent; budget hardware time; be willing to ship Phase 4 late. |
| Unbounded `seen` table at 700 badges | High | LRU cap — fix regardless of Gotcha. |
| Camp uplink down → on-site server unreachable | Medium | Ask for the badge-VLAN route (§6.1); D6 means play continues regardless. |
| Kids running into things | **High (real-world)** | Truce, safe-zone rules, "no running" on the card, host truce button. |
| **Battery: app already gets only ~11 h; Gotcha naively cuts it to ~7 h** | **High** | §8.7. WiFi DTIM power save, reduced scan duty, screen blanking, battery-aware degradation. Measure in Phase 6. |
| Group exclusion makes targets unfindable | Medium | §3.3, §10.1; watch time-to-first-kill in the soak. |
| RSSI at a real camp ≠ RSSI on a bench | Medium | Every threshold is server-tunable live (§5.4). |
| Sybil / collusion | Low | Detected not prevented (§9.5); host can void and revive. |
| Badge never joined WiFi; player cannot tell the game is broken | Medium | Explicit `no network — check WiFi in Settings` state (§7), never silent absence. |

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
  means enrolled once acknowledged, not before.
- **One-press exit on the badge itself** (MENU long-press), not buried in a web page
  that needs a phone. A kid who wants out must get out in three seconds without help.
- **Location tracking is explicitly out of scope** (D17). No AP association, no
  witness-derived location hints. The only proximity data collected is
  `witnesses[]` for anti-cheat (§9.5): store it salted-hashed, retain it for the
  duration of the game only, purge after camp, and **drop it entirely if it is not
  earning its keep** — the soul mechanism carries the cryptographic weight on its own.
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
| A2 | **Can we have a route from the badge VLAN to a laptop on site?** (§6.1) | Badge talks to a LAN address. **Internet leaves the critical path**, the camp uplink stops being a single point of failure, and plain HTTP becomes viable — which **removes the TLS heap-fragmentation risk (§6.2) and Phase 0 item 2**. | Tailscale Funnel or Cloudflare Tunnel as planned. TLS soak stays a Phase 0 blocker. |

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

- **Ceremony slot.** The format is built for a Sunday-noon announcement of four winners
  (two individual, two group). The ceremony is a large part of why people play to the
  end — worth a stage slot if one can be had.
