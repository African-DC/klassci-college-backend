"""Une route littérale ne doit pas être avalée par `/fee-variants/{variant_id}`.

Starlette sert la première route qui correspond. Déclarée après la route
paramétrée, `/fee-variants/mandatory-basket` répondait 422 (« mandatory-basket »
n'est pas un entier) et la simulation de grille restait vide.
"""

from starlette.routing import Match

from app.routers.fees import router


def _first_match(path: str) -> str:
    scope = {"type": "http", "path": path, "method": "GET"}
    for route in router.routes:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            return route.name
    raise AssertionError(f"aucune route pour {path}")


def test_mandatory_basket_is_not_swallowed_by_variant_id() -> None:
    assert _first_match("/admin/fee-variants/mandatory-basket") == "mandatory_basket"


def test_numeric_variant_still_reaches_detail() -> None:
    assert _first_match("/admin/fee-variants/7") == "get_fee_variant"
