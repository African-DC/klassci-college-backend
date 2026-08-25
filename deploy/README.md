# KLASSCI College · Déploiement serveur (démo Windows)

> **Ce dossier est versionné depuis le 2026-08-25.** Il ne l'était nulle part
> auparavant : la configuration de la production n'existait que sur un poste de
> développement. Un incident sur cette machine aurait emporté le seul exemplaire
> du `docker-compose` de production et des scripts de la démo.
>
> **Ce qui est ici** : la forme de l'infrastructure — compose, Caddyfile,
> scripts de déploiement, amorçage MySQL en gabarit, seed de démo.
>
> **Ce qui n'y est pas, et ne doit pas y venir** : `deploy/.secrets.env`, les
> clés SSH, `deploy/server/mysql-setup.sql` une fois rempli. Le `.gitignore`
> de ce dossier les écarte. Les valeurs vivent sur le poste et dans les
> variables d'environnement des services.
>
> **Ce qui est resté sur le poste, délibérément** : les sondes de diagnostic
> (`linux/_*.py`), les captures d'écran de tests et les vidages JSON d'une
> session. Utiles sur le moment, trompeurs six mois plus tard.

Déploiement **natif Windows** du backend FastAPI + frontend Next.js sur le
serveur de **démo** `94.72.96.119` (Windows Server 2022). Mono-tenant (`local`).

