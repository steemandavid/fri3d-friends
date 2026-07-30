#!/usr/bin/env bash
# run_coex.sh -- drive one Phase 0 coexistence/scan-duty condition end to end.
#
#   tools/run_coex.sh <port> <label> <window_us> <interval_us> <off|idle|busy> [dur_s]
#
# WiFi state and traffic load are driven from HERE, not from inside the badge
# app: the wifi service takes foreground when it (re)connects, which pauses the
# probe activity and silently ends the run. So the host sets WiFi first, then
# launches the one-shot probe, then (for "busy") floods the badge to keep the
# WiFi radio working for the whole window.
#
#   off   WiFi disabled on the badge
#   idle  WiFi associated, no traffic
#   busy  WiFi associated + a continuous ping flood from the host (stands in for
#         the §6.2 sync traffic; a badge-side HTTP loop cannot be used because
#         it needs the same foreground the probe holds)
set -u
PORT_RAW="${1:?usage: run_coex.sh <port> <label> <window_us> <interval_us> <off|idle|busy> [dur_s]}"
LABEL="${2:?label}"
WINDOW="${3:?window_us}"
INTERVAL="${4:?interval_us}"
MODE="${5:?off|idle|busy}"
DUR_S="${6:-60}"
if [[ "$PORT_RAW" == /dev/* ]]; then PORT="$PORT_RAW"; else
  PORT="/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_${PORT_RAW}-if00"; fi
REPO=/home/john/claudecode/projects/fri3d-friends
mp() { timeout 40 mpremote connect "$PORT" "$@" 2>&1 | tr -d '\r' | grep -v WARNING; }
alive() { timeout 20 mpremote connect "$PORT" exec "print(1)" >/dev/null 2>&1; }
ensure_alive() {
  alive && return 0
  echo "   port wedged -- USBDEVFS_RESET"
  sudo -n python3 "$REPO/tools/recover_badge_port.py" "$PORT" >/dev/null 2>&1
  sleep 6
  alive && return 0
  echo "   !! still wedged after reset" >&2
  return 1
}
# pull_file <remote> <local>: mp's pipeline always exits 0, so verify by hand.
pull_file() {
  rm -f "$2"
  timeout 40 mpremote connect "$PORT" cp ":$1" "$2" >/dev/null 2>&1
  [ -s "$2" ] && echo "   -> $2" || { echo "   !! MISSING $2"; return 1; }
}

echo "== $LABEL : window=${WINDOW}us interval=${INTERVAL}us wifi=$MODE dur=${DUR_S}s =="
ensure_alive || exit 1

# ---- 1. wifi state (from the REPL, before the probe owns the foreground) ----
if [ "$MODE" = "off" ]; then
  mp exec "
import time
from mpos import WifiService
WifiService.temporarily_disable()
for i in range(20):
    if not WifiService.is_connected(): break
    time.sleep(0.5)
print('wifi off ->', WifiService.is_connected())" | tail -1
  BADGE_IP=""
else
  mp exec "
import time
from mpos import WifiService
if not WifiService.is_connected():
    WifiService.temporarily_enable(True)
for i in range(60):
    if WifiService.is_connected(): break
    time.sleep(0.5)
print('wifi on ->', WifiService.is_connected(), WifiService.get_ipv4_address())" | tail -1
  BADGE_IP=$(mp exec "from mpos import WifiService; print(WifiService.get_ipv4_address())" | tail -1)
  echo "   badge ip: $BADGE_IP"
fi

# ---- 2. config + launch the one-shot probe ----
printf '{"label":"%s","window_us":%s,"interval_us":%s,"dur_ms":%s}' \
  "$LABEL" "$WINDOW" "$INTERVAL" "$((DUR_S * 1000))" > /tmp/coex_cfg.json
mp cp /tmp/coex_cfg.json :/coex_cfg.json >/dev/null
mp exec "import mpos; print('launch ->', mpos.AppManager.start_app('gotcha.coex'))" | tail -1

# ---- 3. load, for the whole measurement window ----
FLOOD_PID=""
if [ "$MODE" = "busy" ] && [ -n "$BADGE_IP" ]; then
  # -s 500 at 100/s: the badge answers these (1000-byte pings get 0 replies), so
  # the load is real two-way radio work, ~400 kbit/s each way.
  echo "   flooding $BADGE_IP for $((DUR_S + 8))s"
  sudo -n ping -i 0.01 -s 500 -w $((DUR_S + 8)) "$BADGE_IP" >/tmp/coex_ping_$LABEL.txt 2>&1 &
  FLOOD_PID=$!
fi

sleep $((DUR_S + 12))
[ -n "$FLOOD_PID" ] && wait $FLOOD_PID 2>/dev/null

# ---- 4. results ----
if [ "$MODE" = "busy" ] && [ -f /tmp/coex_ping_$LABEL.txt ]; then
  echo "   ping load: $(grep -E 'packets transmitted' /tmp/coex_ping_$LABEL.txt || echo '?')"
fi
ensure_alive || exit 1
pull_file "/coex_${LABEL}.json" "probes/logs/coex_${LABEL}.json"
pull_file "/coex_${LABEL}.csv"  "probes/logs/coex_${LABEL}.csv"
[ -s probes/logs/coex_gatt.json ] || pull_file "/coex_gatt.json" "probes/logs/coex_gatt.json"
mp exec "
import os
try: print('ERR:', open('/coex_err.txt').read())
except Exception: pass" | tail -1
# back to the launcher so the next condition starts clean
mp exec "import mpos; mpos.AppManager.restart_launcher()" >/dev/null 2>&1
echo ""
