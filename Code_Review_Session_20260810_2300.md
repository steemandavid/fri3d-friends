# Review of the 2026-08-10 session — my own day's work

**Document ID:** FRI3DFRIENDS-REVIEW-SELF-20260810
**Reviewer:** Claude (reviewing code I wrote today — see the caveat below)
**Scope:** `fa16164..HEAD`, 16 commits, +718/−101 across `app/` and `server/`
**Tests:** 442 passing (401 at the start of the day)

---

## Caveat on this review

This is a self-review by the agent that wrote the code, which is the weakest
useful kind. I already know what I intended, so I am poorly placed to notice
where the intent itself was wrong. Today produced concrete evidence of that
limit: **I reversed two of my own changes and shipped one regression that only
real hardware caught.** Treat the findings below as a floor, not a ceiling, and
weight the "process" section more heavily than the code findings.

---

## 1. What today actually shipped

| Area | Change | Validated how |
|---|---|---|
| `target_seen_ago_s` | clock-domain fix (`ticks_diff`, not `time.time()`) | **Hardware A/B**: `839661950` → `0` |
| `peers_seen` | new `_nearby` headcount before the admission gate | **Hardware A/B**: `0` → `2` on a badge sharing no group |
| §10.4a quiet | badge uploads its window | **Hardware**: `quiet_from=20:00` reached the DB |
| §8.10.3 gate | `below_min` blocks hunting, not the responder | **Hardware**: correct banner variant rendered |
| Card QR | `card_url` + overlay + menu row | **Hardware**: badge-composed URL → private card with target |
| `ring.splice_in` | permanent self-target | **Hardware**: live ring repaired `1004→1004` ⇒ `1004→1003` |
| `admin/appversion` | a floor could never be lifted | Host tests |
| `quiet_window` | ignored its own tunables | Host tests |
| §8.10.4 step 4 | soul grace window | Host tests |
| §14.2 A6 | Latin-1 NO-GO + `fold_ascii` | **Hardware**: 68 px → 53 px |
| Security | leaked admin password rotated | Verified 401/303 |

---

## 2. Findings in today's code

### F-1 · MAJOR · A non-Latin name folded away to an empty beacon name ✅ FIXED
`build_payload` folds the name for display (§8.9). A name with **no** Latin
content at all — Japanese, Greek — folds to `""`, so the badge advertised an
**empty name** and the peer's card lost every trace of who was standing there.
Before my change it showed mojibake boxes, which at least said *someone is here*.

I made a display fix strictly worse for the users it most affects. Fixed in
0.11.28: a fold that empties a non-empty name emits `"?"`. A genuinely unnamed
badge still advertises `""`.

### F-2 · MINOR · The quiet clamp is lossy and runs before the tuned bounds are known
`configure()` does `gotcha.clamp_quiet(g.get("quiet"), self.cfg)` and stores the
**clamped** result in `_quiet_cfg`. At that point `self.cfg` is the default
`GameConfig`, so the clamp uses 20:00/10:00 even if the host has widened
`QUIET_EARLIEST`. The later re-clamp in `_do_sync` then re-clamps the
**already-narrowed** value, so the original window can never be recovered.

Only bites if a host *widens* the band, and the badge-side tunables do arrive on
the next sync — but the fix is to keep the raw configured window and clamp at the
point of use. Left as-is: it touches night-safety semantics and deserves daylight.

### F-3 · INFO · `_hunting_blocked()` has a side effect
It sets the on-screen refusal message from inside what reads as a predicate. It
is documented and intentional (the player needs to know *why* A did nothing), but
a reader will not expect `if self._hunting_blocked():` to draw to the screen.

### F-4 · INFO · `version_tuple` still looks orderable
It exists only as a readability guard now, with a docstring saying "do NOT order
two of these", and one test demonstrating the trap. That is the best available
short of renaming it (`version_is_readable()`), which I did not do because it is
referenced from tests and the plan.

---

## 3. Process findings — the part that matters

