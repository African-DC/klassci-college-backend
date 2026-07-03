# Changelog

Toutes les évolutions notables de KLASSCI College Backend (FastAPI) sont
documentées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et
le projet adhère à [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

### Added

- Demandes de congé : les enseignants et le personnel posent leurs congés (type, dates, motif) et suivent leur statut ; la direction consulte, approuve ou refuse avec un commentaire *(enseignant, personnel, admin)*.
- Documents de l'élève : l'administration téléverse des pièces (extrait de naissance, certificat médical, etc.) sur la fiche d'un élève, avec un type choisi dans un catalogue ou créé à la volée *(admin)*.
- Préférences de notifications : chaque utilisateur choisit, depuis son profil, de recevoir en plus les notifications par email et/ou SMS ; ces choix sont respectés à l'envoi. La notification dans l'application reste toujours active *(tous)*.
- Espace profil personnel : chaque utilisateur consulte ses informations (nom, contact, rôle) et met à jour son téléphone ; l'enseignant et le personnel téléversent ou retirent eux-mêmes leur photo, l'élève restant géré par l'administration *(tous)*.
- Rôle d'accès du personnel choisi à la création et modifiable (Personnel, Comptable, Directeur) : il détermine les droits d'accès dans KLASSCI et est renvoyé partout où le personnel est affiché, sans jamais permettre d'attribuer un rôle d'administrateur *(admin)*.
- Fiche parent enrichie : pour chaque enfant, sa classe, son statut d'inscription et son solde de frais restant, plus un récapitulatif financier global (total dû, payé, reste à payer sur l'année) pour voir d'un coup d'œil la situation du foyer *(admin)*.
- Fiche personnel enrichie d'un aperçu d'activité de l'année : versements encaissés (nombre et montant), inscriptions traitées et dernière connexion *(admin)*.

### Fixed

- Fiche parent : les enfants liés s'affichaient sans nom ni classe (lignes vides) ; ils apparaissent désormais correctement avec toutes leurs informations *(admin)*.

### Changed

