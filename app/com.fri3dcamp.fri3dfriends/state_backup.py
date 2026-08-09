# state_backup.py -- survive an AppStore update that wipes the app dir (§8.10.4).
#
# mpos AppManager.install_mpk deletes + re-extracts the app folder before
# installing, so an AppStore update DESTROYS every persistent file the app keeps
# next to its code (verified 2026-07-28: a folder holding MANIFEST.JSON +
# config.json + contacts.json came back with only the .mpk's files). The damage:
#
#   /apps/com.fri3dcamp.fri3dfriends/config.json     name/groups/sound/quiet hours
#   /apps/com.fri3dcamp.fri3dfriends/contacts.json   every contact ever swapped
#   /apps/com.fri3dcamp.fri3dfriends/gotcha.json     pid/key/soul/score/event queue
#
# contacts.json is the worst: there is no server copy and there never will be --
# the contact swap is deliberately offline-only -- so an update silently erases
# irreplaceable user data. This module mirrors the three files to a BACKUP
# directory the installer never touches, and restores them on boot when the
# in-app copy has vanished (the signature of an update wipe).
#
# Restoring gotcha.json also removes the *cause* of the re-enroll race (§8.10.4
# step 4): if the badge's enrollment survives the update it never re-enrolls, so
# life_id never spuriously advances, so a hunter's queued kill is never voided as
# `life_over`. The grace window is a fallback for the case where the backup
# itself failed -- not the common path.
#
# PURE module: no machine/bluetooth/lvgl/mpos imports, so the host tests drive it
# against an in-memory fake filesystem. The Activity wires the real helpers via
# make_real_fs(); every operation is best-effort and never raises -- a backup
# failure must degrade to "no backup", never "no nametag" (plan §8.6).
import os
import json

# The three files worth surviving an update. duel_log.txt is deliberately NOT
# here: it is an append-only debug/audit log, not user data, and excluding it
# keeps the restore set minimal.
FILES = ("config.json", "contacts.json", "gotcha.json")


def _config_is_template(data):
    """True if `data` (bytes/str) is the bare default config an .mpk ships: no
    groups and no name. A player's real config has at least one of those, so this
    is the signal that distinguishes an extracted template from real user data
    (the auto-nickname is derived at runtime and never written, so a configured
    badge's saved name is genuinely non-empty when set, and groups are set on a
    configured badge). Returns False on anything unreadable/odd -- we only act on
    a clear template, never guess."""
    if not data:
        return False
    try:
        if isinstance(data, (bytes, bytearray)):
            data = str(data, "utf-8")
        o = json.loads(data)
    except Exception:
        return False
    if not isinstance(o, dict):
        return False
    grp = o.get("groups")
    name = o.get("name")
    return (not grp) and (not str(name or "").strip())


class FakeFS(object):
    """In-memory filesystem for the host tests (and a clear spec of the adapter
    the real one implements). Paths are arbitrary strings; only the names in
    FILES ever move between app_dir and backup_dir, so we key the store by full
    path and treat any path as a flat leaf."""
    def __init__(self):
        self._files = {}      # path -> bytes

    def exists(self, path):
        return path in self._files

    def read(self, path):
        return self._files.get(path)      # None if missing, never raises

    def write(self, path, data):
        # The real adapter writes a temp + renames; for the logic under test a
        # plain overwrite is equivalent (atomicity is a power-loss concern, not
        # a logic one).
        self._files[path] = bytes(data)

    def remove(self, path):
        self._files.pop(path, None)

    def listdir(self, path):
        prefix = path.rstrip("/") + "/"
        return [p[len(prefix):] for p in self._files if p.startswith(prefix)]


