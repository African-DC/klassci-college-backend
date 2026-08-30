#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_DIR="$ROOT/deploy/linux"
ENV_FILE="$COMPOSE_DIR/.env"
HOST="${PUBLIC_HOST:-college.klassci.com}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing $1"; exit 1; }; }
need openssl
need python3 || true

rand_hex() { openssl rand -hex 24; }
rand_b64() { openssl rand -base64 32 | tr -d '\n'; }

if [[ ! -f "$ENV_FILE" ]]; then
  MYSQL_ROOT_PASSWORD="$(rand_hex)"
  MYSQL_PASSWORD="$(rand_hex)"
  NEXTAUTH_SECRET="$(rand_b64)"
  SECRET_KEY="$(rand_hex)"
  SUPERADMIN_PASSWORD="$(openssl rand -base64 18 | tr -d '\n=/+' | cut -c1-20)Aa1!"
  cat > "$ENV_FILE" <<EOF
PUBLIC_HOST=${HOST}
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
MYSQL_USER=klassci
MYSQL_PASSWORD=${MYSQL_PASSWORD}
NEXTAUTH_URL=https://${HOST}
NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
NEXT_PUBLIC_EXTRA_ALLOWED_HOSTS=${HOST},serveur.africandigitconsulting.com
APP_ENV=production
DEBUG=false
SECRET_KEY=${SECRET_KEY}
CORS_ORIGINS=["https://${HOST}"]
EXTRA_ALLOWED_HOSTS=["${HOST}","serveur.africandigitconsulting.com","backend"]
PUBLIC_BASE_URL=https://${HOST}
PUBLIC_LOGIN_URL_TEMPLATE=https://${HOST}/login?c={slug}
LOCAL_TENANT_ID=local
SUPERADMIN_EMAIL=superadmin@klassci.com
SUPERADMIN_PASSWORD=${SUPERADMIN_PASSWORD}
KLASSCI_BACKEND_IMAGE=klassci-college-backend:prod
KLASSCI_FRONTEND_IMAGE=klassci-college-frontend:prod
EOF
  echo "Wrote $ENV_FILE"
  echo "SUPERADMIN_PASSWORD=${SUPERADMIN_PASSWORD}"
else
  echo "Reusing $ENV_FILE"
fi
