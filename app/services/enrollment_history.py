"""« Cet élève a-t-il déjà été inscrit ici une année antérieure ? » — une seule définition.

La question se pose à deux endroits qui n'ont rien à voir : la colonne
« Qualité (Red / Non Red) » du rapport approfondi, et la case « nouvel élève »
du formulaire d'inscription, qui décide du tarif appliqué. Elle vivait à
moitié dans `deep_report._context`, avec son tuple de statuts et son critère
d'antériorité. Le jour où quelqu'un ajoute un statut d'inscription, une seule
des deux listes bougerait, et la seconde se mettrait à répondre autre chose
sans que rien ne le dise.

Elle vit donc ici, une fois, et les deux appelants s'en servent.

**Ce que ce module refuse de faire.** Il ne déduit rien tant que l'école n'a
pas déclaré son historique exploitable, et il ne conclut jamais « nouveau » du
seul fait qu'il ne trouve rien. C'est la règle que `_load_history` tenait déjà
pour la colonne Red / Non Red, et pour la même raison, écrite dans son
commentaire : affirmer serait faux dès le premier redoublant. Ici l'enjeu est
une facture. Un collège dont l'année précédente n'est pas reconstituée verrait
sinon ses anciens élèves recevoir les frais d'entrée des nouveaux.

**Pourquoi un réglage, et pas la seule lecture de la base.** Une base qui ne
porte que l'année en cours ne distingue pas un arrivant d'un ancien pas encore
ressaisi : ni l'un ni l'autre n'a d'inscription antérieure. Compter les lignes
ne peut donc pas trancher. Et une reconstitution d'année se fait dossier par
dossier : un garde-fou qui se lèverait tout seul à la première ligne saisie
ferait facturer autrement le matin et l'après-midi, sans que personne ne l'ait
décidé. C'est l'école qui déclare, une fois et explicitement, que son passé
est exploitable : `SchoolSettings.enrollment_history_is_reliable`. Tant qu'elle
ne l'a pas fait, ce module répond « je ne sais pas », quoi que contienne la
base.
"""

from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class, SchoolSettings
from app.models.enrollment import Enrollment, EnrollmentStatus

#: Une inscription rejetée ou annulée n'a jamais occupé de place ; une
#: inscription en validation, si. C'est le périmètre déjà retenu par les
#: statistiques DREN, on ne le change pas d'un usage à l'autre.
COUNTED_STATUSES = (EnrollmentStatus.VALIDE, EnrollmentStatus.EN_VALIDATION)


def anterior_enrollments(reference_start_date: date) -> Select:
    """Les inscriptions comptées d'une année commencée avant celle-ci.

    Le critère d'antériorité porte sur `AcademicYear.start_date` et non sur
    l'identifiant : rien ne garantit que les années aient été créées dans
    l'ordre où elles se sont déroulées.

    Rend `(student_id, level_id)` — le niveau sert au rapport approfondi pour
    reconnaître un redoublant ; celui qui ne cherche qu'une présence ignore la
    seconde colonne.
    """
    return (
        select(Enrollment.student_id, Class.level_id)
        .join(Class, Class.id == Enrollment.class_id)
        .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
        .where(
            AcademicYear.start_date < reference_start_date,
            Enrollment.status.in_(COUNTED_STATUSES),
        )
    )


async def levels_attended_before(
    db: AsyncSession, reference_start_date: date
) -> tuple[set[tuple[int, int]], bool]:
    """Couples (élève, niveau) déjà fréquentés, et si l'histoire existe.

    Une seule requête pour toute la cohorte : le rapport approfondi la lit
    pour quatre cents élèves, une par élève serait quatre cents requêtes sur
    un document qu'un secrétariat imprime depuis une connexion incertaine.

    Le second membre vaut False quand aucune ligne ne remonte : l'appelant
    doit alors laisser la question sans réponse, pas conclure.
    """
    rows = (await db.execute(anterior_enrollments(reference_start_date))).all()
    return {(row[0], row[1]) for row in rows}, bool(rows)


