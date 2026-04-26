# Scripts d'opération KLASSCI College

Scripts shell pour les opérations critiques (backups, restore-test).

## Installation initiale sur EC2

### 1. Pré-requis système

```bash
sudo apt update
sudo apt install -y mysql-client curl rclone
```

### 2. Configurer rclone vers DigitalOcean Spaces

```bash
rclone config
# Choix : n (New remote)
# name  : do-spaces
# type  : s3
# provider : DigitalOcean
# env_auth : false
# access_key_id     : <DO Spaces Access Key>
# secret_access_key : <DO Spaces Secret>
# region   : (laisser vide)
# endpoint : fra1.digitaloceanspaces.com   (ou nyc3, sfo3, etc.)
# location_constraint : (laisser vide)
# acl : private
# server_side_encryption : (laisser vide)
# storage_class : (laisser vide)
```

Vérifier : `rclone lsd do-spaces:` doit lister tes Spaces.

Créer le bucket si pas existant : `rclone mkdir do-spaces:klassci-backups`

### 3. Configurer healthchecks.io (gratuit)

1. Aller sur https://healthchecks.io/, créer un compte
2. Créer **2 checks** :
   - `klassci-backup-daily` — schedule `0 2 * * *` (cron quotidien 02:00 UTC), grace 30min
   - `klassci-restore-test` — schedule `0 3 * * 0` (dimanche 03:00 UTC), grace 60min
3. Copier les 2 UUIDs (visibles dans le check details)
4. Configurer notification email sur ton compte

### 4. Installer la config

```bash
# Cloner le repo si pas déjà fait
cd /home/ubuntu/klassci/klassci-backend
git pull

# Créer le dossier de config
sudo mkdir -p /etc/klassci

# Copier l'exemple et éditer
sudo cp scripts/backup.env.example /etc/klassci/backup.env
sudo chmod 600 /etc/klassci/backup.env
sudo chown root:root /etc/klassci/backup.env
sudo nano /etc/klassci/backup.env
# → remplir MYSQL_ROOT_PASSWORD, HEALTHCHECKS_BACKUP_UUID, HEALTHCHECKS_RESTORE_UUID

# Rendre les scripts exécutables
chmod +x /home/ubuntu/klassci/klassci-backend/scripts/backup-mysql.sh
chmod +x /home/ubuntu/klassci/klassci-backend/scripts/restore-test.sh
```

### 5. Tester manuellement avant d'activer le timer

```bash
# Backup test (devrait afficher logs et pinguer healthchecks)
sudo KLASSCI_BACKUP_ENV=/etc/klassci/backup.env \
  /home/ubuntu/klassci/klassci-backend/scripts/backup-mysql.sh

# Vérifier que le fichier est bien dans Spaces
rclone ls do-spaces:klassci-backups/daily/

# Restore-test
sudo KLASSCI_BACKUP_ENV=/etc/klassci/backup.env \
  /home/ubuntu/klassci/klassci-backend/scripts/restore-test.sh
```

### 6. Installer les systemd units

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

## Opérations courantes

### Voir les logs du dernier backup
```bash
sudo journalctl -u backup-mysql.service -n 200
```

### Déclencher un backup immédiatement
```bash
sudo systemctl start backup-mysql.service
```

### Lister les backups dans Spaces
```bash
rclone lsf do-spaces:klassci-backups/daily/
rclone lsf do-spaces:klassci-backups/weekly/
rclone lsf do-spaces:klassci-backups/monthly/
```

### Restore manuel d'une DB tenant en cas de crash

```bash
# 1. Pull le backup
rclone copy do-spaces:klassci-backups/daily/klassci-mysql-20260426-020000.tar.gz /tmp/

# 2. Extract
tar -xzf /tmp/klassci-mysql-20260426-020000.tar.gz -C /tmp/

# 3. Restore une DB précise
mysql -u root -p < /tmp/dumps/local.sql

# Pour restorer sous un autre nom :
sed 's/local/local_restored/g' /tmp/dumps/local.sql | mysql -u root -p
```

## Rétention

Les fichiers sont organisés par tier dans le bucket :
- `daily/` — chaque jour (lifecycle rule : delete after 7 days)
- `weekly/` — chaque dimanche (lifecycle rule : delete after 28 days)
- `monthly/` — 1er du mois (lifecycle rule : delete after 365 days)

Les **lifecycle rules** sur DO Spaces sont à configurer **une seule fois** :

```bash
# Via s3cmd (à installer : pip install s3cmd)
# Configurer s3cmd avec les mêmes creds DO Spaces

s3cmd setlifecycle - <<'EOF' s3://klassci-backups
<LifecycleConfiguration>
  <Rule>
    <ID>DailyRetention</ID>
    <Filter><Prefix>daily/</Prefix></Filter>
    <Status>Enabled</Status>
    <Expiration><Days>7</Days></Expiration>
  </Rule>
  <Rule>
    <ID>WeeklyRetention</ID>
    <Filter><Prefix>weekly/</Prefix></Filter>
    <Status>Enabled</Status>
    <Expiration><Days>28</Days></Expiration>
  </Rule>
  <Rule>
    <ID>MonthlyRetention</ID>
    <Filter><Prefix>monthly/</Prefix></Filter>
    <Status>Enabled</Status>
    <Expiration><Days>365</Days></Expiration>
  </Rule>
</LifecycleConfiguration>
EOF
```

## Coûts estimés

- **DO Spaces** : 5 USD/mois pour 250 GB (largement suffisant pour ~50 tenants)
- **Healthchecks.io** : 0 USD (free tier 20 checks)
- **Total** : ~5 USD/mois

## En cas d'alerte healthchecks (cron arrêté)

1. Vérifier que la VM EC2 est up : `ping <EC2_IP>`
2. SSH puis : `sudo systemctl status backup-mysql.timer`
3. Logs : `sudo journalctl -u backup-mysql.service --since="48 hours ago"`
4. Tester rclone : `rclone lsd do-spaces:`
5. Tester MySQL : `mysql -u root -p -e "SHOW DATABASES;"`
6. Si tout OK techniquement, déclencher manuellement : `sudo systemctl start backup-mysql.service`

## Sécurité

- Le fichier `/etc/klassci/backup.env` contient le mot de passe MySQL root → permissions 600 obligatoires
- Les dumps sont stockés sur DO Spaces avec ACL `private` (auth requise pour lire)
- Le rclone remote utilise une access key DO Spaces dédiée (pas root account DO)
- TODO P1 : encrypter les dumps avec `age` avant upload (clé sur EC2 dans `/etc/klassci/age-keys.txt`)
