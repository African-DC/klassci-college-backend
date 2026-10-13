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
