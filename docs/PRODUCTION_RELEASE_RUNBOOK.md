# KLASSCI Collège — Plan de déploiement contrôlé (backend, frontend, tenants et données)

> État : plan à valider en préproduction. **Ce document n'autorise aucune action sur la production.** Les PR vers `main` restent en brouillon jusqu'au feu vert.

## 0. Architecture réellement observée dans le dépôt

- Dokploy Raw Compose existant, ID `TAOkd341U3KSlNL49VI1o` ; Dockerfile backend FastAPI Python 3.12, frontend Next.js/Node 20, worker et beat Celery ; MySQL 8.4 ; Redis 7.
- Variables images de la stack : `KLASSCI_BACKEND_IMAGE=klassci-college-backend:prod` et `KLASSCI_FRONTEND_IMAGE=klassci-college-frontend:prod`. GHCR n'est **pas** actuellement référencé par ces variables.
- Volumes **externes existants**, à préserver absolument : `linux_klassci_mysql`, `linux_klassci_redis`, `linux_klassci_uploads`. Ne jamais faire `docker compose down -v`, `docker volume prune` ni supprimer/remplacer ces volumes.
- Le proxy Caddy, MySQL, Redis et WOURI ne font pas partie de la mise à jour des images applicatives. Les services backend, worker et beat doivent utiliser le **même digest backend** ; le frontend a son propre digest.
- L'automatisation GHCR actuelle impose un `workflow_dispatch` explicite (`publish_image=true`). Le préflight Docker utilise `push: false` et ne livre rien.

## 1. Gate « source / image »

- PR approuvées et toutes les CI vertes **sur le dernier commit** : lint/type checks, tests backend, migration Alembic idempotence, sécurité, E2E frontend, build Docker.
- Figer les SHA Git de frontend/backend, puis les digest exacts des images GHCR une fois publiées manuellement ; éviter `:latest` et `:prod` comme seuls identifiants de retour arrière.
- Vérifier depuis le VPS que les images privées GHCR sont accessibles **sans laisser de token dans Compose** ; inventaire des images actuelles par digest et sauvegarde du Compose/.env existants dans un coffre sûr.
- Vérifier les mécanismes natifs Auto Deploy/webhooks de Dokploy : une vérification GitHub **ne suffit pas**. Désactiver toute voie parallèle non maîtrisée avant d'agir.

## 2. Gate « sauvegarde réellement restaurable »

- Maintenance préparée et verrou de déploiement **commun aux deux dépôts** ; arrêter les tâches planifiées/écritures applicatives pendant la fenêtre de sauvegarde cohérente.
- Inventorier toutes les bases tenant, versions Alembic, utilisateurs et comptes SQL, et les dossiers upload concernés ; comparer à la liste attendue des établissements. Une base absente doit bloquer la migration.
- Sauvegarder chaque base tenant, les comptes/configurations nécessaires, et `linux_klassci_uploads` ; sauvegarder également Compose, variables d'environnement de façon chiffrée et SHA/digests de la version précédente. Isoler et chiffrer les sauvegardes hors du VPS si possible.
- **Tester une restauration** des bases et fichiers sur une stack de recette dotée de volumes complètement indépendants. Vérifier les comptages lignes critiques (étudiants, inscriptions, versements, reçus), contrôles d'intégrité et échantillons de fichiers.
- Pas de feu vert si une restauration de bout en bout n'a pas fonctionné.

## 3. Gate « migrations » — priorité aux données

- La CLI `python -m app.cli.migrate_all head` **écrit directement** dans toutes les bases détectées, et continue éventuellement après une migration tenant échouée. **Ce n'est pas un dry-run.**
- Elle repère les tenants par quatre tables (`alembic_version`, `users`, `roles`, `academic_years`) ; vérifier son inventaire par rapport au registre réel. Elle refuse zéro tenant et exige le tenant local en production.
- Examiner chaque nouvelle révision Alembic, notamment DROP, RENAME, NOT NULL, index unique, backfill, contraintes, permissions ; tester d'abord sur copie restaurée représentative de **chaque tenant**.
- Contrôler la compatibilité ancien code / nouveau schéma : préférer expand → déployer → contract lors d'une livraison ultérieure. Ne pas exécuter de migration destructive sans fenêtre de maintenance et plan de récupération par restore.
- Pendant la vraie migration : maintenir les écritures arrêtées, n'exécuter qu'un seul migrateur, journaliser versions/tenant, bloquer la bascule si une migration échoue. Une migration MySQL partiellement appliquée exige investigation/restore : un simple rollback Git ne restaure **pas** le schéma.

