"""Une session de reprise : son jeton, ses etats, son sas.

Dix minutes de vie dans Redis, jamais en base : une session ne justifie
pas une migration sur chaque base d'etablissement. Les transitions
passent par des scripts Lua parce qu'un `if` en Python entre un `get` et
un `set` laisse deux telephones s'attribuer le meme envoi.
"""

import hashlib
import json
import logging
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import redis.asyncio as aioredis
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, resolve_permission

from ._registre import TARGETS, HandoffTarget

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
