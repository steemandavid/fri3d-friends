#!/usr/bin/env bash
# run_soak.sh -- the ON-BADGE half of the plan §11 item 2 1000-signed-sync soak.
#
#   tools/run_soak.sh <port> [base_url] [n]
#
# <port> is a full /dev/... path or the bare Espressif serial id (e.g.
# 1cdbd49d9de40000). Drives 1000 consecutive signed /v1/sync from the badge
# against the real backend (default http://192.168.1.57:8080), watching the
# badge heap, then pulls /soak_result.json to probes/logs/.
#
# The probe runs as a TaskManager task on the OS loop (never a blocking REPL
# script), so it yields and does not starve the launcher or trip the WDT. The
# server half of the same soak is server/tools/smoke.py --soak 1000.
set -u
PORT_RAW="${1:?usage: run_soak.sh <port> [base] [n]}"
BASE="${2:-http://192.168.1.57:8080}"
N="${3:-1000}"
if [[ "$PORT_RAW" == /dev/* ]]; then PORT="$PORT_RAW"; else
  PORT="/dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_${PORT_RAW}-if00"; fi
[[ -e "$PORT" ]] || { echo "!! port not found: $PORT" >&2; exit 1; }
REPO=/home/john/claudecode/projects/fri3d-friends
LOG="$REPO/probes/logs/soak_result.json"

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
  [ -s "$2" ] && echo "   -> $2" || { echo "   !! MISSING $2" >&2; return 1; }
}
has() { # has <remote_path> -> prints 1/0
  timeout 25 mpremote connect "$PORT" exec \
    "import os; print(1 if '$1' in os.listdir('/') else 0)" 2>/dev/null \
    | tr -d '\r' | grep -E '^[01]$' | tail -1
}

echo "== soak: $N signed syncs from $PORT -> $BASE =="
ensure_alive || exit 1

# ---- 1. push the probe + its config ----
mp cp "$REPO/probes/soak_pkg/soak.py" :/soak.py >/dev/null
mp exec "import json
f=open('/soak_cfg.json','w'); json.dump({'base':'$BASE','n':$N}, f); f.flush(); f.close()
print('cfg written')" | tail -1

# ---- 2. clear any stale outputs from a previous run, then launch ----
mp exec "import os
for f in ('soak_result.json','soak_status.txt','soak_err.txt'):
    try: os.remove('/'+f)
    except Exception: pass
print('stale cleared')" | tail -1
# Force a fresh import: MicroPython caches modules across REPL sessions, and a
# stale soak.py from a previous run would silently run the OLD code.
# Force a fresh import: MicroPython caches modules across REPL sessions, and a
# stale soak.py from a previous run would silently run the OLD code.
mp exec "from mpos import TaskManager
import sys
for m in [x for x in list(sys.modules) if x=='soak' or x.startswith('soak.')]:
    del sys.modules[m]
import soak
TaskManager.create_task(soak.run())
print('launched')" | tail -1

# ---- 3. poll for the result file (status heartbeat meanwhile) ----
# Pacing (~80 ms/sync) + possible retries: allow generous wall-clock.
deadline=$(( $(date +%s) + N / 3 + 150 ))
while :; do
  [ "$(has soak_result.json)" = "1" ] && { echo "   result file present"; break; }
  [ "$(has soak_err.txt)" = "1" ] && { echo "   !! probe errored:"; mp exec "print(open('/soak_err.txt').read())" | tail -3; exit 1; }
  [ "$(date +%s)" -ge "$deadline" ] && { echo "   !! timed out waiting for result" >&2; exit 1; }
  sleep 5
  st=$(timeout 25 mpremote connect "$PORT" exec "print(open('/soak_status.txt').read())" 2>/dev/null | tr -d '\r' | tail -1)
  [ -n "$st" ] && echo "   ... $st"
done

# ---- 4. settle, then pull the record. The long WiFi run can leave USB-CDC
#         flaky (a hard-working badge sometimes drops its CDC), so a brief
#         settle + a couple of retries avoids a false miss. The result file
#         survives on the badge flash regardless. ----
sleep 3
_ok=0
for _attempt in 1 2 3; do
  if pull_file /soak_result.json "$LOG"; then _ok=1; break; fi
  echo "   pull attempt $_attempt failed (USB-CDC flaky?); settle + retry"
  sleep 5
done
if [ "$_ok" != 1 ]; then
  echo "   !! result IS on the badge at /soak_result.json but the pull failed." >&2
  echo "      It survives a replug. Recover with tools/recover_badge_port.py" >&2
  echo "      (or replug), then re-run only the pull -- do NOT delete it." >&2
  exit 1
fi
echo "== summary =="
python3 - "$LOG" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
print("  syncs        : %d/%d http200, %d verified, %d errors, %d retries" % (
    r["http200"], r["n"], r["verified"], r["n_errors"], r.get("retries", 0)))
print("  heap free    : %d -> %d KB  (min %d)" % (
    r["baseline_mem_free"]//1024, r["final_mem_free"]//1024,
    r["min_mem_free"]//1024))
print("  warmup drop  : %d B (one-time)   steady drift: %+d B (sync-100 -> final)" % (
    r["warmup_drop_bytes"], r["steady_drift_bytes"]))
print("  latency ms   : median %.1f  p95 %.1f  max %.1f  (%.1f req/s, %.1f s total)" % (
    r["latency_ms"]["median"], r["latency_ms"]["p95"], r["latency_ms"]["max"],
    r["req_s"], r["total_s"]))
print("  RFC4231      : %s" % r["rfc4231_selftest"])
print("  VERDICT      : %s" % ("PASS" if r["pass"] else "CHECK -- see errors_head"))
PY

echo "== cleaning throwaway probe off the badge =="
mp exec "import os
for f in ('soak.py','soak_cfg.json','soak_result.json','soak_status.txt','soak_err.txt'):
    try: os.remove('/'+f)
    except Exception: pass
print('removed soak files')" | tail -1
