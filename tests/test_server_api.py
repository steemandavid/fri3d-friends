"""End-to-end API tests driven by the badge simulator (plan §11, Phase 1).

Every request here is signed by the badge's own `gotcha.py` and every response is
verified by it, so these tests cover the wire contract as well as the rules.

Where a test asserts a rule, the plan reference is in the docstring -- these are
the rules a badge is *not* trusted to enforce (§9.5), so if one of these tests is
ever "fixed" by relaxing the server, read the reference first.
"""
import json

import pytest

from badge_sim import BadgeError
from gotcha_server import service, state


# ---------------------------------------------------------------------------
# Enrollment (§9.2)
# ---------------------------------------------------------------------------

def test_enroll_assigns_a_pid_and_key(server, badges):
    b = badges(1)
    assert b.pid >= 1001
    assert len(b.player_key) == 64
    p = service.player_by_pid(server.db, b.pid)
    assert p["display_name"] == b.display_name
    assert p["commitment"] == b.commitment
    # A first join lands protected (§5.8) -- joining into the middle of a scrum
    # should not mean dying instantly.
    assert state.is_protected(p, server.clock.now())


def test_enroll_is_idempotent_on_badge_key_and_preserves_score(server, badges):
    """§10.5: "gotcha.json wiped -> re-enroll by badge_key -> same pid, score
    intact." No admin action needed."""
    a, victim = badges(2)
    server.start_game()
    server.advance(200)                       # let protection lapse
    _force_target(server, a, victim)
    a.kill(victim)
    before = service.player_by_pid(server.db, a.pid)
    assert before["total_kills"] == 1

    old_key = a.player_key
    a.soul = a.rotate_soul().encode() and a.soul   # fresh soul, as a wiped badge has
    a.enroll()
    after = service.player_by_pid(server.db, a.pid)
    assert after["total_kills"] == 1           # score survived
    assert a.player_key != old_key             # fresh player_key
    assert a.sync()["me"]["pid"] == a.pid


def test_enroll_rejects_a_retired_badge_key(server, badges):
    """After a /rebind the dead badge must not be able to re-enroll into the
    identity it was replaced out of (§9.4)."""
    b = badges(1)
    server.admin_post("/v1/admin/player/%d/rebind" % b.pid,
                      {"new_badge_key": "ffffffffffff"})
    r = server.client.post("/v1/enroll", json={
        "badge_key": b.badge_key, "display_name": "zombie",
        "commitment": b.commitment, "groups": []})
    assert r.status_code == 409
    assert r.json()["error"] == "retired_badge_key"


