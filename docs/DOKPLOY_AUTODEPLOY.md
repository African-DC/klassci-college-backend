# KLASSCI Collège — Dokploy + GitHub Actions (sans SSH)

## État actuel

La production existante est une stack Dokploy Docker Compose **Raw**, identifiant
`TAOkd341U3KSlNL49VI1o`, avec les images locales :

- `KLASSCI_FRONTEND_IMAGE=klassci-college-frontend:prod`
- `KLASSCI_BACKEND_IMAGE=klassci-college-backend:prod` (également worker et beat)

Le Compose de production contient les volumes EXTERNES
`linux_klassci_mysql`, `linux_klassci_redis`,
`linux_klassci_uploads`. Ne jamais les remplacer, supprimer ou monter dans
une stack de test. WOURI tourne aussi sur le VPS, hors du périmètre.

**Aucun compte Contabo ni clé SSH opérationnelle n'est disponible.** L'accès
utilisateur passe par Dokploy et Portainer. Le secret `DOKPLOY_API_KEY` est
présent dans l'environnement GitHub `production` des deux dépôts, mais
NE doit jamais apparaître dans des logs ou captures.

## Phase préparée dans cette PR (aucune mutation en production)

`.github/workflows/production-release.yml`:

1. valide la présence du Dockerfile sur les PR vers develop, staging et main ;
2. après un push vers main, construit et publie l'image de ce dépôt avec un
   identifiant immuable `git-<SHA>` dans GHCR ;
3. sur déclenchement manuel (workflow_dispatch, main seulement), effectue
   un **GET en lecture seule** de `compose.one` avec la clé API Dokploy stockée
   dans GitHub Environment production ;
4. n'exécute PAS `compose.deploy`, `compose.redeploy`,
   `compose.saveEnvironment`, de migration ni de redémarrage de service.

Tags publiés (après que la PR a traversé develop, staging et main) :

- frontend : `ghcr.io/african-dc/klassci-college-frontend:git-<SHA>`
- backend : `ghcr.io/african-dc/klassci-college-backend:git-<SHA>`

Les packages GHCR peuvent être **privés par défaut** : leur visibilité et le
droit de pull sur Contabo doivent être vérifiés avant de changer le Compose
de production. Ne jamais publier un token GitHub dans un fichier Compose.

## Pourquoi l'API ne suffit pas encore

Dokploy sait lire / mettre à jour la configuration Compose, enregistrer son
environnement et relancer la stack. Mais un redéploiement d'images locales
`klassci-college-*:prod` **ne reconstruit pas** automatiquement le frontend
ou backend depuis les deux dépôts GitHub indépendants.

Déclencher `compose.deploy` directement sur cette stack Raw sans nouvelle image
effectivement accessible ne ferait qu'utiliser l'ancienne version (ou relancer
inutilement les services). Et une mise à jour de la configuration qui remplacerait
le `.env` entier risquerait les secrets et les changements concurrents.

## Conditions requises avant livraison automatique

- Vérifier depuis Dokploy/Portainer que Contabo peut tirer les images GHCR,
  notamment si elles restent privées : configurer une authentification registry
  côté serveur sans mettre le token dans les dépôts.
- Confirmer une stratégie pour mettre à jour **seulement** le frontend ou
  `backend + worker + beat` dans le Compose actif sans redémarrer MySQL,
  Redis ni le proxy et sans course entre les deux dépôts.
- Prévoir un verrou partagé entre les deux dépôts au niveau d'un orchestrateur
  unique ; les groupes GitHub concurrency des dépôts sont indépendants.
- Sauvegarder toutes les bases de tous les établissements ; vérifier une
  restauration sur des volumes et DBs **indépendants**.
- Avant une livraison backend, exécuter
  `python -m app.cli.migrate_all head` via la **nouvelle** image dans un
  job/runner contrôlé, en prévoyant une revue pour les migrations destructives.
  Certaines opérations DDL MySQL ne s'annulent pas par rollback.
- Ajouter contrôle de santé et restauration de l'image précédente (le schéma
  migré, lui, ne doit jamais être « downgradé » automatiquement).
- Effectuer au moins une livraison de recette et documenter les résultats.

## Configuration GitHub

Chaque dépôt : `Settings > Environments > production` :
- secret : `DOKPLOY_API_KEY` (déjà renseigné manuellement) ;
- limiter l'environnement aux branches `main` ;
- pas besoin de SSH GitHub Actions dans cette phase.

Actions > `KLASSCI College release preparation` sur main > Run workflow :
le job `dokploy-readonly-check` interroge seulement les métadonnées de la
stack. Ne pas copier sa réponse brute, car elle pourrait inclure des variables
d'environnement.

Ne **pas** activer de redéploiement natif Dokploy en parallèle des futurs
workflows GitHub Actions tant que l'orchestration n'est pas validée.

## Références

- https://docs.dokploy.com/docs/api/compose
- https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- https://docs.dokploy.com/docs/core/docker-compose