async def establishment_has_history(db: AsyncSession, reference_start_date: date) -> bool:
    """L'établissement a-t-il la moindre inscription antérieure en base ?

    Volontairement plus exigeant que « existe-t-il une année antérieure » :
    une année créée mais jamais remplie ne dit rien de qui était là. C'est
    déjà la lecture que fait le rapport approfondi.

    **Ce n'est plus l'interrupteur de la déduction.** Ce rôle appartient au
    réglage déclaré par l'école, `history_is_declared_reliable` : une seule
    ligne d'historique reconstituée ne doit pas suffire à faire basculer la
    facturation au milieu d'une reprise. Reste un indice honnête, à afficher
    dans les réglages pour dire à l'école qu'elle peut activer le sien.
    """
    stmt = anterior_enrollments(reference_start_date).limit(1)
    return (await db.execute(stmt)).first() is not None


async def student_enrolled_before(
    db: AsyncSession, student_id: int, reference_start_date: date
) -> bool:
    """Cet élève-là porte-t-il une inscription antérieure ?

    Le prédicat unitaire du module : mêmes statuts, même critère d'antériorité
    que la requête groupée, parce que c'est littéralement la même requête.
    """
    stmt = (
        anterior_enrollments(reference_start_date)
        .where(Enrollment.student_id == student_id)
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None


async def _load_academic_year(db: AsyncSession, academic_year_id: int) -> AcademicYear:
    year = (
        await db.execute(select(AcademicYear).where(AcademicYear.id == academic_year_id))
    ).scalar_one_or_none()
    if year is None:
        raise NotFoundError("AcademicYear", academic_year_id)
    return year


async def history_is_declared_reliable(db: AsyncSession) -> bool:
    """L'école a-t-elle déclaré ses années passées exploitables ?

    Relu à chaque suggestion, sans mémoire : le réglage se lève au milieu
    d'une reprise d'historique, et une valeur gardée en cache ferait facturer
    la fin de la journée sous la réponse du matin.

    Un établissement fraîchement provisionné n'a pas encore de ligne de
    réglages : l'absence vaut alors `false`, le seul défaut qui ne facture
    rien par surprise.
    """
    stmt = select(SchoolSettings.enrollment_history_is_reliable).limit(1)
    return bool((await db.execute(stmt)).scalar_one_or_none())


async def suggest_new_student(
    db: AsyncSession, student_id: int, academic_year_id: int
) -> tuple[bool | None, str]:
    """Ce que l'écran doit pré-cocher, et la phrase qui l'explique.

    Trois réponses, jamais deux. `None` n'est pas un échec technique : c'est
    l'établissement dont le passé n'est pas exploitable, et la secrétaire qui
    doit trancher elle-même parce qu'elle est la seule à savoir.

    L'année est chargée avant toute autre chose, réglage compris : un
    identifiant d'année qui n'existe pas doit rendre un 404 lisible, que
    l'école déduise ou non.
    """
    year = await _load_academic_year(db, academic_year_id)

    if not await history_is_declared_reliable(db):
        return None, (
            "Les inscriptions des années précédentes ne sont pas déclarées "
            "complètes dans le logiciel : il ne peut pas savoir si cet élève "
            "arrive pour la première fois. À vous de cocher, dossier en main."
        )

    if not await establishment_has_history(db, year.start_date):
        return None, (
            "Aucune inscription des années précédentes n'est enregistrée : "
            "impossible de dire si cet élève est nouveau. À vous de cocher."
        )

    if await student_enrolled_before(db, student_id, year.start_date):
        return False, "Cet élève était déjà inscrit dans l'établissement une année précédente."

    return True, "Aucune inscription antérieure pour cet élève dans l'établissement."


async def deduce_new_student(
    db: AsyncSession, student_id: int, academic_year_id: int
) -> bool | None:
    """Le profil déduit quand le corps d'inscription ne porte pas le champ.

    Rend `None` sans hésiter tant que l'école n'a pas déclaré son historique :
    mieux vaut une case vide qu'un montant choisi par le serveur à sa place.
    """
    suggested, _reason = await suggest_new_student(db, student_id, academic_year_id)
    return suggested
