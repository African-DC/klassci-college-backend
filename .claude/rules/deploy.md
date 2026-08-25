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

# Regle Deploiement backend · Demo Windows, prod Contabo

## La regle

- **Demo Windows** (`94.72.96.119`) : extraire le code, `migrate-seed.ps1` si nouvelles migrations, `nssm restart klassci-backend`. Pas de `pip install` compilant cryptography/weasyprint/lxml.
- **Production Contabo** (`169.58.156.206`, `https://college.klassci.com`, jusqu'a 24 Go RAM) : `docker build` de l'image backend **autorise sur l'hote**, Dokploy compose `klassci-college-prod` dans `/etc/dokploy/compose/klassci-college-prod/code/`. `alembic upgrade head` seulement si migration courte, puis recreate du service `backend` seulement. SSH : `ssh -F deploy/ssh_config klassci-prod`. `EXTRA_ALLOWED_HOSTS` doit inclure `backend` (NextAuth interne). Jamais `down -v`. Wourri : ne pas y toucher.
- **EC2 `16.58.132.68` (2 Go) n'existe plus.** L'interdiction de build lourd venait de cette machine, pas du Contabo.

## Operations lourdes a eviter en heure ouverte

- `pip install -r requirements.txt` avec compilation native **dans** le conteneur live (preferer une image)
- `pytest` complet sur l'hote de trafic
- generation EDT OR-Tools massive en heure ouverte

## Pattern demo Windows

```bash
ssh -F deploy/ssh_config klassci
tar -xzf C:\klassci\backend.tgz -C C:\klassci\backend
powershell -File C:\klassci-deploy\migrate-seed.ps1
nssm restart klassci-backend
```

## Pattern Contabo

Builder l'image sur l'hote (24 Go) ou en CI, `docker load` si besoin, puis
`compose -p klassci-college-prod up -d --no-deps --force-recreate backend`.
Ne pas recreer `mysql` / `redis` / `proxy` sans besoin.

## Voir aussi

- Rule globale : `~/.claude/rules/never-build-on-prod-server.md`
- Rule FE : `klassci-frontend/.claude/rules/deploy.md`