### P-1 · I shipped a regression that only hardware caught
The §10.4a fix uploaded `self.quiet`, which for a player who had set nothing is
the *server's echoed default*. The badge then asserted it back as an explicit
personal window. Consequence: since §2.2 pauses streak decay only for the **camp**
truce, every player who never touched the setting would have silently bled crown
overnight — at camp, nearly everyone.

Host tests passed. It took a real badge and a DB query to see it. **The lesson is
not "write more tests" but "a round-trip through another system needs a
round-trip test"** — I tested the upload and the read-back separately, never the
loop.

### P-2 · I reversed two of my own changes within hours
- **`peers_seen`**: `current_peers()` → `len(_seen)` → `_nearby`. The first fix
  did not work; I had not checked that `admit_peer()` discards strangers before
  they reach `_seen`.
- **Empty `groups`**: omitted, then un-omitted. The original justification was a
  "partial config load" I could not actually reach when I went looking.

Both reversals came from acting on a plausible mechanism without confirming it.
The second was caught only because I re-derived the reasoning while writing D-47.

### P-3 · I cost you a badge and an evening
Deploying with `RESET=1` to three badges in a tight loop, while the foreground
app was advertising and scanning, knocked 9de4 off the USB bus — a documented
hazard in the recovery tool's own docstring. Later, resetting one at a time with
verification worked cleanly on all three.

And I set up the dry run at 21:53 without checking the clock against the 22:00
truce, then spent your evening fighting a system that was correctly asleep. The
precondition check took two minutes once I finally did it.

### P-4 · What went right, and why
Every finding that mattered came from **evidence, not reasoning**: the duel log,
the raw `events` table, the LVGL widget tree, a hardware A/B. The three bugs I am
most confident in (clock domain, self-target ring, duplicate GATT registration)
were each confirmed by an artifact I could point at. The two mistakes above were
both cases where I reasoned instead of looked.

---

## 4. Still open (not code I wrote today)

| Item | Severity for camp |
|---|---|
| **A badge with its app OPEN cannot be connected to** — the hunter's `duel_session` produced no `ds` line at all (not even `ds connected`); with the victim at the launcher every `ds` line appeared and the write landed on the right handle. The victim's dense 50% scan appears to block the inbound connect, and the `suspend()`-on-central-connect logic cannot help because the connect never completes. **This supersedes the duplicate-handle diagnosis I gave first** — that was over-claimed from `write=0` before I checked where the hunter's log line is emitted. | **BLOCKING** — two players with the app open cannot duel |
| **Duplicate GATT registration** — the boot service and the app each build their own `ContactExchange` with its own `_svc_ready`, so the app appends a SECOND service copy (two `start` lines per boot, handles 21/23/26/28 then 35/37/40/42). Real, but probably NOT the duel blocker: the hunter's discovery callback overwrites on each match, so **last wins**, which is the app's live copy. | Medium — wasteful and confusing, unclear if harmful |
| Badge→badge kill never completed end-to-end | **BLOCKING** — the core loop is unproven |
| Link-drop dodge never demoed | High |
| fac0 heartbeats from the boot service while its app is open | Medium — that badge cannot be a target |
| Crash on a second A press (no traceback captured) | Medium |
| Hunt ping is continuous at desk range | Low — UX only |
| §5.9 training mode | Dropped by the plan (droppable) |
| Full-screen UPDATE NODIG | Low — the banner carries the text |

---

## 5. Recommendation

The server is in good shape: every review finding is closed, and today's server
fixes (ring self-target, appversion clearing, quiet tunables, soul grace) are all
host-tested and deployed.

**The badge is not ready, and the gap is the duel.** The duplicate-registration
bug alone would make most of the fleet unattackable, and the badge→badge kill has
still never completed. I would treat Thursday's session as: fix the registration
handover, then prove one kill, before anything else — including the fleet deploy.
Publishing 0.11.28 to ~700 badges while the core loop is unproven would be the
wrong order.
