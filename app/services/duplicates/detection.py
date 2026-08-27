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
from datetime import date
from typing import Any, cast

from sqlalchemy import ColumnElement, Select, and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.functions import Function

from app.core.names import compact
from app.models.academic import Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student
from app.schemas.duplicates import (
    DuplicatesResponse,
    ExistingEnrollment,
    MatchResponse,
)
from app.services.duplicates.similarity import (
    StudentIdentity,
    compare,
)

# Les statuts qui occupent la place : un dossier rejeté ou annulé ne compte
# pas, mais un dossier simplement pas encore validé, si — c'est justement
# celui qu'on risque de recréer parce qu'il ne se voit pas dans les listes.
OCCUPYING_STATUSES = (
    EnrollmentStatus.PROSPECT,
    EnrollmentStatus.EN_VALIDATION,
    EnrollmentStatus.VALIDE,
)


def _exact_enrollment_number(matricule: str | None) -> ColumnElement[bool] | None:
    """Le prédicat « ce matricule exactement », ou rien s'il n'y a rien à comparer.

    Un seul endroit : la même expression servait au filtre et au tri, et une
    règle ajoutée d'un seul côté aurait retiré au tri ce qu'il protège.
    """
    if not matricule or not matricule.strip():
        return None
    return _lowered(Student.enrollment_number) == matricule.strip().lower()


def _certainty_first_order(matricule: str | None) -> list[Any]:
    """Le tri des candidats : la certitude d'abord, puis un ordre stable.

    Sans le premier critere, le plafond de candidats pouvait évincer la seule
    correspondance sûre — un matricule exact — au profit d'homonymes plus
    anciens. Il n'est ajoute que s'il designe quelque chose : un `false()` nu
    dans un ORDER BY se compile en `0`, que SQLite prend pour un numéro de
    colonne.
    """
    exact = _exact_enrollment_number(matricule)
    return [Student.id] if exact is None else [exact.desc(), Student.id]


def _lowered(colonne: Any) -> Function[str]:
    return func.lower(func.coalesce(colonne, ""))


def _meme_matricule(typed: str | None, existing: str | None) -> bool:
    if not typed or not existing:
        return False
    return typed.strip().lower() == existing.strip().lower()


#: Au-dela, on ne compare plus. La troncature est annoncée a l'appelant
#: (`truncated`) et journalisée : un plafond silencieux ferait passer « rien
#: trouve » pour une certitude alors qu'on n'a pas regardé.
CANDIDATE_CAP = 200

logger = logging.getLogger(__name__)


def _search_fragment(valeur: str | None) -> str | None:
    """Le fragment de nom a chercher, ou rien si le nom est trop court.

    On cherche la racine PRIVEE de sa première lettre, ce qui rattrape la faute
    de frappe la plus frequente : COULIBALY saisi KOULIBALY reste trouvable, et
    le prefixe strict etait de toute facon contenu dans ce motif.

    Le seuil porte sur le fragment réellement cherche, pas sur la racine avant
    amputation. Une version antérieure exigeait trois caracteres AVANT de
    retirer la premiere lettre : « YAO » cherchait alors « %ao% », qui remonte
    TRAORE et une bonne part du fichier. YAO est un des noms les plus répandus
    ici, et la troncature a 200 candidats aurait ecarte le vrai doublon.
    """
    racine = compact(valeur)[:6]
    noyau = racine[1:]
    return noyau if len(noyau) >= 3 else None


