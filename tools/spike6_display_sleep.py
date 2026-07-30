#!/usr/bin/env python3
"""spike6_display_sleep.py -- Phase 0 spike 6: can the 2024 panel be blanked?

Plan §8.7 lever 1: on the 2026 `mpos.io_expander.lcd_brightness` exists; on the
2024 there is no backlight API, so the question is whether the GC9307 can be put
to sleep with a panel command instead.

Drives the 2024 badge's display SPI bus directly:
  DISPOFF (0x28) -> hold -> DISPON (0x29)
  SLPIN   (0x10) -> hold -> SLPOUT (0x11) + DISPON

Each step prints what to look for; WATCH THE BADGE SCREEN and note whether the
image goes black and whether the backlight glow stays on. The distinction is the
whole point: DISPOFF/SLPIN stop the panel, they cannot switch off a backlight
that has no GPIO behind it.

  python3 tools/spike6_display_sleep.py <port-or-serial-id> [hold_s]
"""
import subprocess
import sys

DISPOFF, DISPON, SLPIN, SLPOUT = 0x28, 0x29, 0x10, 0x11


def mp(port, code, timeout=60):
    p = subprocess.run(["mpremote", "connect", port, "exec", code],
                       capture_output=True, text=True, timeout=timeout)
    out = (p.stdout or "").replace("\r", "")
    err = (p.stderr or "").replace("\r", "")
    return out.strip(), err.strip()


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else "348518acfac00000"
    hold = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    port = raw if raw.startswith("/dev/") else (
        "/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_%s-if00" % raw)

    print("=" * 70)
    print("SPIKE 6 -- 2024 display blanking     port %s" % port)
    print("=" * 70)

    print("\n1. What the driver itself offers")
    out, err = mp(port, """
import mpos
b = mpos.board.fri3d_2024
inst = b.st7789.ST7789._displays[0]
print('backlight_pin =', inst._backlight_pin)
print('power_pin     =', inst._power_pin)
print('get_backlight ->', inst.get_backlight())
print('get_power     ->', inst.get_power())
print('bus           =', type(inst._data_bus).__name__)
""")
    print(out or err)

    print("\n2. DISPOFF (0x28) for %ds, then DISPON (0x29)  --  WATCH THE SCREEN" % hold)
    out, err = mp(port, """
import mpos, time
bus = mpos.board.fri3d_2024.display_bus
def cmd(c):
    try:
        bus.tx_param(c)
        return 'ok'
    except TypeError:
        try:
            bus.tx_param(c, None)
            return 'ok(2-arg)'
        except Exception as e:
            return 'EXC %r' % (e,)
    except Exception as e:
        return 'EXC %r' % (e,)
print('DISPOFF ->', cmd(0x28))
time.sleep(%d)
print('DISPON  ->', cmd(0x29))
""" % hold, timeout=hold + 40)
    print(out or err)

    print("\n3. SLPIN (0x10) for %ds, then SLPOUT (0x11) + DISPON  --  WATCH THE SCREEN" % hold)
    out, err = mp(port, """
import mpos, time
bus = mpos.board.fri3d_2024.display_bus
def cmd(c):
    try:
        bus.tx_param(c)
        return 'ok'
    except TypeError:
        try:
            bus.tx_param(c, None)
            return 'ok(2-arg)'
        except Exception as e:
            return 'EXC %r' % (e,)
    except Exception as e:
        return 'EXC %r' % (e,)
print('SLPIN  ->', cmd(0x10))
time.sleep(%d)
print('SLPOUT ->', cmd(0x11))
time.sleep(0.2)
print('DISPON ->', cmd(0x29))
""" % hold, timeout=hold + 40)
    print(out or err)

    print("\n4. Did LVGL survive? (forces a full redraw)")
    out, err = mp(port, """
import mpos, lvgl as lv, time
try:
    lv.screen_active().invalidate()
    print('invalidate ok')
except Exception as e:
    print('invalidate EXC', repr(e))
time.sleep(1)
print('foreground:', mpos.get_foreground_app())
""")
    print(out or err)

    print("\n" + "=" * 70)
    print("Record for the plan: did the image go black, and did the backlight")
    print("glow stay on? A black panel with the backlight still lit means the")
    print("command works but lever 1 does NOT recover the ~50 mA -- the LEDs do.")
    print("=" * 70)


if __name__ == "__main__":
    main()
