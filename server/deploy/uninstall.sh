#!/usr/bin/env bash
# Remove everything install.sh created (plan §6.1 deployment, reversed).
#
# This is the "after camp" script. By default it keeps the database, because that
# is the record of the game -- scores, kills, the audit trail -- and deleting it
# is a separate, deliberate act:
#
#     sudo server/deploy/uninstall.sh              # keep /var/lib/gotcha
#     sudo server/deploy/uninstall.sh --purge      # delete the database too
#     sudo server/deploy/uninstall.sh --purge --keep-backup
#
# Every step corresponds to a line in server/DEPLOY_LOG.md.
set -euo pipefail

PURGE=no
KEEP_BACKUP=no
for a in "$@"; do
  case "$a" in
    --purge) PURGE=yes ;;
    --keep-backup) KEEP_BACKUP=yes ;;
    *) echo "unknown option: $a" >&2; exit 1 ;;
  esac
done
if [[ $EUID -ne 0 ]]; then echo "run with sudo" >&2; exit 1; fi

echo "==> stopping the service"
systemctl disable --now gotcha.service 2>/dev/null || true
rm -f /etc/systemd/system/gotcha.service
systemctl daemon-reload
systemctl reset-failed gotcha.service 2>/dev/null || true

echo "==> removing code and virtualenv"
rm -rf /opt/gotcha

echo "==> removing configuration (contains the admin password)"
rm -rf /etc/gotcha

if [[ "$PURGE" == yes ]]; then
  if [[ "$KEEP_BACKUP" == yes && -f /var/lib/gotcha/gotcha.sqlite3 ]]; then
    BK="/root/gotcha-final-$(date +%Y%m%d-%H%M%S).sqlite3"
    cp /var/lib/gotcha/gotcha.sqlite3 "$BK"
    echo "    database backed up to $BK"
  fi
  echo "==> deleting the database"
  rm -rf /var/lib/gotcha
else
  echo "==> KEEPING the database at /var/lib/gotcha (use --purge to delete)"
fi

echo "==> removing the service user"
if id -u gotcha >/dev/null 2>&1; then
  userdel gotcha 2>/dev/null || true
fi

echo "Done. Nothing of the Gotcha backend remains except what is listed above."
