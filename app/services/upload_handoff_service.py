"""La reprise de televersement : un telephone depose, un operateur confirme.

Le geste
========

Un ordinateur sans camera doit pouvoir recevoir une photo d'eleve. L'operateur
ouvre une session depuis son ecran, montre un code 2D, le telephone le scanne,
prend la photo et l'envoie. L'ordinateur voit arriver l'image, la regarde, et
c'est LUI qui confirme — avec sa propre session et sa propre permission.

Le telephone ne touche jamais une fiche. Il depose dans un sas
(`app/utils/handoff_storage.py`) et rien d'autre. C'est la propriete de securite
centrale du dispositif, et elle est ce qui rend acceptable qu'un jeton porteur
circule dans un code que n'importe qui peut photographier dans un couloir : le
pire qu'un code vole produit, c'est une image que l'operateur voit et refuse.

Pourquoi Redis et pas la base
=============================

Une session vit dix minutes. La stocker en base imposerait une migration sur
TOUTES les bases d'etablissement (une par ecole, `app/cli/migrate_all.py`), un
balayage de lignes mortes, et n'offrirait aucune expiration native. Redis fait
les trois gratuitement. Le precedent est dans le depot : la liste blanche des
jetons de rafraichissement y vit deja (`auth_service`), et le quota d'envoi
public s'appuie deja sur un script Lua (`app/core/middleware.py`).

Rancon assumee : Redis tombe, la reprise par code 2D est indisponible. La camera
directe et l'import de fichier ne doivent en aucun cas en dependre.

Le piege, et il est mortel : UNE instance Redis pour TOUTES les ecoles
=====================================================================

Il y a une base MySQL par etablissement, mais une seule instance Redis
(`REDIS_URL`, `app/core/config.py`). Une cle de session sans segment de tenant
serait une passerelle entre ecoles : le jeton de l'une ouvrirait une session
dans l'autre. Les deux cles portent donc le tenant, et il est verifie des deux
cotes — l'ordinateur le tient de son JWT, le telephone du chemin de son URL.

Ce n'est ni un JWT, ni un jeton d'acces personnel, ni un sceau
==============================================================

Le JWT exige un utilisateur et n'est pas revocable individuellement ; le jeton
d'acces personnel est attache a un compte et vit quatre-vingt-dix jours ; le
sceau d'un document est permanent et fait pour etre scanne mille fois. Le jeton
de reprise ne porte qu'une cible et qu'un envoi, expire en dix minutes, se
revoque, et n'est jamais stocke en clair : seul son SHA-256 sert de cle, comme
pour un jeton d'acces personnel.

Deux secrets, pas un : l'operateur ne manipule que l'identifiant de session
(sondage, apercu, confirmation), le telephone ne connait que le jeton. L'un ne
se deduit pas de l'autre.
"""

import hashlib
import json
import logging
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlparse

import redis.asyncio as aioredis
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import TokenData, resolve_permission
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.uploads import DOCUMENTS, LOGOS, PHOTOS, SIGNATURES, UploadKind
from app.services.qr_svg import qr_svg
from app.utils.file_upload import ALLOWED_DOCUMENT_TYPES
from app.utils.photo_upload import EXTENSION_PAR_TYPE

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


# ---------------------------------------------------------------------------
# Une session
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandoffSession:
    """Une session de depot, telle qu'elle vit dans Redis.

    `deadline` est ABSOLUE : une reprise ne la repousse pas. Sans cela, trois
    reprises successives feraient vivre une session — et le code 2D affiche a
    l'ecran — bien au-dela des dix minutes annoncees.
    """

    id: str
    tenant: str
    target_kind: str
    subject_id: int | None
    owner_user_id: int
    label: str
    state: State
    retakes_left: int
    deadline: datetime
    extras: Mapping[str, str] = field(default_factory=dict)
    staged_file: str | None = None
    staged_mime: str | None = None
    staged_client_name: str | None = None
    phone_ip: str | None = None

    @property
    def target(self) -> HandoffTarget:
        return TARGETS[self.target_kind]

    @property
    def mode(self) -> Mode:
        """Sans destinataire, l'ordinateur reprend les octets et rien n'est ecrit."""
        return "finalise" if self.subject_id is not None else "stage-only"


def _cle_session(tenant: str, session_id: str) -> str:
    return f"upload-handoff:{_tenant_valide(tenant)}:{session_id}"


def _cle_jeton(tenant: str, token: str) -> str:
    """L'index jeton -> session. Le jeton n'y figure QUE hache.

    Redis est lu par le support, sauvegarde, et parfois exporte. Un jeton en
    clair dans une cle serait un mot de passe dans un journal.
    """
    empreinte = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"upload-handoff-tok:{_tenant_valide(tenant)}:{empreinte}"