class StateBackup(object):
    """Mirror the protected files app_dir/<name> <-> backup_dir/<name> and
    restore the in-app copies when an update has wiped them.

    All public methods swallow filesystem errors and return best-effort results,
    so a broken/missing backup never breaks app launch."""

    def __init__(self, app_dir, backup_dir, fs):
        self.app_dir = app_dir.rstrip("/")
        self.backup_dir = backup_dir.rstrip("/")
        self.fs = fs

    # -- paths --------------------------------------------------------------
    def _app(self, name):
        return self.app_dir + "/" + name

    def _bak(self, name):
        return self.backup_dir + "/" + name

    # -- mirror (app -> backup) --------------------------------------------
    def mirror(self, name):
        """Copy app_dir/name to backup_dir/name if it exists. Returns True if a
        copy was made, False otherwise. Never raises."""
        try:
            data = self.fs.read(self._app(name))
            if data is None:
                return False
            self.fs.write(self._bak(name), data)
            return True
        except Exception:
            return False

    def mirror_all(self):
        """Mirror every file in FILES. Returns the list of names actually copied."""
        out = []
        for name in FILES:
            if self.mirror(name):
                out.append(name)
        return out

    # -- restore (backup -> app, only what the wipe took) -------------------
    def needs_restore(self):
        """Names missing in the app dir but present in the backup -- i.e. the
        files an update wiped that we can still recover."""
        out = []
        for name in FILES:
            try:
                if not self.fs.exists(self._app(name)) and \
                        self.fs.read(self._bak(name)) is not None:
                    out.append(name)
            except Exception:
                pass
        return out

    def restore_missing(self):
        """Copy backup_dir/name -> app_dir/name for every name missing in the
        app dir but present in the backup. Returns the list restored. A file
        already present in the app dir is NEVER overwritten -- a newer in-app
        copy must win over a stale backup. Never raises."""
        restored = []
        for name in self.needs_restore():
            try:
                data = self.fs.read(self._bak(name))
                if data is None:
                    continue
                self.fs.write(self._app(name), data)
                restored.append(name)
            except Exception:
                pass
        return restored

    def restore_config_over_template(self):
        """Reclaim config.json when an update extracted the bundled template over
        the player's real config. install_mpk ships a bare `config.json` (no
        groups, no name); restore_missing skips it because it is *present*, so
        without this the player silently lands back on first-run setup. If the
        in-app config is that template but the backup holds a configured badge,
        overwrite the template with the backup. Returns True if it acted. The
        official build excludes config.json from the .mpk, so this is a
        belt-and-suspenders guard; it is safe on a normal boot because a real
        in-app config is never the template. Never raises."""
        try:
            app_data = self.fs.read(self._app("config.json"))
            if app_data is None or not _config_is_template(app_data):
                return False
            bak_data = self.fs.read(self._bak("config.json"))
            if bak_data is None or _config_is_template(bak_data):
                return False
            self.fs.write(self._app("config.json"), bak_data)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Real on-device adapter + convenience entry points
# ---------------------------------------------------------------------------
#
# The backup dir is deliberately OUTSIDE the app install tree: install_mpk only
# touches /apps/<fullname>/, so a dir under /prefs/ (the mpos persistent
# SharedPreferences store, where WiFi creds already live across reboots) survives
# an AppStore update. /storage/ does NOT exist on this MicroPython build, and
# os.makedirs does NOT exist either (only os.mkdir), so we mkdir the single
# backup subdir ourselves. (Verified on the bench 2026-08-09: /prefs is writable
# and persists; the install_mpk survival check is §14.2 A5.)

DEFAULT_BACKUP_DIR = "/prefs/fri3dfriends_state"


class _RealFS(object):
    """FS adapter over os/open. Every method is defensive: a missing dir, a
    read-only FS or a corrupt file degrades to None/False, never an exception."""

    def __init__(self, backup_dir):
        self._backup_dir = backup_dir
        self._dir_ok = False

    def _ensure_backup_dir(self):
        if self._dir_ok:
            return
        # MicroPython has os.mkdir but NOT os.makedirs, so create just the one
        # backup subdir (its parent /prefs always exists). Ignore "already
        # exists" -- the next write confirms writability either way.
        try:
            os.mkdir(self._backup_dir)
        except OSError:
            pass
        self._dir_ok = True

    def exists(self, path):
        try:
            return os.path.exists(path) and not path.endswith(".tmp")
        except Exception:
            return False

    def read(self, path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            return None

    def write(self, path, data):
        # Atomic: temp file + rename, the same pattern contacts/gotcha already
        # use, so a power-off mid-backup can't leave a half-written copy that a
        # later restore would resurrect as corrupt user data.
        self._ensure_backup_dir()
        tmp = path + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
            try:
                os.sync()
            except Exception:
                pass
            os.rename(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass

    def remove(self, path):
        try:
            os.remove(path)
        except Exception:
            pass

    def listdir(self, path):
        try:
            return os.listdir(path)
        except Exception:
            return []


def make_real_fs(app_dir, backup_dir=DEFAULT_BACKUP_DIR):
    """Build a StateBackup bound to the real on-device filesystem. The backup
    dir defaults to DEFAULT_BACKUP_DIR but is overridable for a bench test."""
    return StateBackup(app_dir, backup_dir, _RealFS(backup_dir))


def restore_on_boot(app_dir, backup_dir=DEFAULT_BACKUP_DIR):
    """The onCreate hook: restore anything an update wiped, before the app loads
    its config/contacts/game state. Covers two wipe shapes -- files missing
    outright (restore_missing) and config.json extracted as the bundled template
    (restore_config_over_template). Returns the list of names restored (empty on
    a normal boot). Best-effort; never raises."""
    try:
        b = make_real_fs(app_dir, backup_dir)
        out = list(b.restore_missing())
        if b.restore_config_over_template() and "config.json" not in out:
            out.append("config.json")
        return out
    except Exception:
        return []
