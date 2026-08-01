# gotcha_reveal.py -- Phase 3a Reveal probe (THROWAWAY, FORCED SILENT).
#
# Proves the real shipping reveal connect-path on two badges. It wires the shipping
# GotchaController + GotchaService + ContactExchange exactly as the app does
# (connectable beacon + Gotcha GATT service + the BLEProximity IRQ forwarder), so
# the target's responder is the real apply_reveal(). The hunter side fires a reveal
# directly at an in-range peer via the real ContactExchange.gatt_write -- this is
# the only deviation from the shipping request_reveal() (which uses the server-
# assigned target); doing it peer-direct avoids needing admin/ring manipulation.
#
# Both badges enroll under the SAME group, so BLEProximity admits them as friends
# and each sees the other's pid + address (no admit_pids game needed).
#
# SILENT (people are sleeping): NO buzzer is ever driven. The only visible effect
# is the gold LED flash on the target; the machine-readable pass signal is the
# status file. The camp truce (active at night) is overridden to a daytime window
# so validate_reveal does not drop the reveal -- this is a probe-only override.
#
# Launch from the launcher REPL (NOT while the shipping app runs -- advertising
# wedges USB-CDC):
#   import sys; sys.path.insert(0, '/apps/com.fri3dcamp.fri3dfriends')
#   from mpos import TaskManager
#   import gotcha_reveal as g
#   TaskManager.create_task(g.run())
# Poll status from the host (cp works even when exec is wedged):
#   mpremote connect <by-id> cp :/gotcha_reveal_status.txt -

import asyncio
import os
import time

import gotcha
import ble_proximity as bp
import gotcha_app
import gotcha_gatt
import contact_exchange as cx_mod

BASE = "http://192.168.1.57:8080"
DEV_GROUP = "gotcha-reveal"
STATE_PATH = "/gotcha_reveal.json"
STATUS_PATH = "/gotcha_reveal_status.txt"
ERR_PATH = "/gotcha_reveal_err.txt"
SYNC_EVERY_MS = 8000
REVEAL_MIN_GAP_MS = 4000
SCAN_ENABLED = False  # scan OFF test (WiFi also off after phase)

_ST = {"last_attempt": 0, "spotted_was": False, "last_line": "", "last_write": 0,
       "last_result": ""}


def _badge_key():
    try:
        import bluetooth
        from bluetooth import BLE
        b = BLE(); b.active(True)
        return "".join("%02x" % x for x in b.config("mac")[1])
    except Exception:
        return "".join("%02x" % x for x in os.urandom(6))


def _dev_name():
    try:
        import machine
        return "R" + ("".join("%02x" % x for x in machine.unique_id()))[-4:]
    except Exception:
        return "R????"


def _wifi_up():
    try:
        from mpos import WifiService
        return bool(WifiService.is_connected())
    except Exception:
        return False


def _write_status(msg):
    now = time.ticks_ms()
    if msg == _ST["last_line"] and time.ticks_diff(now, _ST["last_write"]) < 1500:
        return
    _ST["last_write"] = now
    _ST["last_line"] = msg
    try:
        f = open(STATUS_PATH, "w"); f.write(str(msg) + "\n"); f.flush(); f.close()
    except Exception:
        pass


def _flash_gold():
    # Silent visible signal: every LED gold (held; probe never clears it). No buzzer.
    try:
        import lights
        for i in range(5):
            lights.set_led(i, 255, 200, 0)
        lights.write()
    except Exception:
        pass


def _best_peer(ble, cfg):
    """Strongest in-range game-peer (a friend in our group advertising a pid), or
    None. rssi_prox must clear REVEAL_RSSI. Returns (pid, rssi_prox)."""
    reveal_rssi = cfg.get("REVEAL_RSSI")
    best = None
    try:
        for e in ble._seen.values():
            pid = e.get("pid")
            prox = e.get("rssi_prox")
            if pid is None or prox is None:
                continue
            if prox >= reveal_rssi and (best is None or prox > best[1]):
                best = (pid, prox)
    except Exception:
        pass
    return best


async def _do_direct_reveal(ble, exch, gc, peer_pid):
    """Fire a REVEAL at peer_pid via the real connect path (clones the shipping
    _do_reveal, but targets a chosen peer). suspend/resume BLEProximity around it."""
    addr = ble.addr_for_pid(peer_pid)
    if addr is None:
        return "no-addr"
    my_pid = gc.state.d.get("pid")
    group = gc.groups[0] if gc.groups else 0
    try:
        nonce = gotcha.new_nonce()
    except Exception:
        nonce = "n0"
    payload = gotcha.build_reveal_payload(group, my_pid, peer_pid, nonce).encode("utf-8")
    try:
        ble.suspend()
    except Exception:
        pass
    try:
        ok = await exch.gatt_write(addr[0], addr[1], gotcha_gatt.REVEAL_CHR,
                                   payload, timeout_ms=4000)
        return "ok" if ok else "no-ack"
    except Exception as e:
        return "exc %r" % (e,)
    finally:
        try:
            ble.resume()
        except Exception:
            pass