def _tenant_valide(tenant: str) -> str:
    if not _TENANT_VALIDE.match(tenant or ""):
        raise HTTPException(status_code=400, detail="Établissement inconnu")
    return tenant


#: `open` -> `receiving` en une operation indivisible.
#:
#: Deux telephones peuvent scanner le meme code — il est affiche sur un ecran,
#: dans une salle. Lire l'etat puis l'ecrire laisserait les deux passer, et le
#: second depot ecraserait le premier sans que personne ne l'ait vu. Le script
#: ne rend 1 qu'a un seul appelant. Meme forme que le compteur de quota public
#: de `app/core/middleware.py`, et pour la meme raison.
_TRANSITION_SCRIPT = """
local etat = redis.call('HGET', KEYS[1], 'state')
if not etat then return 0 end
if etat ~= ARGV[1] then return 0 end
redis.call('HSET', KEYS[1], 'state', ARGV[2])
return 1
"""

#: Le depot : changer d'etat ET poser le fichier en une seule operation.
#:
#: En deux temps, une session pourrait etre `proposed` sans fichier — l'ecran de
#: l'operateur afficherait un apercu vide, et « Confirmer » ecrirait une photo
#: qui n'existe pas.
_DEPOT_SCRIPT = """
local etat = redis.call('HGET', KEYS[1], 'state')
if etat ~= ARGV[1] then return 0 end
redis.call('HSET', KEYS[1],
  'state', ARGV[2],
  'staged_file', ARGV[3],
  'staged_mime', ARGV[4],
  'staged_client_name', ARGV[5],
  'phone_ip', ARGV[6])
return 1
"""

#: La reprise : decompter et repasser a `open`, sans repousser l'echeance.
#:
#: Rend le nombre de reprises restantes, -1 si l'etat ne s'y prete pas, -2 si le
#: plafond est atteint. Deux clics rapides sur « Reprendre » ne peuvent pas
#: consommer deux fois le meme credit.
_REPRISE_SCRIPT = """
local etat = redis.call('HGET', KEYS[1], 'state')
if etat ~= ARGV[1] then return -1 end
local restant = tonumber(redis.call('HGET', KEYS[1], 'retakes_left') or '0')
if restant <= 0 then return -2 end
redis.call('HSET', KEYS[1], 'state', ARGV[2], 'retakes_left', restant - 1)
return restant - 1
"""


def _hash_vers_session(donnees: Mapping[str, str]) -> HandoffSession:
    sujet = donnees.get("subject_id") or ""
    return HandoffSession(
        id=donnees["id"],
        tenant=donnees["tenant"],
        target_kind=donnees["target_kind"],
        subject_id=int(sujet) if sujet else None,
        owner_user_id=int(donnees["owner_user_id"]),
        label=donnees.get("label", ""),
        state=donnees["state"],  # type: ignore[arg-type]
        retakes_left=int(donnees.get("retakes_left", "0")),
        deadline=datetime.fromisoformat(donnees["deadline"]),
        extras=json.loads(donnees.get("extras") or "{}"),
        staged_file=donnees.get("staged_file") or None,
        staged_mime=donnees.get("staged_mime") or None,
        staged_client_name=donnees.get("staged_client_name") or None,
        phone_ip=donnees.get("phone_ip") or None,
    )


# ---------------------------------------------------------------------------
# Ouvrir
# ---------------------------------------------------------------------------


def get_target(target_kind: str) -> HandoffTarget:
    """La cible demandee, ou 400. Le registre est la liste close de ce qui existe."""
    target = TARGETS.get(target_kind)
    if target is None:
        raise HTTPException(status_code=400, detail="Type de dépôt inconnu")
    return target


async def caller_may_open(db: AsyncSession, current_user: TokenData, target: HandoffTarget) -> bool:
    """L'appelant a-t-il le droit d'ouvrir une session sur cette cible ?

    Le droit vit dans le registre, donc il n'est connu qu'a l'execution : c'est
    `resolve_permission` qui repond, jamais une comparaison de role, et jamais
    `has_permission` — celle-ci est une fabrique de dependance FastAPI qui fige
    son slug a la declaration de la route, ce qu'on ne peut pas faire ici.

    Une cible sans slug est un self-service : le droit d'y toucher est d'etre
    soi-meme, et le sujet est force a l'appelant.
    """
    if target.permission is None:
        return True
    return await resolve_permission(current_user, db, target.permission)


