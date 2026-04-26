# Scripts d'opération KLASSCI College

Scripts shell pour les opérations critiques (backups, restore-test).

## Architecture en 3 tiers

Le backup MySQL est conçu pour fonctionner **immédiatement avec un minimum de config** (Tier 1), puis monter en gamme à mesure que les comptes externes sont créés.

| Tier | Activé par | Couvre quoi | Coût |
|------|------------|-------------|------|
| **1 — Local** | `MYSQL_ROOT_PASSWORD` (toujours) | Crash MySQL, drop accidentel, corruption logique | 0 |
| **2 — Off-site S3** | `RCLONE_REMOTE` configuré | Perte EC2 (instance/disk down) | ~5 USD/mois (DO Spaces) |
| **3 — Alerting** | `HEALTHCHECKS_BACKUP_UUID` | Notification si le timer cesse de tourner | 0 (free tier) |

Tier 1 fonctionne **out of the box** — même sans compte DO Spaces ni Healthchecks.io.

---

## Installation initiale sur EC2 (Tier 1 — Local)

### 1. Cloner le code (déjà fait)

```bash
cd /home/ubuntu/klassci/klassci-backend
git pull
chmod +x scripts/backup-mysql.sh scripts/restore-test.sh
```

### 2. Créer la config minimale

```bash
sudo mkdir -p /etc/klassci

# Récupérer le mot de passe MySQL depuis le container Docker
MYSQL_PWD=$(docker inspect klassci-mysql \
  --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep MYSQL_ROOT_PASSWORD | cut -d= -f2)

# Créer le fichier de config (root-only)
sudo tee /etc/klassci/backup.env > /dev/null <<EOF
MYSQL_ROOT_PASSWORD=$MYSQL_PWD
EOF
sudo chmod 600 /etc/klassci/backup.env
sudo chown root:root /etc/klassci/backup.env
```

### 3. Tester le backup manuellement

```bash
sudo KLASSCI_BACKUP_ENV=/etc/klassci/backup.env \
  /home/ubuntu/klassci/klassci-backend/scripts/backup-mysql.sh
```

Doit afficher des logs et créer un fichier dans `/home/ubuntu/klassci/backups/daily/klassci-mysql-*.tar.gz`.

### 4. Installer les systemd units + timers

```bash
sudo cp /home/ubuntu/klassci/klassci-backend/scripts/backup-mysql.service /etc/systemd/system/
sudo cp /home/ubuntu/klassci/klassci-backend/scripts/backup-mysql.timer   /etc/systemd/system/
sudo cp /home/ubuntu/klassci/klassci-backend/scripts/restore-test.service /etc/systemd/system/
sudo cp /home/ubuntu/klassci/klassci-backend/scripts/restore-test.timer   /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now backup-mysql.timer
sudo systemctl enable --now restore-test.timer

# Vérifier
sudo systemctl list-timers --all | grep -E '(backup|restore)'
```

À ce stade : **Tier 1 actif**. Backups quotidiens locaux + restore-test hebdomadaire.

---

## Activer Tier 2 — Off-site S3/Spaces (recommandé avant beta)

### a. Créer un compte DigitalOcean Spaces

1. https://www.digitalocean.com/products/spaces — créer un Space `klassci-backups` en région `fra1` (proche Côte d'Ivoire)
2. Générer une **Spaces access key** (Settings → API → Spaces Keys)
3. Noter `access_key_id` + `secret_access_key`

### b. Installer + configurer rclone

```bash
sudo apt install -y rclone curl
rclone config
```

Réponses :
- `n` (New remote)
- name : `do-spaces`
- type : `s3`
- provider : `DigitalOcean`
- env_auth : `false`
- access_key_id : `<DO Spaces Access Key>`
- secret_access_key : `<DO Spaces Secret>`
- region : (vide)
- endpoint : `fra1.digitaloceanspaces.com`
- location_constraint : (vide)
- acl : `private`
- server_side_encryption : (vide)
- storage_class : (vide)

Vérifier : `rclone lsd do-spaces:` doit lister les Spaces.

### c. Activer dans backup.env

```bash
sudo tee -a /etc/klassci/backup.env > /dev/null <<EOF
RCLONE_REMOTE=do-spaces
SPACES_BUCKET=klassci-backups
EOF
```

### d. Tester

```bash
sudo systemctl start backup-mysql.service
sudo journalctl -u backup-mysql.service -n 50
rclone ls do-spaces:klassci-backups/daily/
```

### e. Lifecycle rules (rétention auto S3)

Sur DO Spaces Console :
- `daily/` → expire après 7 jours
- `weekly/` → expire après 28 jours
- `monthly/` → expire après 365 jours

Ou via `s3cmd` (cf section "Configuration avancée" plus bas).

---

## Activer Tier 3 — Alerting Healthchecks.io (recommandé avant beta)

### a. Compte + 2 checks