> La **production** vise le VPS Contabo Linux `169.58.156.206`
> (https://college.klassci.com) : jusqu'a 24 Go RAM, Dokploy klassci-college-prod. docker build autorise sur l'hote, puis recreate du service. Stack live : /etc/dokploy/compose/klassci-college-prod/code.
>
> L'ancienne EC2 Linux (`16.58.132.68`) n'existe plus. Ne plus l'utiliser.
>
> SSH prod : `ssh -F deploy/ssh_config klassci-prod` (user `marcel`).
> Ne jamais coller de mot de passe dans ce dépôt.

> La demo Windows reste native (pas de Docker Linux sur ce VPS Windows).
> Le Contabo Linux tourne Dokploy + Docker, 24 Go RAM, build autorise.

## Production Contabo (live)

Stack Docker Compose geree par Dokploy (projet klassci-college, env production, app klassci-college-prod).

- IP : 169.58.156.206
- Domaine HTTPS : https://college.klassci.com (Traefik + Let's Encrypt)
- Probe : https://college.klassci.com/login et https://college.klassci.com/svc/health
- IP brute : http://169.58.156.206/login
- Caddy interne (/svc -> backend, reste -> frontend), labels Traefik sur le service proxy
- Fichiers Dokploy : /etc/dokploy/compose/klassci-college-prod/code/
- Volumes existants : linux_klassci_mysql, linux_klassci_redis (ne pas recreer, jamais down -v)
- Superadmin plateforme : tenant local, email superadmin@klassci.com
- Premier etablissement : 
- Premier etablissement : rostan-bouake (College Rostan Bouake)
- Login tenant : https://college.klassci.com/login?c=rostan-bouake
- Login ecole simple : https://college.klassci.com/login + code ROSTAN
- Build : autorise sur Contabo (24 Go). Jamais down -v. Ne pas toucher Wourri.
- Credentials Rostan : /opt/apps/klassci-college/deploy/linux/.rostan-credentials.json (chmod 600, hors git)
- UI Dokploy : https://dokploy.africandigitconsulting.com projet klassci-college
- Wourri tourne sur le meme VPS : ne pas y toucher.
- Demo Windows : 94.72.96.119 reste la cible de presentation/E2E, plus le domaine public.

`ash
ssh -F deploy/ssh_config klassci-prod
docker ps --filter name=klassci-college-prod
`

## Serveur

| | |
|---|---|
| IP publique | `94.72.96.119` |
| OS | Windows Server 2022 Datacenter (build 20348) |
| Specs | 6 vCPU AMD EPYC, 12 Go RAM, 200 Go disque |
| RDP | `administrator` / (mot de passe — voir gestionnaire de secrets) |
| Hostname | `vmi3307378` |

## Accès SSH (depuis le poste de dev)

Clé dédiée : `deploy/.ssh/klassci_deploy` (+ `.pub`). Config : `deploy/ssh_config`.

```bash
cd ~/Downloads/dev/klassci-college
ssh -F deploy/ssh_config klassci            # shell PowerShell distant
scp -F deploy/ssh_config -i deploy/.ssh/klassci_deploy fichier klassci:C:/chemin/
```

La clé publique est dans `C:\ProgramData\ssh\administrators_authorized_keys` sur
le serveur. Shell SSH par défaut = PowerShell. SSH démarre au boot (auto).

## Architecture déployée

```
Navigateur ──http://94.72.96.119:80──> Caddy (reverse proxy)
                                          ├─ /svc/*  → strip → 127.0.0.1:8000  (FastAPI / uvicorn)
                                          └─ /*      →         127.0.0.1:3000  (Next.js standalone)

FastAPI ──> MySQL 9.6 (127.0.0.1:3306, DB `local`)  +  Memurai/Redis (127.0.0.1:6379)
```

- Le backend résout le tenant `local` automatiquement (Host = IP numérique).
- Le frontend appelle le backend via `NEXT_PUBLIC_API_URL=http://94.72.96.119/svc`
  (préfixe `/svc` pour ne pas entrer en collision avec `/api/auth/*` de NextAuth).

## Services Windows (NSSM)

| Service | Rôle | Commande |
|---|---|---|
| `klassci-backend` | uvicorn FastAPI :8000 | `python -m uvicorn app.main:app` |
| `klassci-frontend` | Next.js standalone :3000 | `node .next/standalone/server.js` |
| `klassci-caddy` | reverse proxy :80 | `caddy run --config Caddyfile` |
| `MySQL` | base de données | service choco |
| `Memurai` | Redis | service |
| `klassci-celery` | worker async (PDF/email) — *à ajouter* | `celery -A app.core.celery_app worker --pool=solo` |

Gestion :
```powershell
Get-Service klassci-*
nssm restart klassci-backend
Get-Content C:\klassci\logs\backend.err.log -Tail 50
```

## Emplacements sur le serveur

```
C:\klassci\backend\          code backend + venv + .env
C:\klassci\frontend\         code frontend + node_modules + .next\standalone
C:\klassci\deploy\Caddyfile  config reverse proxy
C:\klassci\logs\             logs des services (rotation 10 Mo)
C:\klassci-deploy\           scripts de provisioning (.ps1)
```

## Comptes de démo (tenant `local`) — mot de passe `Admin@2026`

| Email | Rôle |
|---|---|
| admin@klassci.com | admin |
| prof@klassci.com | teacher |
| eleve@klassci.com | student |
| parent.kone@klassci.com | parent |

## Secrets

Tous générés et stockés dans `deploy/.secrets.env` (gitignored, côté poste de dev) :
MySQL root, user applicatif `klassci`, `SECRET_KEY` backend, `NEXTAUTH_SECRET`.

## Re-déploiement (mise à jour du code)

```bash
# 1. Repackager + envoyer (depuis le poste de dev)
cd ~/Downloads/dev/klassci-college
tar -czf deploy/dist/backend.tgz  --exclude=venv --exclude=.git --exclude=__pycache__ -C klassci-backend .
tar -czf deploy/dist/frontend.tgz --exclude=node_modules --exclude=.next --exclude=.git -C klassci-frontend .
scp -F deploy/ssh_config -i deploy/.ssh/klassci_deploy deploy/dist/backend.tgz  klassci:C:/klassci/backend.tgz
scp -F deploy/ssh_config -i deploy/.ssh/klassci_deploy deploy/dist/frontend.tgz klassci:C:/klassci/frontend.tgz

# 2. Sur le serveur : extraire, migrer, rebuild, restart
ssh -F deploy/ssh_config klassci 'tar -xzf C:\klassci\backend.tgz -C C:\klassci\backend'
ssh -F deploy/ssh_config klassci 'powershell -File C:\klassci-deploy\migrate-seed.ps1'   # si nouvelles migrations
ssh -F deploy/ssh_config klassci 'nssm restart klassci-backend'
ssh -F deploy/ssh_config klassci 'tar -xzf C:\klassci\frontend.tgz -C C:\klassci\frontend'
ssh -F deploy/ssh_config klassci 'powershell -File C:\klassci-deploy\frontend-build.ps1'
ssh -F deploy/ssh_config klassci 'nssm restart klassci-frontend'
```

## Pièges résolus pendant le déploiement

1. **WSL2/Docker impossible** (Contabo, pas de nested virt) → natif Windows.
2. **PyMySQL 1.2.0** (dép transitive non épinglée) casse `aiomysql.ping()` →
   `pip install PyMySQL==1.1.1`. À épingler dans `requirements.txt`.
3. **WeasyPrint** échoue à l'import sans GTK (mais import lazy → app boote ok).
   GTK runtime à installer pour les PDF (voir ci-dessous).
4. **pnpm 10 ERR_PNPM_IGNORED_BUILDS** (sharp/esbuild) → non bloquant pour
   `next build` (Next utilise SWC). Build tolérant à ce code de sortie.
5. **NextAuth `/api/auth/*`** entre en collision si backend proxifié sous `/api`
   → backend sous `/svc`.
6. **Logo/favicon absents** : le tar initial avait `--exclude='*.png'` (pour les
   screenshots) ce qui a aussi exclu `public/images/logo_klassci.png`. Ne PAS
   exclure les png de `public/`. favicon.ico généré via Pillow, ajouté au repo.
7. **`next start` énumère `public/` au boot** : tout asset ajouté à chaud n'est
   servi qu'après `nssm restart klassci-frontend`.
8. **HTTPS — horloge serveur** : le VPS avait ~14h de retard → Node (undici) jugeait
   le cert Let's Encrypt `CERT_NOT_YET_VALID` → login NextAuth serveur cassé.
   Fix : `w32tm /config /manualpeerlist:"time.windows.com,0x8 pool.ntp.org,0x8 time.google.com,0x8" /syncfromflags:manual /reliable:yes /update` + restart w32time. w32time en auto-start.
9. **HTTPS — env NSSM frontend** : les vars runtime (`NEXTAUTH_URL`/`AUTH_URL`) sont
   dans l'`AppEnvironmentExtra` NSSM ET écrasent `.env.local`. Les passer en `https://...`
   au moment de la bascule (sinon NextAuth se croit en HTTP → cookies non-sécurisés).

10. **WeasyPrint 69 ne trouve plus GTK seul** (2026-08-25). Après la montée
    62.3 → 69.0, tous les documents officiels tombaient en 500 :
    `OSError: cannot load library 'C:\gtk3\$_63_\libgobject-2.0-0.dll': error 0x7e`.
    `0x7e` = ERROR_MOD_NOT_FOUND : la DLL nommée est trouvée, c'est **une de ses
    dépendances** qui manque. WeasyPrint 69 s'appuie sur `os.add_dll_directory`,
    qui ne lit que `WEASYPRINT_DLL_DIRECTORIES` et plus le `PATH` machine.
    La 62.3 s'en contentait.

    Correctif — sur le service NSSM `klassci-backend` :

    ```
    WEASYPRINT_DLL_DIRECTORIES=C:\gtk3\$_63_
    ```

    Le poser depuis bash échoue **en silence** : PowerShell mange `$_`. Passer
    par un script sur le serveur qui localise le dossier lui-même :

    ```powershell
    $gtk = (Get-ChildItem C:\gtk3 -Recurse -Filter "libgobject-2.0-0.dll" |
            Select-Object -First 1).DirectoryName
    & nssm set klassci-backend AppEnvironmentExtra "WEASYPRINT_DLL_DIRECTORIES=$gtk"
    ```

    La CI ne peut pas voir ce piège : elle tourne sous Linux, où `ldconfig`
    résout GTK et où `os.add_dll_directory` n'existe pas. **Après toute montée
    de WeasyPrint, régénérer un reçu et un bulletin sur la démo et les
    regarder**, plutôt que de lire le vert de la CI. La production Contabo est
    Linux et n'est pas concernée — vérifié en rendant un PDF dans son image.

## Éprouver une restauration, sans toucher à la production

Vérifier que ce dossier reconstruit un système qui marche demande de le monter
pour de vrai. Deux pièges rendent l'exercice dangereux, et tous deux ont été
rencontrés le 2026-08-25 :

**Les volumes.** Ils étaient épinglés à `linux_klassci_*` en dur : une seconde
pile s'attachait donc aux données de la production. Le premier essai a échoué
sur `Unable to lock ./ibdata1`, tenu par la production — et ce refus était la
chance. Production arrêtée, la pile de test aurait démarré sur ses données et
réinitialisé le mot de passe applicatif avec le sien. Le préfixe est désormais
surchargeable, avec la production pour défaut.

**Le port.** Une surcharge Compose **concatène** les listes ; sans `!override`,
le test réclame encore le 8088 de la production et échoue.

La séquence qui fonctionne :

```bash
D=~/restore-test-$(date +%s) && mkdir -p $D && cd $D
cp /chemin/deploy/linux/docker-compose.dokploy.yml docker-compose.yml
cp /chemin/deploy/linux/Caddyfile .
# Un .env aux valeurs JETABLES — jamais celles de la production.
printf 'services:
  proxy:
    ports: !override
      - "8099:80"
' > docker-compose.override.yml
for v in mysql redis uploads; do docker volume create restoretest_klassci_$v; done
KLASSCI_VOLUME_PREFIX=restoretest docker compose -p restoretest up -d
curl -s -o /dev/null -w '%{http_code}
' http://127.0.0.1:8099/svc/health   # attendu : 200
```

Démontage — `down` **sans** `-v`, puis les volumes de test nommément :

```bash
KLASSCI_VOLUME_PREFIX=restoretest docker compose -p restoretest down
for v in mysql redis uploads; do docker volume rm restoretest_klassci_$v; done
```

Résultat du 2026-08-25 : sept services montés, backend et frontend en 200, les
volumes de production intacts et la production ininterrompue pendant l'exercice.

## Fidélité au serveur

Les fichiers de ce dossier doivent correspondre, à l'octet près, à ce que les
serveurs exécutent. Un exemplaire versionné qui a dérivé est pire que pas
d'exemplaire du tout : il inspire confiance et reconstruit autre chose.

La première synchronisation, le 2026-08-25, a trouvé que le compose versionné
**n'avait pas le service `beat`** que la production fait tourner. Rebâtir depuis
le dépôt aurait donné un système où la fermeture nocturne des sessions de caisse
ne s'exécute jamais, sans que rien ne le signale.

Vérifier après toute modification côté serveur :

```bash
# Production : le compose et le Caddyfile
ssh -4 -F deploy/ssh_config klassci-prod "docker run --rm -v /etc/dokploy/compose/klassci-college-prod/code:/c:ro alpine sha256sum /c/docker-compose.yml /c/Caddyfile"
sha256sum deploy/linux/docker-compose.dokploy.yml deploy/linux/Caddyfile

# Demo : les scripts PowerShell
ssh -F deploy/ssh_config klassci "Get-ChildItem C:\klassci-deploy -Filter *.ps1 | ForEach-Object { $_.Name + ' ' + (Get-FileHash $_.FullName -Algorithm SHA256).Hash }"
sha256sum deploy/server/*.ps1
```

Les empreintes doivent coïncider. Un script présent sur le serveur et absent
d'ici est une pièce d'infrastructure qui n'existe qu'à un exemplaire.

## À finaliser (suivi)

- [x] **GTK runtime** pour WeasyPrint — extrait via 7-Zip (l'installeur GUI et
      innoextract échouent) dans `C:\gtk3`, bin ajouté au PATH machine,
      `FONTCONFIG_PATH=C:\gtk3\etc\fonts`. PDF testé OK (7 Ko, sans erreur fontconfig).
- [x] **Service Celery** (`klassci-celery`) — worker `--pool=solo`, connecté à Redis.
- [x] **Pare-feu 80** ouvert, accès externe `http://94.72.96.119` vérifié (login E2E OK).
- [x] **Domaine + HTTPS** : `college.klassci.com` → 94.72.96.119, Caddy auto-TLS
      Let's Encrypt actif. `flip-https.ps1` applique la bascule (CORS + rebuild FE
      sur le domaine + swap Caddyfile.https). Accès IP HTTP conservé en parallèle.
- [ ] **Multi-tenant par sous-domaine** : ajouter `*.college.klassci.com` (wildcard
      DNS + Caddy) quand on provisionnera plusieurs écoles.
- [ ] Épingler `PyMySQL==1.1.1` dans `requirements.txt` (fix upstream).
- [ ] Enrichir le tenant démo (année scolaire, niveaux, classes) via l'UI admin.
- [ ] Optionnel : rebuild sans `output: standalone` (on tourne en `next start`,
      le warning standalone est inoffensif).
```
