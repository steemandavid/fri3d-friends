#!/usr/bin/env bash
# deploy_coex.sh -- install/remove the Phase 0 coexistence spike app (spikes 1/3/4).
#
#   tools/deploy_coex.sh <port>            # install + reboot
#   tools/deploy_coex.sh <port> --remove
#
# <port> is either a full /dev/... path or the bare Espressif serial id.
# After install, tap "Coex Spike" in the launcher. It runs six conditions
# (wifi off/idle/busy x 50%/12.5% scan duty), ~60 s each, fully automatic.
# Needs another badge advertising its HSNT beacon nearby, and the host load
# server running:  python3 tools/coex_load_server.py
# Pull results:
#   mpremote connect <port> cp :/coex.json    probes/logs/coex.json
#   mpremote connect <port> cp :/coex_raw.csv probes/logs/coex_raw.csv
set -u
PORT_RAW="${1:?usage: deploy_coex.sh <port> [--remove]}"
if [[ "$PORT_RAW" == /dev/* ]]; then PORT="$PORT_RAW"; else
  PORT="/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_${PORT_RAW}-if00"; fi
[[ -e "$PORT" ]] || { echo "!! port not found: $PORT" >&2; exit 1; }
REPO=/home/john/claudecode/projects/fri3d-friends
PKG=/apps/gotcha.coex
mp() { timeout 20 mpremote connect "$PORT" "$@" 2>&1 | tr -d '\r' | grep -v WARNING; }

if [ "${2:-}" = "--remove" ]; then
  echo "== removing gotcha.coex from $PORT =="
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
for f in ('coex.json', 'coex_raw.csv'):
    try: os.remove('/' + f)
    except Exception: pass
print('removed:', 'gotcha.coex' not in os.listdir('/apps'))
" | tail -2
  mp reset >/dev/null 2>&1
  echo "(badge reset; app gone)"
  exit 0
fi

echo "== install gotcha.coex on $PORT =="
mp exec "import os
try: os.mkdir('/apps')
except Exception: pass
try: os.mkdir('$PKG')
except Exception: pass
print('pkg dir ready')" | tail -1
mp cp "$REPO/probes/coex_pkg/MANIFEST.JSON" :$PKG/MANIFEST.JSON >/dev/null
mp cp "$REPO/probes/coex_pkg/coex.py"       :$PKG/coex.py >/dev/null
echo "== files on badge =="
mp exec "import os; print(os.listdir('$PKG'))" | tail -1
mp reset >/dev/null 2>&1
sleep 2
echo "Done. Start tools/coex_load_server.py on the host, make sure another badge"
echo "is advertising, then tap 'Coex Spike' in the launcher (~7 min, automatic)."
