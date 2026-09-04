"""Le registre des cibles : ce qu'une photo va devenir, et ou.

Une cible dit quel sujet elle exige, quelle permission l'ouvre, quels
types de fichier elle accepte, et ce qu'il faut ecrire quand l'operateur
confirme. Ajouter une cible se fait ici, et nulle part ailleurs : le
transport n'a pas a la connaitre.
"""

import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.uploads import DOCUMENTS, LOGOS, PHOTOS, SIGNATURES, UploadKind
from app.utils.file_upload import ALLOWED_DOCUMENT_TYPES
from app.utils.photo_upload import EXTENSION_PAR_TYPE

if TYPE_CHECKING:  # pragma: no cover
    # Sous `TYPE_CHECKING` seulement : la session connait le registre, le
    # registre ne connait la session que pour l'annoter. L'importer
    # vraiment fermerait le cycle.
    from ._session import HandoffSession

logger = logging.getLogger(__name__)

#: Duree de vie d'une session. Assez pour sortir un telephone, deverrouiller,
#: scanner, cadrer et envoyer en 3G ; trop court pour qu'un code affiche sur un
#: ecran que plus personne ne regarde reste une porte ouverte.
SESSION_TTL_SECONDS = 600

#: Nombre de reprises possibles avant qu'il faille rouvrir une session.
#: « Reprendre » ne repousse jamais l'echeance : elle est absolue.
MAX_RETAKES = 3

State = Literal["open", "receiving", "proposed", "done"]

#: Ce que l'ordinateur devra faire du depot une fois confirme.
#:
#: `finalise` : le sujet existe deja, le serveur promeut le fichier et appelle
#: la fonction metier qui ecrit la colonne.
#: `stage-only` : le sujet n'existe pas encore — a l'inscription, la photo est
#: prise AVANT la creation de la fiche. L'ordinateur recupere les octets et les
#: rend au formulaire, qui suit son chemin habituel.
Mode = Literal["finalise", "stage-only"]

#: Ce qu'une cible exige comme sujet.
#:
#: `required` : un identifiant, toujours (photo d'enseignant, piece jointe).
#: `optional` : avec identifiant on finalise, sans on rend les octets.
#: `self`     : le sujet EST l'appelant (photo de profil), jamais un autre.
#: `none`     : la cible est l'etablissement lui-meme (logo, tampon).
SubjectRule = Literal["required", "optional", "self", "none"]

Finaliser = Callable[[AsyncSession, "HandoffSession", str], Awaitable[None]]

#: Le tenant entre dans une cle Redis partagee par toutes les ecoles.
#:
#: Il arrive du chemin d'une URL publique cote telephone. Un segment porteur de
#: `:` ou de `*` melangerait deux espaces de noms ou ouvrirait un motif de
#: recherche : on le refuse plutot que de l'echapper.
_TENANT_VALIDE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}$")


