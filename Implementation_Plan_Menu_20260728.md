# Implementation Plan — Joystick menu redesign + OS-drawer fix (v0.10.0)

Status: **planned** (design agreed 2026-07-28). Two related fixes from this
session are already **done + deployed** and are recorded at the bottom.

## 1. Why

On the **2026 badge**, pressing our buttons pops up the MicroPythonOS **top
bar / drawer** (Test 4: "hold B → flickering OS dropdown", "A → OS menu"). Root
cause, confirmed live:

- The badge's keypad indevs (joystick + button expander) drive the **shared
  default LVGL focus group**, which also holds the OS top-bar/drawer focusables.
- Our app **bypasses LVGL and polls buttons raw** (`_held`/`_edge`), so it adds
  **nothing** to that group. Every button press is therefore "unclaimed" and the
  OS's focus fallback (the bar) grabs it → the drawer opens.

Rather than muzzle the OS input layer (redirect/unregister indevs — a global-state
footgun that broke the launcher when tried), we **use the input system the way it
is meant to be used**: give the keypad a legitimate target of our own. That target
is a **single on-badge menu** navigated with the joystick — which also replaces the
cramped `A:list B:mute Y:swap` button-legend with one discoverable list, removes the
awkward long-press-B gesture, and scales past the near-exhausted button budget.

## 2. Findings this session (the facts the design rests on)

- **Focus-group model = ONE shared default group; membership is per-activity.**
  Launcher foreground → group has its 37 icon focusables. **Our app foreground →
  group is EMPTY (count 0).** So if we add only our own focusables, they are the
  *only* thing the keypad can reach — the bar becomes unreachable. Verified by
  `get_obj_count()` before/after launching our app.
- **We never touch indev→group wiring.** Components add/remove *their* focusables
  on resume/pause (the launcher and `topmenu` both do this via
  `_add/_remove_focusables_from_group`). Doing the same means **no restore
  footgun** — the earlier breakage came from repointing indevs globally from the
  REPL, which we will not do.
- **Navigation convention is identical on both boards** (both have a joystick):
  - **2024 (measured):** joystick → `UP/DOWN/LEFT/RIGHT`, **A → `ENTER`**,
    **X → `ESC`**. B/Y emit ASCII `'B'`/`'Y'` (not nav keys). START/MENU emit
    OS-special codes (2/3).
  - **2026:** same native joystick indev + the OS-wide `A=ENTER` / `X=ESC`
    convention. (Raw 2026 key codes weren't captured — the expander delivers via an
    internal queue, not `get_key()` polling — but this is verified *concretely* at
    build time when the joystick+A menu is tested on the Tarpon 41 badge.)
- **`Y=up/B=down` (an earlier guess) is wrong** and is dropped.

## 3. The design

**Navigation — one model, both boards, no branching:**

| Input | Action |
|---|---|
| Joystick ↑ / ↓ | move highlight (OS moves focus natively) |
| **A** (`ENTER`) | select / activate the focused row |
| **X** (`ESC`) | close menu / back |

Rows are **focusable `lv.button`s with `CLICKED` handlers**. The OS keypad moves
focus and fires `CLICKED` on `ENTER` for free — we write **no** navigation code and
**no** key-to-action mapping.

**Nametag** — passive/glanceable; the button-legend line is replaced by a single
hint. Pressing **A** opens the menu.

```
 12:04              o 87%
        Tarpon 41
   ( Makerspace Baasrode )
   Vrienden dichtbij: Alice, Bob
                                 A: menu
```

**Main menu** (overlay; Dutch, ASCII only):

```
  Menu
  > Vrienden dichtbij       -> friends detail panel
    Contact ruilen          -> start a Y-swap
    Geluid: aan             -> toggle mute (label reflects state)
    Telefoon-setup          -> phone-setup QR window
    Instellingen            -> on-badge editor (SettingsActivity)
  joystick: kies   X: terug
```

**Adopt prompt** (post-swap) reuses the same focusable-row list as a multi-select:
each group is a row that toggles `[x]`/`[ ]` on `ENTER`; a final **`Meedoen`** row
confirms. No separate tick/join buttons.

**Configure-me** (fresh badge) becomes a mini-menu: *Op badge instellen ·
Telefoon-setup · Overslaan*.

## 4. Implementation

All in `app/com.fri3dcamp.fri3dfriends/fri3d_friends.py` unless noted. This
**replaces the input/interaction layer**; the BLE/proximity/swap/LED/clock/battery
logic is untouched.

### 4a. Menu widget + focus-group helpers (the core, and the drawer fix)
- `_build_menu(scr)` — a create-once hidden overlay (same discipline as
  `_build_setup_overlay`: never deleted). Holds a column of `MENU_MAX` pre-built
  `lv.button` rows, each with a label and a `CLICKED` callback slot.
