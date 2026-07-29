#!/usr/bin/env bash
# deploy_rssi_logger.sh -- install (or remove) the boot-service RSSI logger.
#
#   tools/deploy_rssi_logger.sh <port> <target-name> <secs>     # install + reboot
#   tools/deploy_rssi_logger.sh <port> --remove                  # uninstall + reboot
#
# <port>        /dev/serial/by-id/... OR the Espressif serial suffix.
# <target-name> the advertiser's SHORT name ("" = every HSNT beacon).
# <secs>        log length (match the walk protocol, e.g. 130).
#
# After this, the badge logs to /rssi_log.csv automatically every time it boots
# (for <secs>). Power it on, walk, then pull the file:
#   mpremote connect <port> cp :/rssi_log.csv probes/logs/<label>.csv
# The LOGGER badge should have EMPTY groups (badge B does) so its own
# beacon_service stays silent and doesn't fight the logger for the radio.
set -u
PORT_RAW="${1:?usage: deploy_rssi_logger.sh <port> <name> <secs> | <port> --remove}"
if [[ "$PORT_RAW" == /dev/* ]]; then PORT="$PORT_RAW"; else
  PORT="/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_${PORT_RAW}-if00"; fi
[[ -e "$PORT" ]] || { echo "!! port not found: $PORT" >&2; exit 1; }
REPO=/home/john/claudecode/projects/fri3d-friends
PKG=/apps/rssi.logger
mp() { timeout 15 mpremote connect "$PORT" "$@" 2>&1 | tr -d '\r' | grep -v WARNING; }

if [ "${2:-}" = "--remove" ]; then
  echo "== removing rssi.logger from $PORT =="
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
try:
    os.remove('/rssi_cfg.json')
except Exception:
    pass
print('removed:', 'rssi.logger' not in os.listdir('/apps'))
" | tail -2
  mp reset >/dev/null 2>&1
  echo "(badge reset; boot service gone)"
  exit 0
fi

NAME="${2-}"        # empty = log every HSNT beacon (valid)
SECS="${3:-130}"
echo "== install rssi.logger on $PORT (target='$NAME' secs=$SECS) =="
mp exec "import os
try: os.mkdir('/apps')
except Exception: pass
try: os.mkdir('$PKG')
except Exception: pass
print('pkg dir ready')" | tail -1
mp cp "$REPO/probes/rssi_logger_pkg/MANIFEST.JSON" :$PKG/MANIFEST.JSON >/dev/null
mp cp "$REPO/probes/rssi_logger_pkg/svc.py" :$PKG/svc.py >/dev/null
mp cp "$REPO/probes/rssi_log.py" :$PKG/rssi_log.py >/dev/null
printf '{"name":"%s","secs":%s,"window_us":60000,"interval_us":120000,"out":"/rssi_log.csv"}' \
  "$NAME" "$SECS" > /tmp/rssi_cfg_deploy.json
mp cp /tmp/rssi_cfg_deploy.json :/rssi_cfg.json >/dev/null
echo "== verify files =="
mp exec "import os; print(os.listdir('$PKG'))" | tail -1
echo "== reboot -> badge boots into the logger =="
mp reset >/dev/null 2>&1
sleep 2
echo ""
echo "Done. On each boot it logs ${SECS}s of '$NAME' -> /rssi_log.csv."
echo "Power it on (USB or battery), walk, then pull:"
echo "  mpremote connect $PORT cp :/rssi_log.csv probes/logs/<label>.csv"
echo "Remove the boot service when finished:"
echo "  tools/deploy_rssi_logger.sh $PORT_RAW --remove"
