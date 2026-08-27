"""Signaler qu'un élève existe peut-être déjà, avant de le créer une seconde fois.

Trois signaux, du plus sûr au plus incertain :

1. **Le matricule.** Identique, c'est la même personne — on renvoie vers sa
   fiche et vers la réinscription plutôt que vers une création.
2. **L'inscription de l'année en cours.** Si elle existe, même non validée, la
   recréer produit deux dossiers pour un seul élève, et la caisse encaisse sur
   celui que le caissier a sous les yeux.
3. **La ressemblance de l'état civil.** Le filet quand le matricule manque,
   ce qui est le cas de toute famille qui revient sans son papier.

La lecture ne bloque rien : elle rend ce qu'elle a trouvé et laisse l'écran
décider. Bloquer sur une ressemblance ferait refuser un vrai nouvel élève
qui porte le nom de son cousin, et il n'y a pas de recours au copier-coller.
Le matricule identique, lui, est une collision : l'écriture la refuse.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.functions import Function

from app.models.academic import Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student
from app.schemas.duplicates import (
    CorrespondanceResponse,
    DoublonsResponse,
    InscriptionExistante,
)
from app.services.duplicates.similarity import (
    Ressemblance,
    StudentIdentity,
    compact,
    comparer,
)

# Les statuts qui occupent la place : un dossier rejeté ou annulé ne compte
# pas, mais un dossier simplement pas encore validé, si — c'est justement
# celui qu'on risque de recréer parce qu'il ne se voit pas dans les listes.
STATUTS_OCCUPANTS = (
    EnrollmentStatus.PROSPECT,
    EnrollmentStatus.EN_VALIDATION,
    EnrollmentStatus.VALIDE,
)

Motif = Literal["matricule", "ressemblance"]


@dataclass(frozen=True)
class Correspondance:
    """Un élève existant qui pourrait être celui qu'on s'apprête à créer."""

    student_id: int
    last_name: str
    first_name: str
    enrollment_number: str | None
    birth_date: date | None
    birth_place: str | None
    motif: Motif
    ressemblance: Ressemblance | None
    inscription_annee_courante: InscriptionExistante | None

    @property
    def bloquant(self) -> bool:
        """Un matricule identique ne se discute pas."""
        return self.motif == "matricule"

    def vers_reponse(self) -> CorrespondanceResponse:
        return CorrespondanceResponse(
            student_id=self.student_id,
            last_name=self.last_name,
            first_name=self.first_name,
            enrollment_number=self.enrollment_number,
            birth_date=self.birth_date,
            birth_place=self.birth_place,
            motif=self.motif,
            score=self.ressemblance.score if self.ressemblance else None,
            champs_compares=list(self.ressemblance.champs_compares) if self.ressemblance else [],
            juge_sur_peu=self.ressemblance.juge_sur_peu if self.ressemblance else False,
            inscription_annee_courante=self.inscription_annee_courante,
        )


def _minuscules(colonne: ColumnElement[str | None]) -> Function[str]:
    return func.lower(func.coalesce(colonne, ""))


def _compact_sql(colonne: ColumnElement[str | None]) -> Function[str]:
    """Même compactage que `compact()` Python, sans accents ni ponctuation.

    MySQL et SQLite n'ont pas `unaccent`. On retire les diacritiques
    fréquents au copier-coller, on remplace la ponctuation par rien, et
    on compare la forme collée : `N'DRI` retrouve `NDRI`.
    """
    texte = _minuscules(colonne)
    for source, cible in (
        # U+2019 : l'apostrophe des claviers de telephone et des copier-coller.
        # Sans elle, `N’DRI` n'est pas retrouve alors que `N'DRI` l'est.
        ("’", ""),
        ("`", ""),
        ("é", "e"),
        ("è", "e"),
        ("ê", "e"),
        ("ë", "e"),
        ("à", "a"),
        ("â", "a"),
        ("ä", "a"),
        ("î", "i"),
        ("ï", "i"),
        ("ô", "o"),
        ("ö", "o"),
        ("ù", "u"),
        ("û", "u"),
        ("ü", "u"),
        ("ç", "c"),
        ("ñ", "n"),
        ("á", "a"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        ("ã", "a"),
        ("õ", "o"),
        ("ç", "c"),
        ("œ", "oe"),
        ("'", ""),
        ("`", ""),
        ("-", ""),
        (" ", ""),
        (".", ""),
    ):
        texte = func.replace(texte, source, cible)
    return texte


def _meme_matricule(saisi: str | None, existant: str | None) -> bool:
    if not saisi or not existant:
        return False
    return saisi.strip().lower() == existant.strip().lower()


#: Au-dela, on ne compare plus. La troncature est annoncee a l'appelant
#: (`tronque`) et journalisee : un plafond silencieux ferait passer « rien
#: trouve » pour une certitude alors qu'on n'a pas regarde.
PLAFOND_CANDIDATS = 200

logger = logging.getLogger(__name__)


def _motifs(valeur: str | None) -> list[str]:
    """Les debuts de nom a chercher, y compris avec une premiere lettre fausse.

    Un prefixe strict defait la raison d'etre du score : COULIBALY saisi
    KOULIBALY n'est jamais candidat, donc la ressemblance ne tourne meme pas —
    et c'est precisement le cas pour lequel elle existe. On cherche donc aussi
    la racine amputee de sa premiere lettre, ce qui rattrape la faute de frappe
    la plus frequente sans elargir a tout l'etablissement.
    """
    racine = compact(valeur)[:5]
    if len(racine) < 3:
        return []
    return [f"{racine}%", f"%{racine[1:]}%"]


def _requete_avec_inscription(
    nom: str | None,
    prenom: str | None,
    matricule: str | None,
    academic_year_id: int | None,
    naissance: date | None = None,
) -> Select[tuple[Student, Enrollment | None, Class | None]]:
    """Une lecture : élèves candidats, inscription occupante de l'année, classe."""
    inscription = aliased(Enrollment)
    classe = aliased(Class)
    conditions = []
    if matricule and matricule.strip():
        conditions.append(_minuscules(Student.enrollment_number) == matricule.strip().lower())
    for valeur in (nom, prenom):
        for motif in _motifs(valeur):
            conditions.append(_compact_sql(Student.last_name).like(motif))
            conditions.append(_compact_sql(Student.first_name).like(motif))
    # La date de naissance ne depend pas de l'orthographe : elle rattrape les
    # fautes que le prefixe laisse passer, dont l'interversion de deux lettres
    # a l'interieur du debut du nom. Elle ne sert qu'a elargir l'ensemble des
    # candidats ; c'est le score qui tranche ensuite.
    if naissance is not None:
        conditions.append(Student.birth_date == naissance)
    jointure_inscription = and_(
        inscription.student_id == Student.id,
        inscription.academic_year_id == academic_year_id if academic_year_id is not None else False,
        inscription.status.in_([s.value for s in STATUTS_OCCUPANTS]),
    )
    return (
        select(Student, inscription, classe)
        # Le cote gauche est explicite : avec trois entites dans le SELECT,
        # SQLAlchemy ne le devine pas et refuse la requete.
        .select_from(Student)
        .outerjoin(inscription, jointure_inscription)
        .outerjoin(classe, classe.id == inscription.class_id)
        .where(or_(*conditions))
        # Sans ordre explicite, quels 200 remontent depend du plan choisi par
        # la base : deux saisies identiques pourraient ne pas voir les memes.
        .order_by(Student.id)
        .limit(PLAFOND_CANDIDATS)
    )


