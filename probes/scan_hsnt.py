#!/usr/bin/env python3
"""Scan for HSNT beacons and dump pid/name/group for each."""
import asyncio
from bleak import BleakScanner


def parse(d):
    # d = mfg payload after company: HSNT ver blocks gcount groups namelen name [game]
    if not d.startswith(b"HSNT"):
        return None
    try:
        i = 4
        ver = d[i]; i += 1
        blocks = d[i]; i += 1
        gcount = d[i]; i += 1
        groups = []
        for _ in range(gcount):
            groups.append(int.from_bytes(d[i:i + 2], "little")); i += 2
        namelen = d[i]; i += 1
        name = d[i:i + namelen].decode("utf-8", "replace"); i += namelen
        pid = None
        if blocks & 1 and i + 5 <= len(d):
            pid = int.from_bytes(d[i:i + 3], "little")
        return {"ver": ver, "blocks": blocks, "groups": groups, "name": name, "pid": pid}
    except Exception as e:
        return {"err": str(e)}


async def main():
    hits = {}

    def cb(dev, ad):
        md = ad.manufacturer_data.get(0xffff)
        if md and bytes(md).startswith(b"HSNT"):
            hits[dev.address] = bytes(md)

    s = BleakScanner(detection_callback=cb, scanning_mode="active")
    await s.start()
    await asyncio.sleep(8)
    await s.stop()
    for a, d in sorted(hits.items()):
        print(a, parse(d))


asyncio.run(main())
