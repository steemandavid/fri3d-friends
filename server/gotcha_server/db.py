"""SQLite storage.

Design notes that matter:

* **One connection, one lock.** Load is 700 badges / 300 s = ~2.3 req/s (§6.1),
  so serialising every request behind a single connection costs nothing and
  removes a whole class of concurrency bugs. WAL is still on so the admin
  dashboard's reads never block a badge's write.
* **Derive, don't schedule.** `protected`, `dormant`, `stale` and the decayed
  `streak` are computed from timestamps on read (§2.2's idempotence argument
  generalised), so a server that was down for two hours is instantly correct
  when it comes back and there is no cron to get wrong. The only thing a
  reconciliation pass does is act on those derivations (splice the ring).
* **`life_id`** is a server-side per-player death counter (§10.3). It never
  crosses the wire; it exists so the two halves of one death (`kill` from the
  assassin, `killed_by` from the victim) dedupe onto one event.
"""

import json
import os
import sqlite3
import threading

SCHEMA_VERSION = 1

# pid is a u24 on the wire (§3.1). Start well above zero so a truncated or
# zero-filled pid is obviously invalid, and stay far below 2^24.
PID_BASE = 1001

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS games (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    state          TEXT NOT NULL DEFAULT 'lobby',   -- lobby|running|paused|ended
    start_at       INTEGER,
    end_at         INTEGER,
    truce_active   INTEGER NOT NULL DEFAULT 0,      -- host-called truce
    truce_until    INTEGER,
    truce_reason   TEXT,
    truce_from     TEXT NOT NULL DEFAULT '22:00',   -- camp night truce (D7)
    truce_to       TEXT NOT NULL DEFAULT '08:00',
    config_json    TEXT NOT NULL DEFAULT '{}',      -- tunable overrides (§5.4)
    min_version    TEXT,
    latest_version TEXT,
    broadcast      TEXT,                            -- <=120 chars (§8.10.3)
    created_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    pid                 INTEGER PRIMARY KEY,
    game_id             INTEGER NOT NULL,
    display_name        TEXT NOT NULL,
    player_key          TEXT NOT NULL,              -- 32 B hex, issued at enroll
    base_status         TEXT NOT NULL DEFAULT 'active',
                        -- active|dead|opted_out|kicked ; protected/dormant/
                        -- stale are DERIVED (see state.py)
    commitment          TEXT,                       -- sha256(soul), current life
    life_id             INTEGER NOT NULL DEFAULT 0,
    target_pid          INTEGER,
    total_kills         INTEGER NOT NULL DEFAULT 0, -- scoring kills (§2.1)
    score               INTEGER NOT NULL DEFAULT 0, -- sum of points (§2.1 table)
    deaths              INTEGER NOT NULL DEFAULT 0,
    best_streak         INTEGER NOT NULL DEFAULT 0,
    streak_at_last_kill INTEGER NOT NULL DEFAULT 0,
    last_kill_at        INTEGER,
    score_adjust        INTEGER NOT NULL DEFAULT 0, -- host /adjust (§9.4)
    respawn_at          INTEGER,
    protected_until     INTEGER,
    enrolled_at         INTEGER NOT NULL,
    last_sync_at        INTEGER,
    last_seen_at        INTEGER,                    -- seen by ANYONE (§10.1)
    last_event_at       INTEGER,
    app_version         TEXT,
    board               TEXT,
    battery             INTEGER,
    peers_seen          INTEGER,
    bg_service          INTEGER NOT NULL DEFAULT 0, -- app-open vs background
    quiet_from          TEXT,                       -- personal quiet hours
    quiet_to            TEXT,
    opted_out_at        INTEGER,
    kicked_at           INTEGER,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_players_target ON players(target_pid);
CREATE INDEX IF NOT EXISTS idx_players_status ON players(game_id, base_status);

-- One row per life, holding that life's soul commitment (§3.4).
--
-- Why a table and not just `players.commitment`: a kill proof can arrive hours
-- after the death that produced it (§10.3 -- the assassin may have been in a dead
-- zone), by which time the victim has respawned and rotated their soul. Keeping
-- the history means the *soul itself* identifies which life it ended, so a late
-- kill still verifies and still dedupes onto the right death. With a single
-- current commitment, a victim who respawned first would silently invalidate
-- their killer's proof -- and it would look like cheating, not like a race.
CREATE TABLE IF NOT EXISTS lives (
    pid        INTEGER NOT NULL,
    life_id    INTEGER NOT NULL,
    commitment TEXT,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER,
    PRIMARY KEY (pid, life_id)
);
CREATE INDEX IF NOT EXISTS idx_lives_commitment ON lives(commitment);

-- badge_key -> pid, with tombstones so a rebound (§9.4) badge cannot re-enroll
-- into the identity it was replaced out of.
CREATE TABLE IF NOT EXISTS badge_keys (
    badge_key  TEXT PRIMARY KEY,
    pid        INTEGER NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    bound_at   INTEGER NOT NULL,
    retired_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_badge_keys_pid ON badge_keys(pid, active);

-- Current group roster. The per-member denominator uses this (§2.3).
CREATE TABLE IF NOT EXISTS player_groups (
    pid  INTEGER NOT NULL,
    gid  INTEGER NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (pid, gid)
);
CREATE INDEX IF NOT EXISTS idx_player_groups_gid ON player_groups(gid);

CREATE TABLE IF NOT EXISTS kills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         INTEGER NOT NULL,
    assassin_pid    INTEGER NOT NULL,
    victim_pid      INTEGER NOT NULL,
    victim_life_id  INTEGER NOT NULL,
    at              INTEGER NOT NULL,   -- badge clock, offset-corrected
    server_at       INTEGER NOT NULL,   -- authoritative (§10.3)
    points          INTEGER NOT NULL,
    kind            TEXT NOT NULL,      -- target|bounty|repeat
    rssi            INTEGER,
    reported_by     TEXT NOT NULL,      -- assassin|victim|both
    voided          INTEGER NOT NULL DEFAULT 0,
    void_reason     TEXT,
    flagged         INTEGER NOT NULL DEFAULT 0,   -- §9.5: flag, never block
    flag_reason     TEXT,
    UNIQUE (victim_pid, victim_life_id)           -- one death per life (§10.3)
);
CREATE INDEX IF NOT EXISTS idx_kills_assassin ON kills(assassin_pid, server_at);
CREATE INDEX IF NOT EXISTS idx_kills_time ON kills(game_id, server_at);

-- Group attribution snapshotted at kill time (§2.3): joining the winning group
-- on Saturday night must not retroactively claim Friday's kills.
CREATE TABLE IF NOT EXISTS kill_groups (
    kill_id INTEGER NOT NULL,
    gid     INTEGER NOT NULL,
    name    TEXT NOT NULL,
    PRIMARY KEY (kill_id, gid)
);
CREATE INDEX IF NOT EXISTS idx_kill_groups_gid ON kill_groups(gid);

-- Every event ever ingested. Idempotent on uuid (§9.2).
CREATE TABLE IF NOT EXISTS events (
    uuid         TEXT PRIMARY KEY,
    pid          INTEGER NOT NULL,
    type         TEXT NOT NULL,
    at           INTEGER,
    server_at    INTEGER NOT NULL,
    ticks        INTEGER,
    payload_json TEXT,
    accepted     INTEGER NOT NULL,
    reason       TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_pid ON events(pid, server_at);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, server_at);

-- One dodge per (attacker, victim) per life (§5.4 DODGE_LIMIT).
CREATE TABLE IF NOT EXISTS dodges (
    attacker_pid   INTEGER NOT NULL,
    victim_pid     INTEGER NOT NULL,
    victim_life_id INTEGER NOT NULL,
    used           INTEGER NOT NULL DEFAULT 0,
    last_attack_at INTEGER,
    PRIMARY KEY (attacker_pid, victim_pid, victim_life_id)
);

CREATE TABLE IF NOT EXISTS attacks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    attacker_pid INTEGER NOT NULL,
    victim_pid   INTEGER NOT NULL,
    server_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attacks_pair ON attacks(attacker_pid, victim_pid, server_at);

-- Replay cache for X-Nonce, pruned to the signature window (§9.1).
CREATE TABLE IF NOT EXISTS nonces (
    pid   INTEGER NOT NULL,
    nonce TEXT NOT NULL,
    ts    INTEGER NOT NULL,
    PRIMARY KEY (pid, nonce)
);
CREATE INDEX IF NOT EXISTS idx_nonces_ts ON nonces(ts);

-- Host-called truces, kept as intervals because streak decay has to subtract
-- them retroactively (§2.2) long after they have ended.
CREATE TABLE IF NOT EXISTS truce_intervals (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    from_ts INTEGER NOT NULL,
    to_ts   INTEGER,
    reason  TEXT
);
CREATE INDEX IF NOT EXISTS idx_truce_time ON truce_intervals(game_id, from_ts);

CREATE TABLE IF NOT EXISTS modifiers (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    type    TEXT NOT NULL,          -- double_points|amnesty
    from_ts INTEGER NOT NULL,
    to_ts   INTEGER NOT NULL
);

-- Per-minute sync counts. §10.3: "Dormancy must pause when global sync volume
-- collapses" -- a server outage must not mass-dormant the camp and shred the
-- ring. This table is how the server knows an outage happened.
CREATE TABLE IF NOT EXISTS sync_beats (
    minute_ts INTEGER PRIMARY KEY,
    n         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          INTEGER NOT NULL,
    host        TEXT NOT NULL,      -- which volunteer (§9.4)
    action      TEXT NOT NULL,
    target_pid  INTEGER,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_admin_log_at ON admin_log(at);

CREATE TABLE IF NOT EXISTS enroll_attempts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ip        TEXT,
    badge_key TEXT,
    at        INTEGER NOT NULL,
    outcome   TEXT
);
CREATE INDEX IF NOT EXISTS idx_enroll_ip ON enroll_attempts(ip, at);
"""


class Database:
    def __init__(self, path):
        self.path = path
        if path != ":memory:":
            d = os.path.dirname(os.path.abspath(path))
            if d:
                os.makedirs(d, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self.set_meta("schema_version", str(SCHEMA_VERSION))

    # -- plumbing ----------------------------------------------------------
    @property
    def lock(self):
        """Held for the whole of a request's read-modify-write (see routes)."""
        return self._lock

    def close(self):
        with self._lock:
            self._conn.close()

    def execute(self, sql, args=()):
        with self._lock:
            return self._conn.execute(sql, args)

    def executemany(self, sql, seq):
        with self._lock:
            return self._conn.executemany(sql, seq)

    def commit(self):
        with self._lock:
            self._conn.commit()

    def rollback(self):
        with self._lock:
            self._conn.rollback()

    def one(self, sql, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            return cur.fetchone()

    def all(self, sql, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            return cur.fetchall()

    def scalar(self, sql, args=(), default=None):
        row = self.one(sql, args)
        if row is None:
            return default
        v = row[0]
        return default if v is None else v

    # -- meta --------------------------------------------------------------
    def get_meta(self, key, default=None):
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return default if row is None else row["value"]

    def set_meta(self, key, value):
        self.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))
        self.commit()

    def get_meta_json(self, key, default=None):
        raw = self.get_meta(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default

    def set_meta_json(self, key, obj):
        self.set_meta(key, json.dumps(obj, sort_keys=True))

    # -- pid allocation ----------------------------------------------------
    def next_pid(self):
        """Sequential u24 pids from PID_BASE. Sequential rather than random so a
        host reading '#1042' off a badge can find the player, and so the audit
        page's enrollment-clustering heuristic (§9.5) has a natural ordering."""
        top = self.scalar("SELECT MAX(pid) FROM players", default=None)
        return PID_BASE if top is None else int(top) + 1
