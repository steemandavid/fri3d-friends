#!/usr/bin/env python3
"""host_duel_hunter.py -- host-side DUEL hunter (Phase 3b), drives an ATTACK from
the host's BLE adapter against a badge running the app as the victim, so the whole
victim path can be tested WITHOUT a second badge and WITHOUT anyone pressing A.

Steps:
  1. Scan for the victim's HSNT v2 advert; resolve its address by pid.
  2. Connect; list the GATT services -> proves GOTCHA_SVC + ATTACK/DUEL/SPOILS
     actually registered on the victim (the Phase-3b "victim serves no GATT" bug).
  3. Subscribe DUEL notify, write ATTACK, wait for ENGAGED then KILLED/DODGED.
  4. On KILLED, read SPOILS and verify the disclosed soul locally (needs the
     victim's current commitment, passed in or read from the server).

Usage:
  python3 probes/host_duel_hunter.py <victim_pid> [--hold] [--commit <hex>]
    --hold : stay connected through the whole KILL_HOLD (else disconnect right
             after ENGAGED to exercise the link-drop DODGE path).
"""
import asyncio
import sys

sys.path.insert(0, "app/com.fri3dcamp.fri3dfriends")
import gotcha  # noqa: E402

HSNT_COMPANY = 0xffff
GOTCHA_SVC = "6e400030-b5a3-f393-e0a9-e50e24dcca9e"
ATTACK_CHR = "6e400031-b5a3-f393-e0a9-e50e24dcca9e"
DUEL_CHR = "6e400032-b5a3-f393-e0a9-e50e24dcca9e"
SPOILS_CHR = "6e400033-b5a3-f393-e0a9-e50e24dcca9e"


def parse_pid(mfg):
    try:
        if not mfg.startswith(b"HSNT"):
            return None
        i = 4
        i += 1                      # ver
        blocks = mfg[i]; i += 1
        gcount = mfg[i]; i += 1
        i += 2 * gcount
        namelen = mfg[i]; i += 1
        i += namelen
        if (blocks & 1) and i + 5 <= len(mfg):
            return int.from_bytes(mfg[i:i + 3], "little")
    except Exception:
        return None
    return None


async def find_badge(timeout=8.0):
    from bleak import BleakScanner
    found = {}

    def cb(device, ad):
        try:
            data = ad.manufacturer_data.get(HSNT_COMPANY)
        except Exception:
            data = None
        if data and bytes(data).startswith(b"HSNT"):
            pid = parse_pid(bytes(data))
            if pid is not None:
                found[pid] = device          # keep the BLEDevice, not just addr
    scanner = BleakScanner(detection_callback=cb, scanning_mode="active")
    await scanner.start()
    await asyncio.sleep(timeout)
    return scanner, found


async def main():
    args = sys.argv[1:]
    victim_pid = int(args[0]) if args and not args[0].startswith("-") else 1007
    hold = "--hold" in args
    commit = None
    if "--commit" in args:
        commit = args[args.index("--commit") + 1]

    print("scanning 8s for HSNT beacons (active)...")
    scanner, found = await find_badge()
    for pid, dev in found.items():
        print("  beacon pid=%s @ %s" % (pid, dev.address))
    if victim_pid not in found:
        await scanner.stop()
        print("RESULT: victim pid %d not advertising (app not open / not connectable?)" % victim_pid)
        return 2
    mac = found[victim_pid].address
    await scanner.stop()
    await asyncio.sleep(1.0)

    from bleak import BleakClient, BleakScanner
    client = None
    for attempt in range(1, 5):
        try:
            print("connect attempt %d -> %s" % (attempt, mac))
            # Re-resolve a fresh, BlueZ-registered device each attempt (a stored
            # device from a stopped scanner drops out of the cache -> "not found").
            dev = await BleakScanner.find_device_by_address(mac, timeout=10.0)
            if dev is None:
                print("  not discoverable this pass")
                continue
            client = BleakClient(dev)
            await asyncio.wait_for(client.connect(), timeout=15.0)
            break
        except Exception as e:
            print("  failed: %s" % str(e)[:90])
            client = None
            await asyncio.sleep(1.5)
    if client is None or not client.is_connected:
        print("RESULT: could not CONNECT")
        return 6

    try:
        svcs = client.services
        gchars = {}
        for s in svcs.services.values():
            if (s.uuid or "").lower() == GOTCHA_SVC:
                print("  GOTCHA_SVC present; chars:")
                for c in s.characteristics:
                    gchars[c.uuid.lower()] = c
                    print("    ...%s props=%s" % (c.uuid[-4:], sorted(c.properties)))
        if ATTACK_CHR not in gchars or DUEL_CHR not in gchars:
            allsvc = [s.uuid for s in svcs.services.values()]
            print("RESULT: victim did NOT register ATTACK/DUEL. services=%r" % allsvc)
            return 3

        duel_events = []

        def on_duel(_h, data):
            p = gotcha.parse_duel_payload(bytes(data))
            duel_events.append(p)
            print("  <- DUEL notify %r" % (p,))

        await client.start_notify(gchars[DUEL_CHR], on_duel)
        await asyncio.sleep(0.3)

        payload = gotcha.build_attack_payload(0, 9999, victim_pid,
                                              gotcha.ATTACK_TARGET, "host").encode()
        print("-> write ATTACK %r" % payload)
        await client.write_gatt_char(gchars[ATTACK_CHR], payload, response=True)

        # Wait for ENGAGED
        for _ in range(40):
            if any(e and e.get("s") == "engaged" for e in duel_events):
                break
            await asyncio.sleep(0.1)
        eng = next((e for e in duel_events if e and e.get("s") == "engaged"), None)
        if eng is None:
            print("RESULT: ATTACK written but NO ENGAGED notify (victim refused/silent). events=%r"
                  % duel_events)
            return 4
        print("  ENGAGED hold_ms=%s dodges_left=%s" % (eng.get("h"), eng.get("d")))

        if not hold:
            print("  (--hold not set) disconnecting mid-hold to test link-drop DODGE")
            await client.disconnect()
            return 0

        # Stay connected through the hold; wait for terminal state
        hold_ms = int(eng.get("h") or 5000)
        deadline = asyncio.get_event_loop().time() + (hold_ms / 1000.0) + 4.0
        term = None
        while asyncio.get_event_loop().time() < deadline:
            term = next((e for e in duel_events
                         if e and e.get("s") in ("killed", "dodged", "refused")), None)
            if term:
                break
            await asyncio.sleep(0.1)
        if term is None:
            print("RESULT: hold elapsed but NO KILLED/DODGED notify. events=%r" % duel_events)
            return 5
        print("  terminal: %s" % term.get("s"))
        if term.get("s") == "killed":
            raw = await client.read_gatt_char(gchars[SPOILS_CHR])
            sp = gotcha.parse_spoils_payload(bytes(raw))
            print("  SPOILS %r" % sp)
            soul = sp.get("soul") if sp else None
            if commit and soul:
                ok = gotcha.verify_soul(bytes.fromhex(soul), commit)
                print("  soul verifies vs commitment: %s" % ok)
            print("RESULT: KILL handshake COMPLETE (soul disclosed=%s)" % bool(soul))
        else:
            print("RESULT: duel ended %s" % term.get("s"))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