def discreet_label(first_name: str | None, last_name: str | None) -> str:
    """Le libelle affiche sur le telephone : prenom et initiale, rien de plus.

    Un code 2D peut etre scanne par n'importe qui dans un couloir. Afficher le
    nom complet d'un mineur, son matricule ou sa classe transformerait une
    reprise de photo en divulgation. Le meme libelle s'affiche sur l'ecran de
    l'operateur, pour qu'il verifie qu'il regarde bien la bonne session.
    """
    prenom = (first_name or "").strip()
    nom = (last_name or "").strip()
    initiale = f" {nom[0].upper()}." if nom else ""
    return f"{prenom}{initiale}".strip() or "Sans nom"


def _sujet_attendu(target: HandoffTarget, subject_id: int | None, owner_user_id: int) -> int | None:
    """Applique la regle de sujet de la cible, et refuse ce qui n'y entre pas."""
    if target.subject == "self":
        # Force, jamais lu de la requete : sans cela, quiconque peut ouvrir une
        # session sur cette cible pourrait remplacer la photo d'un collegue.
        return owner_user_id
    if target.subject == "none":
        return None
    if target.subject == "required" and subject_id is None:
        raise HTTPException(status_code=400, detail="Ce dépôt exige un destinataire")
    return subject_id


def _extras_attendus(target: HandoffTarget, extras: Mapping[str, str] | None) -> dict[str, str]:
    """Ce que la cible reclame en plus, verifie a l'ouverture et pas apres.

    Le decouvrir a la confirmation reviendrait a refuser une photo deja prise :
    l'operateur a range son telephone, l'eleve est reparti.
    """
    fournis = {k: str(v).strip() for k, v in (extras or {}).items() if k in target.extras}
    manquants = [nom for nom in target.extras if not fournis.get(nom)]
    if manquants:
        raise HTTPException(
            status_code=400,
            detail=f"Information manquante pour ce dépôt : {', '.join(manquants)}",
        )
    return fournis


async def open_session(
    redis: aioredis.Redis,
    *,
    tenant: str,
    target_kind: str,
    owner_user_id: int,
    label: str,
    subject_id: int | None = None,
    extras: Mapping[str, str] | None = None,
) -> tuple[HandoffSession, str]:
    """Ouvre une session et rend (session, jeton en clair).

    Le jeton en clair est rendu UNE fois, pour etre encode dans le code 2D. Il
    n'est stocke nulle part : seul son SHA-256 sert de cle d'index, et il n'y a
    donc aucun moyen de le retrouver ensuite — perdre le code 2D, c'est rouvrir
    une session, pas en recuperer une.
    """
    target = get_target(target_kind)
    tenant = _tenant_valide(tenant)
    sujet = _sujet_attendu(target, subject_id, owner_user_id)
    complements = _extras_attendus(target, extras)

    session_id = secrets.token_urlsafe(16)
    token = secrets.token_urlsafe(32)
    deadline = datetime.now(UTC) + timedelta(seconds=SESSION_TTL_SECONDS)

    donnees: dict[str, str] = {
        "id": session_id,
        "tenant": tenant,
        "target_kind": target.kind,
        "subject_id": str(sujet) if sujet is not None else "",
        "owner_user_id": str(owner_user_id),
        "label": label,
        "state": "open",
        "retakes_left": str(MAX_RETAKES),
        "deadline": deadline.isoformat(),
        "extras": json.dumps(complements, ensure_ascii=False),
    }

    cle = _cle_session(tenant, session_id)
    pipe = redis.pipeline()
    pipe.hset(cle, mapping=donnees)
    pipe.expire(cle, SESSION_TTL_SECONDS)
    pipe.set(_cle_jeton(tenant, token), session_id, ex=SESSION_TTL_SECONDS)
    await pipe.execute()

    return _hash_vers_session(donnees), token


# ---------------------------------------------------------------------------
# Lire
# ---------------------------------------------------------------------------


async def load_session(redis: aioredis.Redis, *, tenant: str, session_id: str) -> HandoffSession:
    """La session, ou 404 si elle a expire ou n'a jamais existe.

    Une session expiree et une session inconnue rendent la meme chose : la
    distinguer dirait a qui essaie des identifiants lesquels ont existe.
    """
    donnees = await redis.hgetall(_cle_session(tenant, session_id))
    if not donnees:
        raise HTTPException(status_code=404, detail="Session de dépôt expirée ou introuvable")
    session = _hash_vers_session(donnees)
    if session.tenant != tenant:
        # La cle porte deja le tenant : arriver ici signifie qu'une cle a ete
        # construite autrement quelque part. On refuse plutot que de servir.
        #
        # L'identifiant N'EST PAS journalise : il vient du chemin d'une URL
        # publique, donc de l'exterieur. Un retour a la ligne glisse dedans
        # fabrique une fausse entree de journal, et c'est le journal qu'on lit
        # le jour ou l'on cherche a comprendre. Les deux etablissements
        # suffisent a diagnostiquer, et ils viennent de la session.
        logger.error(
            "Session de depot lue depuis le mauvais etablissement (attendu %r, trouve %r)",
            tenant,
            session.tenant,
        )
        raise HTTPException(status_code=404, detail="Session de dépôt expirée ou introuvable")
    return session


