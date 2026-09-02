# `RELEASES.json` — ce que la vitrine peut lire

Ce fichier est une **projection de `CHANGELOG.md`**, régénérée à chaque
livraison. Le changelog reste la source : on l'écrit pour un humain, en revue.
Ce fichier-ci existe pour que la page vitrine et son agent n'aient pas à
réécrire un analyseur de Markdown — et à le voir casser le jour où une entrée
sort du gabarit.

## Où le trouver

`RELEASES.json`, à la racine de chaque dépôt :

- `African-DC/klassci-college-backend`
- `African-DC/klassci-college-frontend`

Les deux se lisent ensemble : une même livraison a souvent une moitié de chaque
côté. Le produit est nommé dans le champ `product`.

## Forme

```jsonc
{
  "product": "klassci-college-backend",
  "source": "CHANGELOG.md",
  "generated_at": "2026-09-02T21:14:00Z",
  "current_version": "0.1.0-alpha",   // la dernière version taguée, ou null
  "versions": [
    {
      "version": "Unreleased",        // ou "0.2.0"
      "date": null,                   // null tant que ce n'est pas tagué
      "released": false,
      "sections": {
        "Added":   [ /* entrées */ ],
        "Changed": [], "Deprecated": [], "Removed": [],
        "Fixed":   [], "Security": []
      }
    }
  ]
}
```

Une entrée :

```jsonc
{
  "text": "Un tableau par classe dit qui a soldé quelle catégorie de frais",
  "audience": ["comptable"],   // vide quand la ligne est transverse
  "pull_request": 412          // null quand la ligne n'en nomme pas
}
```

## Ce sur quoi on peut compter

- **`text` est déjà écrit pour un utilisateur final.** La règle du dépôt
  l'impose : pas de nom de classe, pas de module, pas de librairie. Il
  s'affiche tel quel, sans réécriture.
- **`audience`** porte les personas nommés dans le changelog : `admin`,
  `enseignant`, `parent`, `élève`, `comptable`, `caissier`, `secrétariat`,
  `éducateur`, `super-admin`, `devops`. C'est ce qui permet de montrer à un
  parent ce qui a changé pour lui, et rien d'autre.
- **`versions[0]` est toujours la plus récente**, `Unreleased` en tête quand
  elle existe. Une section vide est absente, jamais `null`.

## Ce qu'il ne faut pas en attendre

- **Aucune valeur n'est devinée.** Une ligne sans persona sort avec
  `audience: []` — cela veut dire « transverse », pas « on n'a pas su lire ».
- **`Unreleased` n'a pas de date.** Lui en inventer une ferait annoncer une
  livraison qui n'a pas eu lieu.
- **Ce n'est pas un journal de commits.** Un `chore` ou un `refactor` interne
  n'y figure pas : le changelog ne retient que ce qu'un utilisateur peut faire
  de plus, de mieux, ou différemment.

## Régénérer

```bash
python scripts/release_feed.py            # écrit RELEASES.json
python scripts/release_feed.py --check    # échoue si le fichier a dérivé
```

La CI (`.github/workflows/release-feed.yml`) lance `--check` sur chaque PR qui
touche au changelog. Le hook `pre-commit` le fait aussi, en local.
