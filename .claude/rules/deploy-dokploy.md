---
paths:
  - "deploy/**"
  - "**/docker-compose*.yml"
  - "**/Dockerfile*"
---

# Regle Deploiement production · Dokploy sur Contabo

Complete `deploy.md`, qui reste la reference pour les deux cibles. Ce fichier
traite du seul point qui a fait perdre des semaines : **la production n'execute
pas le compose de ce depot**.

## Le piege central, a lire avant toute intervention

L'application `klassci-college-prod` est declaree dans Dokploy en mode
**`raw`** : Dokploy detient le texte du compose dans sa propre base Postgres et
l'ecrit sur le disque **a chaque deploiement**.

Consequences, dans les deux sens :

- Modifier `deploy/linux/docker-compose.dokploy.yml` ne change **rien** en production.
- Modifier `/etc/dokploy/compose/klassci-college-prod/code/docker-compose.yml`
  a la main tient jusqu'au prochain deploiement depuis l'interface, qui **ecrase**.

La seule modification durable passe par ce que Dokploy a en base : son
interface, ou son API. Le fichier sur disque n'est qu'une projection.

Deux fois le service `beat` et le montage des televersements ont disparu ainsi.
Rien ne tombe en panne quand ils partent : `beat` absent, les sessions de caisse
ne se cloturent plus la nuit et l'ecart s'accumule en silence ; volume absent,
le backend demarre vert et rend 404 sur chaque image.

## La bonne methode : l'API Dokploy

Generer un jeton dans l'interface, `/settings/profile`, section API/CLI. En-tete
documente : `x-api-key: <jeton>` (certains exemples montrent
`Authorization: Bearer <jeton>`, les deux circulent, `x-api-key` est celui de la
doc de reference).

| Endpoint | Methode | Usage |
|---|---|---|
| `/api/compose.one?composeId=...` | GET | Relire le compose stocke |
| `/api/compose.update` | POST | Ecrire `composeFile` et/ou `env` |
| `/api/compose.redeploy` | POST | Redeployer |

`composeId` de `klassci-college` : `TAOkd341U3KSlNL49VI1o` (identifiant non
secret, il ne donne acces a rien sans le jeton).

**Ou vit le jeton** : hors du depot. Ni dans un fichier versionne, ni dans un
message, ni dans un commit. Le README le dit deja : « Ne jamais coller de mot de
passe dans ce depot ». Le poser dans l'environnement de la session, le lire
depuis un gestionnaire de secrets, et ne jamais l'ecrire en clair dans une
commande qui finira dans l'historique du shell.

## Sequence de deploiement, dans l'ordre

```bash
# 1. Se connecter (cle uniquement, jamais de mot de passe en clair)
ssh -4 -F deploy/ssh_config klassci-prod          # user marcel, 169.58.156.206

# 2. Mettre les sources a jour sur l'hote
git -C /opt/apps/klassci-college/src/backend  pull --ff-only origin main
git -C /opt/apps/klassci-college/src/frontend pull --ff-only origin main

# 3. Construire les images SUR l'hote (24 Go, autorise). Le frontend est long :
#    le lancer detache, une deconnexion SSH tue un build attache.
cd /opt/apps/klassci-college/src/backend  && docker build -t klassci-college-backend:prod .
cd /opt/apps/klassci-college/src/frontend && nohup docker build -t klassci-college-frontend:prod . > /tmp/fe-build.log 2>&1 &

# 4. Sauvegarder le compose stocke AVANT de le changer
#    (via l'API compose.one, ou copie du fichier projete)

# 5. Mettre a jour le compose dans Dokploy (API), puis redeployer
```

Recreer service par service quand c'est possible, pour ne pas toucher aux bases :

```bash
docker compose -p klassci-college-prod up -d --no-deps --force-recreate backend
```

Un `up -d` global reevalue tout le projet et **recree aussi MySQL et Redis** si
leur empreinte de configuration differe. Les donnees survivent, les volumes sont
externes, mais c'est une coupure inutile sur une base client.

## Le frontend se reconstruit, il ne se redemarre pas

`NEXT_PUBLIC_*` est inline **a la construction de l'image**. Le Dockerfile fige
`NEXT_PUBLIC_API_URL=/svc`, une origine relative routee par Caddy vers le
backend. Un redemarrage ne prend donc rien en compte, il faut une vraie image.