async def load_by_token(redis: aioredis.Redis, *, tenant: str, token: str) -> HandoffSession:
    """La session que ce jeton designe, dans CET etablissement.

    Le tenant vient du chemin de l'URL publique. Un jeton valide ailleurs ne
    resout rien ici : sa cle d'index n'existe pas sous ce segment.
    """
    session_id = await redis.get(_cle_jeton(tenant, token))
    if not session_id:
        raise HTTPException(status_code=404, detail="Lien de dépôt expiré ou déjà utilisé")
    return await load_session(redis, tenant=tenant, session_id=session_id)


def ensure_owner(session: HandoffSession, user_id: int) -> None:
    """Une session appartient a l'operateur qui l'a ouverte, pas a son metier.

    Deux personnes du secretariat detiennent le meme droit et travaillent en
    parallele : sans cette verification, l'une confirmerait la photo que l'autre
    attend, sur l'eleve qui n'est pas devant elle.
    """
    if session.owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="Cette session de dépôt n'est pas la vôtre")


# ---------------------------------------------------------------------------
# Avancer
# ---------------------------------------------------------------------------


async def _transition(
    redis: aioredis.Redis, session: HandoffSession, *, depuis: State, vers: State
) -> bool:
    resultat = await redis.eval(  # type: ignore[no-untyped-call]
        _TRANSITION_SCRIPT, 1, _cle_session(session.tenant, session.id), depuis, vers
    )
    return bool(int(resultat))


async def claim_for_upload(redis: aioredis.Redis, *, tenant: str, token: str) -> HandoffSession:
    """Le telephone prend la main : `open` -> `receiving`, une seule fois.

    Refuser ici plutot qu'a l'ecriture est ce qui empeche deux telephones ayant
    scanne le meme code de deposer tous les deux, le second ecrasant le premier
    sans que l'operateur ait rien vu passer.
    """
    session = await load_by_token(redis, tenant=tenant, token=token)
    if not await _transition(redis, session, depuis="open", vers="receiving"):
        raise HTTPException(status_code=409, detail="Ce dépôt a déjà été utilisé")
    return session


async def release_claim(redis: aioredis.Redis, session: HandoffSession) -> None:
    """L'envoi a echoue : la session redevient disponible sans nouveau code 2D.

    C'est ce qui fait qu'un « Réessayer » suffit quand la donnee mobile coupe au
    milieu d'un envoi — le fichier est encore dans le telephone, l'echeance n'a
    pas bouge, et personne n'a a se relever pour rescanner.
    """
    await _transition(redis, session, depuis="receiving", vers="open")


async def mark_proposed(
    redis: aioredis.Redis,
    session: HandoffSession,
    *,
    staged_file: str,
    staged_mime: str,
    client_name: str | None,
    phone_ip: str | None,
) -> None:
    """Le fichier est dans le sas : la session passe sous les yeux de l'operateur.

    L'adresse du telephone est rangee ici et nulle part ailleurs : c'est la seule
    trace de qui a reellement pris la photo, et elle sera journalisee a la
    confirmation.
    """
    pose = await redis.eval(  # type: ignore[no-untyped-call]
        _DEPOT_SCRIPT,
        1,
        _cle_session(session.tenant, session.id),
        "receiving",
        "proposed",
        staged_file,
        staged_mime,
        (client_name or "")[:255],
        phone_ip or "",
    )
    if not int(pose):
        raise HTTPException(status_code=409, detail="Ce dépôt n'est plus en attente d'envoi")


async def request_retake(redis: aioredis.Redis, session: HandoffSession) -> int:
    """« Reprendre » : le depot est jete, la session redevient ouverte.

    Rend le nombre de reprises restantes. L'echeance n'est pas repoussee — c'est
    delibere : trois reprises ne doivent pas faire vivre une demi-heure un code
    2D affiche sur un ecran.
    """
    restant = int(
        await redis.eval(  # type: ignore[no-untyped-call]
            _REPRISE_SCRIPT, 1, _cle_session(session.tenant, session.id), "proposed", "open"
        )
    )
    if restant == -1:
        raise HTTPException(status_code=409, detail="Aucun dépôt à reprendre")
    if restant == -2:
        raise HTTPException(
            status_code=409, detail="Trop de reprises. Ouvrez une nouvelle session."
        )
    _oublier_le_fichier(session)
    return restant


