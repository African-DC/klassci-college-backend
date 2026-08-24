# Changelog

Toutes les évolutions notables de KLASSCI College Backend (FastAPI) sont
documentées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et
le projet adhère à [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

### Added
- Une inscription créée prévient qui doit encaisser ; le versement enregistré prévient qui doit valider *(admin)*
- Les notifications de tâche s'adressent à quiconque détient la permission concernée, quel que soit le nom de son rôle dans l'école *(tous)*
- Annuler un versement exige un motif écrit, conservé avec la date et le nom du signataire, repris sur le reçu réimprimé et sur le bordereau de caisse *(caissier, comptable, directeur)*
- L'annulation ne couvre que la saisie en trop, quand aucun argent n'a bougé. Un encaissement réel non dû, ou une imputation sur le mauvais frais, restent à traiter *(comptable)*
- L'enseignant déclare lui-même ses plages d'indisponibilité depuis son portail, et l'administration peut les saisir à sa place quand il a prévenu de vive voix *(enseignant, directeur des études, secrétariat)*
- Poser un créneau montre la semaine de l'enseignant choisi avant de choisir l'horaire : ses cours dans les autres classes et ses plages fermées *(directeur des études, secrétariat, admin)*
- Chaque versement dit qui l'a encaissé : le nom du caissier apparaît dans la liste, dans le reçu et dans les deux exports, et la comptabilité peut isoler une caisse pour la contrôler *(comptable, directeur, caissier)*
- Le journal des versements s'exporte en PDF au gabarit officiel de l'établissement, avec récapitulatif par moyen de paiement et par caissier, et signatures caissier / comptabilité *(comptable, caissier)*
- Le même journal s'exporte en classeur Excel aux couleurs et au logo de l'école, en deux feuilles : le détail ligne à ligne et le récapitulatif, montants calculables et en-têtes répétées à l'impression *(comptable)*
- Installation d'une année scolaire de démonstration complète, de la 6e à la Terminale : élèves, familles, notes, bulletins, versements et vie scolaire *(super-admin, admin)*
- Contrôle automatique que les vingt et un documents officiels s'impriment vraiment sur un établissement de démonstration, avant de le présenter *(super-admin)*
- Le lieu de naissance de l'élève se saisit à la création, à la modification et à l'inscription, et se retrouve sur le certificat de scolarité, l'attestation de fréquentation et la fiche d'inscription, sous la forme « né(e) le ... à ... » attendue par l'administration *(secrétariat, admin, parent)*
- Les listes nominatives du rapport de fin de trimestre remplissent enfin leur colonne « Lieu de naissance », qui sortait vide faute d'être collectée *(directeur, admin)*
- Wave, MTN MoMo, Orange Money et Moov Money se saisissent et se totalisent séparément à la caisse, au lieu d'un « mobile money » unique que le comptable devait démêler pour rapprocher ses relevés *(caissier, comptable)*
- Chaque profil qui encaisse se voit attribuer ses propres moyens de paiement depuis Paramètres : retirer les espèces au comptable prend deux clics, et l'écran prévient qu'autoriser les espèces engage une journée de caisse à ouvrir et à compter *(directeur, admin)*
- Le formulaire d'encaissement ne propose que les moyens que la personne peut réellement utiliser : plus de choix offert puis refusé au moment d'enregistrer *(caissier, comptable, secrétariat)*
- Corriger le montant d'un frais propose de le répercuter sur les inscriptions déjà enregistrées, avec l'impact chiffré avant de confirmer : lignes à mettre à jour, lignes conservées parce qu'un versement y est imputé, et écart total de dette en francs. Répondre non ne change rien *(admin, comptable)*
- Une journée de caisse oubliée est clôturée d'office à minuit, sans montant compté ni écart inventé : la comptabilité du lendemain repart sur une caisse arrêtée *(caissier, comptable)*
- Le caissier retrouve à sa connexion ses journées clôturées d'office et les régularise en saisissant ce qu'il avait compté, ce qui fait naître l'écart réel *(caissier)*
- Le point journalier distingue les caisses arrêtées par leur caissier de celles clôturées d'office, dont l'écart reste inconnu tant que personne n'a compté *(comptable, directeur)*
- L'élève et le parent téléchargent le bulletin depuis leur portail : l'élève le sien, le parent celui de ses enfants, sans passer par le droit qui ouvre les bulletins de toute l'école *(élève, parent)*
- Une tranche de paiement s'exprime au choix en pourcentage ou en montant ferme, et les deux se mélangent dans la même grille : « Inscription 37 000 F à la rentrée », puis 35 / 35 / 30 % du reste *(admin, comptable)*
- Une catégorie de frais dit désormais ce qu'elle donne droit, élément par élément : ce qui se retire au guichet et ce qui s'ouvre comme accès *(admin, comptable)*
- Le reçu de versement porte, sous le montant, ce que la famille obtient contre les frais réglés ce jour : le parent repart avec la preuve écrite de sa tenue et de ses macarons *(parent, caissier, secrétariat)*
- L'état des frais annonce, sous le tableau, ce que chaque frais ouvre à la famille, en plus de son montant *(parent, secrétariat)*
- Le reçu de versement s'imprime en deux exemplaires sur une seule feuille A4, à couper au milieu : un pour la famille, un pour le classeur *(caissier, comptable)*
- Chaque exemplaire du reçu porte la situation financière de l'élève, frais par frais : ce qui est dû, ce qui est déjà versé et ce qu'il reste à payer, avec la prochaine échéance ou le retard *(caissier, comptable, parent)*

### Changed
- L'en-tête des documents devient une carte à coins arrondis portant le logo et les coordonnées de l'établissement *(tous)*
- Le bulletin porte l'en-tête administratif ivoirien : autorité à gauche, titre encadré au centre, année à droite, puis le bloc établissement *(parent, admin)*
- Le bulletin est refait sur le modèle officiel ivoirien : identité avec photo, points par discipline, total, progression d'un trimestre à l'autre, distinctions et sanctions à cocher *(parent, élève, enseignant)*
- Le bulletin porte la photo de l'élève, ou ses initiales, ainsi que son matricule, sa date et son lieu de naissance, comme le bulletin officiel ivoirien *(parent, élève)*
- Le bulletin affiche la colonne des points (moyenne × coefficient) et la ligne de total : le parent peut refaire le calcul de la moyenne générale *(parent, enseignant)*
- La liste des évaluations et celle des bulletins s'affichent par pages : elles rapatriaient toute l'année scolaire pour n'en montrer que vingt lignes, et mettaient plus de quatre secondes à s'ouvrir *(admin, directeur des études, enseignant)*
- Le « 12 / 35 » d'une évaluation est compté par la base et non plus en chargeant les 30 000 notes de l'école *(admin, enseignant)*
- Seules les espèces exigent désormais une journée de caisse ouverte. Un comptable enregistre un virement ou un versement Wave sans qu'une caisse s'ouvre à son nom, alors qu'il n'a aucun tiroir à compter le soir *(comptable, caissier)*
- Les versements enregistrés autrefois en « Mobile Money » gardent ce libellé sur les reçus déjà remis et dans les états : personne ne peut deviner après coup quel opérateur c'était, et le réécrire ferait mentir un papier détenu par une famille *(comptable, parent)*
- Une famille en retard sur son échéancier ne consulte plus le contenu du bulletin : moyenne, rang et mention sont retenus comme l'était déjà le PDF. Le bulletin reste annoncé à l'écran, avec le motif et le montant à régler *(élève, parent)*
- Les notes publiées restent consultables même en cas d'impayé : la retenue porte sur le bulletin, pas sur le relevé des notes *(élève, parent)*
- Les pourcentages d'une grille portent désormais sur ce qui reste après les montants fermes, jamais sur le total. Une école qui n'utilise que des pourcentages retrouve exactement les mêmes échéances qu'avant *(comptable, caissier)*
- L'échéancier annonce la part des frais qu'aucune tranche ne planifie, au lieu de laisser un écart inexpliqué entre les échéances et le total dû *(comptable, secrétariat)*

### Fixed
- Un élève dont l'inscription est ouverte mais pas encore validée n'est plus présenté comme « à inscrire » *(admin)*
- Poser un créneau sans salle était refusé par « La salle « » n'existe pas » *(admin, directeur des études)*
- Un enseignant déclaré disponible toute la matinée ne pouvait recevoir qu'une heure de cours d'affilée : les heures déclarées se recollent désormais *(directeur des études, secrétariat, admin)*
- Noter une seule absence rendait l'enseignant impossible à placer toute la semaine : une absence ne ferme plus que son propre créneau *(directeur des études, secrétariat, admin)*
- Le cahier de textes est désormais numéroté : sur vingt-sept pages, on ne pouvait ni se repérer ni voir qu'il en manquait une *(enseignant, admin)*
- Les traits de signature se soudaient en un seul filet : on ne voyait plus où signait le professeur et où signait le chef d'établissement *(tous)*
- L'emploi du temps s'arrêtait au dernier jour occupé : un vendredi sans créneau disparaissait de la semaine *(admin, enseignant, élève)*
- Les feuilles d'appel et de notes n'avaient aucune case où écrire : les colonnes n'existaient qu'en en-tête *(enseignant)*
- Le bulletin annonçait le code de l'établissement comme une direction régionale *(parent, admin)*
- Le relevé de notes coupait l'intitulé des évaluations à dix-sept signes *(enseignant)*
- Le procès-verbal du conseil imprimait « passage » en minuscules au lieu de la décision en toutes lettres *(admin, enseignant)*
- Les montants du bordereau de caisse s'écrivaient sans séparateur de milliers (« 155000.00 » au lieu de « 155 000 ») *(caissier, comptable)*
- Un compteur à zéro s'affichait en vert ou en orange, comme s'il annonçait une réussite ou une alerte *(tous)*
- Sur tous les documents, les cartes de compteurs, les blocs des responsables légaux et les intitulés de champ se touchaient au lieu d'être espacés *(tous)*
- Les mentions d'État en tête de document se lisaient comme un filigrane : la République prend désormais le premier rang, la devise et le ministère suivent *(tous)*
- Sur la fiche d'inscription, les intitulés étaient collés à leurs valeurs (« SEXEFéminin ») et le cadre photo affichait le mot « Photo » *(admin, parent)*
- La décision du conseil s'imprimait en identifiant technique (« CouncilDecision.PASSAGE ») sur le bulletin remis aux familles *(parent)*
- Un créneau refusé dit enfin pourquoi : quel enseignant, à quelle heure, et avec quelle classe il est déjà pris, au lieu d'un refus sans explication *(directeur des études, secrétariat, admin)*
- La grille de disponibilités d'un enseignant affichait sa semaine fermée alors que la saisie manuelle d'un créneau l'acceptait quand même : les deux appliquent désormais la même règle que la génération automatique *(directeur des études, admin)*
- Le reçu d'un versement ne se générait plus : « Génération impossible ». La famille repartait sans sa preuve de paiement *(caissier, parent)*
- La caissière lisait les chiffres de toute l'école au-dessus d'un tableau qui ne contenait que ses versements *(caissier)*
- La recherche par nom d'élève et le filtre par catégorie de frais étaient acceptés puis ignorés : le tableau ne bougeait pas *(caissier, comptable)*
- Un export des versements ne déverse plus que la caisse de celui qui le demande : un caissier obtenait jusqu'ici les mêmes documents qu'un comptable, alors que son écran ne lui montre que ses propres encaissements *(caissier, comptable, directeur)*
- Le bordereau journalier du comptable était signé « Le Caissier » au nom de la personne qui l'imprimait : une pièce comptable récapitulant trois caisses désignait ainsi le comptable comme caissier *(comptable, directeur)*
- Le bordereau nommait les personnes par le début de leur adresse e-mail, « accountant6 » ou « cashier3 », au lieu de leur nom sur la fiche Personnel *(comptable, caissier)*
- Le bordereau consolidé ne disait pas qui avait encaissé quoi : il ventile désormais par caisse et par moyen de paiement, et le détail porte une colonne Caissier *(comptable)*
- La date du bordereau s'écrivait en anglais, « Friday 21 August 2026 », en tête d'une pièce comptable française *(comptable, caissier)*
- Un refus de changement de statut affichait au guichet « impossible de passer de 'PaymentStatus.COMPLETED' », un nom technique interne, et le journal d'audit financier en gardait la trace *(caissier, comptable)*
- La notification de clôture d'office s'accordait mal au pluriel : « Votre journées de caisse du 19/08, 20/08 ont été clôturées » *(caissier)*
- Le balayage de nuit comptait comme des échecs les bases de données étrangères hébergées sur le même serveur : le compteur d'incidents ne signalait plus rien *(devops)*
- Regénérer un procès-verbal de conseil de classe déjà établi échouait sur une erreur technique : le second essai passe désormais, comme le premier *(admin, directeur des études)*
- Le courriel qui prévient la direction d'une suppression ne partait jamais : l'envoi échouait au moment de nommer l'auteur du geste, et l'échec était avalé pour ne pas bloquer la suppression. La direction se croyait avertie et ne l'était pas *(admin, directeur)*
- Le certificat de scolarité déclarait l'élève né dans sa ville de résidence : faute de lieu de naissance en base, il recopiait le domicile. Un élève né à Bouaké et habitant Cocody était certifié « né à Cocody » sur une pièce officielle *(secrétariat, parent, directeur)*
- Le récapitulatif par moyen de paiement du bordereau journalier et de l'écran caisse omettait tout moyen qu'il ne connaissait pas, alors que le total continuait de le compter : la somme des lignes ne collait plus au total imprimé juste en dessous *(caissier, comptable)*
- Un versement enregistré depuis l'ancien écran de paiement passait même sur une journée de caisse déjà clôturée, ce que le nouvel écran refusait déjà *(caissier)*
- Un élève inscrit depuis le formulaire complet ne recevait AUCUN frais : sa fiche annonçait « 0 F » à la famille et la caisse n'avait rien à encaisser *(secrétariat, caissier, comptable)*
- Le statut d'affectation était bien enregistré mais jamais relu : tout écran affichait « non renseigné » sur une valeur pourtant saisie *(secrétariat, admin)*
- La capacité maximale d'une classe n'était pas vérifiée à l'inscription : le contrôle comptait les élèves d'une année inexistante *(secrétariat)*
- La régénération des frais annonçait « aucun frais à régénérer » après en avoir créé : elle ne comptait que les suppressions *(admin)*
- Les frais d'inscription, dus en totalité le jour de l'inscription, étaient étalés sur les tranches de scolarité : l'échéancier réclamait 43 750 F fin novembre là où l'école attend 37 000 F à la rentrée puis 30 800 F. Une famille pouvait ainsi se voir retenir un certificat sur un calendrier que l'école n'avait jamais annoncé *(comptable, parent, secrétariat)*
- Un montant ferme ne réclame jamais plus qu'un élève ne doit : un affecté subventionné ne se voit plus présenter l'échéancier d'un non affecté *(comptable)*
### Security
- Supprimer définitivement une fiche coupe désormais l'accès au logiciel : le compte de connexion est désactivé et ses jetons révoqués dans le même geste. Une comptable renvoyée dont on supprime la fiche le lundi ne se reconnecte plus le mardi avec son mot de passe, ni depuis une session restée ouverte *(admin, directeur)*
- Le journal d'audit et le courriel de traçabilité disent maintenant ce qu'est devenu le compte : « fiche supprimée, accès révoqué » n'est pas la même information que « fiche supprimée » *(admin, directeur)*

### Changed
- Le registre des convocations et celui des billets d'annulation de zéro se consultent par pages : ils s'empilent d'une année sur l'autre et chargeaient jusqu'ici tout leur historique pour n'en montrer que le haut *(éducateur, secrétariat)*
- Le motif d'une suppression définitive ne circule plus dans l'adresse de la page : il n'apparaît donc plus dans les journaux techniques du serveur *(admin, directeur)*
- Supprimer définitivement une inscription obéit aux mêmes règles que supprimer un élève : motif obligatoire, passage par la corbeille d'abord, courriel à la direction *(admin, directeur)*
- Encaisser sur une inscription qui porte plusieurs frais est plus rapide : la caisse interroge la base une fois au lieu d'une fois par frais *(caissier)*

### Fixed
- L'éducateur et le secrétariat peuvent enfin délivrer un billet d'annulation de zéro : l'écran demandait les évaluations manquées par le cahier de notes de la classe, que ni l'un ni l'autre n'a le droit de lire, et refusait donc leur premier clic *(éducateur, secrétariat)*
- Les quatre compteurs du registre des convocations décrivent l'année consultée et non le filtre en cours : cliquer « Tuteur absent » affichait « Convocations 8, Tuteur venu 0, Tuteur absent 8 » *(éducateur)*
- Une inscription pouvait être détruite sans motif, sans passer par la corbeille et sans que personne n'en soit averti *(admin, directeur)*
- Un élève affecté pouvait porter deux fois la même scolarité, l'une au tarif général et l'autre au tarif affecté : les lignes en double sont fusionnées et la base interdit désormais qu'elles se recréent *(comptable, secrétariat)*
- Le taux d'avancement du tableau de bord contredisait les fiches des élèves : il comparait les versements encaissés à un total qui comptait aussi les frais facultatifs et les frais exonérés *(directeur, comptable)*
- Une famille exonérée après avoir payé restait comptée comme ayant payé dans les chiffres de l'école *(comptable, directeur)*
- Un tarif réservé aux affectés ou aux non affectés ne pouvait plus redevenir universel : le formulaire acceptait « Tous les élèves » et rien ne changeait. Une portée cochée par erreur obligeait à supprimer le tarif, ce que la présence d'un élève inscrit dessus interdit *(comptable, admin)*
- Une portée mal orthographiée était enregistrée telle quelle et ne correspondait plus jamais à aucun élève ; seules les deux valeurs du métier sont désormais acceptées *(comptable, admin)*
- Une famille exonérée après avoir payé paraissait en avance sur sa scolarité et n'était plus signalée en retard : l'argent imputé à un frais annulé sort désormais du calcul *(comptable, caissier)*
- Sur une fiche parent, le solde dû et le badge « à jour » pouvaient se contredire : les deux reposent maintenant sur les mêmes frais *(secrétariat, comptable)*
- Un billet d'entrée dont l'impression échouait laissait l'absence régularisée sans papier, et la relance était refusée ; l'absence reste ouverte tant que le billet n'est pas produit *(éducateur)*
- Un billet d'entrée perdu ou mal imprimé peut être réédité : la réimpression ne modifie plus rien dans le cahier d'appel *(éducateur)*
- L'observation notée dans le cahier d'appel, « parti à l'infirmerie », est conservée au journal avant d'être remplacée par la mention du billet *(éducateur)*
- Un doublon sur une contrainte à plusieurs colonnes conseillait « choisissez un autre nom » devant un formulaire qui n'a pas de champ « nom ». Le message se décide maintenant sur la contrainte violée, et non sur l'apparence de la valeur *(admin, comptable)*
- Deux points d'entrée de l'API annonçaient le dépôt de justificatifs sur une inscription alors qu'aucun code ne les servait : ils échouaient à chaque appel. Les justificatifs se déposent sur la fiche de l'élève, où ils ont toujours fonctionné *(admin)*
- Les erreurs inattendues affichent enfin leur code de référence à l'écran ; le navigateur bloquait jusqu'ici la réponse et l'utilisateur ne voyait qu'une erreur réseau *(admin)*
- La suppression définitive d'un enseignant, d'un membre du personnel ou d'un parent envoie désormais le courriel de traçabilité, comme celle d'un élève *(admin)*

### Added
- Les évaluations manquées d'un élève sur une période s'obtiennent directement, sans passer par le cahier de notes de sa classe : le formulaire du billet d'annulation de zéro les affiche en une requête au lieu d'une quarantaine *(éducateur, secrétariat)*
- Sexe et type de contrat de l'enseignant, permanent, vacataire ou fonctionnaire, saisissables sur sa fiche. Les deux synthèses du rapport de fin de trimestre qui restaient vierges faute de ces informations se remplissent désormais seules *(admin)*
- Type de contrat et sexe des enseignants sur leur fiche. Les deux synthèses du rapport de fin de trimestre qui restaient vierges faute de ces informations se remplissent désormais seules *(admin, directeur)*.
- Rapport de fin de trimestre pour la DEEP, au canevas officiel des 27 tableaux, téléchargeable en un clic pour le trimestre choisi *(admin, directeur)*.
- Les tableaux que la plateforme ne sait pas remplir sortent vierges avec la mention « à compléter manuellement », jamais garnis de zéros : à la DRENA, un zéro se lit comme un constat *(admin, directeur)*.
- Quatre actes de vie scolaire imprimables à l'en-tête officiel du collège : demande de dossier scolaire, billet d'entrée, convocation de parent et billet d'annulation de zéro *(secrétariat, éducateur, directeur des études)*.
- Le billet d'entrée régularise l'absence qu'il vise : le cahier d'appel et le papier remis à l'élève disent enfin la même chose *(éducateur)*.
- Registre des convocations : qui a été convoqué ce trimestre, qui est venu, qui ne s'est pas présenté *(éducateur, directeur des études)*.
- Le billet d'annulation de zéro rouvre les évaluations réellement manquées et ne saisit jamais la note de rattrapage, qui reste la main de l'enseignant *(éducateur, enseignant)*.
- Un élève absent à une épreuve se marque « absent » et non plus « non saisi » : le zéro d'office compte dans la moyenne, et reste rattrapable *(enseignant)*.
- Paramètres de l'établissement : DRENA de rattachement, seconde devise, armoiries, deux numéros de téléphone ; sur la fiche élève, établissement d'origine et décision de transfert *(admin, secrétariat)*.
- Corbeille sur les fiches qui portent une histoire : élèves, parents, enseignants, personnel et inscriptions. Les archiver les retire de tous les écrans sans rien détruire, et on peut les restaurer. La suppression définitive ne se fait qu'ensuite, depuis la corbeille, et reste réservée à la direction *(admin, directeur)*.
- Archiver comme supprimer exigent un motif, repris dans le journal d'audit et destiné à être envoyé par courriel à la direction *(admin, directeur)*.
- Chaque mise à la corbeille et chaque suppression définitive part par courriel à la direction : qui a agi, quand, sur quelle fiche, pour quel motif, et ce qui est parti avec. Les destinataires se règlent dans les paramètres de l'établissement ; sans liste, le message part à l'adresse de l'école. Un courriel sort du logiciel : si quelqu'un efface une trace, il n'efface pas une boîte de réception. Une messagerie injoignable n'empêche jamais une suppression *(admin, directeur)*.
- Les versements encaissés survivent à la suppression d'un élève : l'inscription et les frais partent, l'argent reste, avec le nom et le matricule de l'élève figés sur chaque versement. Le bordereau journalier, le point journalier et les reçus réimprimés continuent d'afficher le nom et de totaliser la même somme qu'avant la suppression *(caissier, comptable)*.
- Écran corbeille : toutes les fiches mises de côté au même endroit, de la plus récente à la plus ancienne, avec le motif et son auteur, filtrable par sorte de fiche *(admin, directeur)*.
- Statut d'affectation sur l'inscription : affecté, réaffecté ou non affecté, avec le numéro de décision. Un tarif peut désormais ne valoir que pour les affectés ou que pour les non affectés, et l'inscription prend automatiquement le bon montant. Un élève subventionné par l'État ne paie plus comme un non affecté *(comptable, secrétariat)*.
- Supprimer une catégorie de frais annonce d'abord ce qu'elle emporte : « 3 montants configurés et 47 frais d'élèves seront supprimés, confirmez pour continuer ». Dès qu'un versement est imputé dessus, la suppression est refusée même confirmée *(comptable, admin)*.
- L'ordre d'imputation d'une catégorie de frais se règle à la création : jusqu'ici toute nouvelle catégorie était servie en dernier, sans moyen de la remonter *(comptable)*.
- Le comptable configure aussi les niveaux et les séries : la grille tarifaire s'y décline, et il restait bloqué au milieu de sa configuration dès qu'un niveau manquait *(comptable)*.

- Tranches de paiement : l'établissement découpe le total des frais obligatoires en tranches exprimées en pourcentage, avec une date limite chacune, une grille par année scolaire dont la somme doit faire 100 %. Le montant attendu suit automatiquement le total de chaque élève, sans ressaisie par niveau *(comptable)*.
- Échéancier négocié : une famille peut obtenir son propre calendrier en montants fermes, qui prime sur la grille de l'établissement. Le total doit correspondre exactement aux frais obligatoires *(comptable)*.
- Retard de paiement calculé sur ce qui est **déjà exigible** et non sur le total de l'année : une famille qui respecte son échéancier n'apparaît jamais en impayé *(tous)*.
- Moyens de paiement acceptés configurables par l'établissement. Tant que rien n'est configuré, tous restent acceptés *(comptable)*.
- Journée de caisse : le caissier voit ce qu'il a encaissé, ventilé par moyen de paiement, puis clôture en saisissant les espèces comptées. Le système affiche l'écart avec le théorique et verrouille la journée. Le comptable dispose du point journalier de toutes les caisses, clôturées ou non, avec leur écart *(caissier, comptable)*.
- Ce qu'une famille doit n'est plus visible de tous : les montants sont réservés à qui manipule l'argent (comptable, caissier, secrétariat qui encaisse, direction). L'éducateur et le directeur des études voient désormais un état « à jour » ou « en retard » et la date du dernier versement, sans aucune somme, ce qui suffit à valider un dossier *(tous)*.
- Le secrétariat garde sa propre caisse mais ne voit plus les encaissements des autres guichets ni la trésorerie consolidée, qui restent au comptable *(secrétariat, comptable)*.
- Journal d'audit consultable : qui a fait quoi, sur quelle fiche et quand, filtrable par type d'information, par personne, par action et par période, avec le détail des valeurs avant et après *(admin, directeur)*.
- Les consultations de dossiers sensibles sont désormais tracées, pas seulement les modifications : ouvrir la fiche d'un élève, un versement, un bulletin ou une fiche du personnel laisse une trace *(admin, directeur)*.
- Journal financier pour le comptable : il remonte un versement contesté jusqu'à la personne qui l'a saisi, sans accéder aux notes ni aux dossiers du personnel *(comptable)*.
- L'identité de l'auteur (adresse et rôle) est figée au moment de l'action : un compte supprimé ou réattribué n'efface plus la trace de ce qu'il a fait.
- Les consultations sont effacées au bout de six mois pour que le journal reste consultable ; les créations, modifications et suppressions sont conservées.
- Documents retenus en cas d'impayé : certificat de scolarité, attestation de fréquentation et bulletin ne sortent plus tant que des échéances arrivées à terme restent dues. Le refus annonce le montant exact et renvoie au secrétariat. Une famille à jour de son échéancier n'est jamais bloquée, même si le solde de l'année reste ouvert *(tous)*.
- Dérogation motivée réservée à la direction : le chef d'établissement peut délivrer un document malgré la dette en indiquant pourquoi, et chaque dérogation est journalisée *(admin, directeur)*.
- Trois nouveaux rôles pour coller à l'organisation réelle d'un collège : **caissier** (encaisse au guichet, sans accès à la trésorerie globale), **éducateur** (monte les inscriptions et réinscriptions, consulte les versements pour valider) et **directeur des études** (tout le pédagogique, aucun accès aux finances). Ils s'attribuent depuis la fiche d'un membre du personnel, chaque rôle indiquant en clair ce qu'il permet de faire *(admin, directeur)*.

### Fixed
- Rapport de fin de trimestre : les enseignants de sexe masculin étaient comptés dans les totaux mais dans aucune colonne, et signalés en plus comme « sexe non renseigné ». Les tableaux 19 et 21 déposés à la DRENA annonçaient un corps enseignant exclusivement féminin. Ils comptent désormais chacun dans sa colonne, et la fiche de l'enseignant affiche son sexe et son type de contrat au lieu de deux tirets *(admin, directeur)*.
- Rapport de fin de trimestre : les tableaux que la plateforme ne sait pas encore remplir sortaient en grille de zéros ou en blanc sans explication — visites de classe, formations, boursiers, synthèses par contrat et par sexe. Ils portent maintenant la mention « à compléter manuellement » et disent en une phrase ce qui manque. Un zéro déposé à la DRENA se lit comme un constat, pas comme une absence de saisie *(admin, directeur)*.
- Rapport de fin de trimestre : les colonnes « N° CNPS » et « N° autorisation d'enseigner » du personnel administratif sortaient vides sans le dire ; le document annonce désormais qu'aucun écran ne permet encore de les saisir *(admin, directeur)*.
- Actes de vie scolaire : émettre un second billet d'annulation de zéro ou une seconde convocation pour le même élève invalidait le premier papier, déjà remis à la famille. L'enseignant qui scannait le code du document du premier trimestre lisait « document remplacé ». Chaque acte garde désormais sa propre référence, et un billet réimprimé reste vérifiable *(éducateur, directeur des études, secrétariat)*.
- Actes de vie scolaire : tous les élèves sans matricule partageaient la même référence de document. Un échec d'impression bloquait alors l'édition pour toute l'école pendant cinq minutes. L'absence de matricule est maintenant refusée avec un message clair, qui indique de le renseigner sur la fiche de l'élève *(secrétariat, éducateur)*.
- Une école qui ajoutait un tarif affecté par-dessus sa grille existante voyait chaque élève affecté inscrit ensuite recevoir deux fois le même frais : dette doublée, échéancier doublé, et certificat de scolarité retenu pour un impayé qui n'existait pas. Un seul tarif s'applique désormais par catégorie de frais, le plus précis. Les frais déjà facturés en double sont fusionnés, sans perdre un seul versement *(admin)*.
- Régénérer les frais d'une inscription échouait sur toute famille ayant déjà versé quelque chose : l'opération voulait remplacer des frais sur lesquels de l'argent était imputé. Les frais payés sont désormais conservés, les autres remplacés, et le décompte des deux est annoncé *(secrétariat, comptable)*.
- Les accueils des portails parent et élève annonçaient un reste à payer trop élevé, et le détail sous un frais soldé n'affichait aucun versement : la famille pouvait croire son argent perdu. Chaque versement apparaît maintenant sous les frais auxquels il a été imputé *(parent, élève)*.
- Les portails parent et élève sous-estimaient les sommes versées depuis la refonte des paiements : une famille ayant versé 155 000 FCFA voyait « 95 000 restants » au lieu de 45 000. Le calcul est désormais le même partout *(parent, élève)*.
- Ajouter un montant à un niveau créait un doublon au lieu d'être refusé, et l'affichage par niveau en retenait un au hasard : d'où l'impression qu'un montant sautait d'un niveau à l'autre. La protection contre les doublons existait mais n'avait jamais fonctionné pour les niveaux de collège. Les doublons déjà en base sont fusionnés sans perdre un seul frais d'élève *(comptable, admin)*.
- Supprimer une série vidait silencieusement la série des classes qui l'utilisaient, en répondant « supprimé » : la base laisse désormais parler ses contraintes au lieu de détacher les données dans le dos de l'utilisateur *(admin)*.
- Plus aucun « Erreur serveur » muet : quand quelque chose d'imprévu se produit, l'écran affiche un message avec un code de référence à communiquer, et ce même code figure dans le journal du serveur. Les téléchargements Excel, qui échouaient jusque-là en silence, sont couverts aussi *(tous)*.
- Les messages de conflit disent enfin la bonne chose : créer un montant en double annonce la combinaison en cause au lieu d'un « 1-2-3-4 existe déjà », et enregistrer sur un élément supprimé entre-temps ne parle plus de suppression *(comptable)*.
- Retirer un échéancier négocié qui n'existait pas ne répond plus « supprimé » et n'écrit plus de trace pour une action qui n'a pas eu lieu ; définir un échéancier sur une inscription inconnue le dit, au lieu d'annoncer des frais à 0 FCFA *(comptable)*.
- Les « Erreur serveur » sur la configuration des frais sont remplacées par un message qui dit quoi faire : créer une catégorie dont le nom existe déjà annonce désormais le nom en cause, et supprimer un élément encore utilisé explique qu'il faut d'abord retirer ce qui en dépend. La règle vaut pour tout l'écran, pas seulement les frais *(tous)*.
- Le « reste à payer » d'un élève était surévalué : les versements enregistrés depuis la refonte des paiements n'étaient pas comptés dans le total de la fiche. Une famille ayant versé 155 000 FCFA en apparaissait à 105 000 *(admin, comptable)*.

- Le bordereau journalier imprimé par un caissier contenait les versements de toute l'école : le nom du caissier ne servait qu'à signer le document, pas à le filtrer. Chacun n'obtient désormais que sa propre caisse, le comptable gardant la vue consolidée *(caissier)*.
- Le comptable ne pouvait ouvrir aucun écran filtrant par année scolaire, dont la page Frais : il lui manquait le droit de lire les années. Il configure désormais la grille tarifaire complète (catégories, montants par niveau, options) et édite les rapports *(comptable)*.
- Le score de performance enseignant restait inaccessible sur les établissements récemment créés, faute d'un droit jamais installé à leur ouverture *(admin, directeur)*.
- Pipeline et production Windows : `PyMySQL` est épinglé à la version compatible avec `aiomysql`, et l'ancien déploiement EC2 automatique est retiré.
- Reçu de versement (PDF) : les informations de l'élève (nom, nature, méthode, référence, statut) sont désormais parfaitement alignées en colonnes, au lieu d'un rendu tassé et décalé *(admin, personnel)*.

### Changed

- Emploi du temps (PDF) refondu : tient désormais sur une seule page, avec une grille premium calée à la minute près (créneaux de 1h, 1h30, 2h ou débutant à la demi-heure placés exactement, comme à l'écran), des couleurs de matière claires et lisibles et une légende des matières *(admin, enseignant, élève, parent)*.
- Durée de connexion prolongée (jeton d'accès porté à 60 minutes) pour éviter les déconnexions intempestives d'un utilisateur pourtant actif ; la session reste limitée à 30 minutes d'inactivité *(tous)*.
- Relevé de notes (PDF) aligné sur le design institutionnel premium des autres documents : bandeau d'identité, titre de section, tableau soigné et synthèse en cartes clés (moyenne de classe, note min/max, taux de saisie) *(admin, enseignant)*.

### Added

- Sceau numérique institutionnel KLASSCI pour les certificats, attestations et bulletins : empreinte SHA-256 du PDF final signée intégralement en Ed25519 avec clé dédiée et rotative, cycle de vie versionné (expiration, révocation, remplacement), aucune identité d'élève dans la réponse publique et contrôle d'intégrité du fichier. L'ancien mécanisme reste vérifiable pour les documents déjà distribués, sans être présenté comme un CEV qualifié *(tous)*.
- Gestion des comptes de connexion depuis la fiche d'un élève, parent, enseignant ou membre du personnel : voir l'état du compte (email, dernière connexion), créer le compte s'il n'existe pas (élève/parent) et réinitialiser le mot de passe. Le mot de passe temporaire est `Bonjour@<année>` et doit être changé à la première connexion *(admin, directeur, personnel)*.
- Statistiques DREN : véritable export en PDF (mise en page institutionnelle premium) et en Excel (trois feuilles : synthèse, niveaux et classes, matières), à la place de l'ancien fichier qui affichait des données brutes *(admin)*.
- Conseil de classe : les décisions de délibération se modifient en lot et le procès-verbal se valide définitivement (il devient alors non modifiable) *(admin)*.
- Feuille de notes vierge à imprimer pour une classe : l'enseignant récupère la liste de ses élèves prête à remplir à la main (colonnes de notes et moyenne), la matière et le trimestre pouvant être pré-renseignés *(enseignant, admin)*.
- Tableau de bord de l'élève : mise en avant de la dernière note obtenue (matière, note sur 20 et intitulé de l'évaluation) *(élève)*.
- MailPulse : nouvel espace de configuration des notifications parents par email et WhatsApp (activation, clé d'accès jamais réaffichée, expéditeur, destinataires de test avec interrupteur, envois réels désactivés par défaut) *(admin)*.
- MailPulse : envoi d'une notification de test (paiement, absence, note, rappel de frais) par email ou WhatsApp vers des destinataires dédiés, en mode simulation ou réel, sans jamais impliquer un vrai parent *(admin)*.
- MailPulse : notification automatique des parents par email et WhatsApp lors d'un paiement reçu, d'une absence signalée ou d'une note saisie, dans le respect des interrupteurs de l'établissement et une fois les envois réels activés *(parent, admin)*.
- MailPulse : réponse automatique aux parents qui écrivent « INFO » sur WhatsApp (classe, moyenne, absences et reste à payer de chaque enfant), sécurisée par un secret partagé propre à l'établissement *(parent, admin)*.
- Intérim : la direction assigne (ou retire) un enseignant remplaçant sur un congé approuvé ; le demandeur voit qui le remplace *(admin, enseignant)*.
- Demandes de congé : les enseignants et le personnel posent leurs congés (type, dates, motif) et suivent leur statut ; la direction consulte, approuve ou refuse avec un commentaire *(enseignant, personnel, admin)*.
- Documents de l'élève : l'administration téléverse des pièces (extrait de naissance, certificat médical, etc.) sur la fiche d'un élève, avec un type choisi dans un catalogue ou créé à la volée *(admin)*.
- Préférences de notifications : chaque utilisateur choisit, depuis son profil, de recevoir en plus les notifications par email et/ou SMS ; ces choix sont respectés à l'envoi. La notification dans l'application reste toujours active *(tous)*.
- Espace profil personnel : chaque utilisateur consulte ses informations (nom, contact, rôle) et met à jour son téléphone ; l'enseignant et le personnel téléversent ou retirent eux-mêmes leur photo, l'élève restant géré par l'administration *(tous)*.
- Rôle d'accès du personnel choisi à la création et modifiable (Personnel, Comptable, Directeur) : il détermine les droits d'accès dans KLASSCI et est renvoyé partout où le personnel est affiché, sans jamais permettre d'attribuer un rôle d'administrateur *(admin)*.
- Fiche parent enrichie : pour chaque enfant, sa classe, son statut d'inscription et son solde de frais restant, plus un récapitulatif financier global (total dû, payé, reste à payer sur l'année) pour voir d'un coup d'œil la situation du foyer *(admin)*.
- Fiche personnel enrichie d'un aperçu d'activité de l'année : versements encaissés (nombre et montant), inscriptions traitées et dernière connexion *(admin)*.

### Fixed

- Relevé de notes : le document sortait vide quand la matière choisie était rattachée à un niveau alors que les notes visaient l'entrée générique (ou l'inverse) ; il rapproche désormais les évaluations par nom de matière et affiche bien toutes les notes du trimestre *(admin, enseignant)*.
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
- L'emblème dessiné qui tenait lieu d'armoiries sur les actes de vie scolaire : les documents officiels ivoiriens n'en portent pas *(admin)*

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
