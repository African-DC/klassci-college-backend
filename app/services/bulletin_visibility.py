"""Ce qu'une famille en retard voit d'un bulletin : qu'il existe, pas ce qu'il dit.

La retenue pour impayé portait jusqu'ici sur le seul téléchargement. Mais la
liste des bulletins d'un portail rend déjà la moyenne, le rang et la mention :
c'est le contenu du bulletin, et le retenir en PDF tout en l'affichant à
l'écran ne retenait rien du tout.

Deux exigences se contredisent en apparence, et ce module les tient ensemble :

- **La famille doit voir que le bulletin existe.** Une liste vide lui ferait
  croire qu'aucun bulletin n'a été édité, et elle appellerait le secrétariat
  pour un problème qui n'existe pas. Le trimestre, la classe et l'année
  restent donc affichés.
- **Elle ne doit pas en lire le contenu.** Moyenne, rang, mention et
  appréciations reviennent à `None`.

`None`, et jamais `0` : le raisonnement est celui de `finance_visibility`.
Un zéro se lit « l'élève a eu zéro de moyenne », ce qui est une calomnie ;
`None` se lit « vous ne voyez pas cette information », et l'écran affiche un
tiret honnête à côté du motif de la retenue.

Les **notes publiées ne passent pas par ici** : elles restent consultables.
La porte s'applique au bulletin, document de synthèse officiel, pas au relevé
des notes.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.document_release_service import ReleaseStatus

# Tout ce qui constitue le jugement porté sur l'élève, plus le lien vers le
# PDF. Rédigés d'un bloc plutôt qu'un par un : un champ de contenu ajouté
# plus tard à un schéma de portail sans être listé ici fuiterait en silence.
CONTENT_FIELDS = frozenset(
    {
        "average",
        "rank",
        "mention",
        "teacher_comment",
        "council_decision",
        "file_url",
    }
)

_TRIMESTER_LABELS = {1: "1er trimestre", 2: "2e trimestre", 3: "3e trimestre"}


def _trimester_label(trimester: int) -> str:
    return _TRIMESTER_LABELS.get(trimester, f"{trimester}e trimestre")


def _francs(amount: float) -> str:
    """80000.0 -> « 80 000 ». Espace comme séparateur, comme partout ailleurs."""
    return f"{amount:,.0f}".replace(",", " ")


@dataclass(frozen=True, slots=True)
class Withholding:
    """La retenue applicable aux bulletins d'un élève, résolue une seule fois.

    Résolue une fois puis appliquée à chaque ligne : interroger l'échéancier
    par bulletin ferait trois fois le même calcul pour les trois trimestres
    d'une même famille.
    """

    active: bool
    late_amount: float

    @classmethod
    def from_release(cls, status: ReleaseStatus) -> Withholding:
        return cls(active=status.blocked, late_amount=status.late_amount)

    def notice_for(self, trimester: int) -> str:
        """La phrase que lit la famille : ce qui est retenu, combien, et où aller.

        Elle nomme le trimestre parce qu'une famille peut avoir trois
        bulletins retenus à l'écran, et un motif identique répété trois fois
        sans dire lequel il concerne se lit comme un bug d'affichage.
        """
        return (
            f"Bulletin du {_trimester_label(trimester)} indisponible : "
            f"{_francs(self.late_amount)} FCFA en retard sur l'échéancier. "
            "Rapprochez-vous du secrétariat."
        )

    def apply(self, block: dict) -> dict:
        """Vide le contenu du bulletin si la famille est en retard, et dit pourquoi.

        Rend toujours les trois champs de retenue, y compris quand rien n'est
        retenu : un écran qui doit deviner si l'absence d'un champ vaut « à
        jour » ou « le serveur ne me l'a pas dit » finit par choisir mal.
        """
        if not self.active:
            return {
                **block,
                "is_withheld": False,
                "withheld_reason": None,
                "withheld_amount": None,
            }

        redacted = {key: (None if key in CONTENT_FIELDS else value) for key, value in block.items()}
        redacted["is_withheld"] = True
        redacted["withheld_reason"] = self.notice_for(int(block["trimester"]))
        redacted["withheld_amount"] = self.late_amount
        return redacted


#: Aucune retenue. Pour les appelants internes dont l'accès est déjà tranché
#: en amont — la fabrique de PDF officielle, un export d'administration.
OPEN = Withholding(active=False, late_amount=0.0)
