# S1 — Trust foundation : checklist user-actions

**Goal** : finir la phase trust de la trajectoire 10-semaines vers le 1er client. Tout ce qui suit demande la création d'un compte externe (gratuit) ou la configuration d'une valeur que je ne peux pas générer pour toi.

État au 2026-04-26 :

| Item | Status | Coût | Bloquant beta ? |
|------|--------|------|-----------------|
| HTTPS Let's Encrypt | ✅ live | 0 | — |
| systemd Restart=always (BE/FE/Celery) | ✅ live | 0 | — |
| Single-domain pivot | ✅ live | 0 | — |
| Sentry SDK intégré (no-op) | ✅ code | 0 | non |
| Backup MySQL Tier 1 (local) | ✅ live | 0 | non |
| Restore-test hebdomadaire | ✅ live | 0 | non |
| **Sentry DSN configuré** | ⏳ user-action | 0 | non, mais important |
| **Resend SMTP configuré** | ⏳ user-action | 0 | OUI (password reset cassé) |
| **Healthchecks.io 2 checks** | ⏳ user-action | 0 | non |
| **Backup Tier 2 (DO Spaces off-site)** | ⏳ user-action | 5 USD/mo | OUI avant 1er client |

---

## 1. Resend SMTP (PRIORITÉ — bloquant beta)

Pourquoi : sans SMTP, le password reset, les invitations, et les notifications email sont muets. Une école beta s'attend à recevoir un email quand son admin reset le password d'un parent.

### Étapes

1. **Créer compte Resend** : https://resend.com (gratuit, 3000 emails/mois)
2. **Vérifier le domaine `klassci.com`** :
   - Dans le dashboard Resend → Domains → Add Domain → `klassci.com`
   - Resend te donne 3 records DNS (DKIM + SPF + return-path)
   - Ajouter ces 3 records dans le DNS provider (Cloudflare/Route53) — propagation ~10 min
3. **Créer une API Key** : Resend dashboard → API Keys → Create → name `klassci-college-prod`, scope `Sending access`
4. **Mettre la valeur sur EC2** :

```bash
ssh -i ~/Downloads/Ec2_key_pair.pem ubuntu@16.58.132.68
sudo nano /home/ubuntu/klassci/klassci-backend/.env
# Ajouter / remplacer :
# SMTP_PASSWORD=re_<ta_clé_API>
# SMTP_FROM_EMAIL=noreply@klassci.com
sudo systemctl restart klassci-backend
```

5. **Tester** : depuis le FE, faire un "mot de passe oublié" → email doit arriver dans la boîte de l'admin test.

---

## 2. Sentry DSN (priorité haute, pas bloquant)

Pourquoi : actuellement les bugs en prod sont invisibles (no-op SDK). Avec un DSN, chaque exception est loggée + tu reçois un email.

### Étapes

1. **Créer compte Sentry** : https://sentry.io (gratuit, 5K events/mois, 1 user)
2. **Créer 2 projets** dans le même organization :
   - `klassci-college-backend` (platform: Python / FastAPI)
   - `klassci-college-frontend` (platform: JavaScript / Next.js)
3. **Copier les 2 DSNs** (visibles dans Project Settings → Client Keys)
4. **Mettre les valeurs sur EC2** :

```bash
ssh -i ~/Downloads/Ec2_key_pair.pem ubuntu@16.58.132.68

# Backend
sudo nano /home/ubuntu/klassci/klassci-backend/.env
# Ajouter :
# SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project_id>
# SENTRY_ENVIRONMENT=production
# APP_VERSION=0.1.0-alpha

# Frontend (le SENTRY_DSN client est NEXT_PUBLIC_*, donc inliné au build !)
sudo nano /home/ubuntu/klassci/klassci-frontend/.next/standalone/.env.local
# Ajouter :
# SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<fe_project_id>   ← server-side, pas inliné, marche tout de suite
# NEXT_PUBLIC_SENTRY_DSN=...   ← inliné au build, NE MARCHERA QU'APRES REBUILD
# NEXT_PUBLIC_SENTRY_ENVIRONMENT=production

sudo systemctl restart klassci-backend klassci-frontend
```

⚠️ Le `NEXT_PUBLIC_SENTRY_DSN` côté browser ne sera actif **qu'après le prochain rebuild FE** (CI/CD à venir, ou rebuild local + ship). Le `SENTRY_DSN` côté server est lu à chaque démarrage, donc actif après restart.

5. **Tester** : trigger une 500 sur le BE (ex: hit un endpoint admin sans token) → l'event doit apparaître dans Sentry dashboard.

---

## 3. Healthchecks.io — 2 deadman switches (priorité moyenne)

Pourquoi : si le timer de backup s'arrête (par ex. après un reboot où l'on aurait oublié `enable`), tu n'es pas notifié. Healthchecks.io ping → si pas de ping pendant la grâce, alerte.

### Étapes

1. **Créer compte** : https://healthchecks.io (gratuit, 20 checks)
2. **Créer 2 checks** :
   - **klassci-backup-daily**
     - Schedule : `0 2 * * *` (cron, quotidien 02:00 UTC)
     - Grace period : 30 min
   - **klassci-restore-test**
     - Schedule : `0 3 * * 0` (cron, dimanche 03:00 UTC)
     - Grace period : 60 min