# ---------------------------------------------------------------------------
# Le registre des cibles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandoffTarget:
    """Tout ce qu'une cible de depot doit dire d'elle-meme.

    Ajouter une cible est une entree dans le dictionnaire ci-dessous. Le
    transport — jeton, sas, machine a etats, routes — ne bouge pas. C'est la
    raison d'etre de ce dataclass : sans lui, la premiere cible non-photo
    obligerait a ouvrir la route de depot pour y ecrire une exception, et la
    deuxieme a l'ouvrir encore.

    Les champs qui ne vont pas de soi :

    `permission` — le slug lu dans la matrice des droits, tel qu'il est deja
    ecrit sur la route equivalente. `None` ne veut PAS dire « ouvert » : il veut
    dire que le geste est un self-service dont la fonction metier porte
    elle-meme la regle (`profile_service.set_my_photo` refuse a qui n'a pas de
    photo a gerer). Une cible `None` a forcement `subject="self"`.

    `accepted_types` — la table MIME de la cible, pas une table globale. Une
    photo accepte trois formats d'image ; une piece jointe accepte en plus le
    PDF, et c'est exactement pour cela que la garde MIME ne peut pas etre
    `extension_pour()` pour tout le monde : elle leve un 400 sur un PDF.

    `max_bytes` — celui de la sorte de destination. Une photo plafonne a cinq
    megaoctets, un document a dix.

    `extras` — les donnees que la cible reclame et que le geste photo ne porte
    pas. Une piece jointe eleve exige un type de document ; il est choisi sur
    l'ordinateur A L'OUVERTURE de la session, pas sur le telephone : l'ecran qui
    sait ce qu'on classe est celui de l'operateur, et le telephone ne doit rien
    apprendre de plus que necessaire.
    """

    kind: str
    metier: str
    permission: str | None
    upload_kind: UploadKind
    prefix: str
    accepted_types: Mapping[str, str]
    subject: SubjectRule
    finalise: Finaliser | None
    extras: tuple[str, ...] = ()

    @property
    def max_bytes(self) -> int:
        return self.upload_kind.max_bytes

    def prefix_for(self, subject_id: int | None) -> str:
        """Le prefixe de nom de fichier, identique a celui de la route existante.

        Les fichiers deja en base suivent ces conventions : une photo d'eleve est
        `42_abcd1234.jpg`, une d'enseignant `teacher_42_...`. Un depot par
        telephone ne doit pas fabriquer une troisieme convention.
        """
        return self.prefix.format(subject=subject_id)

    def extension_pour(self, content_type: str | None) -> str:
        """L'extension du type declare, ou 400 si la cible ne l'accepte pas.

        Meme forme que `photo_upload.extension_pour`, mais la table est celle de
        la cible : c'est ce qui laisse une piece jointe accepter un PDF sans
        ouvrir le PDF aux photos.
        """
        extension = self.accepted_types.get(content_type or "")
        if extension is None:
            formats = ", ".join(sorted({e.upper() for e in self.accepted_types.values()}))
            raise HTTPException(status_code=400, detail=f"Format invalide. Accepte : {formats}")
        return extension


def _trace(session: "HandoffSession") -> str:
    """Ce que le journal d'audit doit dire d'une photo arrivee par telephone.

    L'operateur qui confirme est deja identifie par sa session ; ce que la
    ligne d'audit ne saurait pas sans cela, c'est que l'image n'a PAS ete prise
    depuis son ecran. L'identifiant de session permet de rapprocher la ligne
    des journaux du serveur pendant les dix minutes ou elle a vecu.
    """
    return f"photo reçue par reprise QR, session {session.id}"


async def _finalise_student_photo(db: AsyncSession, session: "HandoffSession", url: str) -> None:
    from app.services import admin_service

    await admin_service.update_student_photo(
        db,
        _sujet(session),
        url,
        updated_by=session.owner_user_id,
        ip_address=session.phone_ip,
        notes=_trace(session),
    )


async def _finalise_teacher_photo(db: AsyncSession, session: "HandoffSession", url: str) -> None:
    from app.services import admin_service

    await admin_service.update_teacher_photo(
        db,
        _sujet(session),
        url,
        updated_by=session.owner_user_id,
        ip_address=session.phone_ip,
        notes=_trace(session),
    )


async def _finalise_staff_photo(db: AsyncSession, session: "HandoffSession", url: str) -> None:
    from app.services import admin_service

    await admin_service.update_staff_photo(
        db,
        _sujet(session),
        url,
        updated_by=session.owner_user_id,
        ip_address=session.phone_ip,
        notes=_trace(session),
    )


async def _finalise_profile_photo(db: AsyncSession, session: "HandoffSession", url: str) -> None:
    from app.services import profile_service

    await profile_service.set_my_photo(
        db,
        session.owner_user_id,
        url,
        ip_address=session.phone_ip,
        notes=_trace(session),
    )


async def _finalise_school_logo(db: AsyncSession, session: "HandoffSession", url: str) -> None:
    from app.schemas.admin import SchoolInfoUpdate
    from app.services import admin_service

    await admin_service.update_school_info(
        db, SchoolInfoUpdate(logo_url=url), updated_by=session.owner_user_id
    )


async def _finalise_school_signature(db: AsyncSession, session: "HandoffSession", url: str) -> None:
    from app.schemas.admin import SchoolInfoUpdate
    from app.services import admin_service

    await admin_service.update_school_info(
        db, SchoolInfoUpdate(signature_image_url=url), updated_by=session.owner_user_id
    )


