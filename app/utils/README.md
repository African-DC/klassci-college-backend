# app/utils/ — Helpers Purs

Fonctions utilitaires sans etat, sans acces DB, sans dependances externes.

## Ce qu on met ici

- Formatage de dates et heures
- Calculs purs (moyennes, totaux, jours ouvres)
- Generation de codes (code retrait 10 chiffres, slugs)
- Helpers export (formatage pour Excel/PDF)
- Fonctions de validation generiques

## Ce qu on ne met PAS ici

- Acces DB → `repositories/`
- Logique metier → `services/`
- Appels HTTP → `services/`
- Config → `core/config.py`