async def close_session(redis: aioredis.Redis, session: HandoffSession) -> None:
    """Fin de vie : la session disparait, et le fichier du sas avec elle.

    Sert a la confirmation comme a la revocation. Le jeton cesse d'ouvrir quoi
    que ce soit a l'instant meme, sans attendre l'echeance.

    **L'index du jeton, lui, survit jusqu'a son echeance, et c'est sans
    consequence.** Sa cle est l'empreinte du jeton, et une empreinte ne se
    remonte pas : on ne peut donc pas l'effacer d'ici, ou le clair n'est plus
    detenu. Ce qu'il rend est un identifiant de session ; la session n'existant
    plus, `load_by_token` ne trouve rien et refuse. La revocation est reelle
    parce que la SESSION disparait, pas parce que les deux cles disparaissent.

    Cette docstring a d'abord affirme le contraire. Une propriete de securite
    annoncee mais non tenue est pire qu'une propriete absente : elle dispense
    le lecteur suivant de la verifier.
    """
    _oublier_le_fichier(session)
    await redis.delete(_cle_session(session.tenant, session.id))


def _oublier_le_fichier(session: HandoffSession) -> None:
    from app.utils.handoff_storage import delete_staged

    delete_staged(session.staged_file)


def promote(session: HandoffSession) -> str:
    """Sort le depot du sas vers sa sorte definitive et rend son URL publique.

    Le sas n'est pas servi : tant que le fichier y est, il n'a pas d'URL du tout.
    C'est ici, et seulement ici — apres le regard de l'operateur — qu'il en
    acquiert une.
    """
    from app.utils.handoff_storage import promote_staged

    if not session.staged_file:
        raise HTTPException(status_code=409, detail="Aucun fichier déposé pour cette session")
    return promote_staged(
        session.staged_file,
        kind=session.target.upload_kind,
        prefix=session.target.prefix_for(session.subject_id),
    )


def staged_bytes(session: HandoffSession) -> tuple[bytes, str]:
    """Les octets deposes et leur type, pour l'apercu et pour le mode `stage-only`.

    Seul chemin de lecture du sas : il n'y a pas de montage statique derriere,
    donc pas d'URL a deviner. L'appelant est deja authentifie et proprietaire de
    la session quand il arrive ici.
    """
    from app.utils.handoff_storage import read_staged

    if not session.staged_file:
        raise HTTPException(status_code=409, detail="Aucun fichier déposé pour cette session")
    return read_staged(session.staged_file), session.staged_mime or "application/octet-stream"


async def receive_deposit(
    redis: aioredis.Redis,
    *,
    tenant: str,
    token: str,
    file: UploadFile,
    phone_ip: str | None,
) -> HandoffSession:
    """Le geste du telephone, en entier : prendre la main, poser, se retirer.

    Aucune colonne n'est touchee ici, et aucune base n'est meme ouverte. Le
    fichier va dans le sas, la session passe sous les yeux de l'operateur, et
    c'est tout. L'ecriture attend un humain devant un ecran authentifie : c'est
    la propriete qui rend acceptable qu'un jeton porteur circule dans un code
    que n'importe qui peut photographier.

    L'ordre compte. On prend d'abord la main — `open` -> `receiving`, en une
    operation indivisible — PUIS on lit le fichier. L'inverse laisserait deux
    telephones lire chacun le leur avant que l'un des deux ne perde, et le
    perdant aurait passe une minute de 3G pour rien.

    Un echec en cours de route rend la main : la session redevient `open` sans
    consommer de reprise et sans nouveau code. C'est ce qui fait qu'un
    « Réessayer » suffit quand la donnee mobile coupe au milieu d'un envoi.

    Le type declare est confronte a la table de la CIBLE, pas a une table
    globale : une piece jointe accepte le PDF, une photo non. Les octets, eux,
    sont confrontes au type a la porte du sas.
    """
    from app.utils.handoff_storage import write_staged

    session = await claim_for_upload(redis, tenant=tenant, token=token)
    target = session.target
    try:
        extension = target.extension_pour(file.content_type)
        nom = await write_staged(
            file,
            session_id=session.id,
            extension=extension,
            max_bytes=target.max_bytes,
        )
    except BaseException:
        await release_claim(redis, session)
        raise

    await mark_proposed(
        redis,
        session,
        staged_file=nom,
        staged_mime=file.content_type or "application/octet-stream",
        client_name=file.filename,
        phone_ip=phone_ip,
    )
    return await load_session(redis, tenant=tenant, session_id=session.id)


