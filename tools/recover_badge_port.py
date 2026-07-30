#!/usr/bin/env python3
"""recover_badge_port.py -- unwedge a badge's USB-CDC with USBDEVFS_RESET.

A badge that has been scanning/advertising hard sometimes stops answering on its
CDC entirely: the /dev node still enumerates, but a raw read returns 0 bytes and
mpremote cannot enter the raw REPL. A USB-level port reset brings it back
without touching the badge physically.

Use it SPARINGLY -- repeated resets in quick succession have pushed a badge into
an enumeration fault that needed a physical replug. Try mpremote first; only
call this when the port is genuinely wedged.

  sudo python3 tools/recover_badge_port.py <port-or-serial-id>
"""
import fcntl
import os
import sys
import time

USBDEVFS_RESET = ord("U") << 8 | 20


def usb_node_for(tty_path):
    tty = os.path.realpath(tty_path)
    sysdev = os.path.realpath("/sys/class/tty/%s/device" % os.path.basename(tty))
    d = sysdev
    while d != "/" and not os.path.exists(os.path.join(d, "busnum")):
        d = os.path.dirname(d)
    if d == "/":
        raise SystemExit("could not find a USB device for %s" % tty)
    bus = int(open(os.path.join(d, "busnum")).read())
    dev = int(open(os.path.join(d, "devnum")).read())
    return "/dev/bus/usb/%03d/%03d" % (bus, dev)


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
    port = raw if raw.startswith("/dev/") else (
        "/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_%s-if00" % raw)
    if not os.path.exists(port):
        raise SystemExit("port not found: %s" % port)
    node = usb_node_for(port)
    fd = os.open(node, os.O_WRONLY)
    try:
        fcntl.ioctl(fd, USBDEVFS_RESET, 0)
    finally:
        os.close(fd)
    print("reset %s (%s)" % (port, node))
    for _ in range(30):
        time.sleep(1)
        if os.path.exists(port):
            print("re-enumerated after %s" % port)
            return
    raise SystemExit("did not re-enumerate -- may need a physical replug")


if __name__ == "__main__":
    main()
