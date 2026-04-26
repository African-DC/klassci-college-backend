#!/usr/bin/env bash
# KLASSCI College — Bootstrap HTTPS sur EC2
#
# À exécuter une seule fois sur l'EC2, après avoir :
#   1. Configuré DNS Cloudflare pour klassci.com (records ci-dessous)
#   2. Créé un Cloudflare API token (voir cloudflare.ini.example)
#   3. Copié le token dans /root/.secrets/cloudflare.ini (mode 600)
#
# Records DNS Cloudflare requis (proxy mode = OFF, DNS only) :
#   college.klassci.com         A     <EC2_IP>     proxy=OFF
#   *.college.klassci.com       A     <EC2_IP>     proxy=OFF
#   api.college.klassci.com     A     <EC2_IP>     proxy=OFF
#
# Le proxy Cloudflare doit rester OFF pendant l'émission cert (DNS-01 propagation).
# On pourra l'activer plus tard si on veut DDoS protection.

set -euo pipefail

# ─── Pré-checks ──────────────────────────────────────────────────────────────
[[ "$EUID" -eq 0 ]] || { echo "ERREUR: à exécuter en root (sudo)"; exit 1; }
[[ -f /root/.secrets/cloudflare.ini ]] || {
  echo "ERREUR: /root/.secrets/cloudflare.ini manquant"
  echo "→ Voir scripts/setup-https/cloudflare.ini.example"
  exit 1
}

PERM=$(stat -c "%a" /root/.secrets/cloudflare.ini)
if [[ "$PERM" != "600" ]]; then
  echo "Fix: chmod 600 sur cloudflare.ini (était $PERM)"
  chmod 600 /root/.secrets/cloudflare.ini
fi

# ─── 1. Installer certbot + plugin Cloudflare ────────────────────────────────
echo "▶ Installation certbot + plugin Cloudflare..."
apt update
apt install -y certbot python3-certbot-dns-cloudflare nginx

# ─── 2. Émettre le certificat wildcard via DNS-01 ────────────────────────────
# Le cert couvre :
#   college.klassci.com           (root pour le subdomain college)
#   *.college.klassci.com         (tous les tenants + api + autres)
echo "▶ Émission cert Let's Encrypt wildcard..."
certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /root/.secrets/cloudflare.ini \
  --dns-cloudflare-propagation-seconds 30 \
  -d "college.klassci.com" \
  -d "*.college.klassci.com" \
  --agree-tos \
  --non-interactive \
  --email "admin@klassci.com" \
  --keep-until-expiring

echo "✓ Cert émis dans /etc/letsencrypt/live/college.klassci.com/"

# ─── 3. Installer config nginx ────────────────────────────────────────────────
echo "▶ Installation config nginx..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp "$SCRIPT_DIR/nginx-klassci.conf" /etc/nginx/sites-available/klassci.conf
ln -sf /etc/nginx/sites-available/klassci.conf /etc/nginx/sites-enabled/klassci.conf

# Désactiver default site si présent
rm -f /etc/nginx/sites-enabled/default

# Préparer la racine pour le challenge HTTP-01 (backup)
mkdir -p /var/www/letsencrypt
chown -R www-data:www-data /var/www/letsencrypt

# Test config + reload
nginx -t
systemctl reload nginx
echo "✓ nginx reloaded"

# ─── 4. Activer renouvellement auto ──────────────────────────────────────────
echo "▶ Vérification du renouvellement automatique..."
systemctl status certbot.timer --no-pager || systemctl enable --now certbot.timer

# Hook post-renew pour reload nginx
mkdir -p /etc/letsencrypt/renewal-hooks/post
cat > /etc/letsencrypt/renewal-hooks/post/reload-nginx.sh <<'EOF'
#!/usr/bin/env bash
systemctl reload nginx
EOF
chmod +x /etc/letsencrypt/renewal-hooks/post/reload-nginx.sh

# Dry-run pour vérifier que le renew marchera
certbot renew --dry-run

# ─── 5. Ouverture firewall ────────────────────────────────────────────────────
if command -v ufw >/dev/null 2>&1; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "✓ HTTPS configuré pour college.klassci.com et *.college.klassci.com"
echo ""
echo "Tester :"
echo "  curl -I https://college.klassci.com"
echo "  curl -I https://api.college.klassci.com/health"
echo "  curl -I https://test.college.klassci.com"
echo ""
echo "Renouvellement auto via systemd timer certbot.timer"
echo "═══════════════════════════════════════════════════════════════════════"