def test_rebind_keeps_score_streak_and_target(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.kill(v)
    target_before = service.player_by_pid(server.db, a.pid)["target_pid"]

    server.admin_post("/v1/admin/player/%d/rebind" % a.pid,
                      {"new_badge_key": "cafecafecafe"})
    # The new badge enrolls normally and lands on the same pid.
    from badge_sim import BadgeSim
    new_badge = BadgeSim(server, "cafecafecafe", a.display_name)
    new_badge.enroll()
    assert new_badge.pid == a.pid
    p = service.player_by_pid(server.db, a.pid)
    assert p["total_kills"] == 1
    assert p["target_pid"] == target_before
    assert state.is_protected(p, server.clock.now())


def test_enroll_validates_its_input(server):
    for body in [{}, {"badge_key": "x"}, {"badge_key": "x", "commitment": "short"}]:
        r = server.client.post("/v1/enroll", json=body)
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Signed transport (§6.2, §9.1)
# ---------------------------------------------------------------------------

def test_sync_requires_a_signature(server, badges):
    b = badges(1)
    assert server.client.get("/v1/sync").status_code == 401
    r = server.client.get("/v1/sync", headers={"X-Pid": str(b.pid), "X-Ts": "1",
                                               "X-Nonce": "abcd", "X-Sig": "00"})
    assert r.status_code == 401


def test_sync_response_is_signed_and_binds_the_nonce(server, badges):
    """§6.2: "Responses must be signed too. Without it, a MITM could inject
    'truce off', 'you are dead', or a fake target." """
    b = badges(1)
    payload = b.sync()                        # BadgeSim raises unless sig+nonce ok
    assert "config" in payload and "me" in payload
    # And a tampered payload fails the badge's own verifier.
    import gotcha
    r, nonce = b._signed("GET", "/v1/sync")
    env = r.json()
    env["payload"]["me"]["streak"] = 99
    assert not gotcha.sig_ok(b.player_key, env["ts"], env["nonce"], env["payload"],
                             env["sig"])


def test_replayed_nonce_is_rejected(server, badges):
    b = badges(1)
    import gotcha
    ts = b.now()
    nonce = "0123456789abcdef"
    sig = gotcha.sign_request(b.player_key, "GET", "/v1/sync", ts, nonce, b"")
    h = {"X-Pid": str(b.pid), "X-Ts": str(ts), "X-Nonce": nonce, "X-Sig": sig}
    assert server.client.get("/v1/sync", headers=h).status_code == 200
    assert server.client.get("/v1/sync", headers=h).status_code == 401


def test_stale_timestamp_is_rejected_but_ten_minutes_is_tolerated(server, badges):
    """Badge RTCs drift (§9.1's generous +-10 min window)."""
    b = badges(1)
    b.clock_offset_s = 540                    # 9 min fast: fine
    assert b.sync()["me"]["pid"] == b.pid
    b.clock_offset_s = 1200                   # 20 min fast: refused
    with pytest.raises(BadgeError):
        b.sync()


def test_signature_covers_the_query_string(server, badges):
    """A tampered `?board=` must not verify -- `crypto.signing_path` pins the
    plan's "METHOD || PATH" to the full request target."""
    import gotcha
    b = badges(1)
    ts, nonce = b.now(), "aaaabbbbccccdddd"
    sig = gotcha.sign_request(b.player_key, "GET", "/v1/leaderboard?board=total",
                              ts, nonce, b"")
    h = {"X-Pid": str(b.pid), "X-Ts": str(ts), "X-Nonce": nonce, "X-Sig": sig}
    assert server.client.get("/v1/leaderboard?board=streak", headers=h).status_code == 401


def test_body_is_signed_as_received(server, badges):
    b = badges(1)
    b.heartbeat()
    assert b.flush()["accepted"]


# ---------------------------------------------------------------------------
# Sync payload (§9.2)
# ---------------------------------------------------------------------------

def test_sync_carries_everything_the_badge_needs_offline(server, badges):
    a, v = badges(2)
    server.start_game()
    p = a.sync()
    for key in ("server_time", "game", "me", "target", "hitlist", "app",
                "broadcast", "config"):
        assert key in p, key
    for key in ("id", "state", "truce_active", "truce_until", "truce_schedule",
                "modifiers"):
        assert key in p["game"], key
    for key in ("pid", "alive", "respawn_at", "protected_until", "streak",
                "best_streak", "total_kills", "rank_total", "rank_streak",
                "dodges", "card_token"):
        assert key in p["me"], key
    # The tunables the badge acts on (§5.4), and none of the server-only ones.
    assert p["config"]["KILL_RSSI"] == -65
    assert p["config"]["SYNC_S"] == 300
    # Added to §5.4 on 2026-07-30 after Phase 0 spike 1: the badge must not sync
    # while the radar bar is lit, because WiFi traffic costs 58 % of the BLE
    # detection rate and a sync in the endgame costs the player the kill.
    assert p["config"]["HUNT_SYNC_DEFER"] is True
    assert p["config"]["HUNT_SYNC_DEFER_MAX_S"] == 900
    # The asymmetric hunt filter (§8.8.2) -- the difference between a working kill
    # and a broken one once both badges are worn.
    assert p["config"]["PROX_ALPHA_UP"] == 0.60
    assert p["config"]["PROX_ALPHA_DOWN"] == 0.08
    assert "DORMANT_H" not in p["config"]
    assert "MAX_KILLS_PER_HOUR" not in p["config"]
    # The dropped RSSI-trend tunables must not reappear (§8.8.2a no-go).
    for gone in ("TREND_ALPHA_FAST", "TREND_ALPHA_SLOW", "TREND_DEADBAND_DB",
                 "PING_BEND_PCT"):
        assert gone not in p["config"]


def test_sync_gives_a_target_with_freshness(server, badges):
    a, v = badges(2)
    server.start_game()
    t = a.sync()["target"]
    assert t is not None
    assert t["pid"] == v.pid
    assert t["commitment"] == v.commitment      # so the badge can verify offline
    assert t["last_seen_ago_s"] >= 0


def test_ring_of_one_has_no_target(server, badges):
    a = badges(1)
    server.start_game()
    assert a.sync()["target"] is None


def test_hunter_learns_the_target_is_asleep_not_where_they_are(server, badges):
    """§10.4: the strip reads "Otter 42 - slaapt": you learn THAT they are
    unavailable, never where they are."""
    a, v = badges(2)
    server.start_game()
    v.set_quiet("20:00", "09:00")
    v.flush()
    server.advance(10 * 3600 + 1800)            # 20:30
    t = a.sync()["target"]
    assert t["halted"] is True


def test_broadcast_and_app_version_reach_the_badge(server, badges):
    b = badges(1)
    server.admin_post("/v1/admin/broadcast", {"text": "Ceremonie om 17:00 aan de bar"})
    server.admin_post("/v1/admin/appversion", {"min_version": "0.11.0",
                                               "latest_version": "0.11.2"})
    p = b.sync()
    assert p["broadcast"] == "Ceremonie om 17:00 aan de bar"
    assert p["app"] == {"min_version": "0.11.0", "latest_version": "0.11.2"}


def test_appversion_floor_can_be_lifted_again(server, badges):
    """A version floor must be removable through the API.

    Since §8.10.3 a badge below min_version stops hunting, so a floor typed by
    mistake takes the camp out of the game. The endpoint used to do
    `str(v) if v else None` + COALESCE, which read an empty string as "keep" --
    so a floor could be set and then never lifted except by editing the DB."""
    b = badges(1)
    server.admin_post("/v1/admin/appversion", {"min_version": "0.99.0",
                                               "latest_version": "0.99.0"})
    assert b.sync()["app"] == {"min_version": "0.99.0", "latest_version": "0.99.0"}

    server.admin_post("/v1/admin/appversion", {"min_version": "",
                                               "latest_version": ""})
    assert b.sync()["app"] == {"min_version": None, "latest_version": None}


def test_appversion_absent_key_leaves_the_other_alone(server, badges):
    # Partial updates must not clear the field they do not mention.
    b = badges(1)
    server.admin_post("/v1/admin/appversion", {"min_version": "0.11.0",
                                               "latest_version": "0.11.9"})
    server.admin_post("/v1/admin/appversion", {"latest_version": "0.12.0"})
    assert b.sync()["app"] == {"min_version": "0.11.0", "latest_version": "0.12.0"}


def test_broadcast_is_capped_at_120_chars(server, badges):
    b = badges(1)
    server.admin_post("/v1/admin/broadcast", {"text": "x" * 500})
    assert len(b.sync()["broadcast"]) == 120


# ---------------------------------------------------------------------------
# The kill (§2, §3.4, §9.3)
# ---------------------------------------------------------------------------

def _force_target(server, hunter, victim):
    """Point the ring at a chosen victim, so a test can be about one rule."""
    server.db.execute("UPDATE players SET target_pid=? WHERE pid=?",
                      (victim.pid, hunter.pid))
    server.db.commit()


def test_kill_scores_one_point_and_inherits_the_target(server, badges):
    a, v, c = badges(3)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    _force_target(server, v, c)

    a.report_kill(v)
    assert a.flush()["accepted"]

    pa = service.player_by_pid(server.db, a.pid)
    pv = service.player_by_pid(server.db, v.pid)
    assert pa["total_kills"] == 1 and pa["score"] == 1
    assert pa["streak_at_last_kill"] == 1 and pa["best_streak"] == 1
    assert pa["target_pid"] == c.pid            # classic inheritance (D10)
    assert pv["base_status"] == state.DEAD
    assert pv["respawn_at"] == server.clock.now() + 1800


def test_kill_without_the_soul_is_refused(server, badges):
    """§9.5: "Cryptographically enforced: a kill requires the victim's soul. No
    soul, no kill." An assassin cannot POST "I killed Otter 42" from a tent."""
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a._queue("kill", victim_pid=v.pid, soul="00" * 16, rssi=-60)
    out = a.flush()
    assert out["accepted"] == []
    assert out["rejected"][0]["reason"] == "bad_soul"
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.ACTIVE


def test_a_replayed_soul_cannot_kill_the_next_life(server, badges):
    """§3.4: "A fresh soul per life binds each proof to one specific death."

    The soul of a life that has already ended buys nothing: it resolves to that
    finished life, dedupes onto the death it already proved, and produces no
    second kill and no second point. A *different* player replaying a sniffed
    soul is refused outright.
    """
    a, v, sniffer = badges(3)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    old_soul = v.soul
    a.kill(v)                                   # v rotates its soul on death

    server.advance(1900)                        # respawn
    a.sync()
    server.advance(100)
    _force_target(server, a, v)
    a._queue("kill", victim_pid=v.pid, soul=old_soul.hex())
    a.flush()
    assert service.player_by_pid(server.db, a.pid)["total_kills"] == 1
    assert int(server.db.scalar("SELECT COUNT(*) FROM kills", default=0)) == 1
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.ACTIVE

    _force_target(server, sniffer, v)
    sniffer._queue("kill", victim_pid=v.pid, soul=old_soul.hex())
    assert sniffer.flush()["rejected"][0]["reason"] == "already_dead"


def test_events_are_idempotent_on_uuid(server, badges):
    """§9.2: a badge that flushes twice, or retries after a dropped POST, must not
    double-score."""
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    ev = a.report_kill(v)
    a.flush()
    a.queue.append(ev)                          # the same event again
    a.flush()
    assert service.player_by_pid(server.db, a.pid)["total_kills"] == 1
    assert int(server.db.scalar("SELECT COUNT(*) FROM kills", default=0)) == 1


def test_both_halves_of_one_death_dedupe(server, badges):
    """§10.3: the assassin's `kill` and the victim's `killed_by` are one death,
    deduped by (victim_pid, life_id)."""
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.kill(v)                                   # reports both halves
    assert int(server.db.scalar("SELECT COUNT(*) FROM kills", default=0)) == 1
    row = server.db.one("SELECT * FROM kills")
    assert row["reported_by"] == "both"
    assert service.player_by_pid(server.db, a.pid)["total_kills"] == 1


def test_victim_only_report_credits_the_kill_immediately(server, badges):
    """§10.3: "Only the victim reports: killed_by names the attacker -- credit the
    kill immediately." The assassin may be in a dead zone for hours."""
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    v.report_death(a)
    assert v.flush()["accepted"]
    assert service.player_by_pid(server.db, a.pid)["total_kills"] == 1
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.DEAD


def test_assassin_only_report_applies_the_death(server, badges):
    """§10.3: "Only the assassin reports: accept on soul proof alone." """
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.report_kill(v)
    a.flush()
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.DEAD


def test_bounty_kill_scores_two(server, badges):
    """§2: a bounty player (live streak >= 3) who is not your target is worth 2."""
    hunter, leader = badges(2)
    others = badges(4)
    server.start_game()
    server.advance(200)
    # Give the leader a streak of 3 by killing three players.
    for victim in others[:3]:
        _force_target(server, leader, victim)
        leader.kill(victim)
    assert service.player_by_pid(server.db, leader.pid)["streak_at_last_kill"] == 3
    assert leader.pid in [h["pid"] for h in hunter.sync()["hitlist"]]

    _force_target(server, hunter, others[3])    # NOT the leader
    hunter.report_kill(leader, as_kind="bounty")
    assert hunter.flush()["accepted"]
    ph = service.player_by_pid(server.db, hunter.pid)
    assert ph["score"] == 2
    k = server.db.one("SELECT * FROM kills WHERE assassin_pid=?", (hunter.pid,))
    assert k["kind"] == "bounty"


def test_killing_a_stranger_without_a_bounty_is_refused(server, badges):
    a, v, stranger = badges(3)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.report_kill(stranger)
    out = a.flush()
    assert out["rejected"][0]["reason"] == "not_your_target"


def test_repeat_kill_within_six_hours_scores_zero(server, badges):
    """§2: "Repeat kill of the same victim within 6 h -> 0 (anti-farming; still
    counts as a death for the victim)." """
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.kill(v)
    server.advance(1900)                        # v respawns
    a.sync()
    server.advance(100)                         # spawn protection lapses
    _force_target(server, a, v)
    a.report_kill(v)
    a.flush()

    pa = service.player_by_pid(server.db, a.pid)
    assert pa["score"] == 1                     # the second kill added nothing
    assert pa["total_kills"] == 1
    assert service.player_by_pid(server.db, v.pid)["deaths"] == 2   # still a death
    kinds = [r["kind"] for r in server.db.all("SELECT kind FROM kills ORDER BY id")]
    assert kinds == ["target", "repeat"]


def test_repeat_kill_scores_again_after_six_hours(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.kill(v)
    # Six hours pass with both badges visibly in the field -- otherwise the
    # victim goes `stale` and is legitimately spliced out (§10.1), which is a
    # different rule than the one under test.
    for _ in range(7):
        server.advance(3600)
        a.heartbeat(target_seen_ago_s=30)
        a.flush()
        v.sync()
    _force_target(server, a, v)
    a.report_kill(v)
    a.flush()
    assert service.player_by_pid(server.db, a.pid)["score"] == 2


def test_kills_during_a_truce_are_rejected(server, badges):
    """§2/D7: "Any kill during a truce -> rejected." Checked server-side even
    though the badge refuses first (§9.5's defence in depth)."""
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    server.advance(13 * 3600)                   # 23:00, inside the night truce
    a.report_kill(v)
    out = a.flush()
    assert out["rejected"][0]["reason"] == "truce"
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.ACTIVE


def test_a_kill_made_before_the_truce_still_counts_when_it_uploads_later(server, badges):
    """The queue may sit for hours (§10.3). Rule checks use the event's own
    timestamp, so a legal kill at 21:55 is not voided by a 23:00 upload."""
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    server.advance(11 * 3600 + 3000)            # ~21:50
    ev = a.report_kill(v)
    v.report_death(a)
    server.advance(5000)                        # now 23:13, inside the truce
    out = a.flush()
    assert ev["uuid"] in out["accepted"]
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.DEAD


def test_kill_during_personal_quiet_hours_is_refused_both_ways(server, badges):
    """§10.4a: quiet hours are symmetric. "If you cannot be attacked you cannot
    attack" -- an asymmetric version would be a straightforward invulnerability
    exploit and every kid would find it on Friday afternoon."""
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    v.set_quiet("20:00", "09:00")
    v.flush()
    server.advance(10 * 3600 + 1800)            # 20:30

    a.report_kill(v)
    assert a.flush()["rejected"][0]["reason"] == "victim_quiet"

    # And the sleeper cannot attack either.
    _force_target(server, v, a)
    v.report_kill(a)
    assert v.flush()["rejected"][0]["reason"] == "attacker_quiet"


def test_a_badge_cannot_declare_itself_quiet_all_afternoon(server, badges):
    """The badge-declared window is clamped server-side on ingest (§10.4a)."""
    a, v = badges(2)
    server.start_game()
    v.set_quiet("12:00", "19:00")
    v.flush()
    p = service.player_by_pid(server.db, v.pid)
    assert p["quiet_from"] == "20:00"            # clamped to QUIET_EARLIEST
    assert p["quiet_to"] == "10:00"
    server.advance(200)
    _force_target(server, a, v)
    a.report_kill(v)
    assert a.flush()["accepted"]                 # 10:05, wide awake


def test_protected_players_cannot_be_killed(server, badges):
    """§5.8: the responder refuses with PROTECTED; re-checked here so a badge that
    lies about protection gains nothing."""
    a, v = badges(2)
    server.start_game()
    _force_target(server, a, v)                 # v is still inside its join protection
    a.report_kill(v)
    assert a.flush()["rejected"][0]["reason"] == "protected"


def test_attacking_forfeits_your_own_protection(server, badges):
    """§5.8: "Protection ends immediately when the protected player sends an
    ATTACK. It is a breath, not a bunker." """
    a, v = badges(2)
    server.start_game()
    assert state.is_protected(service.player_by_pid(server.db, a.pid),
                              server.clock.now())
    a.report_attack_started(v)
    a.flush()
    assert not state.is_protected(service.player_by_pid(server.db, a.pid),
                                  server.clock.now())


def test_killing_a_dead_player_is_refused(server, badges):
    a, v, c = badges(3)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.kill(v)
    _force_target(server, c, v)
    c.report_kill(v)
    assert c.flush()["rejected"][0]["reason"] in ("already_dead", "bad_soul")


def test_kill_is_refused_before_the_game_starts(server, badges):
    a, v = badges(2)
    _force_target(server, a, v)
    server.advance(200)
    a.report_kill(v)
    assert a.flush()["rejected"][0]["reason"] == "game_not_running"


def test_stale_pairing_voids_the_kill_and_spares_the_victim(server, badges):
    """§10.2: "an invalid pairing is voided and the victim is revived with streak
    restored. A stale assassin must never be able to permanently cost someone
    their streak." """
    a, v, other = badges(3)
    server.start_game()
    server.advance(200)
    _force_target(server, a, other)             # a's target is NOT v
    v.report_death(a)                           # v's badge believed it died
    out = v.flush()
    assert out["accepted"]                       # the report is accepted...
    k = server.db.one("SELECT * FROM kills WHERE victim_pid=?", (v.pid,))
    assert k["voided"] == 1                      # ...but the kill does not count
    assert k["void_reason"] == "not_your_target"
    pv = service.player_by_pid(server.db, v.pid)
    assert pv["base_status"] == state.ACTIVE     # and v keeps their life
    assert service.player_by_pid(server.db, a.pid)["total_kills"] == 0


def test_streak_continues_from_the_decayed_value(server, badges):
    """§2.2: decay lowers the live streak, and the next kill continues from
    there -- not from the pre-decay high-water mark."""
    a = badges(1)
    victims = badges(6)
    server.start_game()
    server.advance(200)
    for v in victims[:3]:
        _force_target(server, a, v)
        a.kill(v)
    assert a.sync()["me"]["streak"] == 3
    server.advance(7 * 3600)                     # 3 h grace + 2 x 2 h decay = -2
    a.sync()
    assert a.sync()["me"]["streak"] == 1
    _force_target(server, a, victims[3])
    a.kill(victims[3])
    assert a.sync()["me"]["streak"] == 2
    assert a.sync()["me"]["best_streak"] == 3    # never decays


# ---------------------------------------------------------------------------
# Respawn, dodge, opt-out (§5.4, §5.8, rule 15)
# ---------------------------------------------------------------------------

def test_respawn_after_thirty_minutes_with_protection(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.kill(v)
    assert v.sync()["me"]["alive"] is False
    server.advance(1801)
    p = v.sync()
    assert p["me"]["alive"] is True
    assert p["me"]["status"] == state.PROTECTED
    assert p["me"]["streak"] == 0                # a death resets the streak
    assert p["target"] is not None               # and they are back in the ring


def test_dodge_is_recorded_once_per_pair_per_life(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    v.report_dodge(attacker=a)
    v.flush()
    assert v.sync()["me"]["dodges"] == {str(a.pid): 0}
    # A second dodge in the same life cannot go below zero left.
    v.report_dodge(attacker=a)
    v.flush()
    assert v.sync()["me"]["dodges"] == {str(a.pid): 0}


def test_dodge_reported_by_either_side_lands_on_the_same_row(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.report_dodge(victim=v)
    a.flush()
    rows = server.db.all("SELECT * FROM dodges")
    assert len(rows) == 1
    assert rows[0]["attacker_pid"] == a.pid and rows[0]["victim_pid"] == v.pid


def test_optout_splices_out_and_optin_returns_protected(server, badges):
    a, v, c = badges(3)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    _force_target(server, v, c)

    v.optout()
    v.flush()
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.OPTED_OUT
    # The hunter is reassigned on their next sync -- never left hunting a ghost.
    assert a.sync()["target"]["pid"] != v.pid
    # And an opted-out player cannot be killed.
    _force_target(server, a, v)
    a.report_kill(v)
    assert a.flush()["rejected"][0]["reason"] == "victim_opted_out"

    v.optin()
    v.flush()
    p = v.sync()
    assert p["me"]["status"] == state.PROTECTED
    assert p["target"] is not None


def test_dormant_badge_is_spliced_out_and_returns_on_sync(server, badges):
    """§2.4: 12 h with no sync splices a badge out, "within an evening-plus-night
    while surviving any realistic charging break"."""
    a, v, c = badges(3)
    server.start_game()
    server.advance(200)
    for b in (a, v, c):
        b.sync()
    # a and c keep syncing for a day; v's badge is off in a tent. Note it takes
    # more than 12 *wall* hours: the 22:00-08:00 truce plus its 1 h grace does not
    # count towards dormancy (§10.4), so a badge switched off at 10:00 on Friday
    # is spliced out mid-morning on Saturday, not at 22:00 on Friday.
    for _ in range(24 * 4):
        server.advance(900)
        a.sync()
        c.sync()
    pv = service.player_by_pid(server.db, v.pid)
    assert state.status_of(pv, server.game, server.db,
                           server.clock.now()) == state.DORMANT
    assert a.sync()["target"]["pid"] != v.pid
    # Any sync brings them back, protected.
    assert v.sync()["me"]["status"] == state.PROTECTED


def test_stale_target_is_reassigned_but_keeps_hunting(server, badges):
    """§10.1 / §9.6: `stale` is the one asymmetric status -- "a player whose badge
    is in a tent should stop stranding their hunter without also being told they
    are out of the game"."""
    a, v, c = badges(3)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    # v keeps syncing (so not dormant) but nobody ever reports seeing them.
    for _ in range(7 * 2):
        server.advance(1800)
        v.sync(flush=False)
        v.queue.clear()
    pv = service.player_by_pid(server.db, v.pid)
    assert state.status_of(pv, server.game, server.db,
                           server.clock.now()) == state.STALE
    assert a.sync()["target"]["pid"] != v.pid     # a is not stranded
    assert v.sync()["target"] is not None         # but v still hunts


def test_heartbeat_freshness_keeps_a_target_out_of_stale(server, badges):
    a, v = badges(2)
    server.start_game()
    _force_target(server, a, v)
    for _ in range(8):
        server.advance(3600)
        a.heartbeat(target_seen_ago_s=60)
        a.flush()
    pv = service.player_by_pid(server.db, v.pid)
    assert not state.is_stale(pv, server.clock.now())


def test_reveal_refreshes_liveness(server, badges):
    """§9.3: being revealed "proves you were physically near someone, so it
    refreshes last_seen"."""
    a, v = badges(2)
    server.start_game()
    server.advance(4 * 3600)
    a.report_reveal(v)
    v.report_revealed(a)
    a.flush()
    v.flush()
    pv = service.player_by_pid(server.db, v.pid)
    assert pv["last_seen_at"] == server.clock.now()


# ---------------------------------------------------------------------------
# Leaderboards (§2.3, §9.2)
# ---------------------------------------------------------------------------

def test_leaderboards_and_group_boards(server, badges):
    chiro = badges(4, groups=["Chiro"], name_prefix="Chiro")
    makers = badges(3, groups=["Makerspace Baasrode"], name_prefix="Maker")
    solo = badges(1, groups=["Solo"], name_prefix="Solo")
    server.start_game()
    server.advance(200)

    # Chiro's first player kills two makers; a maker kills a chiro member.
    for v in makers[:2]:
        _force_target(server, chiro[0], v)
        chiro[0].kill(v)
    server.advance(1900)
    _force_target(server, makers[2], chiro[3])
    makers[2].kill(chiro[3])

    total = chiro[0].leaderboard("total")["entries"]
    assert total[0]["pid"] == chiro[0].pid and total[0]["score"] == 2

    streak = chiro[0].leaderboard("streak")["entries"]
    assert streak[0]["best_streak"] == 2

    gt = chiro[0].leaderboard("group_total")["entries"]
    by_name = {g["name"]: g for g in gt}
    assert by_name["chiro"]["points"] == 2
    assert by_name["makerspace baasrode"]["points"] == 1

    # §2.3: the per-member board needs at least 3 members.
    pm = chiro[0].leaderboard("group_per_member")["entries"]
    names = [g["name"] for g in pm]
    assert "solo" not in names                   # 1 member: excluded
    assert by_name["chiro"]["members"] == 4
    # chiro: 2 points / 4 members = 0.5; makerspace: 1 / 3 = 0.33.
    assert names[0] == "chiro"
    per = {g["name"]: g["per_member"] for g in pm}
    assert per["chiro"] == 0.5 and per["makerspace baasrode"] == 0.33


def test_group_attribution_is_snapshotted_at_kill_time(server, badges):
    """§2.3: "joining the winning group on Saturday night does not retroactively
    claim Friday's kills"."""
    a, v = badges(2, groups=["Chiro"])
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.kill(v)

    a.groups = ["Winnaars"]                      # switches groups mid-camp
    a.heartbeat()
    a.flush()

    boards = {g["name"]: g for g in a.leaderboard("group_total")["entries"]}
    assert boards["chiro"]["points"] == 1        # the kill stayed with chiro
    assert boards.get("winnaars", {"points": 0})["points"] == 0


def test_public_pages_and_card_token(server, badges):
    a, v = badges(2)
    server.start_game()
    p = a.sync()
    token = p["me"]["card_token"]

    pub = server.client.get("/v1/public/player/%d" % a.pid).json()
    assert pub["name"] == a.display_name and "target" not in pub

    priv = server.client.get("/v1/public/player/%d?t=%s" % (a.pid, token)).json()
    assert priv["target"]["pid"] == v.pid

    bad = server.client.get("/v1/public/player/%d?t=%s" % (a.pid, "0.deadbeef")).json()
    assert "target" not in bad
    # The token is bound to the player it was issued for.
    other = server.client.get("/v1/public/player/%d?t=%s" % (v.pid, token)).json()
    assert "target" not in other

    assert server.client.get("/gotcha/").status_code == 200
    assert server.client.get("/healthz").json()["ok"] is True


# ---------------------------------------------------------------------------
# Admin (§9.4)
# ---------------------------------------------------------------------------

def test_admin_requires_login(server):
    assert server.client.get("/v1/admin/dashboard").status_code == 401
    r = server.client.post("/admin/login", data={"host": "x", "password": "wrong"})
    assert r.status_code == 401
    assert server.client.get("/admin").status_code == 200      # login form


def test_dashboard_numbers(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.sync()
    v.sync()
    a.kill(v)

    d = server.admin_get("/v1/admin/dashboard")
    assert d["kills_10m"] == 1
    assert d["kills_1h"] == 1
    assert d["population"]["enrolled"] == 2
    assert d["population"]["dead"] == 1
    assert d["health"]["synced_15m"] == 2
    assert d["fleet"]["versions"] == {"0.11.0": 2}
    assert d["leaders"]["total"][0]["pid"] == a.pid
    assert d["game"]["state"] == "running"


def test_host_truce_button_stops_kills_immediately(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    server.admin_post("/v1/admin/truce", {"active": True,
                                          "until": server.clock.now() + 600,
                                          "reason": "onweer"})
    assert a.sync()["game"]["truce_active"] is True
    a.report_kill(v)
    assert a.flush()["rejected"][0]["reason"] == "truce"

    server.admin_post("/v1/admin/truce", {"active": False})
    assert a.sync()["game"]["truce_active"] is False
    a.report_kill(v)
    assert a.flush()["accepted"]


def test_host_truce_pauses_streak_decay_retroactively(server, badges):
    """§2.2 subtracts host truces from the decay clock long after they end -- which
    is why they are stored as intervals, not just a flag."""
    a = badges(1)
    victims = badges(3)
    server.start_game()
    server.advance(200)
    for v in victims:
        _force_target(server, a, v)
        a.kill(v)
    assert a.sync()["me"]["streak"] == 3

    # A 5 h host truce, then 5 h of play: without the truce exclusion the streak
    # would have decayed by (10 - 3) / 2 = 3.
    server.admin_post("/v1/admin/truce", {"active": True, "reason": "nacht"})
    server.advance(5 * 3600)
    server.admin_post("/v1/admin/truce", {"active": False})
    server.advance(5 * 3600)
    assert a.sync()["me"]["streak"] == 2         # only the 5 playable hours decayed


def test_void_kill_revives_the_victim_and_removes_the_score(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.kill(v)
    kill_id = server.db.one("SELECT id FROM kills")["id"]

    out = server.admin_post("/v1/admin/player/%d" % a.pid,
                            {"action": "void_kill", "kill_id": kill_id,
                             "reason": "vals gespeeld"})
    assert out["revived"] is True
    assert service.player_by_pid(server.db, a.pid)["score"] == 0
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.ACTIVE


def test_kick_and_adjust_and_protect(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)

    server.admin_post("/v1/admin/player/%d" % v.pid, {"action": "kick"})
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.KICKED
    _force_target(server, a, v)
    a.report_kill(v)
    assert a.flush()["rejected"][0]["reason"] == "victim_kicked"

    server.admin_post("/v1/admin/player/%d" % a.pid, {"action": "adjust", "delta": 5})
    assert a.sync()["me"]["score"] == 5

    server.admin_post("/v1/admin/player/%d" % a.pid,
                      {"action": "protect", "seconds": 300})
    assert a.sync()["me"]["status"] == state.PROTECTED
    # ...and `seconds: 0` clears it rather than re-arming the default 90 s.
    server.admin_post("/v1/admin/player/%d" % a.pid,
                      {"action": "protect", "seconds": 0})
    assert a.sync()["me"]["status"] == state.ACTIVE
    assert service.player_by_pid(server.db, a.pid)["protected_until"] is None


def test_admin_actions_are_attributed_to_a_host(server, badges):
    """§9.4: "Admin actions are logged with which host performed them." """
    b = badges(1)
    server.admin_login("Ward")
    server.client.post("/v1/admin/player/%d" % b.pid, json={"action": "kick"})
    rows = server.db.all("SELECT * FROM admin_log ORDER BY id")
    actions = [(r["host"], r["action"]) for r in rows]
    assert ("Ward", "kick") in actions
    assert ("Ward", "login") in actions


def test_live_tunables_reach_the_badge(server, badges):
    """§5.4: "Retuning KILL_RSSI and KILL_HOLD_MS live from the admin page is worth
    a lot... you will want to adjust on Friday afternoon without reflashing 700
    badges." """
    b = badges(1)
    out = server.admin_post("/v1/admin/tunables",
                            {"config": {"KILL_RSSI": -72, "KILL_HOLD_MS": 3000,
                                        "NOT_A_TUNABLE": 1}})
    assert out["applied"] == {"KILL_RSSI": -72, "KILL_HOLD_MS": 3000}
    assert out["rejected"] == ["NOT_A_TUNABLE"]
    cfg = b.sync()["config"]
    assert cfg["KILL_RSSI"] == -72 and cfg["KILL_HOLD_MS"] == 3000


def test_feature_kill_switches(server, badges):
    """§8.10.1: a feature can be switched off camp-wide without an app update."""
    a, leader = badges(2)
    server.admin_post("/v1/admin/tunables", {"config": {"reveal_enabled": False,
                                                        "bounty_enabled": False}})
    cfg = a.sync()["config"]
    assert cfg["reveal_enabled"] is False and cfg["bounty_enabled"] is False
    # With bounties off, nobody is on the hit list even at a high streak.
    server.db.execute("UPDATE players SET streak_at_last_kill=5, last_kill_at=? "
                      "WHERE pid=?", (server.clock.now(), leader.pid))
    server.db.commit()
    assert a.sync()["hitlist"] == []


def test_double_points_modifier(server, badges):
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    now = server.clock.now()
    server.admin_post("/v1/admin/modifier", {"type": "double_points",
                                             "from": now, "to": now + 3600})
    _force_target(server, a, v)
    a.kill(v)
    assert service.player_by_pid(server.db, a.pid)["score"] == 2


def test_audit_report_flags_farming_patterns(server, badges):
    """§9.5: rate limits FLAG, they do not block -- "refusing a real sweep would
    break the best moment in the game" (D16)."""
    a = badges(1)
    victims = badges(12)
    server.start_game()
    server.advance(200)
    for v in victims:
        _force_target(server, a, v)
        a.kill(v)
    # All 12 kills went through...
    assert service.player_by_pid(server.db, a.pid)["total_kills"] == 12
    # ...and the ones past MAX_KILLS_PER_HOUR are flagged for a human to look at.
    audit = server.admin_get("/v1/admin/audit")
    assert audit["over_rate_limit"][0]["assassin_pid"] == a.pid
    assert len(audit["flagged_kills"]) >= 1


def test_audit_spots_mutual_only_pairs(server, badges):
    """§9.5's graph shape: two players who only ever kill each other."""
    a, b = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, b)
    a.kill(b)
    server.advance(1900)
    a.sync()
    b.sync()
    server.advance(200)
    _force_target(server, b, a)
    b.kill(a)
    audit = server.admin_get("/v1/admin/audit")
    pairs = [(p["a"], p["b"]) for p in audit["mutual_only_pairs"]]
    assert (min(a.pid, b.pid), max(a.pid, b.pid)) in pairs


def test_export_never_leaks_player_keys(server, badges):
    badges(2)
    dump = server.admin_get("/v1/admin/export")
    blob = json.dumps(dump)
    assert "player_key" not in blob
    assert dump["players"]


def test_game_start_builds_a_group_aware_ring(server, badges):
    chiro = badges(6, groups=["Chiro"], name_prefix="Chiro")
    makers = badges(6, groups=["Makerspace"], name_prefix="Maker")
    out = server.admin_post("/v1/admin/game/%d/state" % server.game["id"],
                            {"state": "running"})
    assert out["ring"]["players"] == 12
    assert out["ring"]["conflicts"] == 0
    # Nobody hunts a member of their own group, and everybody has a target.
    for b in chiro + makers:
        t = b.sync()["target"]
        assert t is not None
        assert (t["pid"] in [m.pid for m in makers]) if b in chiro else \
               (t["pid"] in [c.pid for c in chiro])


def test_events_endpoint_caps_a_batch(server, badges):
    b = badges(1)
    for _ in range(210):
        b.heartbeat()
    out = b.flush()
    assert len(out["accepted"]) + len(out["rejected"]) == 210
    assert any(r["reason"] == "too_many" for r in out["rejected"])


def test_unknown_event_type_is_rejected_without_failing_the_batch(server, badges):
    b = badges(1)
    b._queue("nonsense", foo=1)
    b.heartbeat()
    out = b.flush()
    assert len(out["accepted"]) == 1
    assert out["rejected"][0]["reason"] == "unknown_type"


def test_a_hundred_badges_sync_and_the_ring_stays_consistent(server):
    """A small-scale stand-in for the Phase 6 soak: 100 badges, a ring, a round of
    kills, and no player left hunting themselves or a dead player."""
    from badge_sim import BadgeSim
    bs = []
    for i in range(100):
        b = BadgeSim(server, "b%010x" % i, "Speler %d" % i,
                     groups=["groep%d" % (i % 7)])
        b.enroll()
        bs.append(b)
    server.start_game()
    server.advance(200)

    for b in bs:
        b.sync()
    # Everyone attacks whoever the ring gave them.
    by_pid = {b.pid: b for b in bs}
    killed = set()
    for b in bs[:40]:
        t = b.sync()["target"]
        if t is None or t["pid"] in killed or b.pid in killed:
            continue
        victim = by_pid[t["pid"]]
        b.report_kill(victim)
        if not b.flush()["rejected"]:
            killed.add(victim.pid)

    assert len(killed) > 20
    rows = server.db.all("SELECT pid, target_pid, base_status FROM players")
    alive = {r["pid"] for r in rows if r["base_status"] == "active"}
    for r in rows:
        assert r["target_pid"] != r["pid"]
        if r["pid"] in alive and r["target_pid"] is not None:
            assert r["target_pid"] in alive


def test_host_can_move_the_nightly_truce_window(server, badges):
    """The schedule is pushed to badges as `game.truce_schedule`, so a host who
    moves it moves it everywhere on the next sync."""
    b = badges(1)
    server.advance(13 * 3600)                      # 23:00: inside 22:00-08:00
    assert b.sync()["game"]["truce_active"] is True
    server.admin_post("/v1/admin/truce_schedule", {"from": "01:00", "to": "06:00"})
    p = b.sync()
    assert p["game"]["truce_active"] is False
    assert p["game"]["truce_schedule"] == {"from": "01:00", "to": "06:00"}
    # Garbage is ignored rather than bricking the schedule.
    server.admin_post("/v1/admin/truce_schedule", {"from": "nonsense", "to": "99:99"})
    assert b.sync()["game"]["truce_schedule"] == {"from": "01:00", "to": "06:00"}


def test_admin_dashboard_page_renders_when_logged_in(server, badges):
    """The dashboard HTML is a blob of CSS and JS containing literal % signs, so
    it is assembled with explicit replacement rather than %-formatting. This test
    exists because getting that wrong 500s the one page a host actually opens."""
    badges(2)
    assert server.client.get("/admin").status_code == 200        # login form
    server.admin_login("Ward & Co <hq>")
    r = server.client.get("/admin")
    assert r.status_code == 200
    assert "Gotcha dashboard" in r.text
    assert "/v1/admin/game/%d/state" % server.game["id"] in r.text
    assert "onder 20%" in r.text
    # The host name is escaped, not injected raw.
    assert "Ward &amp; Co &lt;hq&gt;" in r.text
    assert "<hq>" not in r.text


# ---------------------------------------------------------------------------
# Regression tests for the Phase 0-2 code-review CRITICALs / MAJORs.
# Each of these fails on the reviewed commit (80568a9) and passes with the fix.
# ---------------------------------------------------------------------------

def test_two_kills_in_one_batch_both_land(server, badges):
    """D12: a table sweep is ONE POST (HUNT_SYNC_DEFER batches it). Killing the
    first target inherits the second as the reporter's target, so the second kill
    must also be accepted -- refusing a real sweep breaks the best moment in the
    game (§9.5, D16)."""
    a, v1, v2 = badges(3)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v1)
    _force_target(server, v1, v2)               # so a inherits v2 after killing v1
    a.report_kill(v1)
    a.report_kill(v2)
    out = a.flush()                             # both halves in a single POST
    assert len(out["accepted"]) == 2 and out["rejected"] == [], out
    assert service.player_by_pid(server.db, a.pid)["total_kills"] == 2
    assert service.player_by_pid(server.db, v1.pid)["base_status"] == state.DEAD
    assert service.player_by_pid(server.db, v2.pid)["base_status"] == state.DEAD


def test_a_heartbeat_cannot_rotate_the_live_commitment(server, badges):
    """C2 / §3.4: a victim being chased cannot heartbeat a fresh soul commitment
    to invalidate the proof the assassin already holds. The commitment is binding
    within a life; only a respawn (which opens a life with a NULL commitment) lets
    a new one be published."""
    a, v = badges(2)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.report_kill(v)                            # a captured v's current-life soul
    fresh = v.rotate_soul()                     # v tries to move the goalposts...
    v._queue("heartbeat", commitment=fresh, peers_seen=1, battery=80)
    assert v.flush()["accepted"]                # heartbeat is accepted...
    out = a.flush()                             # ...but the queued kill still lands
    assert out["accepted"] and out["rejected"] == [], out
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.DEAD


def test_a_late_killed_by_after_respawn_leaves_the_victim_killable(server, badges):
    """C3: a killed_by that sat in an offline queue across the victim's own
    respawn resolves to the FINISHED life, not a voided marker on the live life.
    Reachable with zero malice on the first afternoon at camp."""
    a, v, b = badges(3)
    server.start_game()
    server.advance(200)
    _force_target(server, a, v)
    a.report_kill(v)                            # a's soul is v's life-0 soul
    late = v.report_death(a)                    # v's own report; will be delayed
    assert a.flush()["accepted"]                # v dies (life 0 -> 1)
    server.advance(1900)
    v.sync(flush=False)                         # reconcile respawns v; queue held
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.ACTIVE
    assert v.flush()["accepted"]                # the stale killed_by finally lands
    # No voided marker was parked on v's live life...
    assert int(server.db.scalar(
        "SELECT COUNT(*) FROM kills WHERE victim_pid=? AND victim_life_id=1 "
        "AND voided=1", (v.pid,), default=0)) == 0
    # ...so a fresh hunter's legitimate kill on the current life still lands.
    server.advance(100)                         # clear the 90 s respawn protection
    _force_target(server, b, v)
    b.report_kill(v)
    assert b.flush()["accepted"], "victim is unkillable"
    assert service.player_by_pid(server.db, v.pid)["base_status"] == state.DEAD


def test_bounty_kill_does_not_orphan_the_victims_hunter(server, badges):
    """D8: a bounty kill must NOT apply ring inheritance -- the assassin was not
    the victim's hunter, so inheriting the victim's target strands the victim's
    real hunter for the rest of camp (§3.2 rule 10, §3.3). The victim is spliced
    out (their hunter inherits) and the assassin keeps its own target."""
    hunter, leader, o3, spare = badges(4)
    server.start_game()
    server.advance(200)
    # Give the leader a bounty streak without disturbing the ring's pointers.
    server.db.execute("UPDATE players SET streak_at_last_kill=3, last_kill_at=? "
                      "WHERE pid=?", (server.clock.now(), leader.pid))
    server.db.commit()
    _force_target(server, hunter, spare)        # hunter's own target (NOT leader)
    _force_target(server, o3, leader)           # o3 is the leader's hunter
    _force_target(server, leader, spare)        # the leader's target
    hunter.report_kill(leader, as_kind="bounty")
    assert hunter.flush()["accepted"]
    # The assassin kept its own target -- it did not inherit the leader's.
    assert service.player_by_pid(server.db, hunter.pid)["target_pid"] == spare.pid
    # The leader's hunter inherited the leader's target, not a corpse.
    o3t = service.player_by_pid(server.db, o3.pid)["target_pid"]
    assert o3t == spare.pid and o3t != leader.pid
    assert service.player_by_pid(server.db, leader.pid)["base_status"] == state.DEAD


def test_heartbeat_app_version_is_capped(server, badges):
    """C1: the admin dashboard interpolates app_version into innerHTML, and the
    heartbeat was the one write path that stored it with no length bound."""
    a = badges(1)
    server.start_game()
    server.advance(200)
    a._queue("heartbeat", app_version="x" * 500, peers_seen=1, battery=80)
    assert a.flush()["accepted"]
    stored = service.player_by_pid(server.db, a.pid)["app_version"]
    assert len(stored) <= 16