## 4. Gate « préproduction »

- Construire les **mêmes** images immuables que la production et lancer une stack de recette isolée (DB, Redis, uploads, hostname, secrets différents, pas de worker qui consomme la queue de prod, aucun accès WOURI).
- Migrer les copies restaurées, redémarrer et tester `/health` FastAPI, l'ouverture des pages Next.js, login/logout, sélection du tenant et des domaines autorisés, cookies/session, `/svc` proxy, rôles/autorisations.
- Scénarios métier : inscriptions/réinscriptions, calcul des effectifs, paiements + reçu + historique + solde, exports enseignants/classes PDF/Word/Excel, uploads et téléchargement de fichiers, jobs Celery, planificateur beat et messages.
- Contrôler logs, erreurs Sentry, latence, migrations, ressources CPU/RAM/disque et connectivité entre conteneurs.
- Ne pas utiliser de données personnelles réelles en préproduction sans protections d'accès et minimisation.

## 5. Bascule de production — uniquement après approbation

1. Fenêtre de maintenance, contrôle d'Auto Deploy, verrou global, snapshot/sauvegardes vérifiés ; noter image/digest, Compose et statistiques pré-déploiement.
2. Stopper/mettre en pause les écritures et jobs si nécessaires ; sauvegarde cohérente finale ; migrations sur bases réelles **seulement après** test restauration et examen des révisions.
3. Appliquer une modification Compose minimale et ciblée aux images backend/worker/beat, puis frontend, sans changer les services MySQL, Redis, Caddy, volumes ou environnement.
4. Préférer une action service-scoped validée par la version Docker/Dokploy en place, plutôt qu'un `compose.deploy` aveugle de la stack Raw. Contrôler `config` et le diff avant mutation ; ne pas écraser le `.env` intégral.
5. Vérifier la santé réelle (FastAPI, Next.js, sessions, jobs, files, paiement en lecture/test contrôlé), puis lever la maintenance. Surveiller erreurs, saturation et tâches jusqu'à stabilisation.

## 6. Critères GO / NO-GO et retour arrière

**GO :** CI totalement vertes, image digest prouvé, Auto Deploy connu, sauvegardes et restaurations réussies, inventaire tenants complet, migrations testées, recette métier passée, rollback répété, responsable de validation identifié.

**NO-GO :** tenant manquant, migration non testée, volume inaccessible, GHCR non accessible, outil/proxy non contrôlé, test de login/paiement en échec, ressources VPS insuffisantes, sauvegarde non restaurable.

**Rollback applicatif :** rétablir digest, variables/Compose et conteneurs applicatifs précédents **sans toucher aux volumes** si ancien code compatible avec nouveau schéma. **Rollback données :** procédure de restauration sur décision explicite, en évitant d'écraser les écritures survenues après la sauvegarde ; jamais de `alembic downgrade` aveugle.

## 7. Preuves de livraison à archiver

- PR, SHA backend/frontend, digest d'image, résultats CI, capture du diff Compose, versions Alembic **par tenant**, manifestes et tests de restauration, statut des health checks, captures anonymisées des scénarios métier, journaux d'incident éventuel, dates et autorisation GO.

Sources :
- https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments
- https://docs.docker.com/compose/how-tos/startup-order/
- https://docs.dokploy.com/docs/core/docker-compose


## 8. Exécution manuelle vérifiable — stack Raw Compose *réellement en place*

> **Ne pas exécuter cette section avant GO.** Ce n'est pas une automatisation et elle ne remplace pas la validation humaine des sauvegardes et des migrations.

### 8.1 Préflight à lecture seule (VPS Contabo)

