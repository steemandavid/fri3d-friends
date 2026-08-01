#!/usr/bin/env python3
"""host_reveal_hunter.py -- host-side Reveal hunter (one badge + host Bluetooth).

Drives the Phase 3a reveal from the host's BLE adapter, so the connect path can be
proven with a SINGLE badge (the badge is the connectable target/responder). This
sidesteps needing two badges.

It:
  1. Scans for the badge's HSNT v2 advertisement (manufacturer data 0xffff starting
     with b"HSNT") -- proves the connectable beacon is actually on air.
  2. Connects, lists the GATT services/characteristics -- proves the Gotcha service
     (6e400030..) + REVEAL (6e400034..) registered.
  3. Writes a REVEAL payload {g,h,t,n} with t == the badge's pid -> the badge's
     apply_reveal() should flash gold + go SPOTTED.

Usage: python3 probes/host_reveal_hunter.py <target_pid> [hunter_pid]
  target_pid is the badge's pid (read from its gotcha_reveal_status.txt).
"""
import asyncio
import sys

sys.path.insert(0, "app/com.fri3dcamp.fri3dfriends")
import gotcha  # noqa: E402  (build_reveal_payload)

HSNT_COMPANY = 0xffff
GOTCHA_SVC = "6e400030-b5a3-f393-e0a9-e50e24dcca9e"
REVEAL_CHR = "6e400034-b5a3-f393-e0a9-e50e24dcca9e"


async def find_badge(timeout=8.0):
    from bleak import BleakScanner
    found = {}  # pid -> (BLEDevice, address)

    def cb(device, advertisement_data):
        try:
            data = advertisement_data.manufacturer_data.get(HSNT_COMPANY)
        except Exception:
            data = None
        if data and bytes(data).startswith(b"HSNT"):
            pid = parse_pid(bytes(data))
            found[pid] = (device, device.address)

    scanner = BleakScanner(detection_callback=cb, scanning_mode="active")
    await scanner.start()
    await asyncio.sleep(timeout)
    # NOTE: leave the scanner RUNNING so BlueZ keeps the device cached for connect.
    return scanner, found


def parse_pid(mfg):
    """pid from an HSNT manufacturer payload (bytes after the 0xffff company id),
    or None. Layout: b'HSNT' ver blocks gcount [groups..] namelen name [game?]."""
    try:
        if not mfg.startswith(b"HSNT"):
            return None
        i = 4
        ver = mfg[i]; i += 1            # noqa: F841
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


async def main():
    target_pid = int(sys.argv[1]) if len(sys.argv) > 1 else 1005
    hunter_pid = int(sys.argv[2]) if len(sys.argv) > 2 else 9999
    print("scanning for HSNT beacons (8s, active)...")
    scanner, found = await find_badge()
    if not found:
        await scanner.stop()
        print("RESULT: NO HSNT BEACON FOUND -- connectable beacon NOT confirmed on air")
        return 2
    for pid, (_, addr) in found.items():
        print("  HSNT beacon pid=%s @ %s" % (pid, addr))
    if target_pid not in found:
        await scanner.stop()
        print("RESULT: target pid %d not among beacons; aborting" % target_pid)
        return 5
    _, address = found[target_pid]
    print("target pid %d -> %s" % (target_pid, address))

    payload = gotcha.build_reveal_payload(0, hunter_pid, target_pid, "host").encode("utf-8")
    from bleak import BleakClient
    # STOP the scanner before connecting: BlueZ refuses a connect while the adapter
    # is scanning ("Operation already in progress"). The address is enough.
    await scanner.stop()
    client = BleakClient(address)
    connected = False
    for attempt in range(1, 4):
        try:
            print("connect attempt %d -> %s" % (attempt, address))
            await asyncio.wait_for(client.connect(), timeout=15.0)
            connected = True
            break
        except Exception as e:
            print("  attempt %d failed: %s" % (attempt, str(e)[:80]))
            await asyncio.sleep(1.5)
    if not connected:
        print("RESULT: could not CONNECT")
        return 6
    try:
        print("  connected; discovering services...")
        services = client.services
        gotcha_chars = []
        for s in services.services.values():
            if s.uuid == GOTCHA_SVC:
                print("  GOTCHA_SVC present")
                for c in s.characteristics:
                    gotcha_chars.append(c)
                    print("    char ...%s props=%s" % (c.uuid[-4:], sorted(c.properties)))
        if not gotcha_chars:
            print("RESULT: connected but GOTCHA_SVC NOT FOUND -- registration failed")
            return 3
        reveal = next((c for c in gotcha_chars if c.uuid == REVEAL_CHR), None)
        if reveal is None:
            print("RESULT: GOTCHA_SVC present but REVEAL char missing")
            return 4
        print("writing REVEAL (%d bytes, t=%d h=%d) ..." % (len(payload), target_pid, hunter_pid))
        await client.write_gatt_char(reveal, payload, response=True)
        print("RESULT: REVEAL WRITE ACKED -- badge should flash gold + go SPOTTED")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