- `_grab_focus(objs)` / `_release_focus()` — add our focusable objects to
  `lv.group_get_default()` and focus the first; remove them again. **This is the
  drawer fix**: while our objects are the group's only members, the keypad drives
  them, not the bar.
  - Call `_grab_focus([...])` whenever a menu/list/overlay opens; `_release_focus()`
    when it closes.
  - Call `_release_focus()` in `onPause`/`onStop`/`onDestroy` so the next activity
    (launcher / editor) gets a clean group. Removing *our* objs only (not
    `remove_all_objs`) so we never delete another component's focusables.
- **Backstop:** if testing shows the bar is still reachable, additionally call
  `topmenu._remove_focusables_from_group()` on open / `_add_...` on close (private
  OS API — use only if needed).

### 4b. Menu open/close + item wiring
- Nametag gets a single focusable "open menu" affordance (a focusable row/obj that,
  on `ENTER`, calls `_open_menu()`). `_open_menu()` populates the rows for the
  current state, `_grab_focus(rows)`, shows the overlay. `X`/`ESC` → `_close_menu()`.
- Item handlers reuse existing methods: friends panel (existing `_detail` toggle),
  swap (`_do_exchange`), mute (existing toggle + `_save_config("sound", …)`),
  phone-setup (`_open_setup_window`), editor (`_open_settings`).
- Mute row label reflects state (`Geluid: aan`/`uit`) and updates in place on toggle.

### 4c. Adopt prompt → focusable rows
- Rebuild `_build_adopt_panel` rows as focusable `lv.button`s; `ENTER` toggles the
  tick; a `Meedoen` row confirms → existing `_adopt_groups_now(chosen)`.
- Delete the current A=next/B=tick/Y=join polling path in `_handle_adopt_buttons`.

### 4d. Configure-me mini-menu
- Replace the current `A: set up on badge / Y: skip for now` raw handling with three
  focusable rows (*Op badge instellen* → `_open_settings`, *Telefoon-setup* →
  setup window, *Overslaan* → `_skip_setup`).

### 4e. Remove the old input model
- Delete the raw-poll action dispatch: `_handle_buttons`, `_handle_b_button`
  (long-press), `_edge`, and the A/B/Y/START branches. Audit **every** `_held`/
  `_edge` call site before removing.
- `_setup_buttons`/`_held` and the `BTN_2024*`/`BTN_2026_EXP`/`START_PIN` maps can
  go **iff** nothing else needs raw pins (audit first — e.g. any diagnostic use).
- Remove the bottom button-legend (`_controls_text`/`_controls_lbl`) → single
  `A: menu` hint. Remove long-press-B and START-opens-editor (both are menu items
  now).

## 5. Risks / open questions

- **Focus bookkeeping across states** (nametag ↔ menu ↔ adopt ↔ setup-window ↔
  banner) is the fiddly part: always exactly our focusables in the group, focus
  never on nothing or the bar. Contained by routing every open/close through
  `_grab_focus`/`_release_focus`.
- **2026 raw key codes unconfirmed** — accepted; verified concretely by testing the
  joystick+A menu on the 2026 badge (a mismatch would surface immediately, not
  silently).
- **Sub-Activity round-trip** (editor): `onPause` releases focus, `onResume`
  re-grabs. Confirm on device that returning re-establishes the menu focus cleanly.
- **Setup-window overlay** needs a focusable (e.g. a `Sluiten` row or just `ESC`)
  so the keypad has a target there too — otherwise the bar could reappear while it's
  open.
- **`lv.button` + focus highlight**: use `mpos.add_focus_highlight(row)` so the
  focused row is visibly highlighted (the OS's own helper; consistent look).

## 6. Verification

- **Host:** existing 118 tests stay green (this change is UI-layer; pure logic
  unchanged). Any new pure helper (e.g. menu-item model) gets a test.
- **On-device, BOTH boards** (2024 `348518acfac00000`, 2026 `90706901bac80000`):
  1. Nametag → **A opens the menu**; joystick moves the highlight; **A activates**;
     **X closes**. **No OS drawer** appears on any press.
  2. Each item works: friends panel, swap, mute (label flips + persists),
     phone-setup QR, editor (round-trips without reboot).
  3. Post-swap adopt: joystick + A multi-select + `Meedoen`; group joins; beacon
     goes live.
  4. Configure-me mini-menu on a fresh badge.
  5. Quit with **X** → clean exit to launcher; relaunch fine; launcher keypad still
     works (focus released on pause).
- Deploy via `tools/deploy.sh <serial> <files>` (sha-verified); reboot after copy so
  boot-service `sys.modules` reload.

## 7. Already done this session (v0.9.x fixes, deployed to both connected badges)

- **Ghost-splash fixed.** Splash was a second screen pushed via `setContentView`,
  leaving a stale OS-stack entry (X revealed it, X again quit). Now a **full-screen
  overlay on `self._scr`** with a single `setContentView` → X quits cleanly.
  Verified on device.
- **Adopt-panel overlap fixed.** The 2-line title overran the first group row; rows
  now start at y=50 (title occupies y=4–44). Verified on device.
- **nostr boot service disabled** on the two connected 2026 dev badges (it thrashed
  relays → thread exhaustion, contaminating tests). `MANIFEST.JSON` backed up to
  `.bak`; reversible.
