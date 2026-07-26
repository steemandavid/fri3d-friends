#!/usr/bin/env python3
"""Passive serial console capture — read-only, timestamped.

Reads whatever MicroPythonOS prints to the USB-CDC console (prints, tracebacks,
OS log lines) and writes it to a file with monotonic timestamps, so we can see
exactly what the badge does at the moment a symptom occurs. Does NOT enter the
REPL or write anything, so the user can keep driving the badge by touch.

Usage: serialcap.py <by-id-port> <seconds> <outfile>
"""
import sys
import time
import serial

port, secs, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
end = time.monotonic() + secs


def emit(f, msg):
    f.write("[%8.2f] %s\n" % (time.monotonic(), msg))
    f.flush()


with open(out, "w") as f:
    emit(f, "# capture start")
    buf = b""
    s = None
    disconnected = False
    while time.monotonic() < end:
        # (Re)open the port. A badge reboot / native-USB CDC reset re-enumerates
        # the device — the old fd dies. Reopen so we capture the boot banner and
        # any traceback the OS prints on the way down/up.
        if s is None:
            try:
                s = serial.Serial(port, 115200, timeout=0.5)
                if disconnected:
                    emit(f, "# ---- port REAPPEARED (badge re-enumerated / rebooted) ----")
                    disconnected = False
            except Exception:
                if not disconnected:
                    emit(f, "# ---- port GONE (badge disconnected / rebooting) ----")
                    disconnected = True
                time.sleep(0.4)
                continue
        try:
            data = s.read(256)
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            s = None
            continue
        if not data:
            continue
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            emit(f, line.decode("utf-8", "replace").rstrip("\r"))
    emit(f, "# capture end")