1. https://healthchecks.io/ — créer un compte (gratuit, 20 checks)
2. Créer **2 checks** :
   - `klassci-backup-daily` — schedule cron `0 2 * * *`, grace 30 min
   - `klassci-restore-test` — schedule cron `0 3 * * 0`, grace 60 min
3. Copier les 2 UUIDs (visibles dans le check details URL : `https://hc-ping.com/<UUID>`)
4. Configurer notification email/Slack/Discord sur ton compte

### b. Activer dans backup.env

```bash
sudo tee -a /etc/klassci/backup.env > /dev/null <<EOF
HEALTHCHECKS_BACKUP_UUID=00000000-0000-0000-0000-000000000000
HEALTHCHECKS_RESTORE_UUID=11111111-1111-1111-1111-111111111111
EOF
```

### c. Tester le ping

```bash
sudo systemctl start backup-mysql.service
# Vérifier sur https://healthchecks.io que le check est passé "up"
```

---

## Opérations courantes

### Voir les logs du dernier backup
```bash
sudo journalctl -u backup-mysql.service -n 200
```

### Déclencher un backup immédiatement
```bash
sudo systemctl start backup-mysql.service
```

### Lister les backups locaux
```bash
ls -lh /home/ubuntu/klassci/backups/{daily,weekly,monthly}/ 2>/dev/null
```

### Lister les backups S3 (si Tier 2 actif)
```bash
rclone lsf do-spaces:klassci-backups/daily/
rclone lsf do-spaces:klassci-backups/weekly/
rclone lsf do-spaces:klassci-backups/monthly/
```

### Restore manuel d'une DB tenant en cas de crash

```bash
# 1. Trouver le backup
ls -t /home/ubuntu/klassci/backups/daily/  # plus récent en premier

# 2. Extract dans /tmp
mkdir -p /tmp/restore && cd /tmp/restore
tar -xzf /home/ubuntu/klassci/backups/daily/klassci-mysql-*.tar.gz

# 3. Restore (attention : écrase les données existantes !)
docker exec -i -e MYSQL_PWD=<password> klassci-mysql \
  mysql -uroot < dumps/local.sql

# 4. Restore sous un autre nom (sans écraser)
sed 's/`local`/`local_restored`/g' dumps/local.sql \
  | docker exec -i -e MYSQL_PWD=<password> klassci-mysql mysql -uroot
```

---

## Rétention

### Locale (Tier 1)
| Tier | Schedule | Rétention |
|------|----------|-----------|
| daily | tous les jours | 7 jours |
| weekly | dimanche | 28 jours |
| monthly | 1er du mois | 365 jours |

Tailles attendues (estimation pour 1 tenant `local` avec ~100 élèves) : ~5 MB par dump compressé. Sur 1 an avec rétention complète : ~250 MB.

### Off-site (Tier 2)
Configurer les **lifecycle rules** sur DO Spaces (à faire une seule fois) :

```xml
<LifecycleConfiguration>
  <Rule><ID>DailyRetention</ID><Filter><Prefix>daily/</Prefix></Filter><Status>Enabled</Status><Expiration><Days>7</Days></Expiration></Rule>
  <Rule><ID>WeeklyRetention</ID><Filter><Prefix>weekly/</Prefix></Filter><Status>Enabled</Status><Expiration><Days>28</Days></Expiration></Rule>
  <Rule><ID>MonthlyRetention</ID><Filter><Prefix>monthly/</Prefix></Filter><Status>Enabled</Status><Expiration><Days>365</Days></Expiration></Rule>
</LifecycleConfiguration>
```

Application via la console DO Spaces ou `s3cmd setlifecycle`.

---

## Coûts estimés (Tier complet)

- **Local** : 0 (disque EC2 existant, ~250 MB/an pour 1 tenant)
- **DO Spaces** : 5 USD/mois pour 250 GB
- **Healthchecks.io** : 0 (free tier 20 checks)
- **Total** : 5 USD/mois pour Tier 2+3

---

## Sécurité

- `/etc/klassci/backup.env` contient le mot de passe MySQL → permissions 600 root obligatoires
- Les dumps locaux sont dans `/home/ubuntu/klassci/backups/` (lecture user ubuntu uniquement)
- Les dumps Spaces sont en ACL `private` (auth requise)
- Le mot de passe MySQL transite via env var `MYSQL_PWD` (pas via argv → invisible dans `ps -ef`)
- TODO P1 : encrypter les dumps avec `age` avant upload (clé sur EC2 dans `/etc/klassci/age-keys.txt`)

---

## En cas d'alerte healthchecks (cron arrêté)

1. Vérifier que la VM EC2 est up : `ping 16.58.132.68`
2. SSH puis : `sudo systemctl status backup-mysql.timer`
3. Logs : `sudo journalctl -u backup-mysql.service --since="48 hours ago"`
4. Tester docker : `docker ps | grep klassci-mysql`
5. Tester accès MySQL : `docker exec -e MYSQL_PWD=<pwd> klassci-mysql mysql -uroot -e "SHOW DATABASES;"`
6. Si tout OK techniquement, déclencher manuellement : `sudo systemctl start backup-mysql.service`
