"""Host tests for state_backup -- the §8.10.4 data-survival layer.

These run entirely against the in-memory FakeFS: the module is pure (no
machine/bluetooth/lvgl/mpos), so we can simulate an AppStore update wipe
(delete the in-app file) and prove the backup restores it byte-identically,
without a badge."""

import json

from state_backup import FILES, FakeFS, StateBackup, _config_is_template

APP = "/apps/com.fri3dcamp.fri3dfriends"
BAK = "/storage/fri3dfriends_state"

TEMPLATE_CFG = json.dumps(
    {"groups": [], "name": "", "rssi_floor": -120,
     "contact": {"Email": "", "Phone": "", "Website": "", "Discord": ""}}).encode()


def _backup(fs=None):
    return StateBackup(APP, BAK, fs or FakeFS())


def _seed(fs, **files):
    for name, data in files.items():
        fs.write(APP + "/" + name, data)


# Realistic payloads so the round-trip also proves JSON survives intact.
CONFIG = json.dumps(
    {"name": "Otter 42", "groups": [3], "sound": True,
     "rssi_floor": -75, "board": "2026"}).encode()
CONTACTS = json.dumps(
    [{"name": "Fox 7", "fields": {"irc": "fox7"}, "ts": 1786694400},
     {"name": "Lynx 3", "fields": {}, "ts": 1786695000}]).encode()
GOTCHA = json.dumps(
    {"enrolled": True, "pid": 1004, "player_key": "deadbeef", "soul": "aabb",
     "queue": [{"uuid": "x1", "kind": "kill"}]}).encode()


# -- the headline: an update wipes the app dir, the backup brings it back ----

def test_survive_full_wipe():
    fs = FakeFS()
    _seed(fs, **{"config.json": CONFIG, "contacts.json": CONTACTS,
                 "gotcha.json": GOTCHA})
    b = _backup(fs)
    assert sorted(b.mirror_all()) == sorted(FILES)

    # An AppStore update: install_mpk deletes the whole app folder.
    for name in FILES:
        fs.remove(APP + "/" + name)

    assert sorted(b.needs_restore()) == sorted(FILES)
    restored = b.restore_missing()
    assert sorted(restored) == sorted(FILES)

    # Byte-identical recovery -- nothing mangled in the round trip.
    assert fs.read(APP + "/contacts.json") == CONTACTS
    assert fs.read(APP + "/config.json") == CONFIG
    assert fs.read(APP + "/gotcha.json") == GOTCHA
    # contacts.json specifically: the irreplaceable one. Prove the JSON is valid
    # and the collected contacts are all still there.
    rec = json.loads(fs.read(APP + "/contacts.json").decode())
    assert [c["name"] for c in rec] == ["Fox 7", "Lynx 3"]


def test_only_missing_files_are_restored():
    # config survived the update (maybe rewritten first-run), contacts + gotcha
    # did not. Only the two missing files should come back; the present one must
    # NOT be clobbered by a stale backup.
    fs = FakeFS()
    fresh_config = json.dumps({"name": "Otter 42", "groups": [9]}).encode()
    _seed(fs, **{"config.json": CONFIG, "contacts.json": CONTACTS,
                 "gotcha.json": GOTCHA})
    b = _backup(fs)
    b.mirror_all()

    fs.remove(APP + "/contacts.json")
    fs.remove(APP + "/gotcha.json")
    fs.write(APP + "/config.json", fresh_config)      # newer than the backup

    restored = b.restore_missing()
    assert sorted(restored) == ["contacts.json", "gotcha.json"]
    # The newer in-app config wins; the backup's stale copy did not overwrite it.
    assert fs.read(APP + "/config.json") == fresh_config
    assert fs.read(APP + "/contacts.json") == CONTACTS