- Cahier de texte fidèle au calendrier scolaire : il utilise l'emploi du temps de l'année scolaire à laquelle appartient la période demandée (plus seulement l'année courante) et ne génère plus de séances pendant les vacances (semaines hors trimestre) ; une semaine de congés affiche « Vacances scolaires » au lieu d'un planning trompeur *(enseignant, admin)*.
- Mise en page affinée document par document dans la ligne institutionnelle sobre : le bulletin présente la moyenne, le rang et la mention (point focal) dans une bande de chiffres-clés compacte plutôt qu'en grosses boîtes, avec les colonnes du tableau des matières calées et le nom du professeur en sous-ligne discrète ; la liste de classe, l'emploi du temps, l'état des frais et le reçu de versement ont leurs colonnes alignées, l'état des frais met le solde restant dû en évidence avec une ligne de total, et le reçu met en avant le montant versé *(admin, enseignant, parent, élève)*.
- Documents officiels et exports repensés en **design institutionnel sobre** : la typographie embarquée (Spectral pour le nom de l'établissement et les titres, Inter pour le corps et les tableaux) et la hiérarchie portent l'autorité à la place du décor. En-tête condensé (logo + identité + mention « République de Côte d'Ivoire » sur une ligne + filet aux couleurs de l'établissement), tableaux réalignés (colonnes calées, en-tête sobre), et allègement radical : suppression du double cadre, du filigrane et du sceau décoratif au profit du seul Cachet Électronique Visible comme élément de confiance. Les couleurs de l'établissement sont utilisées avec parcimonie : la primaire pour la structure, l'accent pour un seul point focal par document *(transverse)*.
- Documents officiels repensés en documents premium aux couleurs de chaque établissement : certificat de scolarité, attestation de fréquentation, liste de classe, emploi du temps, bordereau de caisse, procès-verbal de conseil, reçu de paiement, état des frais et fiche d'inscription reçoivent désormais un cadre officiel, un filigrane discret au nom de l'école, un en-tête d'identité complet (logo ou monogramme, code MENA, contacts, devise), un cachet et une zone de signature, un numéro de référence, et une mise en page qui remplit la page (le cadre se répète sur chaque page des documents qui en comptent plusieurs) *(admin, enseignant, parent, élève)*.
- Bulletin de notes habillé du cadre officiel aux couleurs de l'établissement, enrichi pour chaque matière du professeur, du rang de l'élève, de la moyenne de la classe et d'une appréciation (Excellent, Très bien, Bien, Assez bien, Passable, Insuffisant), plus un bandeau de synthèse (moyenne et écart de la classe, absences, retards) *(enseignant, parent, élève)*.
- Espacements des documents affinés : le logo (ou monogramme) de l'établissement n'est plus collé à son nom dans l'en-tête, et le bloc du Cachet Électronique Visible est aéré (texte espacé, code plus lisible). Le lien de vérification imprimé pointe vers le domaine de l'école plutôt qu'une adresse IP *(transverse)*.

### Fixed

- Documents officiels (certificat, attestation) : le signataire n'apparaît plus en double (« Le Chef d'Établissement, Le Chef d'Établissement ») quand le nom du chef d'établissement n'est pas distinct de son titre *(admin)*.
- Bulletin : la mention affiche désormais son libellé en clair (« Très Bien », « Bien », « Assez Bien »…) au lieu d'un code technique (« Mention.TRES_BIEN ») *(enseignant, parent, élève)*.
- Liste de classe : le numéro matricule de chaque élève s'affiche à nouveau au lieu d'un tiret, le champ étant désormais lu sur la fiche élève et non sur l'inscription *(admin, enseignant)*.

### Added

- Score de performance des enseignants et tableau d'activité du personnel : chaque enseignant reçoit une note sur 100 transparente, décomposée en trois axes (assiduité aux séances, saisie des notes, prise de l'appel) et repondérée sur les seuls axes réellement mesurables ; quand une donnée manque, l'axe est marqué « données insuffisantes » plutôt que noté zéro. L'enseignant consulte sa propre note depuis son espace ; la direction voit l'ensemble. Le personnel dispose d'un tableau d'activité factuel (versements encaissés, inscriptions traitées) sans note fabriquée *(admin, enseignant)*.
- Portail enseignant : accès à la liste des élèves d'une classe assignée pour faire l'appel (nouvel endpoint scopé enseignant, vérifie que la classe appartient bien à l'enseignant) *(enseignant)*.
- Calendrier des congés et jours fériés paramétrable par l'établissement (congés de Toussaint, fêtes mobiles, jour férié isolé…) : le cahier de texte n'affiche plus de séances pendant ces congés, même quand ils tombent en plein trimestre, et indique le motif (ex. « Congés de Toussaint ») *(admin, enseignant)*.
- Relevé de notes de classe rempli et cahier de texte, en PDF paysage sobre : le **relevé de notes** restitue pour une matière et un trimestre les notes déjà saisies (une colonne par évaluation avec coefficient et date), calcule la moyenne pondérée par les coefficients et le rang de chaque élève, et affiche les statistiques de classe (moyenne, min, max, taux de saisie) ; le **cahier de texte** développe l'emploi du temps sur une période (semaine courante par défaut) en séances datées, avec les colonnes « Contenu de la séance » et « Travail à faire » laissées vides à remplir à la main *(admin, enseignant)*.
- Feuilles de travail vierges à imprimer pour une classe, en PDF paysage : une **feuille d'appel** (colonnes de présence numérotées à cocher au stylo, avec légende P/A/R/E) et une **feuille de notes** (colonnes de notes et colonne moyenne à remplir à la main). Les deux reprennent l'en-tête institutionnel de l'établissement mais restent de simples feuilles de travail (ni cachet électronique ni signature), avec un nombre de colonnes paramétrable *(admin, enseignant)*.
- Rapport de synthèse de classe par trimestre, en PDF officiel aux couleurs de l'établissement : palmarès des élèves (rang, moyenne, mention), statistiques par matière (moyenne de la classe, min, max) et indicateurs clés (effectif, moyenne de classe, taux de réussite), prêt pour le conseil de classe *(admin, enseignant)*.
- Cachet Électronique Visible (CEV) sur le certificat de scolarité, l'attestation de fréquentation et le bulletin : un cachet 2D (Datamatrix) signé cryptographiquement plus un code lisible « CEV-XXXX-XXXX-XXXX ». Un parent ou un employeur scanne le cachet ou saisit le code sur la page publique pour confirmer l'authenticité du document, sans aucun compte *(admin, parent, élève)*.
- Page de vérification publique des documents : confirme l'authenticité (établissement, type, élève, classe, année, date, référence) et détecte toute falsification grâce à la signature. La falsification d'un document imprimé est ainsi immédiatement repérable *(transverse)*.
- Indicateurs clés du tableau de bord et des pages de gestion (élèves, classes, enseignants, personnel, parents, salles, matières, inscriptions) calculés directement côté serveur : les chiffres restent justes même pour les grands établissements, là où l'ancien comptage se limitait aux 100 premières lignes *(admin)*.

### Fixed

- Profil élève (`/student/profile`) accessible sans erreur serveur : Aminata, Bertrand et Fatou voient désormais leur fiche au lieu d'une page blanche *(élève)*.
- Emploi du temps de l'enfant côté parent (`/parent/children/{id}/timetable`) charge sans erreur serveur : Mariam voit l'EDT d'Aminata au lieu d'une page blanche *(parent)*.
- Année scolaire courante (`/admin/academic-years/current`) accessible sans erreur de validation : le dashboard admin affiche désormais l'année active sans bug *(admin)*.

### Added

- Permission `grades:edit` distincte de `grades:write` : la première autorise à saisir une note pour la première fois, la seconde à modifier une note déjà enregistrée. Une école peut désormais autoriser un enseignant à saisir sans pouvoir réviser, ou inversement. Attribuée par défaut à admin, directeur et enseignant ; révocable depuis Rôles & Permissions *(admin)*.

### Changed

- Noms des matières seedés avec les accents officiels : Mathématiques, Français, Histoire-Géographie, Éducation Civique et Morale, Éducation Physique et Sportive. Affichage cohérent partout (bulletins, EDT, kanban, liste des notes). Un script SQL one-shot met à jour les tenants existants *(admin, enseignant, parent)*.
- Niveaux du tronc commun seedés avec les accents officiels : 6ème, 5ème, 4ème, 3ème et 1ère affichent désormais les bons accents partout (kanban, table, bulletins, EDT). Les anciens tenants gardent leur orthographe existante tant qu'une mise à jour explicite n'est pas appliquée *(admin)*.

### Added

- Script SQL one-shot pour seeder les 36 matières de référence du lycée selon la grille officielle MENA-CI / DECO : 2nde A, 1ère C/D, Terminale A/C/D avec coefficients BAC officiels (SVT coef 6 en série D, Mathématiques et Sciences physiques coef 5 en série C, Philosophie coef 4 partout au Terminal) *(admin)*.
- Pointage de présence des enseignants par créneau d'emploi du temps : l'admin saisit l'absence (excusée / non excusée / retard avec minutes), l'enseignant peut s'auto-déclarer absent (en attente de validation admin). Statistiques par année scolaire (taux de présence, retards cumulés, déclarations en attente) sur la fiche enseignant *(admin, enseignant)* (#146).
- Versement caissier en 3 champs (élève, montant, méthode) : le système alloue automatiquement le montant aux frais impayés dans l'ordre Inscription, scolarité trimestre 1/2/3, COGES, tenue. Plus besoin de choisir un frais avant de saisir le montant *(admin)*.
- Aperçu d'allocation avant validation : le caissier visualise comment le versement sera réparti aux différents frais et est averti d'un éventuel surplus avant de confirmer *(admin)*.
- Historique détaillé des paiements d'une inscription avec le détail des allocations par frais sur chaque versement, pour la traçabilité comptable *(admin)*.
- Ordre de priorité des frais configurable par catégorie : l'admin peut ajuster l'ordre dans lequel les paiements sont alloués aux frais (par défaut Inscription en premier, tenue en dernier) *(admin)*.
- Reçu de paiement enrichi : quand un versement est alloué à plusieurs frais, le PDF affiche maintenant un tableau Frais / Affecté / Cumul / Statut avec pastilles de couleur, pour une traçabilité comptable claire *(admin, parent)*.
- État individuel des frais (PDF) : document parent qui synthétise pour une inscription les KPIs (total attendu, versé, reste, % avancement), le détail par frais et l'historique des versements. Téléchargeable depuis la fiche de l'inscription *(admin, parent)*.
- Bordereau journalier (PDF) : récap des versements d'une date par méthode (espèces, mobile money, virement, chèque) avec total général et signatures Caissier / Comptabilité. Imprimable fin de journée pour la clôture caisse *(admin)*.
- Liste de classe (PDF) : effectif imprimable avec photos miniatures, matricule, sexe, date de naissance et téléphone parent urgence, signé par le professeur principal. Utile pour conseil de classe, sortie scolaire ou appel papier *(admin)*.
- Fiche d'inscription officielle (PDF) : document à signer par le parent à la rentrée avec identité élève, blocs père/mère/tuteur, classe affectée et tableau des frais scolaires avec total. Bandeau République de Côte d'Ivoire + signatures Parent et Chef d'établissement *(admin, parent)*.

### Fixed

- Téléchargement d'un PDF en erreur : le serveur renvoie maintenant un message JSON explicite (« Génération PDF impossible pour … ») au lieu d'une réponse vide générique. Bulletin, reçu, EDT, certificat, fiche d'inscription, PV de conseil, bordereau, état des frais et liste de classe sont protégés *(admin, parent, enseignant)*.
- Fiche élève : les graphes « Moyennes par trimestre » et « Absences par trimestre » du tab Parcours affichent désormais les vraies données (trimestre 1 : moyenne générale, meilleure et plus faible matière) au lieu d'un message « Pas encore de notes » trompeur *(admin)*.
- Bulletin scolaire : la liste des élèves affiche le nom complet, le matricule et un avatar à initiales au lieu d'un identifiant technique `#3`. La fenêtre de détail montre le détail par matière avec coefficient et moyenne *(admin)*.
- Chaîne de migrations Alembic réparée : la migration de présence enseignant pointait vers un ancêtre nommé `0029_school_pdf_customization` qui n'existe pas (le vrai id étant juste `0029`). Toute installation d'établissement échouait avec une erreur cryptique avant cette correction *(devops)*.
- Pointage de présence des enseignants désormais accessible : les permissions des 3 nouveaux endpoints (admin saisit, lecture, prof auto-déclare) sont maintenant attribuées aux rôles correspondants (admin, director, staff, teacher). Auparavant tous les appels retournaient 403, ce qui rendait la feature inopérante *(admin, enseignant)* (#148).
- Reçus de paiement et bordereaux : la méthode et le statut s'affichent désormais en français lisible (« Espèces », « Validé ») au lieu du nom technique brut (« PaymentMethod.CASH », « PaymentStatus.COMPLETED ») *(admin, parent)*.
- Génération PDF désormais compatible avec les versions récentes de `pydyf` : pin explicite `pydyf<0.12` dans `requirements.txt` car la 0.12 a un breaking change incompatible avec WeasyPrint 62 (Stream.transform retiré → 500 silencieux au render) *(devops)*.
- Identité visuelle de l'école désormais appliquée à TOUS les documents PDF : les bulletins, certificats de scolarité, attestations de fréquentation, emplois du temps, listes de classe, fiches d'inscription et PV de conseil reprennent maintenant les couleurs, la devise et le site web configurés. Auparavant ces 6 documents retombaient silencieusement sur la palette KLASSCI par défaut malgré la configuration tenant *(admin, parent, enseignant)*.
- PV de conseil de classe (PDF) : génération corrigée, l'année scolaire n'était pas pré-chargée et provoquait une erreur 500 silencieuse au téléchargement *(admin)*.

### Changed

- Identité visuelle des PDFs personnalisable par école : chaque établissement peut configurer sa couleur principale, sa couleur d'accent, sa devise et son site web. Le logo et les couleurs apparaissent automatiquement sur tous les documents (reçus, état des frais, bordereaux, etc.). Migration `0029` *(admin, super-admin)*.
- Tous les documents PDF officiels (bulletins, reçus, attestations, certificats, EDT, PV conseil, liste de classe, fiche d'inscription, bordereau journalier, état des frais) reprennent maintenant les couleurs et la devise de l'établissement. Composants visuels unifiés : entête République de Côte d'Ivoire avec logo, blocs signatures premium, tableaux zebra, pastilles de statut sémantiques, mentions cadrées *(tous)*.
- Création de tenant : les slugs réservés (`admin`, `api`, `auth`, `www`, `local`, `super-admin`, ...) sont désormais refusés à la création pour éviter toute collision avec un chemin plateforme *(super-admin)* (#136).
- Lien de connexion configurable via `PUBLIC_LOGIN_URL_TEMPLATE` : par défaut `https://college.klassci.com/login?c=<slug>` (pattern single-domain), bascule vers sous-domaine sans changement de code *(devops)* (#136).
- Provisionnement d'un nouvel établissement en libre-service : nouveau rôle « Super Administrateur », tableau de bord dédié et création de tenant en quelques clics, avec validation en direct du nom d'URL et progression visible des étapes *(super-admin)* (#134).
- Onboarding par ligne de commande pour les agents IA : le CLI `klassci` (`tenant create`, `tenant list`, `pat create`, `doctor`, `db query`, `logs`, `alembic`, etc.) permet de provisionner et opérer la plateforme sans passer par le navigateur ni SSH *(super-admin, devops)* (#134).
- Tokens d'accès personnels (PAT) : créer, lister, et révoquer ses propres tokens avec scopes (`super-admin:tenants:read`, `super-admin:db:execute`, …), expiration obligatoire (90 jours par défaut), et affichage du token clair une seule fois à la création *(super-admin)* (#134).
- Diagnostic de plateforme : vue temps réel de l'état du backend, de la base, de Redis et de la configuration SMTP avec rafraîchissement automatique toutes les 30 secondes *(super-admin)* (#134).
- Lecture des logs système avec masquage automatique des secrets : les en-têtes Authorization, mots de passe, tokens PAT, JWT et adresses email sont remplacés par `[REDACTED]` à la volée. Pause / reprise automatique toutes les 5 secondes *(super-admin)* (#134).
- Exécution de requêtes SQL ad-hoc sur n'importe quel tenant via une page dédiée ou en CLI, avec mode aperçu (`dry_run`) qui détecte les `DROP / TRUNCATE / DELETE sans WHERE` avant exécution et trace l'identité de l'exécutant dans les logs d'audit *(super-admin)* (#134).
- Navigation cross-tenant en lecture seule : `klassci student list --tenant=lycee-x`, `klassci teacher list`, `klassci class list` listent les entités d'une école depuis n'importe quel poste *(super-admin)* (#134).
- Re-provisionner un tenant déjà bootstrapped renvoie maintenant une erreur claire (HTTP 409) au lieu de planter avec une duplicate-email — l'admin existant garde son mot de passe et n'est jamais écrasé silencieusement *(super-admin)* (#134).
- Tableau de bord parent : un seul appel retourne pour chaque enfant la classe, la moyenne générale, le nombre d'absences et le solde restant à payer, sans avoir à ouvrir chaque fiche *(parent)* (#120).
- **Attestation de fréquentation officielle** : PDF République de Côte d'Ivoire signé par le chef d'établissement avec un tableau des statistiques de présence (présent / retard / absence excusée / absence non excusée) et un taux de fréquentation calculé sur l'année scolaire en cours. Endpoint `GET /students/{id}/documents/attestation-frequentation.pdf` avec les mêmes gardes d'accès que le certificat *(admin, parent, élève)* (#109).
- **Certificat de scolarité officiel** : l'admin (et le parent en self-service) peut télécharger un PDF République de Côte d'Ivoire signé par le chef d'établissement, avec corps formel "Le soussigné certifie que [élève], né(e) le ... à ..., est régulièrement inscrit(e) en classe de [...] au titre de l'année scolaire [...]". Endpoint `GET /students/{id}/documents/certificat-scolarite.pdf` avec garde d'accès parent (lien parent_student) et étudiant (compte propre) *(admin, parent, élève)* (#107).
- Trois champs sur les paramètres de l'établissement pour signer officiellement les documents administratifs : signature/tampon (image), nom du chef d'établissement, et son titre. Endpoint d'upload dédié pour la signature et permissions seedées pour les futurs documents *(admin)* (#105).
- Le logo de l'établissement et la signature officielle sont désormais embarqués dans tous les PDFs (bulletin, PV de conseil, reçu de paiement, emploi du temps) lorsqu'ils sont configurés. L'absence de configuration ne casse rien, le PDF se génère sans logo *(admin)* (#105).
- Promotion en masse de fin d'année : l'admin choisit la classe de destination de chaque classe source et obtient en un appel un aperçu des élèves promus, des avertissements de capacité, et un rapport de promotions appliquées avec les exceptions *(admin)* (#95).
- Validation d'inscription en un appel dédié : l'admin peut désormais passer un prospect ou une inscription en attente directement à l'état validé, avec audit traçable et message clair si la transition est refusée *(admin)* (#93).
- Liste des élèves côté admin enrichie de la classe et du statut d'inscription pour l'année courante : un seul appel API au lieu de cliquer chaque fiche pour savoir où l'élève est *(admin)* (#82).
- Filtres par classe et liste des élèves « à inscrire » exposés en un endpoint dédié, prêt à alimenter les chips de la liste élèves *(admin)* (#82).
- Création d'évaluation par un admin ou un personnel administratif au nom d'un enseignant, avec contrôle d'identité du titulaire et trace d'audit *(admin, enseignant)*.
- Endpoint exposant les permissions effectives de l'utilisateur courant, consommé par les portails pour afficher uniquement les actions autorisées *(tous)*.
- Outils de provisioning : script de seed déterministe pour les comptes admin / enseignant / élève / parent des scénarios E2E. Le compte parent est lié à un élève seedé pour exercer les flows portail parent *(devops)* (#118).
- Tableau de bord élève : nom, classe, prochain cours, moyenne générale, frais restants et total d'absences, en un seul appel *(élève)* (#75).
- Liste exhaustive des évaluations de l'enseignant connecté pour alimenter la page « Mes évaluations » côté portail *(enseignant)* (#75).

### Changed

- Les classes (6ème A, Terminale C, …) deviennent permanentes : on ne crée plus une nouvelle classe à chaque rentrée. À chaque changement d'année, la classe reste, on réinscrit ou on promeut les élèves, et la promotion devient un simple choix de destination *(admin)* (#97).
- Audit des changements de permissions de rôle : on garde désormais l'état avant et après pour reconstruire le diff de chaque modification *(admin, super-admin)*.
- Tableau de bord enseignant repensé : nom, prochain cours, totaux et liste des évaluations à venir avec progression de saisie, en cohérence avec ce qu'affiche le portail *(enseignant)* (#75).
- Création d'évaluation : la matière doit être enseignée dans la classe sélectionnée. Toute combinaison incohérente est refusée avec un message clair en français *(admin, enseignant)* (#76).
- Liste des matières filtrable par classe : on n'affiche plus que les matières du niveau (et de la série) de la classe demandée *(admin)* (#76).

### Removed

- Génération asynchrone des bulletins via Celery + Puppeteer : flow orphelin depuis le pivot architectural d'avril 2026. La génération sync via WeasyPrint reste seule porte d'entrée *(devops, super-admin)* (#103).
- Endpoints `POST /bulletins/generate` et `GET /bulletins/tasks/{task_id}` exposés à la racine : remplacés par les endpoints `/reports/bulletins/*` qui retournent directement les bulletins générés sans détour Celery (#103).

### Added

- Endpoint `GET /reports/bulletins` avec filtres optionnels (`class_id`, `trimester`, `academic_year_id`, `is_published`) pour la consultation transverse côté admin (#103).
- Endpoint `GET /reports/bulletins/{bulletin_id}` pour récupérer un bulletin précis par identifiant (utilisé par la modale de prévisualisation côté admin) (#103).

### Changed

- Publication des bulletins : la réponse expose désormais un message lisible et un compteur (`{message, count}`) au lieu d'un objet brut, pour cohérence avec le contrat utilisé côté front *(admin)* (#103).

### Fixed

- Fiche enseignant : la vue d'ensemble (nombre de classes, d'élèves, d'évaluations, heures par semaine) restait à zéro à cause d'une 500 silencieuse sur le profil enrichi. Tous les indicateurs s'affichent désormais correctement *(admin)* (#114).
- Liste des bulletins (`GET /reports/bulletins`) qui renvoyait une 500 « Internal Server Error » à cause d'un `NULLS LAST` dans le tri par rang non supporté par MySQL. Remplacé par l'astuce portable `IS NULL` qui place les bulletins sans rang en queue *(admin)* (#113).
- Publication des bulletins : la mise à `publié` ne s'appliquait à aucune ligne (les notifications aux parents n'étaient jamais envoyées). Bug silencieux d'un `not` Python évalué au chargement du module au lieu d'un filtre SQL (#101).
- Frais optionnels (cantine, transport, activités) qui n'étaient jamais récupérés automatiquement à l'inscription d'un élève : seuls les frais obligatoires apparaissaient. Même bug `not` Python sur la colonne SQLAlchemy *(admin)* (#101).
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
