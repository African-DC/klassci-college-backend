# alembic/ — Migrations Base de Donnees

Toutes les migrations de schema MySQL sont versionnees ici.

## Commandes

```bash
alembic revision --autogenerate -m "description"  # Nouvelle migration
alembic upgrade head                               # Appliquer toutes les migrations
alembic downgrade -1                               # Revenir d une migration
alembic current                                    # Etat actuel
alembic history --verbose                          # Historique
```

## Regles CRITIQUES

1. Ne JAMAIS modifier une migration deja appliquee en staging ou production
2. Toujours tester le `downgrade` avant de merger
3. Creer des index sur toutes les colonnes FK et colonnes filtrees frequemment
4. Utiliser le skill `/new-migration [description]` pour etre guide

## Multi-tenant

Pour appliquer une migration sur toutes les bases tenant :
```bash
python scripts/migrate_all_tenants.py
```
Le script lit la liste des tenants depuis `klassci_master` et applique la migration
sur chaque base, avec rapport de succes/echec par tenant.