def test_restore_is_a_noop_on_a_normal_boot():
    # Nothing wiped -> restore_missing touches nothing and returns [].
    fs = FakeFS()
    _seed(fs, **{"config.json": CONFIG, "contacts.json": CONTACTS})
    b = _backup(fs)
    b.mirror_all()
    assert b.needs_restore() == []
    assert b.restore_missing() == []
    assert b.mirror_all() == ["config.json", "contacts.json"]


def test_first_run_no_backup_no_crash():
    # A brand-new badge: no app files yet, no backup. restore must be a quiet
    # no-op, never an exception -- the app launches into first-run setup.
    fs = FakeFS()
    b = _backup(fs)
    assert b.needs_restore() == []
    assert b.restore_missing() == []


def test_missing_backup_for_one_file_is_skipped():
    # config wiped, but it was never backed up (e.g. the very first save failed
    # before any mirror). That file is simply unrecoverable; the others are fine.
    fs = FakeFS()
    _seed(fs, **{"contacts.json": CONTACTS, "gotcha.json": GOTCHA})
    b = _backup(fs)
    b.mirror_all()
    fs.remove(APP + "/contacts.json")
    fs.remove(APP + "/gotcha.json")
    fs.remove(APP + "/config.json")          # never had a backup
    assert b.needs_restore() == ["contacts.json", "gotcha.json"]
    assert sorted(b.restore_missing()) == ["contacts.json", "gotcha.json"]


def test_mirror_noop_when_app_file_absent():
    fs = FakeFS()
    b = _backup(fs)
    assert b.mirror("config.json") is False
    assert b.mirror_all() == []
    assert b.needs_restore() == []


def test_never_raises_on_fs_errors():
    # A hostile FS adapter that throws on everything: every method must swallow
    # and return a safe empty/false, never propagate.
    class Boom(object):
        def exists(self, p): raise OSError("disk gone")
        def read(self, p): raise OSError("disk gone")
        def write(self, p, d): raise OSError("disk gone")
        def remove(self, p): raise OSError("disk gone")
        def listdir(self, p): raise OSError("disk gone")
    b = StateBackup(APP, BAK, Boom())
    assert b.mirror("config.json") is False
    assert b.mirror_all() == []
    assert b.needs_restore() == []
    assert b.restore_missing() == []


def test_restore_is_idempotent():
    # Running restore_missing twice (e.g. after a soft reboot within the same
    # session) must not double-restore or error: the second call finds nothing.
    fs = FakeFS()
    _seed(fs, **{"contacts.json": CONTACTS})
    b = _backup(fs)
    b.mirror_all()
    fs.remove(APP + "/contacts.json")
    assert b.restore_missing() == ["contacts.json"]
    assert b.restore_missing() == []
    assert fs.read(APP + "/contacts.json") == CONTACTS


def test_partial_wipe_then_remirror_keeps_backup_fresh():
    # After restoring, a new save re-mirrors so the backup tracks the latest
    # data -- the invariant that makes any-moment update safe.
    fs = FakeFS()
    _seed(fs, **{"config.json": CONFIG})
    b = _backup(fs)
    b.mirror_all()
    fs.remove(APP + "/config.json")
    b.restore_missing()
    new_config = json.dumps({"name": "Badger 1", "groups": [5]}).encode()
    fs.write(APP + "/config.json", new_config)
    assert b.mirror("config.json") is True
    assert fs.read(BAK + "/config.json") == new_config


def test_files_set_excludes_duel_log():
    # duel_log.txt is an audit log, not user data; it must never be in the
    # restore set (keeps the set minimal and avoids thrashing a chatty file).
    assert "duel_log.txt" not in FILES
    assert set(FILES) == {"config.json", "contacts.json", "gotcha.json"}


