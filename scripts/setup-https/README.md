# Setup HTTPS — KLASSCI College

Configuration SSL wildcard via Let's Encrypt + Cloudflare DNS-01 + nginx reverse proxy.

## Architecture finale

```
                     Internet
                        │
                        ▼
        ┌───────────────────────────────────┐
        │  Cloudflare DNS (proxy=OFF)        │
        │  *.college.klassci.com → EC2 IP    │
        └───────────────┬───────────────────┘
                        │
                        ▼
        ┌───────────────────────────────────┐
        │  EC2 nginx :443                    │
        │  SSL termination (LE wildcard)     │
        └─────┬───────────────────────┬─────┘
              │                       │
              ▼                       ▼
     api.college.klassci.com   *.college.klassci.com
        ↓ proxy_pass               ↓ proxy_pass
     127.0.0.1:8000           127.0.0.1:3000
       (FastAPI)               (Next.js standalone)
```

## Étapes (dans l'ordre)

### 1. Configurer Cloudflare DNS (à faire AVANT install)

Sur https://dash.cloudflare.com → klassci.com → DNS → Records :

| Type | Name           | Content        | Proxy status |
|------|----------------|----------------|--------------|
| A    | college        | `<EC2_IP>`     | DNS only (OFF) |
| A    | *.college      | `<EC2_IP>`     | DNS only (OFF) |
| A    | api.college    | `<EC2_IP>`     | DNS only (OFF) |

Vérifier que la propagation est OK :
```bash
dig +short college.klassci.com
dig +short test.college.klassci.com
dig +short api.college.klassci.com
# Doit retourner l'IP EC2
```

### 2. Créer le Cloudflare API token

1. https://dash.cloudflare.com/profile/api-tokens
2. **Create Token** → template "Edit zone DNS"
3. Permissions : **Zone:Read** + **Zone:DNS:Edit**
4. Zone Resources : **Specific zone → klassci.com**
5. TTL : **None** (pas d'expiration)
6. Continue → Create Token → **copier la valeur** (visible une seule fois)

### 3. Sur l'EC2 — Installer le token

```bash
# SSH vers EC2
ssh -i ~/Downloads/Ec2_key_pair.pem ubuntu@<EC2_IP>

# Créer le secret
sudo mkdir -p /root/.secrets
sudo nano /root/.secrets/cloudflare.ini
# → coller :
#   dns_cloudflare_api_token = <token>
sudo chmod 600 /root/.secrets/cloudflare.ini
sudo chown root:root /root/.secrets/cloudflare.ini
```

### 4. Lancer le bootstrap script

```bash
cd /home/ubuntu/klassci/klassci-backend
git pull
sudo bash scripts/setup-https/install-https.sh
```

Le script va :
1. Installer certbot + plugin Cloudflare + nginx
2. Émettre le cert wildcard `*.college.klassci.com` via DNS-01 (≈ 30s pour propagation)
3. Installer la config nginx + reload
4. Activer le renouvellement auto via systemd timer
5. Tester un dry-run de renew

### 5. Tester

```bash
curl -I https://college.klassci.com
curl -I https://api.college.klassci.com/health
curl -I https://demo.college.klassci.com

# Doit retourner HTTP/2 200 ou 301/302
```

### 6. Update env vars BE et FE

**BE** — `/home/ubuntu/klassci/klassci-backend/.env` :
```bash
CORS_ORIGINS=["https://college.klassci.com","https://api.college.klassci.com"]
ALLOWED_HOST_PATTERN=^[a-z0-9][a-z0-9\-]{0,61}\.college\.klassci\.com$
EXTRA_ALLOWED_HOSTS=["college.klassci.com","api.college.klassci.com"]
```

**FE** — `/home/ubuntu/klassci/klassci-frontend/.env.local` :
```bash
NEXT_PUBLIC_API_URL=https://api.college.klassci.com/api/v1
NEXTAUTH_URL=https://college.klassci.com
AUTH_TRUST_HOST=true
```

Restart les 2 services :
```bash
sudo systemctl restart klassci-backend
fuser -k 3000/tcp; cd /home/ubuntu/klassci/klassci-frontend/.next/standalone && PORT=3000 HOSTNAME=0.0.0.0 node server.js &
```

## Renouvellement automatique

Géré par `certbot.timer` (installé par défaut sur Ubuntu 24.04). Il tourne 2× par jour et renew si le cert expire dans < 30 jours.

Vérifier :
```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

Hook post-renew dans `/etc/letsencrypt/renewal-hooks/post/reload-nginx.sh` reload nginx automatiquement.

## Troubleshooting

### "DNS-01 challenge timed out"
- Vérifier que les records sont bien en **DNS only** (pas Proxied)
- Augmenter `--dns-cloudflare-propagation-seconds 60` dans le script
- Tester manuellement la propagation : `dig +short _acme-challenge.college.klassci.com TXT`

### "Permission denied on cloudflare.ini"
```bash
sudo chmod 600 /root/.secrets/cloudflare.ini
sudo chown root:root /root/.secrets/cloudflare.ini
```

### "nginx test failed"
- Vérifier que `klassci-backend` tourne sur :8000 et `klassci-frontend` sur :3000
- Logs : `sudo nginx -t` et `sudo journalctl -u nginx -n 50`

### Bypass nginx (test direct backend)
```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3000/
```

## Activer Cloudflare proxy mode plus tard (optionnel)

Une fois tout stable, on peut activer le proxy Cloudflare pour DDoS protection +
caching. Avant :
1. Vérifier que Celery / WebSocket marche bien (Cloudflare proxy a des contraintes)
2. Configurer "Full (strict)" SSL mode dans Cloudflare → SSL/TLS
3. Toggle proxy ON dans DNS records (orange cloud)
4. Trust `CF-Connecting-IP` dans nginx (`real_ip_header CF-Connecting-IP`)

## Coûts

- Domain `klassci.com` : ~10€/an
- Let's Encrypt : 0€
- Cloudflare DNS : 0€
- nginx + certbot sur EC2 existant : 0€
