#!/usr/bin/env bash
# Deploy the app to a badge and verify every file by sha256.
#
# Usage: tools/deploy.sh <serial-id> [file ...]
#   With no files, deploys the full app folder (fresh install).
#
# Always addresses the badge by its stable /dev/serial/by-id/ path — ttyACMx
# numbers reorder on every replug. Resets first so the REPL is healthy and the
# app's BLE stack isn't wedging the USB CDC (the deploy recipe learned the hard
# way; see changelog "USB-CDC wedge").
set -u

SERIAL="$1"; shift
APP=/home/john/claudecode/projects/fri3d-friends/app/com.fri3dcamp.fri3dfriends
FULLNAME=com.fri3dcamp.fri3dfriends
DEST="/apps/$FULLNAME"

port() { echo "/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_${SERIAL}-if00"; }

wait_port() {
    for _ in $(seq 1 40); do
        [ -e "$(port)" ] && sleep 0.5 && return 0
        sleep 0.5
    done
    echo "!! port never came back: $(port)" >&2
    return 1
}

# The port node reappears BEFORE MicroPythonOS has finished booting, so a fixed
# sleep races the filesystem coming up (mkdir silently no-op'd, every cp then
# failed). Probe the REPL until it actually answers.
wait_ready() {
    for _ in $(seq 1 30); do
        if timeout 10 mpremote connect "$(port)" exec "print('rdy')" 2>/dev/null | grep -q rdy; then
            return 0
        fi
        sleep 1
    done
    echo "!! REPL never became ready on $(port)" >&2
    return 1
}

if [ $# -eq 0 ]; then
    FILES=(MANIFEST.JSON fri3d_friends.py ble_proximity.py ble_setup.py \
           contact_exchange.py beacon_service.py identity.py config.json \
           icon_64x64.png fri3dfriends.png montserrat_name.ttf)
else
    FILES=("$@")
fi

# RESET=1 forces a reboot first (use when the app is running and its BLE stack
# is wedging the CDC). Off by default: a reset costs a long, flaky re-enumerate,
# and from the launcher the REPL is already healthy.
if [ "${RESET:-0}" = "1" ]; then
    echo "== $SERIAL: reset to a clean REPL"
    timeout 20 mpremote connect "$(port)" reset >/dev/null 2>&1
    sleep 5
    wait_port || exit 1
fi
wait_ready || exit 1

echo "== $SERIAL: ensure $DEST exists"
timeout 20 mpremote connect "$(port)" exec "
import os
try: os.mkdir('/apps')
except Exception: pass
try: os.mkdir('$DEST')
except Exception: pass
print('dir', '$DEST'.split('/')[-1] in os.listdir('/apps'))
" 2>&1 | tail -1

rc=0
for f in "${FILES[@]}"; do
    if ! timeout 60 mpremote connect "$(port)" cp "$APP/$f" ":$DEST/$f" >/dev/null 2>&1; then
        echo "   cp FAILED $f — retrying once"
        sleep 2
        if ! timeout 60 mpremote connect "$(port)" cp "$APP/$f" ":$DEST/$f" >/dev/null 2>&1; then
            echo "   cp FAILED $f (twice)"; rc=1; continue
        fi
    fi
    echo "   sent $f"
done

echo "== $SERIAL: verify sha256"

LIST=$(printf "'%s'," "${FILES[@]}")
OUT=$(timeout 90 mpremote connect "$(port)" exec "
import hashlib, binascii
for f in [$LIST]:
    try:
        h = hashlib.sha256()
        with open('$DEST/' + f, 'rb') as fh:
            while True:
                b = fh.read(512)
                if not b: break
                h.update(b)
        print(f, binascii.hexlify(h.digest()).decode())
    except Exception as e:
        print(f, 'ERR', e)
" 2>&1 | tr -d '\r')      # mpremote emits CRLF; a trailing \r breaks the compare

for f in "${FILES[@]}"; do
    local_sha=$(sha256sum "$APP/$f" | cut -d' ' -f1)
    remote_sha=$(echo "$OUT" | awk -v n="$f" '$1==n {print $2}')
    if [ "$local_sha" = "$remote_sha" ]; then
        echo "   OK   $f"
    else
        echo "   BAD  $f  local=$local_sha remote=${remote_sha:-<none>}"; rc=1
    fi
done

exit $rc
