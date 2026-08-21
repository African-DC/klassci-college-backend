"""Le contexte partagé par toutes les étapes du semis.

Un seul objet circule d'une étape à l'autre : la session, le tirage
reproductible, l'année scolaire visée et les identifiants déjà résolus. Sans
lui, chaque étape rechargerait les mêmes niveaux et les mêmes classes, et rien
ne garantirait qu'elles parlent des mêmes.

Le tirage est **déterministe**. C'est ce qui rend le script relançable : deux
exécutions produisent les mêmes noms, les mêmes notes et les mêmes montants,
donc les mêmes lignes : que l'on retrouve au lieu de les recréer.
"""

from __future__ import annotations

import hashlib
import logging
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("klassci.seed")

#: Graine du tirage. Toute valeur convient ; la changer change l'école entière.
SEED = 20_260_821

#: Domaines des adresses e-mail créées par le semis. Séparés pour qu'un
#: administrateur repère d'un coup d'œil ce qui vient de la démonstration.
STAFF_DOMAIN = "demo.klassci.ci"
FAMILY_DOMAIN = "familles.demo.klassci.ci"

#: Préfixe des matricules. Sert aussi de clé de rapprochement : c'est par lui
#: que le script retrouve un élève qu'il a déjà créé.
MATRICULE_PREFIX = "KLS26"

#: Mot de passe unique des comptes de démonstration. Assumé : ces comptes
#: n'existent que sur le locataire de démonstration, et un présentateur doit
#: pouvoir se connecter devant la salle sans chercher dans ses notes.
DEMO_PASSWORD = "Demo@2026"


@dataclass
class SeedContext:
    """Tout ce qu'une étape du semis doit savoir, et rien de plus."""

    db: AsyncSession
    tenant: str
    today: date
    #: Compte qui « signe » les écritures : c'est lui qu'on lira dans le
    #: journal d'audit et dans `created_by`.
    actor_id: int
    rng: random.Random = field(default_factory=lambda: random.Random(SEED))
    counts: Counter[str] = field(default_factory=Counter)

    # Année scolaire visée, renseignée par l'étape référentiel.
    academic_year_id: int = 0
    academic_year_name: str = ""
    next_year_id: int | None = None
    #: (rang, début, fin) de chaque trimestre, dans l'ordre.
    trimesters: list[tuple[int, date, date]] = field(default_factory=list)

    # Identifiants résolus, partagés entre étapes.
    level_ids: dict[str, int] = field(default_factory=dict)
    series_ids: dict[tuple[str, str], int] = field(default_factory=dict)
    #: (niveau, série|None, division) → identifiant de classe.
    class_ids: dict[tuple[str, str | None, str], int] = field(default_factory=dict)
    #: (niveau, série|None, matière) → identifiant de l'instance de matière.
    subject_ids: dict[tuple[str, str | None, str], int] = field(default_factory=dict)
    fee_category_ids: dict[str, int] = field(default_factory=dict)
    #: Enseignants du semis : nom de matière → identifiants de profils.
    teachers_by_subject: dict[str, list[int]] = field(default_factory=dict)
    #: Identifiants des profils de personnel, par métier.
    staff_by_role: dict[str, int] = field(default_factory=dict)
    #: Comptes utilisateur du personnel, par métier, pour `received_by`.
    staff_user_by_role: dict[str, int] = field(default_factory=dict)
    #: Élèves du semis : matricule → (identifiant élève, identifiant inscription).
    students: dict[str, tuple[int, int]] = field(default_factory=dict)

    def reseed(self, step: str) -> None:
        """Donne à l'étape son propre tirage, indépendant des autres.

        Sans cette remise à zéro, toutes les étapes puisaient dans un unique
        flux : ajouter un tirage dans le référentiel décalait tous ceux des
        étapes suivantes, et une relance ne reconnaissait plus les enseignants
        ni les convocations qu'elle avait elle-même semés. Le semis cessait
        d'être relançable dès qu'on touchait à une ligne, n'importe où.
        """
        digest = hashlib.sha256(step.encode("utf-8")).digest()
        self.rng = random.Random(SEED ^ int.from_bytes(digest[:8], "big"))

    def tally(self, label: str, amount: int = 1) -> None:
        """Compte ce que l'étape vient d'écrire, pour le récapitulatif final."""
        if amount:
            self.counts[label] += amount

    def matricule(self, index: int) -> str:
        """Le matricule d'un élève, jamais optionnel et jamais aléatoire."""
        return f"{MATRICULE_PREFIX}-{index:04d}"

    def trimester_of(self, day: date) -> int:
        """Le trimestre auquel appartient une date, le premier par défaut.

        Le défaut n'est pas un aveu d'ignorance : les seules dates qu'on lui
        soumet sont des dates de classe, donc à l'intérieur de l'année. Il
        évite simplement qu'un jour de congé oublié fasse planter le semis.
        """
        for order, start, end in self.trimesters:
            if start <= day <= end:
                return order
        return 1

    def school_days(self, trimester: int, count: int) -> list[date]:
        """Des jours ouvrés répartis dans un trimestre.

        Répartis, et non tirés au hasard : une école tient l'appel toutes les
        semaines, pas trois fois en octobre puis plus rien. On saute le week-end
        sans consulter le calendrier des congés : un jour de classe en trop dans
        un registre de démonstration se remarque moins qu'un trimestre vide.
        """
        _order, start, end = self.trimesters[trimester - 1]
        span = (end - start).days
        if span <= 0 or count <= 0:
            return []

        step = max(1, span // (count + 1))
        days: list[date] = []
        for index in range(1, count + 1):
            day = start.fromordinal(start.toordinal() + step * index)
            while day.weekday() >= 5:  # samedi, dimanche
                day = day.fromordinal(day.toordinal() + 1)
            if day <= end and day not in days:
                days.append(day)
        return days
