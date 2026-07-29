#!/usr/bin/env bash
# deploy_rssi_walk.sh -- install/remove the prompted RSSI-walk app.
#
#   tools/deploy_rssi_walk.sh <port> <target-name>     # install + reboot
#   tools/deploy_rssi_walk.sh <port> --remove
#
# <target-name>  the advertiser's SHORT name ("" = every HSNT beacon).
#
# After install + reboot, tap "RSSI Walk" in the launcher and follow the on-screen
# prompts (A advances to the next action and records a marker; X stops then quits).
# It writes /rssi_log.csv + /rssi_markers.csv. Pull BOTH after a walk:
#   mpremote connect <port> cp :/rssi_log.csv     probes/logs/<label>.csv
#   mpremote connect <port> cp :/rssi_markers.csv probes/logs/<label>_markers.csv
# The LOGGER badge should have EMPTY groups (badge B does).
set -u
PORT_RAW="${1:?usage: deploy_rssi_walk.sh <port> <name> | <port> --remove}"
if [[ "$PORT_RAW" == /dev/* ]]; then PORT="$PORT_RAW"; else
  PORT="/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_${PORT_RAW}-if00"; fi
[[ -e "$PORT" ]] || { echo "!! port not found: $PORT" >&2; exit 1; }
REPO=/home/john/claudecode/projects/fri3d-friends
PKG=/apps/rssi.walk
mp() { timeout 15 mpremote connect "$PORT" "$@" 2>&1 | tr -d '\r' | grep -v WARNING; }

if [ "${2:-}" = "--remove" ]; then
  echo "== removing rssi.walk from $PORT =="
  mp exec "
import os
def rm(p):
    try:
        if os.stat(p)[0] & 0x4000:
            for n in os.listdir(p):
                rm(p + '/' + n)
            os.rmdir(p)
        else:
            os.remove(p)
    except Exception as e:
        print('rm-err', p, repr(e))
rm('$PKG')
for f in os.listdir('/'):
    if f.startswith('walk_') or f in ('rssi_cfg.json', 'rssi_log.csv', 'rssi_markers.csv'):
        try: os.remove('/' + f)
        except Exception: pass
print('removed:', 'rssi.walk' not in os.listdir('/apps'))
" | tail -2
  mp reset >/dev/null 2>&1
  echo "(badge reset; app gone)"
  exit 0
fi

NAME="${2-}"        # empty = log every HSNT beacon (valid)
echo "== install rssi.walk on $PORT (target='$NAME') =="
mp exec "import os
try: os.mkdir('/apps')
except Exception: pass
try: os.mkdir('$PKG')
except Exception: pass
print('pkg dir ready')" | tail -1
mp cp "$REPO/probes/rssi_walk_pkg/MANIFEST.JSON" :$PKG/MANIFEST.JSON >/dev/null
mp cp "$REPO/probes/rssi_walk_pkg/walk.py" :$PKG/walk.py >/dev/null
printf '{"name":"%s"}' "$NAME" > /tmp/rssi_walk_cfg.json
mp cp /tmp/rssi_walk_cfg.json :/rssi_cfg.json >/dev/null
echo "== files on badge =="
mp exec "import os; print(os.listdir('$PKG'))" | tail -1
echo "== reboot -> tap 'RSSI Walk' in the launcher =="
mp reset >/dev/null 2>&1
sleep 2
echo ""
echo "Done. Tap 'RSSI Walk' in the launcher, follow the prompts (A = next + marker)."
echo "Per condition, pull BOTH files:"
echo "  mpremote connect $PORT cp :/rssi_log.csv     probes/logs/<label>.csv"
echo "  mpremote connect $PORT cp :/rssi_markers.csv probes/logs/<label>_markers.csv"
echo "Remove when finished: tools/deploy_rssi_walk.sh $PORT_RAW --remove"