def public_view(session: HandoffSession) -> dict[str, Any]:
    """Ce que le telephone a le droit de savoir, et rien de plus.

    Pas d'etat civil, pas de matricule, pas de classe : de quoi peindre une page
    et cadrer une photo. Le libelle est deja reduit a un prenom et une initiale
    par `discreet_label`.
    """
    target = session.target
    return {
        "label": session.label,
        "kind": target.kind,
        "metier": target.metier,
        "accepts": sorted(target.accepted_types),
        "max_bytes": target.max_bytes,
        "state": session.state,
        "expires_at": session.deadline,
    }


# ---------------------------------------------------------------------------
# Ce que l'ordinateur demande
# ---------------------------------------------------------------------------
#
# Au-dessus : la mecanique d'une session (jeton, etats, sas). Ici : les quatre
# gestes de l'operateur — ouvrir, regarder, confirmer, reprendre. Ils vivent
# dans ce module et non dans le routeur parce que chacun est une decision, pas
# un branchement : quel droit exiger, quel libelle montrer, dans quel ordre
# promouvoir puis ecrire.


#: Le chemin de la page telephone, cote frontend. Meme forme que la page de
#: verification d'un document (`/verifier/{tenant}/{token}`) : le tenant est
#: dans le chemin, parce qu'un telephone n'a pas de session et que c'est la
#: seule chose qui dise quelle base ouvrir.
PUBLIC_PATH = "televerser"


def handoff_url(tenant: str, token: str) -> str:
    """L'URL absolue encodee dans le code QR."""
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/{PUBLIC_PATH}/{_tenant_valide(tenant)}/{token}"


def public_base_warnings() -> list[str]:
    """Ce qui empechera le telephone d'arriver au bout du lien, dit a l'avance.

    Le code QR encode une URL ABSOLUE, construite depuis `PUBLIC_BASE_URL`. Or
    l'ordinateur est sur le reseau de l'ecole et le telephone sur sa donnee
    mobile : les deux ne voient pas le meme reseau. Une base pointant sur
    `localhost` ou sur une plage privee donne un code QR parfaitement valide qui
    mene a une page blanche, et l'operateur n'a aucun moyen de comprendre
    pourquoi — le telephone dit « site inaccessible », pas « votre serveur a mal
    configure une variable ».

    On avertit, on ne refuse pas : sur un poste de developpement la base EST
    `localhost`, et refuser d'ouvrir la session y rendrait l'ecran intestable.
    L'avertissement remonte a l'ecran de l'operateur ET dans les journaux, ce
    qui en fait la seule chose visible quand la configuration est fausse en
    production.

    Rien ici ne PROUVE la joignabilite : un nom public peut n'etre pas resolu
    depuis un reseau mobile, un pare-feu peut filtrer, un certificat peut
    manquer. Ce controle elimine les configurations dont on SAIT qu'elles
    echouent ; il ne remplace pas le scan reel depuis un telephone en donnee
    mobile, qui reste la seule verification qui vaille.
    """
    alertes: list[str] = []
    base = settings.PUBLIC_BASE_URL.strip()
    adresse = urlparse(base)
    hote = (adresse.hostname or "").lower()

    if adresse.scheme not in {"http", "https"} or not hote:
        alerte = (
            "L'adresse publique du site (PUBLIC_BASE_URL) n'est pas une URL absolue : "
            "le code QR ne mènera nulle part. Corrigez la configuration du serveur."
        )
        logger.warning("Reprise par code QR — %s", alerte)
        return [alerte]

    if _hote_local(hote):
        alertes.append(
            f"L'adresse publique du site ({base}) ne désigne que ce réseau : un téléphone "
            "sur sa donnée mobile n'y accédera pas. Le code QR ne fonctionnera que depuis "
            "le réseau de l'établissement, s'il y accède."
        )

    if adresse.scheme == "http":
        alertes.append(
            "Le site est servi en HTTP : le téléphone ne pourra pas ouvrir sa caméra en "
            "direct et proposera l'appareil photo du système à la place."
        )

    for alerte in alertes:
        logger.warning("Reprise par code QR — %s", alerte)
    return alertes