Connecter avec la configuration SSH du dépôt : `ssh -F deploy/ssh_config klassci-prod`. La stack Dokploy Raw est stockée sous `/etc/dokploy/compose/klassci-college-prod/code` ; les sources backend et frontend sont respectivement sous `/opt/apps/klassci-college/src/backend` et `/opt/apps/klassci-college/src/frontend`.

Avant toute action, vérifier le *véritable* projet et la configuration Compose effective : ne pas supposer que le nom du répertoire, la configuration du dépôt et celle du serveur sont identiques.

```bash
docker compose ls
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker volume inspect linux_klassci_mysql linux_klassci_redis linux_klassci_uploads
docker image inspect klassci-college-backend:prod klassci-college-frontend:prod \
  --format '{{.RepoTags}} {{.Id}} {{.Created}}'
docker system df
df -h
cd /opt/apps/klassci-college/src/backend && git status --short && git rev-parse HEAD
cd /opt/apps/klassci-college/src/frontend && git status --short && git rev-parse HEAD
```

Consigner les informations **sans recopier les secrets** et sans diffuser la sortie d'un `docker compose config` non masqué ; utiliser `docker compose config --quiet` après avoir repéré le fichier exact et les variables réellement chargées par Dokploy. Vérifier qu'aucun autre service n'écrit dans la DB partagée et que le webhook Dokploy exposé auparavant a été régénéré.

### 8.2 Sauvegardes et modèle de récupération

Une sauvegarde hors VPS a été déclarée par l'exploitant. Son existence n'est **pas** la preuve de sa restaurabilité. Confirmer sa date, ses journaux de succès, l'inventaire complet des bases tenant (notamment `local` et `rostan-bouake`), les uploads, la conservation, l'accès depuis une autre machine et un essai de restauration isolé. Une copie brute « à chaud » de `/var/lib/mysql` n'est pas assimilable automatiquement à un snapshot SQL cohérent. Pour les tables InnoDB, `mysqldump --single-transaction --quick` est une possibilité documentée par MySQL ; empêcher les DDL concurrents pendant l'opération.

Les backups de volumes Dokploy pourront compléter la sauvegarde existante, mais la livraison ne dépend pas de la marque du logiciel utilisé : elle dépend d'une restauration indépendante réussie et des trois volumes `linux_klassci_*` préservés.

### 8.3 Préparer et basculer **uniquement** les applications

Après fusion des deux `main` en commits coordonnés et essais Windows réussis : relever la référence exacte actuellement exécutée, sauvegarder le Compose et le `.env` chiffrés hors du dossier public ; vérifier `git status --short`, puis `git pull --ff-only` sur les deux sources de `main` (ne pas forcer si divergence locale). Taguer **avant le build** les deux images actives en `:rollback-<timestamp>` (même timestamp).

Élaborer les images applicatives à partir des commits figés. Vérifier que le frontend embarque `NEXT_PUBLIC_API_URL=/svc` **au build** (dans le Dockerfile actuel) ; les variables `NEXT_PUBLIC_*` sont incorporées dans le bundle Next.js, une variable runtime ne corrige pas un build erroné. Vérifier les image IDs résultants et ne modifier ni `MYSQL_*`, ni `REDIS_URL`, ni `UPLOAD_ROOT`, ni les définitions de volumes. Le Compose versionné comporte notamment un sas `HANDOFF_ROOT` qui doit être rapproché du Compose Raw effectivement utilisé : **ne pas remplacer intégralement le Compose Raw par le fichier Git**.

Exécuter `python -m app.cli.migrate_all head` **uniquement si des révisions nouvelles l'exigent**, après test sur DB restaurées, pause des écritures et contrôle de tous les tenants attendus. Ne jamais invoquer `downgrade` automatiquement.

Depuis le **bon dossier Compose** et avec le **même nom de projet** que les conteneurs existants, employer une opération ciblée telle que :

```bash
# EXEMPLAR : ne pas lancer sans vérifier la CLI, le projet et le fichier effectifs.
docker compose -p klassci-college-prod up -d --no-deps --wait backend
docker compose -p klassci-college-prod up -d --no-deps --wait worker beat
docker compose -p klassci-college-prod up -d --no-deps --wait frontend
```