def test_paths_are_namespaced_per_app():
    # Each app has its OWN backup dir (the default is /storage/fri3dfriends_state,
    # named for this app), so two apps -- or a re-install under a different
    # fullname -- never share one backup namespace. Prove the dirs are fully
    # independent: the other app's backup cannot leak into this app's restore.
    fs = FakeFS()
    other_app = "/apps/com.example.other"
    other_bak = "/storage/other_state"
    fs.write(other_app + "/config.json", b"OTHER")
    StateBackup(other_app, other_bak, fs).mirror_all()

    main = StateBackup(APP, BAK, fs)        # this app's own namespace
    assert main.needs_restore() == []        # nothing in THIS backup dir
    assert fs.read(BAK + "/config.json") is None
    assert fs.read(APP + "/config.json") is None
    # The other app's data lives only in its own backup dir.
    assert fs.read(other_bak + "/config.json") == b"OTHER"


# -- template-config reclamation (install_mpk extracts a bundled config.json) --

def test_config_is_template_signature():
    # The bare default the .mpk ships: no groups, no name.
    assert _config_is_template(TEMPLATE_CFG) is True
    assert _config_is_template(json.dumps({"groups": [], "name": ""}).encode()) is True
    # A player's config is never the template: groups set, or a name set.
    assert _config_is_template(json.dumps({"groups": [3]}).encode()) is False
    assert _config_is_template(json.dumps({"name": "Otter 42"}).encode()) is False
    # Unreadable / odd -> not a template (we never act on a guess).
    assert _config_is_template(None) is False
    assert _config_is_template(b"not json") is False
    assert _config_is_template(b"[]") is False


def test_template_config_is_reclaimed_over_bundled_default():
    # The exact camp failure mode: install_mpk extracts the .mpk's bundled
    # template config.json over the player's real one. config.json is therefore
    # *present* (so restore_missing skips it) but it is the template. The backup
    # holds the player's real config -> restore_config_over_template reclaims it.
    fs = FakeFS()
    fs.write(APP + "/config.json", TEMPLATE_CFG)        # what the update left
    fs.write(BAK + "/config.json", CONFIG)              # the player's real config
    b = _backup(fs)
    assert b.restore_missing() == []                    # config present -> skipped
    assert b.restore_config_over_template() is True
    assert fs.read(APP + "/config.json") == CONFIG      # real config recovered
    assert _config_is_template(fs.read(APP + "/config.json")) is False


def test_real_config_is_not_overwritten_by_template_guard():
    # Normal boot: the in-app config is the player's real one (not the template).
    # The guard must NOT touch it, even though a (stale) backup exists.
    fs = FakeFS()
    fresh = json.dumps({"name": "Badger 1", "groups": [7]}).encode()
    fs.write(APP + "/config.json", fresh)
    fs.write(BAK + "/config.json", CONFIG)              # older backup
    b = _backup(fs)
    assert b.restore_config_over_template() is False
    assert fs.read(APP + "/config.json") == fresh       # untouched


def test_template_guard_noop_without_richer_backup():
    # In-app is the template and the backup is ALSO a template (or absent):
    # nothing to reclaim, no crash.
    fs = FakeFS()
    fs.write(APP + "/config.json", TEMPLATE_CFG)
    fs.write(BAK + "/config.json", TEMPLATE_CFG)
    b = _backup(fs)
    assert b.restore_config_over_template() is False
    # backup absent entirely
    fs2 = FakeFS()
    fs2.write(APP + "/config.json", TEMPLATE_CFG)
    assert _backup(fs2).restore_config_over_template() is False


def test_restore_on_boot_covers_both_wipe_shapes():
    # A full update: gotcha.json vanished (restore_missing) AND config.json was
    # extracted as the template (restore_config_over_template). restore_on_boot
    # must report both recovered.
    fs = FakeFS()
    fs.write(APP + "/config.json", TEMPLATE_CFG)
    fs.write(BAK + "/config.json", CONFIG)
    fs.write(BAK + "/gotcha.json", GOTCHA)              # gotcha wiped from app
    from state_backup import StateBackup
    b = StateBackup(APP, BAK, fs)
    out = list(b.restore_missing())
    assert b.restore_config_over_template() is True
    assert "gotcha.json" in out
    assert fs.read(APP + "/gotcha.json") == GOTCHA
    assert fs.read(APP + "/config.json") == CONFIG
