"""Injectable wall clock.

Every duration rule in the game (respawn, streak decay, dormancy, spawn
protection, the +-10 min signature window) is time-dependent, so the tests need
to move time without sleeping. Nothing in the server calls `time.time()`
directly; it calls `clock.now()`, and the test fixture swaps in a FakeClock.

Times are unix seconds (int) everywhere in the schema and on the wire. Local
wall-clock questions -- only the 22:00-08:00 truce and personal quiet hours --
go through `local_hm()`, which is the single place the camp timezone matters.
"""

import time
from datetime import datetime, timedelta, timezone

# The camp is in Belgium; the truce schedule ("22:00-08:00") is local time.
# Fixed offset rather than a tzdata lookup: the camp is 14-16 Aug 2026, entirely
# inside CEST, and a fixed offset cannot fail on a freshly imaged laptop with no
# tzdata. If this game is ever run in winter, change CAMP_UTC_OFFSET_H to 1.
CAMP_UTC_OFFSET_H = 2
CAMP_TZ = timezone(timedelta(hours=CAMP_UTC_OFFSET_H))


class Clock:
    """Real time."""

    def now(self):
        return int(time.time())


class FakeClock(Clock):
    """Test clock: starts at `t` and only moves when told to."""

    def __init__(self, t):
        self.t = int(t)

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += int(seconds)
        return self.t


_clock = Clock()


def set_clock(clock):
    """Install a clock (the app factory does this; tests pass a FakeClock)."""
    global _clock
    prev = _clock
    _clock = clock
    return prev


def get_clock():
    return _clock


def now():
    return _clock.now()


def local_dt(ts=None):
    """A camp-local datetime for a unix timestamp."""
    if ts is None:
        ts = now()
    return datetime.fromtimestamp(ts, CAMP_TZ)


def local_hm(ts=None):
    """Camp-local (hour, minute) -- what the truce schedule is expressed in."""
    d = local_dt(ts)
    return d.hour, d.minute


def local_minutes(ts=None):
    """Minutes since camp-local midnight."""
    h, m = local_hm(ts)
    return h * 60 + m


def day_start(ts=None):
    """Unix time of camp-local midnight on the day containing `ts`."""
    d = local_dt(ts).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp())


def parse_hm(s, default=(0, 0)):
    """'22:00' -> (22, 0). Tolerant: bad input returns `default`."""
    try:
        parts = str(s).split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except Exception:
        pass
    return default


def hm_str(h, m):
    return "%02d:%02d" % (h, m)
