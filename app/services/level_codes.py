"""Code national d'un niveau, à partir du nom libre que l'école lui a donné.

Une école écrit « 6ème », une autre « 6eme », « Sixième » ou « 6e ». Le
lycée ajoute souvent la série au nom : « 2nde C », « Terminale D ». La fiche
de renseignements, elle, parle en codes nationaux (`PreviousLevel`). Ce
module fait le pont, avec le repliage que le rapport DEEP utilise déjà pour
reconnaître un cycle.

Un nom qui ne ressemble à rien de connu rend `None`. On ne devine pas : un
code faux ferait passer un élève pour redoublant.
"""

from app.models.enrollment import PreviousLevel
from app.services.deep_report._metrics import normalise_level_label

# L'ordre compte : « 1ere » doit être lu avant qu'un préfixe plus court ne
# l'attrape, et le lycée passe avant le collège pour la même raison.
_PREFIXES: tuple[tuple[tuple[str, ...], PreviousLevel], ...] = (
    (("terminale", "tle"), PreviousLevel.TERMINALE),
    (("premiere", "1ere", "1re"), PreviousLevel.PREMIERE),
    (("seconde", "2nde", "2de", "2nd"), PreviousLevel.SECONDE),
    (("troisieme", "3eme", "3e"), PreviousLevel.TROISIEME),
    (("quatrieme", "4eme", "4e"), PreviousLevel.QUATRIEME),
    (("cinquieme", "5eme", "5e"), PreviousLevel.CINQUIEME),
    (("sixieme", "6eme", "6e"), PreviousLevel.SIXIEME),
    (("cm2",), PreviousLevel.CM2),
)

# Un niveau nommé d'un seul chiffre (« 6 ») reste reconnaissable.
_BARE_DIGITS = {
    "6": PreviousLevel.SIXIEME,
    "5": PreviousLevel.CINQUIEME,
    "4": PreviousLevel.QUATRIEME,
    "3": PreviousLevel.TROISIEME,
}

#: Niveaux où la LV2 ne s'enseigne pas encore.
LEVELS_WITHOUT_LV2 = frozenset({PreviousLevel.SIXIEME, PreviousLevel.CINQUIEME})


def national_level_code(level_name: str | None) -> PreviousLevel | None:
    """Le code national d'un nom de niveau, ou `None` s'il n'évoque rien de sûr."""
    if not level_name:
        return None
    normalised = normalise_level_label(level_name)
    if normalised in _BARE_DIGITS:
        return _BARE_DIGITS[normalised]
    for prefixes, code in _PREFIXES:
        if normalised.startswith(prefixes):
            return code
    return None
