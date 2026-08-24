# Jeu de données de démonstration

Peuple un locataire avec **une année scolaire complète de collège-lycée privé
ivoirien**, pour qu'aucun écran ni aucun document ne se présente vide devant un
client.

## Lancer le semis

```bash
python -m app.cli.seed_demo --tenant local
```

Sur le serveur de démonstration Windows :

```powershell
cd C:\klassci\backend
.\venv\Scripts\python.exe -m app.cli.seed_demo --tenant local
```

Reprendre une seule étape après un incident (le référentiel tourne toujours,
il fournit les identifiants aux autres) :

```bash
python -m app.cli.seed_demo --tenant local --only cashdesk --only academics
```

Étapes disponibles, dans leur ordre d'exécution : `referentiel`, `staffing`,
`curriculum`, `billing`, `families`, `timetabling`, `academics`, `cashdesk`,
`presence`, `schoollife`, `deep_data`, `extras`.

## Vérifier que les documents sortent

Le semis n'est utile que si les documents s'impriment. Le script de contrôle
appelle les vingt et un points d'entrée réels et vérifie que chaque réponse est
bien un PDF (`%PDF`) d'une taille plausible, ou un JSON non vide :

```powershell
cd C:\klassci\backend
.\venv\Scripts\python.exe scripts\verify_demo_documents.py `
    --tenant local --base-url http://localhost:8000 `
    --email admin@klassci.com --password '<mot de passe admin>'
```

Il sort en code 0 quand les vingt et un documents répondent 200.

## Ce que le semis pose

| Domaine | Contenu |
|---|---|
| Référentiel | Année 2025-2026 courante, ses trois trimestres et ses congés, sept niveaux de la 6e à la Terminale, séries A et C en seconde, A, C et D au second cycle, dix-huit divisions, une salle par classe plus les laboratoires, identité complète de l'établissement |
| Personnel | Équipe enseignante dimensionnée sur les heures à assurer, avec sexe, type de contrat, numéro CNPS et autorisation d'enseigner renseignés pour chacun ; les six métiers du secrétariat, chacun avec son rôle d'accès |
| Familles | Élèves aux noms ivoiriens avec portrait, tuteurs rattachés, fratries, inscriptions dans les trois états (prospect, en validation, validée), élèves affectés et non affectés |
| Finances | Grille du collège pilote, échéancier 37 000 F puis 35 / 35 / 30 %, versements en espèces, Wave, Orange Money et virement, journées de caisse clôturées avec écarts, journée du jour ouverte |
| Pédagogie | Emploi du temps complet, deux évaluations par matière et par trimestre, notes des trois trimestres, bulletins publiés, conseils de classe tenus |
| Vie scolaire | Convocations avec leurs suites, billets d'entrée, autorisations de reprise, demandes de dossier scolaire |
| Rapport officiel | Visites de classe, formations d'enseignants, transferts et bourses, quatre tables qu'aucun écran ne saisit et sans lesquelles cinq tableaux de la DEEP restent vierges |

## Les garanties du script

**Additif et relançable.** Chaque étape rapproche avant d'écrire, sur une clé
naturelle stable : le matricule pour un élève, la référence pour un versement,
le couple (classe, jour) pour une feuille d'appel. Relancer ne duplique rien.

**Rien n'est jamais supprimé.** Aucune table n'est vidée, aucune ligne détruite.

**Il passe par les services de l'application.** Les inscriptions, les frais, les
versements, les notes, les bulletins et les conseils empruntent le même code
que l'interface : les imputations de versement sont donc exactes, les statuts
cohérents, et le journal d'audit se remplit au passage.

**Le tirage est déterministe.** Deux exécutions produisent les mêmes noms, les
mêmes notes et les mêmes montants.

## Les deux effets de bord à connaître

Le script configure une grille tarifaire, et configurer une grille suppose de
retirer celle qui la précède.

1. **Les catégories de frais obligatoires absentes de la brochure passent hors
   grille** (`is_mandatory = 0`). Sans cela, un élève de 6e se verrait facturer
   la scolarité de la grille **et** les trois trimestres d'un modèle abandonné.
   Rien n'est supprimé : les lignes déjà facturées, les versements et
   l'historique restent intacts, et un clic dans l'écran Frais suffit à les
   réactiver.
2. **Le rang d'affichage d'un niveau est corrigé quand il est faux.** C'est lui
   qui ordonne toutes les listes ; une « première » rangée avant la 6e ferait
   ouvrir chaque écran sur le lycée. Seul cet entier bouge, jamais le libellé
   que l'école a saisi.

Les deux gestes sont journalisés ligne par ligne dans la sortie du script.

## Comptes de démonstration créés

Tous partagent le mot de passe `Demo@2026`.

| Rôle | Adresse |
|---|---|
| Secrétariat | `staff1@demo.klassci.ci` |
| Caisse | `cashier2@demo.klassci.ci`, `cashier3@demo.klassci.ci` |
| Éducateur | `educator4@demo.klassci.ci`, `educator5@demo.klassci.ci` |
| Comptable | `accountant6@demo.klassci.ci` |
| Directeur des études | `studies_director7@demo.klassci.ci` |
| Directeur | `director8@demo.klassci.ci` |
| Enseignants | `prenom.nomN@demo.klassci.ci` |
| Parents | `prenom.nomN@familles.demo.klassci.ci` (un quart des familles) |
| Élèves | `kls26-XXXX@familles.demo.klassci.ci` |

Les comptes administrateur existants du locataire ne sont jamais touchés : le
semis en emprunte un pour signer ses écritures, afin que le journal d'audit
désigne quelqu'un que l'établissement reconnaît.
