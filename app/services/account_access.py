"""Couper l'accès d'un compte quand la fiche qui le portait est détruite.

Jusqu'ici, supprimer définitivement une fiche détruisait la fiche et laissait
le compte de connexion intact : une comptable renvoyée le lundi se connectait
encore le mardi avec son mot de passe. Ce module ferme cette porte, et il la
ferme en **désactivant** le compte, pas en le supprimant.

Pourquoi désactiver plutôt que supprimer
----------------------------------------

Huit clés étrangères pointent vers ``users`` en ``RESTRICT`` : une caisse
tenue, un message envoyé ou reçu, une convocation de parent, une autorisation
de composer, un appel de classe déclaré, et les deux profils eux-mêmes. La
base refuse donc de supprimer précisément les comptes qui ont le plus agi. La
suppression échouerait là où la révocation compte le plus, et réussirait
ailleurs à effacer l'attribution d'actes passés. Un versement encaissé ou une
convocation signée doit rester attribuable à quelqu'un : on retire le droit
d'entrer, jamais la signature.

Le journal d'audit, lui, survivrait à une suppression — il ne porte aucune clé
étrangère vers ``users`` et fige ``actor_email`` sur chaque ligne. Mais il est
le seul dans ce cas ; le reste du logiciel ne l'est pas.

Ce que la désactivation coupe réellement
----------------------------------------

Vérifié à la lecture, pas supposé : ``auth_service.login``,
``auth_service.refresh``, ``dependencies._authenticate_jwt`` et
``dependencies._authenticate_pat`` relisent tous ``users.is_active`` en base à
chaque appel. Un jeton d'accès déjà émis, même valable encore trente minutes,
est donc refusé dès la requête suivante : il n'y a pas de session en mémoire à
attendre.

Les jetons personnels (``personal_access_tokens``) sont malgré tout révoqués
nommément. Ils survivent au drapeau ``is_active`` par nature — un compte
réactivé plus tard (l'écran « modifier le compte » remet ``is_active`` à vrai)
les ramènerait à la vie, silencieusement, avec leurs portées d'origine.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AccessRevocation:
    """Ce qui est arrivé au compte de connexion, pour le journal et le courriel.

    « Fiche supprimée » et « fiche supprimée, accès révoqué » ne sont pas la
    même information : la seconde répond à la question que se pose vraiment un
    chef d'établissement le lendemain d'un licenciement.
    """

    user_id: int | None = None
    email: str | None = None
    #: Le compte était déjà désactivé avant le geste. On le dit plutôt que de
    #: laisser croire à une révocation qui n'a rien changé.
    was_already_inactive: bool = False
    tokens_revoked: int = 0

    @property
    def happened(self) -> bool:
        """Vrai quand un compte a effectivement été touché."""
        return self.user_id is not None

    def sentence(self) -> str:
        """Une phrase pour le courriel, lisible par une directrice."""
        if not self.happened:
            return "Cette fiche ne donnait accès au logiciel par aucun compte de connexion."

        compte = self.email or "le compte de connexion"
        if self.was_already_inactive:
            phrase = f"Le compte de connexion {compte} était déjà désactivé : il le reste."
        else:
            phrase = (
                f"Accès révoqué : le compte de connexion {compte} ne permet "
                "plus de se connecter, ni avec son mot de passe, ni avec une "
                "session déjà ouverte."
            )

        if self.tokens_revoked:
            accord = "" if self.tokens_revoked == 1 else "s"
            phrase += (
                f" {self.tokens_revoked} jeton{accord} d'accès personnel également révoqué{accord}."
            )
        return phrase

    def as_audit_values(self) -> dict[str, object]:
        """Ce que le journal d'audit retient du sort du compte."""
        if not self.happened:
            return {"acces_revoque": False, "compte": None}
        return {
            "acces_revoque": True,
            "compte": self.email,
            "compte_id": self.user_id,
            "deja_desactive": self.was_already_inactive,
            "jetons_revoques": self.tokens_revoked,
        }


#: Rendu quand la fiche ne portait aucun compte — une inscription, un élève
#: sans identifiants, un parent que l'école n'a jamais inscrit au portail.
NO_ACCOUNT = AccessRevocation()


async def revoke_access(db: AsyncSession, user_id: int | None) -> AccessRevocation:
    """Ferme l'accès du compte donné. Ne lève jamais pour un compte absent.

    À appeler DANS la transaction de la suppression : si la destruction de la
    fiche échoue, la révocation doit disparaître avec elle. L'inverse — un
    compte coupé pour une fiche finalement conservée — mettrait quelqu'un
    dehors sans que personne ne l'ait décidé.
    """
    if user_id is None:
        return NO_ACCOUNT

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        # La fiche pointait un compte qui n'existe plus. Rien à couper, mais on
        # le dit : c'est le genre d'incohérence qu'on veut voir passer.
        logger.warning("Fiche liee au compte %s, introuvable au moment de couper l'acces", user_id)
        return NO_ACCOUNT

    was_already_inactive = not user.is_active
    user.is_active = False

    from app.services.pat_service import revoke_user_pats

    tokens_revoked = await revoke_user_pats(db, user_id)
    await db.flush()

    logger.warning(
        "Acces revoque : compte %s (%s), %s jeton(s) personnel(s) revoque(s)",
        user_id,
        user.email,
        tokens_revoked,
    )
    return AccessRevocation(
        user_id=user_id,
        email=user.email,
        was_already_inactive=was_already_inactive,
        tokens_revoked=tokens_revoked,
    )
