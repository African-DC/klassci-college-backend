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

from sqlalchemy import ColumnElement, Select, and_, false, func, or_, select
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
    motif: Motif
    ressemblance: Ressemblance | None
    inscription_annee_courante: InscriptionExistante | None

    def vers_reponse(self) -> CorrespondanceResponse:
        return CorrespondanceResponse(
            student_id=self.student_id,
            last_name=self.last_name,
            first_name=self.first_name,
            enrollment_number=self.enrollment_number,
            birth_date=self.birth_date,
            motif=self.motif,
            score=self.ressemblance.score if self.ressemblance else None,
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
        ("œ", "oe"),
        ("'", ""),
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


def _noyau(valeur: str | None) -> str | None:
    """Le fragment de nom a chercher, ou rien si le nom est trop court.

    On cherche la racine PRIVEE de sa premiere lettre, ce qui rattrape la faute
    de frappe la plus frequente : COULIBALY saisi KOULIBALY reste trouvable, et
    le prefixe strict etait de toute facon contenu dans ce motif.

    Le seuil porte sur le fragment reellement cherche, pas sur la racine avant
    amputation. Une version anterieure exigeait trois caracteres AVANT de
    retirer la premiere lettre : « YAO » cherchait alors « %ao% », qui remonte
    TRAORE et une bonne part du fichier. YAO est un des noms les plus repandus
    ici, et la troncature a 200 candidats aurait ecarte le vrai doublon.
    """
    racine = compact(valeur)[:6]
    noyau = racine[1:]
    return noyau if len(noyau) >= 3 else None


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
        noyau = _noyau(valeur)
        if noyau is None:
            continue
        conditions.append(_compact_sql(Student.last_name).like(f"%{noyau}%"))
        conditions.append(_compact_sql(Student.first_name).like(f"%{noyau}%"))
    # La date de naissance ne depend pas de l'orthographe : elle rattrape les
    # fautes que le prefixe laisse passer, dont l'interversion de deux lettres
    # a l'interieur du debut du nom. Elle ne sert qu'a elargir l'ensemble des
    # candidats ; c'est le score qui tranche ensuite.
    if naissance is not None:
        conditions.append(Student.birth_date == naissance)
    # Sans annee visee, aucune inscription ne peut occuper la place :
    # `false()` est l'expression SQL correspondante, `False` nu n'en est pas une.
    annee_visee = (
        inscription.academic_year_id == academic_year_id
        if academic_year_id is not None
        else false()
    )
    jointure_inscription = and_(
        inscription.student_id == Student.id,
        annee_visee,
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
    # Deux conditions distinctes, qu'une version anterieure confondait.
    #
    # De quoi CHERCHER : au moins un fragment assez long pour un motif SQL.
    if _noyau(nom) is None and _noyau(prenom) is None:
        return False
    # De quoi RAPPORTER : `Ressemblance.saisie_suffisante` exige le nom plus un
    # second element. Sans cet accord, le nom seul — l'etat le plus frequent du
    # formulaire, avant que le prenom soit tape — lancait quatre LIKE a joker de
    # tete sur deux colonnes non indexees, a chaque touche, pour un resultat qui
    # ne pouvait etre rapporte.
    #
    # Le second element n'a pas besoin d'etre assez long pour un motif : « Aya »
    # est un prenom courant, trois lettres, et suffit a departager deux
    # homonymes une fois les candidats remontes par le nom.
    return bool(compact(nom)) and (bool(compact(prenom)) or naissance is not None)


async def chercher_doublons(
    db: AsyncSession,
    *,
    last_name: str | None,
    first_name: str | None,
    birth_date: date | None = None,
    enrollment_number: str | None = None,
    academic_year_id: int | None = None,
    ignorer_student_id: int | None = None,
) -> tuple[list[Correspondance], bool]:
    """Les fiches qui pourraient etre la meme personne, les plus sures d'abord.

    Rend aussi si la recherche a ete tronquee : le plafond de candidats peut
    couper avant le vrai doublon, et l'ecran doit pouvoir le dire plutot que
    d'afficher un silence qui ressemble a une certitude.
    """
    # Sans critere exploitable, il n'y a rien a chercher : on evite
    # l'aller-retour plutot que de demander a MySQL une requete batie pour ne
    # rien rendre.
    if not _criteres_exploitables(last_name, first_name, enrollment_number, birth_date):
        return [], False

    resultat = await db.execute(
        _requete_avec_inscription(
            last_name, first_name, enrollment_number, academic_year_id, birth_date
        )
    )
    # Pas de `.unique()` : sans `joinedload` il ne dedoublonne rien, et se
    # lirait comme s'il interagissait avec le compte de troncature ci-dessous.
    lignes = list(resultat.all())
    tronque = len(lignes) >= PLAFOND_CANDIDATS
    if tronque:
        # Le vrai doublon peut etre au-dela : le dire, plutot que de laisser
        # croire qu'on a tout regarde.
        logger.warning(
            "doublons: %s candidats atteints, comparaison tronquee (nom=%r prenom=%r)",
            PLAFOND_CANDIDATS,
            last_name,
            first_name,
        )

    saisi = StudentIdentity(last_name=last_name, first_name=first_name, birth_date=birth_date)
    trouves: dict[int, Correspondance] = {}
    for existant, inscription, classe in lignes:
        if ignorer_student_id is not None and existant.id == ignorer_student_id:
            continue
        if existant.id in trouves:
            continue

        meme_matricule = _meme_matricule(enrollment_number, existant.enrollment_number)
        # `Student` satisfait `Identite` structurellement : c'est la raison
        # d'etre du protocole, et le recopier l'annulait.
        r = comparer(saisi, existant)
        if not meme_matricule and not r.a_signaler:
            continue

        trouves[existant.id] = Correspondance(
            student_id=existant.id,
            last_name=existant.last_name,
            first_name=existant.first_name,
            enrollment_number=existant.enrollment_number,
            birth_date=existant.birth_date,
            motif="matricule" if meme_matricule else "ressemblance",
            ressemblance=None if meme_matricule else r,
            inscription_annee_courante=_inscription_jointe(inscription, classe),
        )

    trouves_list = list(trouves.values())
    trouves_list.sort(
        key=lambda c: (c.motif != "matricule", -(c.ressemblance.score if c.ressemblance else 1.0))
    )
    return trouves_list, tronque


async def reponse_doublons(
    db: AsyncSession,
    *,
    last_name: str | None,
    first_name: str | None,
    birth_date: date | None = None,
    enrollment_number: str | None = None,
    academic_year_id: int | None = None,
    ignorer_student_id: int | None = None,
) -> DoublonsResponse:
    trouves, tronque = await chercher_doublons(
        db,
        last_name=last_name,
        first_name=first_name,
        birth_date=birth_date,
        enrollment_number=enrollment_number,
        academic_year_id=academic_year_id,
        ignorer_student_id=ignorer_student_id,
    )
    correspondances = [c.vers_reponse() for c in trouves]
    return DoublonsResponse(
        correspondances=correspondances, total=len(correspondances), tronque=tronque
    )
