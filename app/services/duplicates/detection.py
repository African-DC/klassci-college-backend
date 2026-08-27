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

from app.models.academic import Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student
from app.schemas.duplicates import (
    CorrespondanceResponse,
    DoublonsResponse,
    InscriptionExistante,
)
from app.services.duplicates.similarity import (
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


def _predicat_matricule_exact(matricule: str | None) -> ColumnElement[bool] | None:
    """Le prédicat « ce matricule exactement », ou rien s'il n'y a rien à comparer.

    Un seul endroit : la même expression servait au filtre et au tri, et une
    règle ajoutée d'un seul côté aurait retiré au tri ce qu'il protège.
    """
    if not matricule or not matricule.strip():
        return None
    return _minuscules(Student.enrollment_number) == matricule.strip().lower()


def _tri_certitude_dabord(matricule: str | None) -> list[Any]:
    """Le tri des candidats : la certitude d'abord, puis un ordre stable.

    Sans le premier critere, le plafond de candidats pouvait évincer la seule
    correspondance sûre — un matricule exact — au profit d'homonymes plus
    anciens. Il n'est ajoute que s'il designe quelque chose : un `false()` nu
    dans un ORDER BY se compile en `0`, que SQLite prend pour un numéro de
    colonne.
    """
    exact = _predicat_matricule_exact(matricule)
    return [Student.id] if exact is None else [exact.desc(), Student.id]


def _minuscules(colonne: ColumnElement[str | None]) -> Function[str]:
    return func.lower(func.coalesce(colonne, ""))


def _compact_sql(colonne: ColumnElement[str | None]) -> Function[str]:
    """Même compactage que `compact()` Python, sans accents ni ponctuation.

    Suivi : #343 — une colonne normalisee et indexee supprimerait cette
    fonction entière, et avec elle le risque de dérive entre les deux
    normalisations.

    Les formes MAJUSCULES sont listees en plus des minuscules : SQLite ne
    minuscule que l'ASCII, donc la table des minuscules accentuees ne s'y
    déclenche jamais et aucun test ne pouvait la couvrir. MySQL les replie,
    mais la liste doit rester vérifiable sous les deux moteurs.

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
        ("É", "e"),
        ("È", "e"),
        ("Ê", "e"),
        ("Ë", "e"),
        ("À", "a"),
        ("Â", "a"),
        ("Ä", "a"),
        ("Î", "i"),
        ("Ï", "i"),
        ("Ô", "o"),
        ("Ö", "o"),
        ("Ù", "u"),
        ("Û", "u"),
        ("Ü", "u"),
        ("Ç", "c"),
        ("Ñ", "n"),
        ("Á", "a"),
        ("Í", "i"),
        ("Ó", "o"),
        ("Ú", "u"),
        ("Ã", "a"),
        ("Õ", "o"),
        ("Œ", "oe"),
    ):
        texte = func.replace(texte, source, cible)
    return texte


def _meme_matricule(saisi: str | None, existant: str | None) -> bool:
    if not saisi or not existant:
        return False
    return saisi.strip().lower() == existant.strip().lower()


#: Au-dela, on ne comparé plus. La troncature est annoncée a l'appelant
#: (`tronque`) et journalisée : un plafond silencieux ferait passer « rien
#: trouve » pour une certitude alors qu'on n'a pas regardé.
PLAFOND_CANDIDATS = 200

logger = logging.getLogger(__name__)


def _noyau(valeur: str | None) -> str | None:
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
    exact = _predicat_matricule_exact(matricule)
    if exact is not None:
        conditions.append(exact)
    for valeur in (nom, prenom):
        noyau = _noyau(valeur)
        if noyau is not None:
            conditions.append(_compact_sql(Student.last_name).like(f"%{noyau}%"))
            conditions.append(_compact_sql(Student.first_name).like(f"%{noyau}%"))
            continue
        # Trop court pour un motif flou, mais pas pour une egalite. « YAO » et
        # « Aya » sont parmi les noms les plus répandus ici : les ignorer
        # rendait une fiche identique introuvable. L'egalite ne remonte pas
        # TRAORE, contrairement a « %ao% ».
        exact = compact(valeur)
        if exact:
            conditions.append(_compact_sql(Student.last_name) == exact)
            conditions.append(_compact_sql(Student.first_name) == exact)
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
        inscription.status.in_([s.value for s in STATUTS_OCCUPANTS]),
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
        # `false()` en tete : un `or_()` vide supprimé la clause WHERE entière
        # et la requête rend TOUTE la table. Aucun critere ne doit jamais
        # vouloir dire « tout le monde » sur un fichier d'élèves.
        .where(or_(false(), *conditions))
        # Sans ordre explicite, quels 200 remontent depend du plan choisi par
        # la base : deux saisies identiques pourraient ne pas voir les mêmes.
        .order_by(*_tri_certitude_dabord(matricule))
        .limit(PLAFOND_CANDIDATS)
    )
    return cast("Select[tuple[Student, Enrollment | None, Class | None]]", requete)


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


def _correspondance_ou_rien(
    saisi: StudentIdentity,
    existant: Student,
    matricule_saisi: str | None,
    inscription: Enrollment | None,
    classe: Class | None,
) -> CorrespondanceResponse | None:
    """La fiche est-elle a signaler, et a quel titre ?

    Rend `None` quand ni le matricule ni le score ne justifient de deranger
    quelqu'un.
    """
    meme_matricule = _meme_matricule(matricule_saisi, existant.enrollment_number)
    # `Student` satisfait `Identite` structurellement : c'est la raison d'être
    # du protocole, et le recopier l'annulait.
    r = comparer(saisi, existant)
    if not meme_matricule and not r.a_signaler:
        return None
    return CorrespondanceResponse(
        student_id=existant.id,
        last_name=existant.last_name,
        first_name=existant.first_name,
        enrollment_number=existant.enrollment_number,
        birth_date=existant.birth_date,
        motif="matricule" if meme_matricule else "ressemblance",
        # Un matricule identique n'est pas une ressemblance : il ne passe pas
        # par le score, et n'a donc ni pourcentage ni réserve.
        score=None if meme_matricule else r.score,
        juge_sur_peu=False if meme_matricule else r.juge_sur_peu,
        inscription_annee_courante=_inscription_jointe(inscription, classe),
    )


def _par_certitude_puis_score(c: CorrespondanceResponse) -> tuple[bool, float]:
    """Une certitude avant une ressemblance, puis du plus sur au moins sur.

    Sinon l'écran met en avant la correspondance la moins fiable des deux.
    """
    return (c.motif != "matricule", -(c.score if c.score is not None else 1.0))


async def chercher_doublons(
    db: AsyncSession,
    *,
    last_name: str | None,
    first_name: str | None,
    birth_date: date | None = None,
    enrollment_number: str | None = None,
    academic_year_id: int | None = None,
    ignorer_student_id: int | None = None,
) -> DoublonsResponse:
    """Les fiches qui pourraient etre la meme personne, les plus sures d'abord.

    Rend aussi si la recherche a ete tronquee : le plafond de candidats peut
    couper avant le vrai doublon, et l'écran doit pouvoir le dire plutot que
    d'afficher un silence qui ressemble a une certitude.
    """
    # Sans critere exploitable, il n'y a rien a chercher : on evite
    # l'aller-retour plutot que de demander a MySQL une requête batie pour ne
    # rien rendre.
    saisi = StudentIdentity(last_name=last_name, first_name=first_name, birth_date=birth_date)
    # Se prononcer ne coûte rien, chercher coûte un balayage complet. Un second
    # garde a existe ici : il ne pouvait plus se déclencher, celui-ci ayant déjà
    # établi ses conditions, et se lisait pourtant comme porteur.
    #
    # Le `.strip()` retient le cas d'un matricule fait d'espaces, qui sinon
    # coûtait un aller-retour pour une requête vide.
    if not ((enrollment_number or "").strip() or saisi.suffisante):
        return DoublonsResponse(correspondances=[], tronque=False)

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
        # Le vrai doublon peut être au-dela : le dire, plutot que de laisser
        # croire qu'on a tout regardé.
        logger.warning(
            "doublons: %s candidats atteints, comparaison tronquee (nom=%r prenom=%r)",
            PLAFOND_CANDIDATS,
            last_name,
            first_name,
        )

    trouves: dict[int, CorrespondanceResponse] = {}
    for existant, inscription, classe in lignes:
        if ignorer_student_id is not None and existant.id == ignorer_student_id:
            continue
        if existant.id in trouves:
            continue

        correspondance = _correspondance_ou_rien(
            saisi, existant, enrollment_number, inscription, classe
        )
        if correspondance is not None:
            trouves[existant.id] = correspondance

    trouves_list = sorted(trouves.values(), key=_par_certitude_puis_score)
    return DoublonsResponse(correspondances=trouves_list, tronque=tronque)