async def _finalise_student_document(db: AsyncSession, session: "HandoffSession", url: str) -> None:
    """Le seul finaliseur qui a besoin d'autre chose que d'une URL.

    `add_student_document` exige un type de document et un nom de fichier. Le
    premier est choisi par l'operateur a l'ouverture de la session et voyage
    dans `extras` ; le second est le nom que le telephone a envoye, conserve
    pour l'affichage seulement — il n'a jamais servi a nommer quoi que ce soit
    sur le disque.
    """
    from app.services import attachment_service

    await attachment_service.add_student_document(
        db,
        _sujet(session),
        document_type=session.extras.get("document_type", ""),
        file_url=url,
        file_name=session.staged_client_name,
        mime_type=session.staged_mime,
        uploaded_by=session.owner_user_id,
    )


def _sujet(session: "HandoffSession") -> int:
    """L'identifiant du sujet, dont un finaliseur ne peut pas se passer."""
    if session.subject_id is None:
        raise HTTPException(status_code=409, detail="Cette session n'a pas de destinataire")
    return session.subject_id


#: Le registre. Une cible de plus = une entree de plus, et rien d'autre.
TARGETS: Mapping[str, HandoffTarget] = {
    target.kind: target
    for target in (
        HandoffTarget(
            kind="student_photo",
            metier="Photo d'élève",
            permission="admin:students:update",
            upload_kind=PHOTOS,
            prefix="{subject}",
            accepted_types=EXTENSION_PAR_TYPE,
            # A l'inscription la photo est prise AVANT que la fiche existe :
            # sans ce `optional`, la reprise par telephone raterait precisement
            # l'ecran ou elle est la plus utile.
            subject="optional",
            finalise=_finalise_student_photo,
        ),
        HandoffTarget(
            kind="teacher_photo",
            metier="Photo d'enseignant",
            permission="admin:teachers:update",
            upload_kind=PHOTOS,
            prefix="teacher_{subject}",
            accepted_types=EXTENSION_PAR_TYPE,
            subject="required",
            finalise=_finalise_teacher_photo,
        ),
        HandoffTarget(
            kind="staff_photo",
            metier="Photo de personnel",
            permission="admin:staff:update",
            upload_kind=PHOTOS,
            prefix="staff_{subject}",
            accepted_types=EXTENSION_PAR_TYPE,
            subject="required",
            finalise=_finalise_staff_photo,
        ),
        HandoffTarget(
            kind="profile_photo",
            metier="Photo de profil",
            # Aucun slug, et ce n'est pas un oubli : la route existante
            # (`/profile/me/photo`) n'en exige aucun non plus. Le geste est un
            # self-service, et `set_my_photo` porte lui-meme la regle de qui a
            # une photo a gerer. Le sujet est force a l'appelant plus bas :
            # personne ne peut ouvrir une session sur le profil d'un autre.
            permission=None,
            upload_kind=PHOTOS,
            prefix="u{subject}",
            accepted_types=EXTENSION_PAR_TYPE,
            subject="self",
            finalise=_finalise_profile_photo,
        ),
        HandoffTarget(
            kind="school_logo",
            metier="Logo de l'établissement",
            # Le slug en place sur `POST /admin/settings/logo`. Il surprend, et
            # on le reprend tel quel : inventer ici un droit que la matrice ne
            # connait pas donnerait un bouton que personne ne peut utiliser.
            permission="admin:academic-years:update",
            upload_kind=LOGOS,
            prefix="logo",
            accepted_types=EXTENSION_PAR_TYPE,
            subject="none",
            finalise=_finalise_school_logo,
        ),
        HandoffTarget(
            kind="school_signature",
            metier="Tampon de signature",
            permission="admin:academic-years:update",
            upload_kind=SIGNATURES,
            prefix="signature",
            accepted_types=EXTENSION_PAR_TYPE,
            subject="none",
            finalise=_finalise_school_signature,
        ),
        HandoffTarget(
            kind="student_document",
            metier="Pièce jointe d'élève",
            permission="admin:students:update",
            upload_kind=DOCUMENTS,
            prefix="s{subject}",
            # La seule cible qui accepte le PDF, et le seul plafond a dix
            # megaoctets. C'est ce que la table et la sorte disent ici, plutot
            # qu'une regle globale qui refuserait le PDF a tout le monde.
            accepted_types=ALLOWED_DOCUMENT_TYPES,
            subject="required",
            finalise=_finalise_student_document,
            extras=("document_type",),
        ),
    )
}
