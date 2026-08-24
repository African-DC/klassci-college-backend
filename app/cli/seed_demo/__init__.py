"""Jeu de données de démonstration : un collège-lycée privé ivoirien complet.

Ce paquet peuple un locataire avec une **année scolaire vécue de bout en bout** :
sept niveaux de la 6e à la Terminale, des séries au lycée, des élèves aux noms
ivoiriens, leurs familles, l'équipe pédagogique et les six métiers du
secrétariat, l'emploi du temps, les trois trimestres de notes, les bulletins,
les conseils de classe, la grille tarifaire du collège pilote, les versements
imputés par le service de paiement, les journées de caisse, la vie scolaire et
les tables que le rapport officiel réclame sans qu'aucun écran ne les saisisse.

**Additif et relançable.** Chaque étape rapproche avant d'écrire, sur une clé
naturelle stable : matricule, référence de versement, couple (classe, jour).
Relancer le script ne duplique rien et ne détruit rien. Aucune table n'est
jamais vidée.

**Il passe par les services de l'application.** Les inscriptions, les frais, les
versements, les notes, les bulletins et les conseils sont écrits par le même
code que celui qu'utilise l'interface. Les allocations de versement sont donc
justes, les statuts cohérents, et le journal d'audit se remplit au passage.

Usage :

    python -m app.cli.seed_demo --tenant local

Reprendre une seule étape après un incident :

    python -m app.cli.seed_demo --tenant local --only cashdesk
"""
