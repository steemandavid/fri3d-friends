"""Off-device unit tests for beacon_service.py pure helpers.

Covers the host-testable half (no BLE / mpos needed):
  - load_beacon_config: unconfigured rules (no groups, bad JSON, missing file),
    the v0.9.0 auto-nickname fallback for a blank name, and the (own_ids, name)
    result matching what the app itself would advertise.
  - app_in_stack: screen-stack membership by appFullName.
"""
import json

import beacon_service as bs
from ble_proximity import hash_groups
from identity import auto_nickname

UID = b"\x34\x85\x18\xac\xfa\xb8"

FULLNAME = "com.fri3dcamp.fri3dfriends"


def _write_cfg(tmp_path, cfg):
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    return str(tmp_path)


def test_load_beacon_config_configured(tmp_path):
    d = _write_cfg(tmp_path, {"name": "Alex", "groups": ["Makerspace Baasrode"]})
    own_ids, name = bs.load_beacon_config(d)
    assert name == "Alex"
    assert own_ids == hash_groups(["Makerspace Baasrode"])[0]


def test_load_beacon_config_unconfigured_variants(tmp_path):
    # Since v0.9.0 the rule is GROUPS ONLY: no valid group -> None (stay silent).
    # Groups are never auto-assigned, so an un-set-up badge is off the air.
    for cfg in ({"name": "Alex", "groups": []},
                {"name": "Alex", "groups": "not-a-list"},
                {"name": "Alex"},
                {"name": "Alex", "groups": ["", "   "]}):
        assert bs.load_beacon_config(_write_cfg(tmp_path, cfg), uid=UID) is None


def test_load_beacon_config_blank_name_falls_back_to_nickname(tmp_path):
    # A badge whose owner never set a name still beacons, under the same
    # auto-nickname the app shows on screen -- previously it stayed silent.
    for cfg in ({"name": "", "groups": ["G"]},
                {"name": "   ", "groups": ["G"]},
                {"groups": ["G"]},
                {"name": 42, "groups": ["G"]}):
        own_ids, name = bs.load_beacon_config(_write_cfg(tmp_path, cfg), uid=UID)
        assert name == auto_nickname(UID)
        assert own_ids == hash_groups(["G"])[0]


def test_load_beacon_config_real_name_wins(tmp_path):
    d = _write_cfg(tmp_path, {"name": "  Alex  ", "groups": ["G"]})
    assert bs.load_beacon_config(d, uid=UID)[1] == "Alex"


def test_load_beacon_config_missing_or_corrupt_file(tmp_path):
    assert bs.load_beacon_config(str(tmp_path)) is None      # no config.json
    (tmp_path / "config.json").write_text("{not json")
    assert bs.load_beacon_config(str(tmp_path)) is None


# ---- Phase 4: load_service_config (the background responder's full config) ----

def test_load_service_config_configured(tmp_path):
    d = _write_cfg(tmp_path, {"name": "Sam", "groups": ["G"],
                              "rssi_floor": -90, "sound": False,
                              "gotcha": {"api": "https://x"}, "quiet": {"from": "22:00", "to": "08:00"}})
    cfg = bs.load_service_config(d, uid=UID)
    assert cfg is not None
    assert cfg["name"] == "Sam"
    assert cfg["groups"] == ["G"]
    assert cfg["rssi_floor"] == -90
    assert cfg["sound"] is False
    assert cfg["gotcha"] == {"api": "https://x"}
    assert cfg["quiet"] == {"from": "22:00", "to": "08:00"}


def test_load_service_config_defaults(tmp_path):
    # Minimal valid config -> defaults for the optional fields, nickname fallback.
    d = _write_cfg(tmp_path, {"groups": ["G"]})
    cfg = bs.load_service_config(d, uid=UID)
    assert cfg is not None
    assert cfg["name"] == auto_nickname(UID)
    assert cfg["sound"] is True
    assert cfg["gotcha"] == {}
    assert cfg["quiet"] is None
    # rssi_floor defaults to the proximity default (disabled) when absent/invalid.
    from ble_proximity import RSSI_FLOOR_DEFAULT
    assert cfg["rssi_floor"] == RSSI_FLOOR_DEFAULT


def test_load_service_config_silent_when_unconfigured(tmp_path):
    # No valid group -> None: a badge not on the air is not a reachable target.
    for c in ({"name": "Sam"}, {"name": "Sam", "groups": []},
              {"name": "Sam", "groups": "nope"}):
        assert bs.load_service_config(_write_cfg(tmp_path, c), uid=UID) is None


class _FakeActivity:
    def __init__(self, fullname):
        self.appFullName = fullname


def test_app_in_stack():
    us = (_FakeActivity(FULLNAME), "scr", None, None)
    launcher = (_FakeActivity("com.micropythonos.launcher"), "scr", None, None)
    assert bs.app_in_stack([launcher, us], FULLNAME)          # top
    assert bs.app_in_stack([us, launcher], FULLNAME)          # buried
    assert not bs.app_in_stack([launcher], FULLNAME)
    assert not bs.app_in_stack([], FULLNAME)
    # Entries with a None/odd activity don't blow up the check.
    assert not bs.app_in_stack([(None, "scr", None, None), ("weird",)], FULLNAME)