def _hote_local(hote: str) -> bool:
    """L'hote ne designe-t-il que le reseau local ?

    Deux familles : les noms qui ne se resolvent que sur place (`localhost`, le
    `.local` du mDNS, un nom sans point donc sans domaine) et les adresses IP
    des plages non routables sur Internet (RFC 1918, boucle locale, lien local,
    plages reservees).
    """
    if hote in {"localhost", "127.0.0.1", "::1"} or hote.endswith((".local", ".localhost")):
        return True
    try:
        adresse = ip_address(hote)
    except ValueError:
        # Un nom d'hote. Sans point, il n'a pas de domaine : il ne se resout que
        # sur un reseau qui le connait deja.
        return "." not in hote
    return bool(
        adresse.is_private
        or adresse.is_loopback
        or adresse.is_link_local
        or adresse.is_reserved
        or adresse.is_unspecified
    )


async def _label_eleve(db: AsyncSession, subject_id: int) -> str:
    from app.repositories import admin_repository as repo

    eleve = await repo.get_student_by_id(db, subject_id)
    if eleve is None:
        raise NotFoundError("Student", subject_id)
    return discreet_label(eleve.first_name, eleve.last_name)


async def _label_enseignant(db: AsyncSession, subject_id: int) -> str:
    from app.repositories import admin_repository as repo

    enseignant = await repo.get_teacher_by_id(db, subject_id)
    if enseignant is None:
        raise NotFoundError("Teacher", subject_id)
    return discreet_label(enseignant.first_name, enseignant.last_name)


async def _label_personnel(db: AsyncSession, subject_id: int) -> str:
    from app.repositories import admin_repository as repo

    personne = await repo.get_staff_by_id(db, subject_id)
    if personne is None:
        raise NotFoundError("Staff", subject_id)
    return discreet_label(personne.first_name, personne.last_name)


#: Les cibles dont le sujet porte un nom. Ce sont exactement celles dont la
#: regle de sujet est `required` ou `optional` — donc celles ou l'identifiant
#: demande par l'operateur EST le sujet retenu. Les autres n'ont personne a
#: nommer : un logo n'a pas de prenom, et la photo de profil est celle de qui
#: regarde l'ecran.
_LABELS: Mapping[str, Callable[[AsyncSession, int], Awaitable[str]]] = {
    "student_photo": _label_eleve,
    "student_document": _label_eleve,
    "teacher_photo": _label_enseignant,
    "staff_photo": _label_personnel,
}


async def resolve_label(db: AsyncSession, target: HandoffTarget, subject_id: int | None) -> str:
    """Le libelle discret de la session, lu en base et jamais recu du client.

    Deux raisons de ne pas laisser l'ecran l'envoyer. La premiere : ce libelle
    s'affiche sur un telephone que n'importe qui peut avoir en main, et un champ
    libre y ferait passer ce que l'appelant veut — le matricule, la classe, la
    date de naissance. La seconde : le charger ICI verifie du meme geste que le
    destinataire existe. Le decouvrir a la confirmation reviendrait a refuser
    une photo deja prise, l'eleve reparti.

    Chaine vide quand il n'y a personne a nommer : l'ecran affiche alors la
    nature du geste (`metier`), qui ne revele rien.
    """
    if subject_id is None:
        return ""
    charger = _LABELS.get(target.kind)
    return await charger(db, subject_id) if charger else ""


def operator_view(session: HandoffSession) -> dict[str, Any]:
    """Ce que l'ecran de l'operateur relit toutes les deux secondes.

    Symetrique de `public_view`, et deliberement un peu plus riche : celui qui
    lit ceci est authentifie, proprietaire de la session et titulaire du droit.
    Il voit l'etat, le mode et le type recu — de quoi choisir entre
    « Confirmer » et « Reprendre ».

    Toujours pas d'etat civil, et ce n'est pas un oubli : le libelle est le MEME
    que celui du telephone. C'est ce qui permet a l'operateur de verifier d'un
    coup d'oeil que les deux ecrans parlent de la meme personne.
    """
    return {
        "id": session.id,
        "state": session.state,
        "mode": session.mode,
        "label": session.label,
        "metier": session.target.metier,
        "expires_at": session.deadline,
        "retakes_left": session.retakes_left,
        "staged_mime": session.staged_mime,
    }


@dataclass(frozen=True)
class OpenedSession:
    """Ce qu'une ouverture rend a l'ecran de l'operateur.

    Le jeton en clair n'y figure pas seul : il ne vit que dans `url`, et `url`
    n'est la que parce qu'un ecran doit pouvoir montrer le lien a taper quand un
    telephone ne scanne pas.
    """

    session: HandoffSession
    url: str
    qr_svg: str
    warnings: tuple[str, ...]


