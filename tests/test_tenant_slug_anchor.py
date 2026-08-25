"""Un slug de tenant ne doit pas pouvoir finir par un saut de ligne.

Le slug finit entre accents graves dans un `CREATE DATABASE`, qui n'accepte
aucun paramètre lié : la seule protection est la validation en amont.

La classe de caractères interdit l'accent grave et le point-virgule, donc
aucune injection n'était possible — c'est ce que dit ce fichier, et il fallait
le vérifier plutôt que de le supposer. Mais `$` en Python accepte aussi la
position juste avant un saut de ligne final, si bien qu'un slug terminé par
`\n` passait. La base créée portait alors ce saut de ligne dans son nom,
indiscernable à l'écran de celle qui n'en a pas, et impossible à retrouver en
tapant le nom qu'on croit avoir donné.

Les tests appellent le validateur, ils ne lisent pas son motif.
"""

import pytest

from app.core.slug import is_valid_tenant_slug


@pytest.mark.parametrize("slug", ["rostan-bouake", "local", "a1", "ecole-2026-b"])
def test_un_slug_normal_reste_accepte(slug: str) -> None:
    assert is_valid_tenant_slug(slug)


@pytest.mark.parametrize(
    "slug",
    [
        "rostan\n",  # le défaut : accepté avant le passage à \Z
        "rostan\n\n",
        "\nrostan",
        "rostan-bouake\r\n",
    ],
)
def test_un_saut_de_ligne_est_refuse(slug: str) -> None:
    assert not is_valid_tenant_slug(slug)


@pytest.mark.parametrize(
    "slug",
    ["a`b", "a;b", "a b", "ABC", "a", "-abc", "abc-", "a/b", "a--b\n"],
)
def test_ce_qui_pourrait_sortir_du_nom_de_base_est_refuse(slug: str) -> None:
    """L'accent grave et le point-virgule fermeraient l'identifiant cité.

    Ils étaient déjà refusés : ce test l'établit au lieu de le supposer, pour
    que le jour où quelqu'un élargit la classe de caractères, la conséquence
    soit visible ici.
    """
    assert not is_valid_tenant_slug(slug)
