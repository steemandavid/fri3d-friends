#!/usr/bin/env bash
# rssi_walk.sh -- run the RSSI-trend logger as a native OS-loop task on a badge.
#
# Usage:
#   tools/rssi_walk.sh <logger-port> <advertiser-name> <secs> [label] [window_us] [interval_us] [--walk]
#
#   <logger-port>      /dev/serial/by-id/... path, OR the Espressif serial suffix
#                      of the badge that LOGS. Give it EMPTY groups (silent
#                      beacon_service) so its USB-CDC stays healthy.
#   <advertiser-name>  the SHORT name (<= ~12 chars) on the OTHER badge, which
#                      advertises HSNT (app open, or at the launcher with a group).
#                      "" = log every HSNT beacon (use only with 2 badges total).
#   <secs>             run length (match your walk protocol, e.g. 130).
#   <label>            filename label (open/tent/bodies/pocket).
#   [window_us]/[interval_us]  scan duty. Defaults 60000/120000 (50 %). For the
#                      scan-duty spike (#4) also run 30000/240000 (12.5 %).
#   --walk             WALK mode: schedule, then UNPLUG the logger and carry it
#                      (it logs to flash on battery), replug when done, pull.
#                      Without --walk (bench mode) the logger stays plugged and
#                      you get live progress (use for the coexistence #1 and
#                      scan-duty #4 tests, where the logger is stationary).
#
# ADVERTISER: configure a SHORT name + at least one group on the other badge
# (so it beacons HSNT), then either open the app there or leave it at the
# launcher (its background beacon_service advertises). Opening the app wedges
# THAT badge's USB-CDC (BLE up) -- fine, you only need the LOGGER over USB.
#
# The logger runs as an asyncio task on the badge OS loop (MPS dispatches BLE
# IRQs through that loop; a blocking mpremote script would see 0 adverts). We
# drive it with short, non-blocking execs. Output -> probes/logs/<label>_<HHMMSS>.csv,
# ready for:  python3 tools/analyze_rssi.py probes/logs/*.csv [--plot]
set -u

WALK=0
args=()
for a in "$@"; do [ "$a" = "--walk" ] && WALK=1 || args+=("$a"); done
set -- "${args[@]}"

PORT_RAW="${1:?usage: rssi_walk.sh <logger-port> <name> <secs> [label] [win] [int] [--walk]}"
NAME="${2:-}"; SECS="${3:-120}"; LABEL="${4:-run}"
WINDOW="${5:-60000}"; INTERVAL="${6:-120000}"

if [[ "$PORT_RAW" == /dev/* ]]; then PORT="$PORT_RAW"; else
  PORT="/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_${PORT_RAW}-if00"; fi
[[ -e "$PORT" ]] || { echo "!! port not found: $PORT" >&2; exit 1; }

REPO=/home/john/claudecode/projects/fri3d-friends
mkdir -p "$REPO/probes/logs"
CFG=$(mktemp); STAMP=$(date +%H%M%S); OUT_HOST="$REPO/probes/logs/${LABEL}_${STAMP}.csv"
printf '{"name":"%s","secs":%s,"window_us":%s,"interval_us":%s,"out":"/rssi_log.csv"}' \
  "$NAME" "$SECS" "$WINDOW" "$INTERVAL" > "$CFG"
mp() { timeout 15 mpremote connect "$PORT" "$@" 2>&1 | tr -d '\r' | grep -v WARNING; }

echo "== logger: $PORT   target: ${NAME:-<all HSNT>}   duty: $(awk "BEGIN{printf \"%.0f\",100*$WINDOW/$INTERVAL}")%   secs: $SECS   ${WALK:+WALK mode}"
echo "== advertiser: short name '${NAME:-<any>}' + a group on the other badge (app open or launcher)"
echo "== press ENTER when the logger is plugged in and you're ready to start the ${SECS}s run"
read -r

echo "== deploying probe + config..."
mp cp "$REPO/probes/rssi_log.py" :/rssi_log.py >/dev/null
mp cp "$CFG" :/rssi_cfg.json >/dev/null
echo "== starting the logging task on the badge OS loop..."
mp exec "import rssi_log; from mpos import TaskManager; TaskManager.create_task(rssi_log.run()); print('scheduled')" >/dev/null

if [ "$WALK" = 1 ]; then
  echo ""
  echo "  >>> UNPLUG THE LOGGER NOW and walk your protocol for ${SECS}s <<<"
  echo "  >>> (it logs to flash on battery; the advertiser walks with you) <<<"
  sleep "$SECS"
  echo ""
  echo "  >>> time's up -- REPLUG the logger, then press ENTER <<<"
  read -r
else
  echo "== logging (live, every 2.5s) -- keep the logger plugged..."
  DEADLINE=$(( SECS + 30 )); START=$(date +%s)
  while true; do
    [ $(( $(date +%s) - START )) -ge $DEADLINE ] && { echo "!! timed out"; break; }
    LINE=$(mp exec "import rssi_log; print('POLL', rssi_log.count, rssi_log.done, rssi_log.last_rssi)" | grep POLL | tail -1)
    [ -n "$LINE" ] && echo "  $LINE" || echo "  (CDC flake, retrying)"
    echo "$LINE" | grep -q " True " && break
    sleep 2.5
  done
fi

echo "== pulling log (with retries)..."
for i in $(seq 1 8); do
  if mp cp :/rssi_log.csv "$OUT_HOST" >/dev/null 2>&1 && [ -s "$OUT_HOST" ]; then
    echo "pulled on try $i"; break
  fi; sleep 2
done
mp rm :/rssi_log.py :/rssi_cfg.json :/rssi_log.csv >/dev/null 2>&1
rm -f "$CFG"
LINES=$(grep -cv '^#' "$OUT_HOST" 2>/dev/null || echo 0)
echo "== done: $LINES adverts in $OUT_HOST"
echo "   analyze: python3 tools/analyze_rssi.py $OUT_HOST [--plot]"