async def _autoriser(db: AsyncSession, current_user: TokenData, target: HandoffTarget) -> None:
    """Le droit de la CIBLE, redemande a la matrice a chaque geste.

    Pas une fois a l'ouverture : a chaque appel. Une session vit dix minutes, et
    un droit retire pendant ce temps doit fermer la porte tout de suite — la
    photo n'est pas encore ecrite, c'est precisement le moment ou refuser coute
    le moins cher.
    """
    if not await caller_may_open(db, current_user, target):
        raise PermissionDeniedError(target.permission or target.kind)


async def start_session(
    redis: aioredis.Redis,
    db: AsyncSession,
    *,
    current_user: TokenData,
    target_kind: str,
    subject_id: int | None = None,
    extras: Mapping[str, str] | None = None,
) -> OpenedSession:
    """Ouvre une session de depot et rend de quoi peindre l'ecran de l'operateur.

    L'ordre compte : le droit d'abord, le destinataire ensuite, la session en
    dernier. Ouvrir puis verifier laisserait derriere chaque refus une session
    valide dix minutes, avec son jeton, pour un geste qu'on vient d'interdire.

    L'etablissement n'est pas un parametre : il vient du jeton de l'appelant,
    lui-meme deja confronte au tenant de la requete par `get_current_user`. Le
    laisser choisir ferait de cette route la passerelle inter-ecoles que la cle
    Redis s'applique a interdire.
    """
    target = get_target(target_kind)
    await _autoriser(db, current_user, target)
    label = await resolve_label(db, target, subject_id)

    session, token = await open_session(
        redis,
        tenant=current_user.tenant_id,
        target_kind=target.kind,
        owner_user_id=current_user.user_id,
        label=label,
        subject_id=subject_id,
        extras=extras,
    )
    url = handoff_url(session.tenant, token)
    return OpenedSession(
        session=session,
        url=url,
        qr_svg=qr_svg(url),
        warnings=tuple(public_base_warnings()),
    )


async def load_for_operator(
    redis: aioredis.Redis,
    db: AsyncSession,
    *,
    current_user: TokenData,
    session_id: str,
) -> HandoffSession:
    """La session, si elle est celle de cet operateur et qu'il en a toujours le droit.

    Deux verifications, et elles ne disent pas la meme chose. La propriete
    repond a « est-ce MA session » : deux personnes du secretariat detiennent le
    meme droit et travaillent en parallele. La permission repond a « ai-je
    encore le droit de ce geste » : elle vit dans la matrice, elle peut changer
    pendant la session, et le registre seul sait laquelle exiger pour cette
    cible.
    """
    session = await load_session(redis, tenant=current_user.tenant_id, session_id=session_id)
    ensure_owner(session, current_user.user_id)
    await _autoriser(db, current_user, session.target)
    return session


async def confirm_session(redis: aioredis.Redis, db: AsyncSession, session: HandoffSession) -> str:
    """Le regard de l'operateur devient une ecriture. Une seule fois.

    L'etat passe a `done` AVANT la promotion, et de facon indivisible : deux
    clics rapides sur « Confirmer » doivent produire une photo, pas deux
    fichiers ni — pour une piece jointe — deux lignes en base. Le second clic
    trouve un etat qui n'est plus `proposed` et repart avec un refus.

    Si la promotion echoue, le fichier est encore dans le sas et la session
    retourne a l'operateur : une panne de disque ne doit pas lui faire perdre
    une photo qu'il a sous les yeux. Si c'est l'ecriture metier qui echoue, le
    fichier est deja sorti du sas : l'erreur remonte telle quelle et la session
    reste fermee, parce que la retenter n'aurait plus rien a promouvoir.

    Sans destinataire il n'y a rien a ecrire : a l'inscription, la fiche n'existe
    pas encore. L'ecran recupere alors les octets par l'apercu puis revoque la
    session — c'est le mode `stage-only`, et le refus ci-dessous est ce qui
    empeche de sortir un fichier du sas pour ne l'attacher a personne.
    """
    if session.mode == "stage-only":
        raise HTTPException(
            status_code=409,
            detail="Ce dépôt n'a pas de destinataire : récupérez l'image par l'aperçu.",
        )
    target = session.target
    if target.finalise is None:  # pragma: no cover - toute cible du registre en porte une
        raise HTTPException(status_code=409, detail="Ce type de dépôt ne sait pas se confirmer")

    if not await _transition(redis, session, depuis="proposed", vers="done"):
        raise HTTPException(status_code=409, detail="Aucun dépôt à confirmer")

    try:
        url = promote(session)
    except Exception:
        await _transition(redis, session, depuis="done", vers="proposed")
        raise

    await target.finalise(db, session, url)
    await close_session(redis, session)
    return url
