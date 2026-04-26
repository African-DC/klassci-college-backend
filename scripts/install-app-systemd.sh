#!/usr/bin/env bash
# Install KLASSCI app systemd units (backend, celery, frontend).
#
# Reads units from this repo + the frontend repo, copies them to
# /etc/systemd/system/, daemon-reload, enable + start each.
#
# Idempotent: safe to re-run after pulling new units.
#
# Usage:
#   ./scripts/install-app-systemd.sh         # install + start
#   ./scripts/install-app-systemd.sh status  # show status

set -euo pipefail

UNIT_DIR=/etc/systemd/system
BE_REPO=/home/ubuntu/klassci/klassci-backend
FE_REPO=/home/ubuntu/klassci/klassci-frontend
UNITS=("klassci-backend.service" "klassci-celery.service" "klassci-frontend.service")

case "${1:-install}" in
    status)
        for u in "${UNITS[@]}"; do
            echo "=== ${u} ==="
            systemctl status "${u}" --no-pager --lines=5 || true
            echo
        done
        exit 0
        ;;
    install)
        ;;
    *)
        echo "Usage: $0 [install|status]" >&2
        exit 2
        ;;
esac

echo "==> Copying unit files"
sudo install -m 0644 "${BE_REPO}/scripts/klassci-backend.service" "${UNIT_DIR}/"
sudo install -m 0644 "${BE_REPO}/scripts/klassci-celery.service"  "${UNIT_DIR}/"
sudo install -m 0644 "${FE_REPO}/scripts/klassci-frontend.service" "${UNIT_DIR}/"

echo "==> systemctl daemon-reload"
sudo systemctl daemon-reload

echo "==> Enable + start units"
for u in "${UNITS[@]}"; do
    sudo systemctl enable "${u}"
    sudo systemctl restart "${u}"
done

echo
echo "==> Status (5 lines each)"
for u in "${UNITS[@]}"; do
    echo "--- ${u} ---"
    systemctl status "${u}" --no-pager --lines=3 || true
done

echo
echo "Done. Use:"
echo "  journalctl -u klassci-backend -f      # live logs BE"
echo "  journalctl -u klassci-frontend -f     # live logs FE"
echo "  journalctl -u klassci-celery -f       # live logs Celery"
echo "  systemctl restart klassci-backend     # restart BE"
