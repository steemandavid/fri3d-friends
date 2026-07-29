#!/usr/bin/env bash
# pull_walks.sh -- pull every walk_<N>.csv + walk_<N>_markers.csv off a badge.
#
#   tools/pull_walks.sh <port>
#
# After "RSSI Walk" has logged several walks, run this to copy them all to
# probes/logs/, then:  python3 tools/analyze_rssi.py probes/logs/walk_*.csv [--plot]
set -u
PORT_RAW="${1:?usage: pull_walks.sh <port>}"
if [[ "$PORT_RAW" == /dev/* ]]; then PORT="$PORT_RAW"; else
  PORT="/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_${PORT_RAW}-if00"; fi
[[ -e "$PORT" ]] || { echo "!! port not found: $PORT" >&2; exit 1; }
REPO=/home/john/claudecode/projects/fri3d-friends
mkdir -p "$REPO/probes/logs"
mp() { timeout 15 mpremote connect "$PORT" "$@" 2>&1 | tr -d '\r' | grep -v WARNING; }

files=$(mp exec "import os; print(' '.join(sorted(f for f in os.listdir('/') if f.startswith('walk_'))))" | tail -1)
echo "walk files on badge: ${files:-<none>}"
[ -z "$files" ] && exit 0
for f in $files; do
  for i in 1 2 3; do
    if mp cp :/$f "$REPO/probes/logs/$f" >/dev/null 2>&1 && [ -s "$REPO/probes/logs/$f" ]; then
      lines=$(grep -cv '^#' "$REPO/probes/logs/$f" 2>/dev/null || echo 0)
      echo "  pulled $f ($lines lines)"; break
    fi; sleep 1
  done
done
echo ""
echo "Pulled to probes/logs/. Analyze all at once:"
echo "  python3 tools/analyze_rssi.py probes/logs/walk_*.csv [--plot]"
echo "Clear them off the badge when done:"
echo "  mpremote connect $PORT exec \"import os; [os.remove('/'+f) for f in os.listdir('/') if f.startswith('walk_')]\""