async def _run():
    _write_status("starting")
    if not _wifi_up():
        _write_status("NO WIFI -- join fri3d-badge in Settings")
        return
    name = _dev_name()
    _write_status(name + " wifi ok")

    ble = bp.BLEProximity()
    exch = cx_mod.ContactExchange()
    gc = gotcha_app.GotchaController(ble, STATE_PATH, exchange=exch)
    svc = gotcha_gatt.GotchaService(on_reveal=gc.apply_reveal)
    exch.attach_gotcha(svc)
    gc.set_service(svc)
    gc.set_exchange(exch)
    gc.configure({"api": BASE, "enroll": BASE}, name, [DEV_GROUP])
    gc.start()

    if not gc.ever_enrolled():
        _write_status(name + " enrolling...")
        gc.request_enroll()
        for _ in range(40):
            await asyncio.sleep_ms(500)
            if gc.ever_enrolled():
                break
    if not gc.ever_enrolled():
        _write_status(name + " ENROLL FAILED " + BASE)
        return
    _write_status(name + " enrolled pid=" + str(gc.state.d.get("pid")))

    # Activate the radio + register the Gotcha GATT service BEFORE the connectable
    # advert starts (the contact-exchange order: services first, then advertise).
    # Registering gatts AFTER advertising appeared to break the advert's
    # connectability -- this order is the fix under test.
    import bluetooth
    # Force a controller reset before registering: gatts_register_services is
    # once-per-power-on, so if the shipping app (or anything) registered GATT first
    # this boot, our registration would EINVAL and the Gotcha service would be
    # missing. An active(False)/active(True) cycle clears the table + the gate, so
    # we register cleanly as if first. (Re-registration after an active cycle is
    # permitted -- DESIGN.md §10.)
    b = bluetooth.BLE()
    try: b.active(False)
    except Exception: pass
    try: b.active(True)
    except Exception: pass
    exch._svc_ready = False
    exch._mtu_set = False
    exch._ble = None
    exch.ensure_radio(bluetooth)           # BLE up + register exchange/setup/gotcha services
    ble.set_connectable(True)              # connectable from the start (probe override)
    ble.begin([DEV_GROUP], name, game=gc._make_game_block())

    last_forced_sync = 0
    _write_status("%s pid=%d svch=%d svc_ready=%s cable=%d -- bringing up BLE" % (
        name, gc.state.d.get("pid"), len(svc._h), getattr(exch, "_svc_ready", "?"),
        int(ble._connectable)))
    # WiFi transfers blot out BLE on this build (§8.7/Phase 0): a connectable advert
    # cannot accept a connection while a sync is in flight. So sync ONCE up front,
    # then stop gc.tick's WiFi so BLE stays free for incoming connections.
    wifi_until = time.ticks_add(time.ticks_ms(), 15000)
    while True:
        now = time.ticks_ms()
        if SCAN_ENABLED:
            ble.tick(now, 300)         # drive the proximity scanner (the app does this in its loop)
        in_wifi_phase = time.ticks_diff(wifi_until, now) > 0
        if in_wifi_phase:
            if time.ticks_diff(now, last_forced_sync) >= 2000:
                last_forced_sync = now
                gc._next_sync_ms = 0      # force a quick sync during the WiFi phase
            try:
                gc.tick(now, True, False)  # sound_on=False -> never sounds
            except Exception as e:
                _write_status(name + " tick err %r" % (e,))
        else:
            # WiFi quiet: just drain inbound reveals + refresh the view (no network).
            try:
                gc._drain_reveals()
                gc._refresh_view()
            except Exception:
                pass
        # Probe-only: defeat the night camp truce so reveals pass (people are
        # sleeping == truce window). The shipping app would (correctly) suppress.
        gc.cfg.d["truce_from"] = "12:00"
        gc.cfg.d["truce_to"] = "13:00"

        # Target side: drain any inbound REVEAL (fired by gc.tick) + gold flash.
        spotted = gc.is_spotted(now)
        if spotted and not _ST["spotted_was"]:
            _flash_gold()
        _ST["spotted_was"] = spotted

        # Hunter side: reveal the strongest in-range peer.
        peer = _best_peer(ble, gc.cfg)
        if (peer is not None and not gc.revealing()
                and time.ticks_diff(now, _ST["last_attempt"]) >= REVEAL_MIN_GAP_MS):
            _ST["last_attempt"] = now
            res = await _do_direct_reveal(ble, exch, gc, peer[0])
            _ST["last_result"] = "reveal pid=%s -> %s prox=%.0f" % (peer[0], res, peer[1])

        npeers = len(ble._seen)
        _write_status("%s pid=%s live=%s conn=%s cable=%d peers=%d SPOTTED=%s(by %s) | %s | %s" % (
            name, gc.state.d.get("pid"), gc.game_live, gc.online, int(ble._connectable),
            npeers, int(spotted), gc._revealed_by or "-", _ST["last_result"],
            ("best=%s/%.0f" % (peer[0], peer[1])) if peer else "none-in-range"))
        await asyncio.sleep_ms(300)


async def run():
    """TaskManager.create_task(gotcha_reveal.run()) -- primary launch."""
    try:
        await _run()
    except Exception as e:
        try:
            f = open(ERR_PATH, "w"); f.write("%r\n" % (e,)); f.flush(); f.close()
        except Exception:
            pass
        _write_status("ERROR %r" % (e,))