def _query_with_enrollment(
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
    exact = _exact_enrollment_number(matricule)
    if exact is not None:
        conditions.append(exact)
    # Les colonnes normalisées que l'élève porte déjà (#343). La lecture ne
    # replie plus rien : elle ne peut donc plus replier autrement que
    # l'écriture. Les index posés dessus ne servent que la branche d'égalité
    # plus bas ; le motif flou reste un balayage, joker en tête oblige.
    nom_compacte = Student.last_name_key
    prenom_compacte = Student.first_name_key
    for valeur in (nom, prenom):
        noyau = _search_fragment(valeur)
        if noyau is not None:
            conditions.append(nom_compacte.like(f"%{noyau}%"))
            conditions.append(prenom_compacte.like(f"%{noyau}%"))
            continue
        # Trop court pour un motif flou, mais pas pour une egalite. « YAO » et
        # « Aya » sont parmi les noms les plus répandus ici : les ignorer
        # rendait une fiche identique introuvable. L'egalite ne remonte pas
        # TRAORE, contrairement a « %ao% ».
        entier = compact(valeur)
        if entier:
            conditions.append(nom_compacte == entier)
            conditions.append(prenom_compacte == entier)
    # La date de naissance ne depend pas de l'orthographe : elle rattrape les
    # fautes que le prefixe laisse passer, dont l'interversion de deux lettres
    # a l'interieur du debut du nom. Elle ne sert qu'a elargir l'ensemble des
    # candidats ; c'est le score qui tranche ensuite.
    if naissance is not None:
        conditions.append(Student.birth_date == naissance)
    # Sans année visee, aucune inscription ne peut occuper la place :
    # `false()` est l'expression SQL correspondante, `False` nu n'en est pas une.
    annee_visee = (
        inscription.academic_year_id == academic_year_id
        if academic_year_id is not None
        else false()
    )
    jointure_inscription = and_(
        inscription.student_id == Student.id,
        annee_visee,
        inscription.status.in_([s.value for s in OCCUPYING_STATUSES]),
    )
    # SQLAlchemy type un `outerjoin` comme s'il rendait toujours l'entite, alors
    # qu'une jointure externe rend `None` quand rien ne correspond — ce qui est
    # le cas le plus fréquent ici : la plupart des élèves n'ont pas
    # d'inscription ouverte sur l'année visee. Le type declare par la fonction
    # est le vrai ; ce `cast` ne fait que le dire au verificateur.
    requete = (
        select(Student, inscription, classe)
        # Le côté gauche est explicite : avec trois entites dans le SELECT,
        # SQLAlchemy ne le devine pas et refuse la requête.
        .select_from(Student)
        .outerjoin(inscription, jointure_inscription)
        .outerjoin(classe, classe.id == inscription.class_id)
        # `false()` en tete : un `or_()` vide supprime la clause WHERE entière
        # et la requête rend TOUTE la table. Aucun critere ne doit jamais
        # vouloir dire « tout le monde » sur un fichier d'élèves.
        .where(or_(false(), *conditions))
        # Sans ordre explicite, quels 200 remontent depend du plan choisi par
        # la base : deux saisies identiques pourraient ne pas voir les mêmes.
        .order_by(*_certainty_first_order(matricule))
        .limit(CANDIDATE_CAP)
    )
    return cast("Select[tuple[Student, Enrollment | None, Class | None]]", requete)


def _joined_enrollment(
    inscription: Enrollment | None, classe: Class | None
) -> ExistingEnrollment | None:
    if inscription is None:
        return None
    return ExistingEnrollment(
        enrollment_id=inscription.id,
        status=inscription.status,
        class_name=classe.name if classe is not None else None,
    )


def _identity_of(eleve: Student) -> StudentIdentity:
    """L'état civil d'une fiche, sous la forme que le comparateur attend.

    Un protocole structurel a existé ici pour éviter cette conversion. Il ne
    tenait pas : `Student.last_name` est un `Mapped[str]`, que le vérificateur
    de types refuse contre `str | None`, et son unique appel de production ne
    le satisfaisait donc pas. Trois lignes explicites valent mieux qu'une
    abstraction qui ne vérifie rien.
    """
    return StudentIdentity(
        last_name=eleve.last_name,
        first_name=eleve.first_name,
        birth_date=eleve.birth_date,
    )


def _match_or_none(
    typed: StudentIdentity,
    existing: Student,
    matricule_saisi: str | None,
    inscription: Enrollment | None,
    classe: Class | None,
) -> MatchResponse | None:
    """La fiche est-elle a signaler, et a quel titre ?

    Rend `None` quand ni le matricule ni le score ne justifient de deranger
    quelqu'un.
    """
    meme_matricule = _meme_matricule(matricule_saisi, existing.enrollment_number)
    r = compare(typed, _identity_of(existing))
    if not meme_matricule and not r.worth_reporting:
        return None
    return MatchResponse(
        student_id=existing.id,
        last_name=existing.last_name,
        first_name=existing.first_name,
        enrollment_number=existing.enrollment_number,
        birth_date=existing.birth_date,
        reason="enrollment_number" if meme_matricule else "similarity",
        # Un matricule identique n'est pas une ressemblance : il ne passe pas
        # par le score, et n'a donc ni pourcentage ni réserve.
        score=None if meme_matricule else r.score,
        partial_identity=False if meme_matricule else r.partial_identity,
        current_year_enrollment=_joined_enrollment(inscription, classe),
    )


def _by_certainty_then_score(c: MatchResponse) -> tuple[bool, float]:
    """Une certitude avant une ressemblance, puis du plus sur au moins sur.

    Sinon l'écran met en avant la correspondance la moins fiable des deux.
    """
    return (c.reason != "enrollment_number", -(c.score if c.score is not None else 1.0))


async def find_duplicates(
    db: AsyncSession,
    *,
    last_name: str | None,
    first_name: str | None,
    birth_date: date | None = None,
    enrollment_number: str | None = None,
    academic_year_id: int | None = None,
    exclude_student_id: int | None = None,
) -> DuplicatesResponse:
    """Les fiches qui pourraient etre la meme personne, les plus sures d'abord.

    Rend aussi si la recherche a ete tronquee : le plafond de candidats peut
    couper avant le vrai doublon, et l'écran doit pouvoir le dire plutot que
    d'afficher un silence qui ressemble a une certitude.
    """
    # Sans critere exploitable, il n'y a rien a chercher : on evite
    # l'aller-retour plutot que de demander a MySQL une requête batie pour ne
    # rien rendre.
    typed = StudentIdentity(last_name=last_name, first_name=first_name, birth_date=birth_date)
    # Se prononcer ne coûte rien, chercher coûte un balayage complet. Un second
    # garde a existe ici : il ne pouvait plus se déclencher, celui-ci ayant déjà
    # établi ses conditions, et se lisait pourtant comme porteur.
    #
    # Le `.strip()` retient le cas d'un matricule fait d'espaces, qui sinon
    # coûtait un aller-retour pour une requête vide.
    if not ((enrollment_number or "").strip() or typed.is_actionable):
        return DuplicatesResponse(matches=[], truncated=False)

    resultat = await db.execute(
        _query_with_enrollment(
            last_name, first_name, enrollment_number, academic_year_id, birth_date
        )
    )
    # Pas de `.unique()` : il serait sans effet. `uq_enrollment_student_year`
    # garantit au plus une inscription par élève et par année, et la classe est
    # jointe sur sa clé primaire, donc la jointure rend au plus une ligne par
    # élève.
    lignes = list(resultat.all())
    truncated = len(lignes) >= CANDIDATE_CAP
    if truncated:
        # Le vrai doublon peut être au-dela : le dire, plutot que de laisser
        # croire qu'on a tout regardé.
        logger.warning(
            "doublons: %s candidats atteints, comparaison tronquee (nom=%r prenom=%r)",
            CANDIDATE_CAP,
            last_name,
            first_name,
        )

    found: list[MatchResponse] = []
    for existing, inscription, classe in lignes:
        if exclude_student_id is not None and existing.id == exclude_student_id:
            continue

        correspondance = _match_or_none(typed, existing, enrollment_number, inscription, classe)
        if correspondance is not None:
            found.append(correspondance)

    found.sort(key=_by_certainty_then_score)
    return DuplicatesResponse(matches=found, truncated=truncated)
