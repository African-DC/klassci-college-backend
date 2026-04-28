# Changelog

Toutes les évolutions notables de KLASSCI College Backend (FastAPI) sont
documentées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et
le projet adhère à [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

### Added

- Promotion en masse de fin d'année : l'admin choisit la classe de destination de chaque classe source et obtient en un appel un aperçu des élèves promus, des avertissements de capacité, et un rapport de promotions appliquées avec les exceptions *(admin)* (#95).
- Validation d'inscription en un appel dédié : l'admin peut désormais passer un prospect ou une inscription en attente directement à l'état validé, avec audit traçable et message clair si la transition est refusée *(admin)* (#93).
- Liste des élèves côté admin enrichie de la classe et du statut d'inscription pour l'année courante : un seul appel API au lieu de cliquer chaque fiche pour savoir où l'élève est *(admin)* (#82).
- Filtres par classe et liste des élèves « à inscrire » exposés en un endpoint dédié, prêt à alimenter les chips de la liste élèves *(admin)* (#82).
- Création d'évaluation par un admin ou un personnel administratif au nom d'un enseignant, avec contrôle d'identité du titulaire et trace d'audit *(admin, enseignant)*.
- Endpoint exposant les permissions effectives de l'utilisateur courant, consommé par les portails pour afficher uniquement les actions autorisées *(tous)*.
- Outils de provisioning : script de seed déterministe pour les comptes admin / enseignant / élève des scénarios E2E *(devops)*.
- Tableau de bord élève : nom, classe, prochain cours, moyenne générale, frais restants et total d'absences, en un seul appel *(élève)* (#75).
- Liste exhaustive des évaluations de l'enseignant connecté pour alimenter la page « Mes évaluations » côté portail *(enseignant)* (#75).

### Changed

- Les classes (6ème A, Terminale C, …) deviennent permanentes : on ne crée plus une nouvelle classe à chaque rentrée. À chaque changement d'année, la classe reste, on réinscrit ou on promeut les élèves, et la promotion devient un simple choix de destination *(admin)* (#97).
- Audit des changements de permissions de rôle : on garde désormais l'état avant et après pour reconstruire le diff de chaque modification *(admin, super-admin)*.
- Tableau de bord enseignant repensé : nom, prochain cours, totaux et liste des évaluations à venir avec progression de saisie, en cohérence avec ce qu'affiche le portail *(enseignant)* (#75).
- Création d'évaluation : la matière doit être enseignée dans la classe sélectionnée. Toute combinaison incohérente est refusée avec un message clair en français *(admin, enseignant)* (#76).
- Liste des matières filtrable par classe : on n'affiche plus que les matières du niveau (et de la série) de la classe demandée *(admin)* (#76).

### Fixed

- Fiche élève, création, modification et upload de photo qui renvoyaient « Connexion au serveur impossible » depuis l'enrichissement de la liste : restaurés en eager-loadant l'inscription année courante au chargement d'un élève *(admin)*.
- Création d'évaluation qui échouait silencieusement avec « Erreur serveur » : l'audit serveur sait désormais sérialiser correctement la date *(admin, enseignant)* (#76).
- Permissions de gestion des rôles, des salles et des séries désormais seedées par défaut. Auparavant, les pages correspondantes côté portail étaient inaccessibles en silence (#73).
- Démontage propre de la migration ajoutant la traçabilité de saisie des notes (l'ordre de suppression de l'index et de la contrainte cassait la rétrogradation sur MySQL).
- Tableau de bord enseignant et tableau de bord élève qui renvoyaient « Connexion impossible » en boucle : les chemins et formats de réponse sont désormais alignés avec ce que les portails attendent *(enseignant, élève)* (#75).
- Script de seed des comptes test : protège contre la création de profils élève en double pour un même utilisateur, qui faisait planter le tableau de bord élève en production *(devops)*.

## [0.1.0-alpha] - 2026-04-26

### Added

- Authentification par email et mot de passe avec session persistante via cookie sécurisé et endpoint de profil *(admin, enseignant, parent, élève)*.
- Provisioning d'un nouvel établissement en une commande (CLI ou API) avec création automatique de l'admin, des rôles et des données de démarrage *(super-admin)* (#40).
- Inscriptions des élèves en plusieurs étapes avec contrôle de capacité de classe, gestion des doublons et réinscription d'une année à l'autre *(admin)* (#16, #44).
- CRUD complet des élèves, enseignants, personnel, classes, niveaux, séries, salles et matières avec recherche, filtres et pagination *(admin)* (#31).
- Création automatique d'un compte de connexion lors de l'ajout d'un élève ou d'un enseignant, et endpoint dédié pour générer un compte ultérieurement *(admin)*.
- Fiche détaillée 360° de l'élève avec compte utilisateur, inscription en cours, présences et résumé des frais en un seul écran *(admin)*.
- Gestion des parents avec rattachement aux enfants et accès au portail famille *(admin, parent)*.
- Catégories et variantes de frais paramétrables par niveau et série, avec distinction obligatoire/optionnel et options multiples (cantine, transport, etc.) *(admin)* (#46).
- Création automatique des frais à payer dès l'inscription, régénération en cas de changement de classe et abonnement aux frais optionnels *(admin)*.
- Encaissement des paiements en espèces avec workflow validation/annulation, génération d'un reçu PDF et résumé par élève *(admin)* (#32, #55).
- Saisie des présences cours par cours avec statistiques par élève, par classe et alertes d'absence *(enseignant, admin)* (#33).
- Saisie des notes et évaluations avec coefficients par matière, classement et historique *(enseignant)* (#18).
- Génération et publication des bulletins de notes en PDF avec téléchargement individuel ou par lot *(admin, enseignant, parent, élève)* (#38).
- Procès-verbaux de conseil de classe en PDF avec décisions par élève (admis, redouble, exclu, etc.) *(admin, enseignant)* (#37, #55).
- Statistiques DREN agrégées (effectifs, taux de présence, résultats) prêtes à exporter *(admin)* (#39).
- Tableau de bord de l'admin avec compteurs en temps réel (élèves, paiements, présences) et flux d'activité récente *(admin)*.
- Emploi du temps avec génération automatique intelligente (OR-Tools), durées variables, préservation des créneaux saisis manuellement et détection des conflits salles/profs *(admin)* (#17).
- Export PDF de l'emploi du temps prêt à imprimer pour affichage *(admin, enseignant, élève)*.
- Coloration des matières et duplication par glisser-déposer pour configurer rapidement la grille hebdomadaire *(admin)*.
- Configuration du format des numéros matricule par établissement, avec aperçu en direct avant validation *(admin)* (#52).
- Téléversement de la photo des élèves, enseignants et personnel, et de documents officiels (carte, justificatifs) *(admin)*.
- Import en lot des élèves depuis un fichier CSV *(admin)* (#53).
- Portail élève avec emploi du temps, notes, bulletins, présences et notifications *(élève)* (#34).
- Portail enseignant avec classes assignées, saisie des notes/présences, emploi du temps et messagerie de notifications *(enseignant)* (#36).
- Portail parent avec suivi multi-enfants : bulletins, présences, paiements, emploi du temps *(parent)* (#35).
- Notifications multi-canal (email SMTP, SMS Twilio, in-app) déclenchées sur publication de bulletin, absence et paiement *(admin, enseignant, parent, élève)* (#30, #54).
- Paramètres établissement éditables : informations école, année scolaire en cours, format matricule *(admin)*.
- Données de démonstration pré-remplies pour démarrer un établissement test (CI) en une commande *(super-admin)* (#45).

### Changed

- Résolution du tenant unifiée via le token JWT puis l'en-tête `X-Tenant-Slug`, avec repli sur le sous-domaine, pour le déploiement en domaine unique `college.klassci.com` *(devops)* (#72).
- Réponses des inscriptions, classes, matières et paiements enrichies avec les noms et photos liés (élève, classe, matière, photo) pour éviter des appels supplémentaires *(admin, enseignant)*.

### Fixed

- Recherche multi-mots traitée correctement (chaque mot filtre indépendamment) avec repli flou (RapidFuzz) lorsqu'aucun résultat exact n'est trouvé *(admin)*.
- Inscriptions filtrées correctement par élève sur la liste *(admin)*.
- Génération du reçu PDF de paiement et du PV de conseil ne plante plus sur les profils sans prénom *(admin)*.
- Détection du tenant en local (adresses IP numériques) pour le développement *(devops)*.

### Security

- Permissions dynamiques pilotées par la base de données (rôles × permissions configurables par tenant) avec endpoints d'administration dédiés *(admin)*.
- Journal d'audit horodaté pour toutes les actions sensibles (création, modification, suppression, login) avec sérialisation sûre des paramètres *(admin)*.
- Token JWT scopé au tenant : impossible d'utiliser un token d'un établissement sur un autre, contrôle appliqué aussi sur le refresh et le logout *(devops, admin)*.
- Refresh token stocké en cookie HttpOnly + SameSite + Secure, supprimé proprement au logout *(devops)*.
- Verrou pessimiste (`SELECT FOR UPDATE`) sur la création d'inscription pour empêcher tout dépassement de capacité de classe en cas d'accès simultané *(admin)*.
- Mise à jour `PyJWT 2.12.0`, `cryptography 46.0.5` et remplacement de `python-jose` (CVE critiques résolues) *(devops)*.
- Workflow de sécurité automatisé en CI : Bandit, pip-audit, CodeQL et TruffleHog sur chaque PR *(devops)*.
- Validation stricte des fichiers téléversés (taille, type MIME réel via `finfo`) sur les photos et documents *(devops)*.

[unreleased]: https://github.com/African-DC/klassci-college-backend/compare/v0.1.0-alpha...HEAD
[0.1.0-alpha]: https://github.com/African-DC/klassci-college-backend/releases/tag/v0.1.0-alpha
