"""Game tunables (plan §5.4) and server settings.

Every constant in TUNABLE_DEFAULTS is **pushed to badges in the sync response**
and is live-editable from the admin page (§5.4: "Retuning KILL_RSSI and
KILL_HOLD_MS live from the admin page is worth a lot"). Nothing here is compiled
into the badge; the badge ships defaults only as a fallback for its very first
sync.

Values dropped by the §8.8.2a RSSI-trend no-go (TREND_*, PING_BEND_PCT) are
deliberately absent -- see `Phase0_RSSI_Trend_Spike_20260729.md`.
"""

import os

# --- Tunables pushed to the badge (§5.4). Order matches the plan's table. ----
TUNABLE_DEFAULTS = {
    "KILL_RSSI": -65,             # dBm, arm's length
    "KILL_HOLD_MS": 5000,         # sustained proximity for a kill
    "FLEE_RSSI": -78,             # escape threshold (hysteresis vs KILL_RSSI)
    "FLEE_MS": 1500,
    "REVEAL_RSSI": -80,           # looser than KILL_RSSI: reveal is the approach
    "REVEAL_COOLDOWN_S": 120,     # per hunter, not per target
    "REVEAL_FLASH_MS": 2500,
    "PING_ENABLED": True,
    "PING_FROM_SEG": 3,
    "PING_MS": 40,
    "PING_FREQ_FAR": 1400,
    "PING_FREQ_NEAR": 2400,
    "PING_INTERVAL_NEAR": 350,
    "PROX_ALPHA_UP": 0.60,        # hunt-path rssi_prox filter (§8.8.2)
    "PROX_ALPHA_DOWN": 0.08,
    "DODGE_LIMIT": 1,             # per (attacker, victim) pair per life
    "DODGE_DECAY_MS": 3600000,
    "INSTANT_KILL_MS": 1000,
    "ATTACK_COOLDOWN_MS": 60000,
    "RESPAWN_S": 1800,            # 30 min
    "SPAWN_PROTECT_S": 90,        # §5.8, forfeited on attacking
    "BOUNTY_STREAK": 3,           # live streak at which you are fair game
    "STREAK_GRACE_S": 10800,      # 3 h before decay starts (§2.2)
    "STREAK_DECAY_S": 7200,       # -1 streak per 2 h thereafter
    "QUIET_EARLIEST": "20:00",    # personal quiet-hours bounds (§10.4a)
    "QUIET_LATEST": "10:00",
    "TRAINING_WINDOW_S": 10,      # §5.9, Phase 6
    "TRAINING_SESSION_S": 300,
    "TRAINING_REENTRY_S": 600,
    "SYNC_S": 300,                # D13, jittered +-20% badge-side
    # Do not sync while the radar bar is lit (§5.4, added to the plan 2026-07-30
    # after Phase 0 spike 1): WiFi traffic drops BLE detection to 42 % of baseline
    # and stretches the worst presence gap from 1.6 s to 6.7 s, so a sync fired
    # during the endgame costs the player the kill. Badge-side behaviour, but it is
    # a tunable, so it is server-pushed like everything else.
    "HUNT_SYNC_DEFER": True,
    # Ceiling on that deferral, so a player parked next to their target cannot
    # starve the queue.
    #
    # ANCHOR (§5.4, pinned 2026-07-30) -- **PHASE 2 MUST MEASURE THIS FROM THE LAST
    # SUCCESSFUL SYNC, NOT FROM WHEN DEFERRAL BEGAN.** The server cannot enforce
    # that: it only ever observes silence, and both anchorings look identical until
    # the silence is too long. The choice is what makes the bound below hold ---
    #   from last successful sync: total silence is flat 900 s          -> safe
    #   from deferral start:       SYNC_S x 1.2 + 900 = 1260 s         -> BREACHES
    #
    # And the bound: keep this BELOW `state.OUTAGE_GAP_MIN` (20 min = 1200 s).
    # Deferral is a badge deliberately not talking, and §10.3 infers a server outage
    # from silence; if deferral could outlast that window, a camp-wide chase would
    # read as the server having been down and would pause dormancy accounting for
    # everyone. Unlikely at 700 badges, easy with 2 dev badges or 4 players in the
    # endgame. Both constants are live-tunable, so raising this one from the admin
    # page at camp can break dormancy accounting -- raise OUTAGE_GAP_MIN first.
    # `tests/test_server_plan_parity.py` guards the ordering *and* checks the 60 s
    # bucket rounding runs in the safe direction.
    "HUNT_SYNC_DEFER_MAX_S": 900,
    # Feature kill switches (§8.10.1). Absent == true on the badge; we always
    # send them explicitly so a switch can be flipped without an app update.
    "reveal_enabled": True,
    "bounty_enabled": True,
    "training_enabled": False,    # Phase 6; off until it exists
    "alarm_enabled": True,
}

# --- Server-side rules not pushed to badges ---------------------------------
SERVER_DEFAULTS = {
    "TARGET_STALE_H": 6,          # §2.4 -- splice out as a target, keep hunting
    "DORMANT_H": 12,              # §2.4, settled at rev. 5
    "DORMANT_GRACE_S": 3600,      # 1 h grace after truce/quiet (§10.4)
    "REPEAT_KILL_S": 21600,       # 6 h: repeat kill of same victim scores 0
    "MAX_KILLS_PER_HOUR": 10,     # §9.5 -- FLAG, never block
    "MAX_REPAIR_PASSES": 20,      # §3.2 ring repair
    "SIG_WINDOW_S": 600,          # +-10 min on X-Ts (§9.1)
    "CARD_TOKEN_S": 86400,        # private player-card read token lifetime
    "ADMIN_SESSION_S": 43200,     # 12 h admin login
    # §9.2's enrollment rate limit. Deliberately loose: it is an abuse guard, not
    # a game rule, and Friday morning is 700 badges enrolling at once. If the camp
    # network ever puts the badge SSID behind NAT they all share one source IP, so
    # a tight limit here would look exactly like "the game is broken". The
    # per-badge_key limit below it, and §9.5's enrollment-clustering audit, are
    # what actually catch a farm.
    "ENROLL_MAX_PER_IP_HOUR": 900,
    "TRUCE_FROM": "22:00",        # camp night truce (D7)
    "TRUCE_TO": "08:00",
    "MAX_EVENTS_PER_POST": 200,
    "HITLIST_MAX": 16,            # §9.2, sync response cap
}

DEFAULTS = dict(TUNABLE_DEFAULTS)
DEFAULTS.update(SERVER_DEFAULTS)


def tunables_for_badge(config):
    """The `config` block of the sync response: badge-relevant keys only.

    Server-side rules (DORMANT_H, MAX_KILLS_PER_HOUR, ...) are withheld -- the
    badge cannot act on them and every byte rides 700 badges x 12 syncs an hour.
    """
    out = {}
    for k in TUNABLE_DEFAULTS:
        out[k] = config.get(k, TUNABLE_DEFAULTS[k])
    return out


class Settings:
    """Deployment settings. Environment-driven so the systemd unit is the only
    place a host path or password appears."""

    def __init__(self, db_path=None, secret=None, admin_password=None,
                 dev_mode=False):
        self.db_path = db_path or os.environ.get(
            "GOTCHA_DB", "/var/lib/gotcha/gotcha.sqlite3")
        self.secret = secret or os.environ.get("GOTCHA_SECRET") or ""
        self.admin_password = (admin_password
                               or os.environ.get("GOTCHA_ADMIN_PASSWORD") or "")
        self.dev_mode = dev_mode or os.environ.get("GOTCHA_DEV") == "1"
