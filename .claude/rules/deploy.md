---
paths:
  - "scripts/**"
  - ".github/workflows/**"
  - "requirements*.txt"
  - "alembic/**"
  - "**/*.service"
  - "**/deploy*.sh"
  - "**/deploy*.md"
  - "**/Dockerfile*"
---

# Règle Déploiement — Jamais d'opération lourde sur EC2 prod

## La règle

**Aucune opération CPU/RAM-intensive ne doit s'exécuter sur EC2 16.58.132.68** tant que c'est l'unique serveur de prod KLASSCI College (t3.small, 2 vCPU, 2 GB RAM).

Côté backend, opérations lourdes typiques :
- `pip install -r requirements.txt` avec des wheels à compiler (cryptography, weasyprint, ortools, lxml…)
- `alembic upgrade head` qui touche des tables très larges
- Tests pytest avec coverage sur la suite complète
- Tâches Celery batch très lourdes (génération EDT OR-Tools sur 50+ classes)

Ces opérations doivent passer par CI ou un runner externe. Sur EC2 prod = uniquement `sudo systemctl restart klassci-backend` après pull du code + venv déjà prêt.

## Pourquoi

Sur t3.small (2 vCPU, 2 GB RAM), tout ce qui sature CPU :
- nginx ne sert plus les requêtes en temps acceptable
- SSH banner timeout
- Real users (ex: `102.209.220.136`, observé 2026-04-26) prennent 30 s+ sur `https://college.klassci.com/api/...`
- Récupération nécessite souvent `aws ec2 stop-instances --force` → 2-3 min de downtime additionnels

`pip install` qui compile cryptography from source = build lourd. Encore plus lourd que `next build` côté FE. Mêmes conséquences.

## Pattern acceptable — GitHub Actions (objectif S2)

```yaml
# .github/workflows/deploy-be.yml
name: Deploy BE
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: { python-version: "3.12", cache: pip }

      - name: Build wheelhouse
        run: |
          pip install --upgrade pip wheel
          pip wheel --wheel-dir=wheels -r requirements.txt
          tar czf wheels.tgz wheels/

      - name: Pack code
        run: tar czf code.tgz app alembic alembic.ini scripts requirements.txt

      - name: Ship + migrate + restart
        env:
          SSH_KEY: ${{ secrets.EC2_SSH_KEY }}
          HOST:    ${{ secrets.EC2_HOST }}
        run: |
          echo "$SSH_KEY" > /tmp/k && chmod 600 /tmp/k
          scp -i /tmp/k wheels.tgz code.tgz ubuntu@$HOST:/tmp/
          ssh -i /tmp/k ubuntu@$HOST '
            set -e
            cd /home/ubuntu/klassci/klassci-backend
            tar xzf /tmp/wheels.tgz -C /tmp/
            source .venv/bin/activate
            pip install --no-index --find-links=/tmp/wheels -r requirements.txt
            tar xzf /tmp/code.tgz
            alembic upgrade head
            sudo systemctl restart klassci-backend klassci-celery
            sleep 3
            curl -fsS http://localhost:8000/health > /dev/null || exit 1'
```

`pip install --no-index --find-links=/tmp/wheels` = aucune compilation côté EC2, juste un copier-coller de wheels précompilés.

Downtime perçu : <2 s (le restart uvicorn).

## Pattern de secours — Build wheels en local

Sur machine dev Linux ou WSL :

```bash
pip wheel --wheel-dir=/tmp/wheels -r requirements.txt
tar czf /tmp/wheels.tgz -C /tmp wheels
rsync -avz /tmp/wheels.tgz ubuntu@16.58.132.68:/tmp/
ssh ubuntu@16.58.132.68 '
  cd /home/ubuntu/klassci/klassci-backend &&
  source .venv/bin/activate &&
  tar xzf /tmp/wheels.tgz -C /tmp/ &&
  pip install --no-index --find-links=/tmp/wheels -r requirements.txt &&
  alembic upgrade head &&
  sudo systemctl restart klassci-backend klassci-celery'
```

## Anti-patterns à bloquer

| Pattern | Pourquoi NON |
|---|---|
| `ssh ubuntu@16.58.132.68 "pip install -r requirements.txt"` | compile cryptography/weasyprint sur prod, sature CPU/RAM |
| `ssh ubuntu@16.58.132.68 "alembic downgrade base && alembic upgrade head"` sur DB > 100 MB | locks longues, OOM possible |
| Lancer `pytest` complet sur EC2 prod | charge CPU + DB |
| Celery worker batch très lourd (gen EDT 50+ classes) en pleine heure ouvrée | sature les 2 vCPU partagés avec uvicorn |
| Compiler une dépendance native (`cffi`, `lxml`, `cryptography`) sur le serveur prod | par déf interdit, doit venir en wheel |

## Exception explicite

Le seul `pip install` autorisé sur EC2 prod : install **incrémental** d'un package déjà publié en wheel sur PyPI (pas de compilation, juste un download + extract — quelques secondes, peu de CPU). Ex: `pip install sentry-sdk[fastapi]==2.18.0`.

Mais même là, dès qu'on a un pipeline CI/CD, c'est `pip wheel` côté CI puis `pip install --no-index --find-links=/tmp/wheels`.

## Voir aussi

- Mémoire incident fondateur : `feedback_never_build_on_prod.md`
- Rule globale : `~/.claude/rules/never-build-on-prod-server.md`
- Rule FE équivalente : `klassci-college-frontend/.claude/rules/deploy.md`
- Rule sœur : `ssh-remote-commands.md`