`--no-deps` évite le redémarrage des services dépendants ; `--wait` assure running/healthy suivant l'existence d'un healthcheck mais **pas** la bonne exécution métier. Aucune commande `compose down`, `-v`, `prune`, `--remove-orphans` ni remplacement global du `.env`.

### 8.4 Validation et décision de retour arrière

Contrôler `https://college.klassci.com/svc/health` et `https://college.klassci.com/login` puis, depuis le bon compte tenant, tester l'authentification, les permissions, une classe courante, l'export PDF/Word/Excel, une inscription passée payée aujourd'hui, le bordereau jour, l'export des versements avec recherche/catégorie, l'historique de paiements et le rapprochement des totaux. Vérifier worker via `celery -A app.core.celery_app inspect ping` **en lecture seule**, tâches actives/réservées, logs du beat et erreurs pendant la fenêtre de surveillance. Contrôler le statut des 7 conteneurs et les versions Alembic des tenants.

Si les contrôles échouent : stopper la livraison, consigner l'incident et remettre **uniquement** les tags/digests applicatifs précédents si l'ancien code est compatible avec les migrations déjà exécutées. Un rollback des images ne restaure **jamais** automatiquement les lignes MySQL ni les documents supprimés.

### 8.5 Démo Windows (distincte de la production Linux)

La démo est un déploiement **natif Windows**, sans Docker Linux : `ssh -F deploy/ssh_config klassci`, serveur `94.72.96.119`, `https://college-demo.klassci.com`. Préparer archives des deux commits depuis le poste de build, sauvegarder puis copier/extraitre dans `C:\klassci\backend` et `C:\klassci\frontend`. Pour les scripts Python utiliser `py` (pas `python3`). N'exécuter des migrations que si requises et avec sauvegarde testée. Lancer `C:\klassci-deploy\frontend-build.ps1`, redémarrer les services NSSM `klassci-backend` et `klassci-frontend`, contrôler logs Windows et faire passer la matrice de tests métier avant autorisation Contabo.

**Sources techniques** :
- https://docs.docker.com/reference/cli/docker/compose/up/
- https://docs.dokploy.com/docs/core/docker-compose
- https://dev.mysql.com/doc/refman/8.4/en/mysqldump.html
- https://docs.celeryq.dev/en/stable/userguide/monitoring.html

## Gate 0 bis — inventaire Docker sans modification (Contabo uniquement)

Avant de livrer, exécuter **sur le VPS Linux** le diagnostic du dépôt. Il n'appelle
que `docker ps`, `docker inspect`, `docker volume ls` et une lecture de
l'espace disque ; aucun `docker exec`, build, migration, restart, `compose up`
ou écriture de fichiers. Il masque les variables d'environnement et les secrets.

```bash
# Depuis la source backend à jour du commit à auditer (jamais depuis un ZIP inconnu).
cd /opt/apps/klassci-college/src/backend
python3 deploy/linux/preflight_readonly.py --project klassci-college-prod
```

Vérifier d'abord le vrai nom Docker Compose du projet via `docker compose ls` ;
si différent, le fournir explicitement à `--project`. La sortie lisible signale
les sept services, l'état des trois volumes externes, la cohérence des images
backend/worker/beat, les mounts des uploads et le statut des healthchecks.
`--json` produit un rapport structuré filtré pouvant être archivé dans un
espace privé, **sans** y copier de `.env`, dump SQL ni logs sensibles.

**Code retour non nul = NO-GO Docker. Code retour zéro ≠ GO de livraison.**
Ce diagnostic ne démontre ni l'intégrité des données, ni la restauration des
backups externes, ni la bonne configuration du webhook Dokploy, ni le succès
des scénarios d'inscription/paiement/export. Ces étapes restent obligatoires.

Sur la stack Raw fournie, le volume `klassci_handoff` n'est pas monté ;
le diagnostic émet un avertissement non destructif. Examiner les fonctions
de dépôt de photo et la copie effective du Compose avant d'ajouter un volume ;
ne jamais copier intégralement `docker-compose.dokploy.yml` par-dessus le Raw.