Et les navigateurs gardent les anciens bundles, `Cache-Control: immutable` :
apres deploiement, verifier avec un rechargement force, Ctrl+Shift+R.

## Interdits

- `docker compose down -v` : jamais. `linux_klassci_uploads` porte le logo du
  client, `linux_klassci_mysql` porte toute sa base.
- Transformer un volume `external: true` en volume cree par le compose. Cela
  fabrique un volume neuf et vide a cote : rien n'est efface, tout devient hors
  de portee. C'est le pire des deux mondes, une donnee vivante que plus personne
  ne sert.
- Toucher au stack Wourri ni au LMS : d'autres produits vivent sur le meme VPS.
- `pnpm build` ou `next build` **dans** le conteneur frontend live.
- Toute adresse en `16.58.132.68` ou tout `ubuntu@` : cette infra est morte.
- Appliquer `deploy/linux/docker-compose.dokploy.yml` tel quel, voir ci-dessous.

## Le compose versionne n'est pas applicable tel quel

Constate le 2026-08-31. Il bind-monte le Caddyfile depuis
`/etc/dokploy/compose/klassci-college-prod/code/Caddyfile`, **fichier qui
n'existe pas sur l'hote** : Docker creerait un repertoire vide a ce chemin, Caddy
n'aurait plus de configuration et le site tomberait. En prime,
`deploy/linux/Caddyfile` commence par un BOM UTF-8 (`EF BB BF`).

Le compose execute, lui, embarque le Caddyfile en `configs:` inline, et les deux
configurations sont **semantiquement identiques**. Converger veut donc dire
importer ce qui manque, pas remplacer le fichier :

1. `UPLOAD_ROOT: /app/uploads` sur `backend` et sur `worker`
2. `klassci_uploads:/app/uploads` en volume sur `backend` et sur `worker`
3. le service `beat` (image backend, `celery -A app.core.celery_app beat`), sans volume
4. dans `volumes:` : `klassci_uploads` en `external: true`,
   `name: linux_klassci_uploads`

Valider avant d'appliquer, sans rien demarrer :

```bash
docker compose -f <fichier> --env-file .env config --services
```

## Verifications, dans cet ordre

La derniere est la seule qui prouve quelque chose. Les conteneurs peuvent
demarrer verts avec `/uploads` qui rend 404 sur tout : c'etait l'etat de la
production pendant des semaines.

```bash
# 1. Le volume existe et a garde son contenu
docker volume inspect linux_klassci_uploads
docker run --rm -v linux_klassci_uploads:/v:ro alpine find /v -type f

# 2. Le backend ET le worker montent bien ce volume
docker inspect --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{println}}{{end}}' \
  klassci-college-prod-backend-1

# 3. Le site repond
curl -o /dev/null -w '%{http_code}\n' https://college.klassci.com/login

# 4. LE test : un fichier reellement televerse est reellement servi.
#    L'URL en base est relative au backend, le public passe par /svc.
#    logo_url vaut par exemple /uploads/logos/rostan.jpg :
curl -o /dev/null -w '%{http_code} %{content_type}\n' \
  https://college.klassci.com/svc/uploads/logos/rostan.jpg
#    200 image/jpeg attendu. Un 404 sur /uploads/... sans /svc est NORMAL :
#    Caddy n'envoie au backend que /svc/*, et le front prefixe via getUploadUrl().

# 5. beat tourne
docker ps --filter name=klassci-college-prod --format '{{.Names}}\t{{.Status}}'

# 6. Aucune erreur d'upload au demarrage
docker logs klassci-college-prod-backend-1 2>&1 | grep -iE 'upload|traceback'
```

## Rollback

Les images portent des tags de repli (`rollback-<date>`). A defaut, `main` est
reconstructible : noter le commit de `main` **avant** deploiement, il suffit de
le rebattre et de reconstruire. Garder aussi la copie du compose stocke prise a
l'etape 4.

## Voir aussi

- `deploy.md` : cibles, patterns demo Windows et Contabo
- `deploy/README.md` : historique des deux derives compose, et pourquoi
- Doc API Dokploy : https://docs.dokploy.com/docs/api/reference-compose