3. **Configurer notification** : Settings → Integrations → Email (default, sur ton compte)
4. **Copier les 2 UUIDs** (dans l'URL de chaque check : `https://healthchecks.io/checks/<UUID>/`)
5. **Activer sur EC2** :

```bash
ssh -i ~/Downloads/Ec2_key_pair.pem ubuntu@16.58.132.68
sudo tee -a /etc/klassci/backup.env > /dev/null <<EOF
HEALTHCHECKS_BACKUP_UUID=<uuid_du_check_backup>
HEALTHCHECKS_RESTORE_UUID=<uuid_du_check_restore>
EOF

# Tester immédiatement
sudo systemctl start backup-mysql.service
# → Doit voir le check passer "up" sur https://healthchecks.io
```

---

## 4. Backup Tier 2 — Off-site DO Spaces (avant 1er client)

Pourquoi : actuellement les backups sont seulement sur l'EC2. Si l'instance crash + disk corrompu, on perd les backups en même temps que la DB.

### Étapes

1. **Créer compte DigitalOcean** : https://www.digitalocean.com — choisir région `fra1` (Paris, latence Côte d'Ivoire OK)
2. **Créer un Space** :
   - Spaces Object Storage → Create → name `klassci-backups`, region `fra1`, file listing `restricted`
   - Coût : 5 USD/mois pour 250 GB (largement assez)
3. **Générer une Spaces access key** :
   - Settings → API → Spaces Keys → Create → name `klassci-backups-rclone`
   - Noter `access_key` + `secret_access_key`
4. **Configurer rclone sur EC2** :

```bash
ssh -i ~/Downloads/Ec2_key_pair.pem ubuntu@16.58.132.68
sudo apt install -y rclone
rclone config
# Réponses :
# n (New remote)
# name : do-spaces
# type : s3
# provider : DigitalOcean
# env_auth : false
# access_key_id : <ta_key>
# secret_access_key : <ton_secret>
# region : (vide)
# endpoint : fra1.digitaloceanspaces.com
# location_constraint : (vide)
# acl : private
# server_side_encryption : (vide)
# storage_class : (vide)
# y (yes, save)

# Vérifier
rclone lsd do-spaces:
# → doit lister "klassci-backups"
```

5. **Activer dans backup.env** :

```bash
sudo tee -a /etc/klassci/backup.env > /dev/null <<EOF
RCLONE_REMOTE=do-spaces
SPACES_BUCKET=klassci-backups
EOF

# Tester
sudo systemctl start backup-mysql.service
sudo journalctl -u backup-mysql.service -n 30 | grep -i "upload\|spaces"
rclone ls do-spaces:klassci-backups/daily/
# → doit lister le tarball uploadé
```

6. **(Optionnel) Lifecycle rules** sur DO Spaces console pour rétention auto :
   - `daily/` → expire après 7 jours
   - `weekly/` → expire après 28 jours
   - `monthly/` → expire après 365 jours

   Sinon, le script local applique déjà la rétention sur EC2 ; les fichiers Spaces s'accumulent jusqu'à ce qu'on les nettoie.

---

## 5. Test end-to-end de la trust foundation

Une fois 1+2+3+4 fait :

```bash
ssh -i ~/Downloads/Ec2_key_pair.pem ubuntu@16.58.132.68

# 1. Backup déclenché manuellement → vérifier les 3 tiers
sudo systemctl start backup-mysql.service
sudo journalctl -u backup-mysql.service -n 50

# 2. Restore-test passe → vérifier l'intégrité
sudo systemctl start restore-test.service
sudo journalctl -u restore-test.service -n 30

# 3. Healthchecks doit afficher les 2 checks "up" (vérifier sur https://healthchecks.io)

# 4. Sentry doit recevoir un test event :
curl -X POST https://college.klassci.com/api-be/sentry-debug   # endpoint à créer si pas existant

# 5. Resend doit envoyer un email — depuis le FE login, déclencher "mot de passe oublié"
```

---

## Récap : valeurs à préparer côté user

À la fin de cette checklist, tu auras 6 secrets à coller dans 2 fichiers EC2 :

**`/etc/klassci/backup.env`** (root:ubuntu, mode 640) :
```
MYSQL_ROOT_PASSWORD=<auto, déjà fait>
RCLONE_REMOTE=do-spaces
SPACES_BUCKET=klassci-backups
HEALTHCHECKS_BACKUP_UUID=<uuid>
HEALTHCHECKS_RESTORE_UUID=<uuid>
```

**`/home/ubuntu/klassci/klassci-backend/.env`** :
```
SMTP_PASSWORD=re_<resend_api_key>
SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project>
SENTRY_ENVIRONMENT=production
APP_VERSION=0.1.0-alpha
```

**`/home/ubuntu/klassci/klassci-frontend/.next/standalone/.env.local`** :
```
SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<fe_project>
NEXT_PUBLIC_SENTRY_DSN=<même valeur>   # actif après prochain rebuild FE
NEXT_PUBLIC_SENTRY_ENVIRONMENT=production
```

Restart les services après chaque modif d'`.env` :
```bash
sudo systemctl restart klassci-backend klassci-frontend
```

---

## Coût mensuel total après S1 complet

| Service | Coût |
|---------|------|
| Resend (3K emails/mois) | 0 USD |
| Sentry (5K events/mois) | 0 USD |
| Healthchecks.io (20 checks) | 0 USD |
| DO Spaces (250 GB) | 5 USD |
| EC2 t3.small (existant) | ~17 USD |
| **Total ajouté par S1** | **5 USD/mois** |