def _identite_saisie(
    last_name: str | None,
    first_name: str | None,
    birth_date: date | None,
    birth_place: str | None,
) -> StudentIdentity:
    return StudentIdentity(
        last_name=last_name,
        first_name=first_name,
        birth_date=birth_date,
        birth_place=birth_place,
    )


def _identite_eleve(eleve: Student) -> StudentIdentity:
    return StudentIdentity(
        last_name=eleve.last_name,
        first_name=eleve.first_name,
        birth_date=eleve.birth_date,
        birth_place=eleve.birth_place,
    )


def _inscription_jointe(
    inscription: Enrollment | None, classe: Class | None
) -> InscriptionExistante | None:
    if inscription is None:
        return None
    return InscriptionExistante(
        enrollment_id=inscription.id,
        status=inscription.status,
        class_name=classe.name if classe is not None else None,
    )


def _criteres_exploitables(
    nom: str | None, prenom: str | None, matricule: str | None, naissance: date | None
) -> bool:
    """Y a-t-il de quoi chercher ?"""
    if matricule and matricule.strip():
        return True
    if naissance is not None:
        return True
    return any(_motifs(valeur) for valeur in (nom, prenom))


async def chercher_doublons(
    db: AsyncSession,
    *,
    last_name: str | None,
    first_name: str | None,
    birth_date: date | None = None,
    birth_place: str | None = None,
    enrollment_number: str | None = None,
    academic_year_id: int | None = None,
    ignorer_student_id: int | None = None,
) -> list[Correspondance]:
    """Les fiches existantes qui pourraient être la même personne, les plus sûres d'abord."""
    # Sans critere exploitable, il n'y a rien a chercher : on evite
    # l'aller-retour plutot que de demander a MySQL une requete batie pour ne
    # rien rendre.
    if not _criteres_exploitables(last_name, first_name, enrollment_number, birth_date):
        return []

    resultat = await db.execute(
        _requete_avec_inscription(
            last_name, first_name, enrollment_number, academic_year_id, birth_date
        )
    )
    lignes = list(resultat.unique().all())
    if len(lignes) >= PLAFOND_CANDIDATS:
        # Le vrai doublon peut etre au-dela : le dire, plutot que de laisser
        # croire qu'on a tout regarde.
        logger.warning(
            "doublons: %s candidats atteints, comparaison tronquee (nom=%r prenom=%r)",
            PLAFOND_CANDIDATS,
            last_name,
            first_name,
        )

    saisi = _identite_saisie(last_name, first_name, birth_date, birth_place)
    trouves: dict[int, Correspondance] = {}
    for existant, inscription, classe in lignes:
        if ignorer_student_id is not None and existant.id == ignorer_student_id:
            continue
        if existant.id in trouves:
            continue

        meme_matricule = _meme_matricule(enrollment_number, existant.enrollment_number)
        r = comparer(saisi, _identite_eleve(existant))
        if not meme_matricule and not r.a_signaler:
            continue

        trouves[existant.id] = Correspondance(
            student_id=existant.id,
            last_name=existant.last_name,
            first_name=existant.first_name,
            enrollment_number=existant.enrollment_number,
            birth_date=existant.birth_date,
            birth_place=existant.birth_place,
            motif="matricule" if meme_matricule else "ressemblance",
            ressemblance=None if meme_matricule else r,
            inscription_annee_courante=_inscription_jointe(inscription, classe),
        )

    trouves_list = list(trouves.values())
    trouves_list.sort(
        key=lambda c: (c.motif != "matricule", -(c.ressemblance.score if c.ressemblance else 1.0))
    )
    return trouves_list


async def reponse_doublons(
    db: AsyncSession,
    *,
    last_name: str | None,
    first_name: str | None,
    birth_date: date | None = None,
    birth_place: str | None = None,
    enrollment_number: str | None = None,
    academic_year_id: int | None = None,
    ignorer_student_id: int | None = None,
) -> DoublonsResponse:
    trouves = await chercher_doublons(
        db,
        last_name=last_name,
        first_name=first_name,
        birth_date=birth_date,
        birth_place=birth_place,
        enrollment_number=enrollment_number,
        academic_year_id=academic_year_id,
        ignorer_student_id=ignorer_student_id,
    )
    correspondances = [c.vers_reponse() for c in trouves]
    return DoublonsResponse(correspondances=correspondances, total=len(correspondances))
