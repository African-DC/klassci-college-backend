"""Une somme versée ne peut pas valoir trois montants selon l'écran.

Ces tests relisent le code source plutôt que d'exécuter des requêtes. C'est
grossier, assumé, et c'est le seul verrou qui tienne contre la façon dont ce
bug est né : un copier-coller d'un calcul qui sommait `EnrollmentFee.payments`,
répliqué d'écran en écran bien après que la migration 0028 eut vidé cette
relation. Chaque copie était juste le jour où elle a été écrite, fausse le
lendemain, et aucun test fonctionnel ne la voyait puisqu'un frais sans
versement et un frais dont les versements sont invisibles se ressemblent.
"""

import ast
from pathlib import Path

from app.services import fees_paid

_APP = Path(__file__).resolve().parent.parent / "app"

#: Le seul endroit où la relation dépréciée a le droit d'apparaître : sa
#: déclaration ORM. La déclarer ne coûte rien, c'est la **lire** qui ment.
_DECLARATION_AUTORISEE = ("models",)


def _fichiers_de_code() -> list[Path]:
    """Tous les modules applicatifs hors déclarations de modèles."""
    return [
        chemin
        for chemin in sorted(_APP.rglob("*.py"))
        if chemin.relative_to(_APP).parts[0] not in _DECLARATION_AUTORISEE
    ]


def _acces_attribut(chemin: Path, nom: str) -> list[tuple[int, str]]:
    """Chaque lecture de l'attribut `nom` dans ce fichier, avec sa ligne.

    On passe par l'AST et non par une recherche de texte : un nom cité dans
    une docstring ou un commentaire n'est pas une lecture, et ces fichiers en
    contiennent beaucoup — ils expliquent précisément pourquoi il ne faut
    plus lire cette relation.
    """
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    return [
        (noeud.lineno, ast.unparse(noeud))
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Attribute) and noeud.attr == nom
    ]


def test_le_calcul_vit_a_un_seul_endroit() -> None:
    """Trois services calculaient « déjà payé » de trois façons. Le portail
    parent et le portail élève sommaient une relation dépréciée depuis la
    migration 0028 et sous-estimaient donc ce que la famille avait versé —
    50 000 FCFA invisibles sur un cas réel du tenant de démonstration."""
    assert hasattr(fees_paid, "paid_by_enrollment_fee")
    assert hasattr(fees_paid, "paid_by_enrollment")
    assert hasattr(fees_paid, "payments_by_enrollment_fee")
    assert hasattr(fees_paid, "fee_ids_with_allocations")


def test_plus_personne_ne_lit_la_relation_depreciee() -> None:
    """`EnrollmentFee.payments` s'appuie sur `Payment.enrollment_fee_id`, vide
    sur tout versement passé par les allocations.

    Le verrou porte sur la lecture, où qu'elle soit : sommer cette relation
    donnait un montant faux, la parcourir donnait une liste vide sous un
    frais pourtant soldé, et la précharger coûtait une requête pour rien.
    Aucun de ces trois usages n'a de raison de revenir.
    """
    fautifs = [
        f"{chemin.relative_to(_APP)}:{ligne} — {source}"
        for chemin in _fichiers_de_code()
        for ligne, source in _acces_attribut(chemin, "payments")
    ]
    assert not fautifs, (
        "La relation dépréciée `EnrollmentFee.payments` est relue. "
        "Passer par `app.services.fees_paid` :\n  " + "\n  ".join(fautifs)
    )


def test_plus_personne_ne_requete_la_colonne_depreciee() -> None:
    """Même verrou sur la colonne elle-même.

    `Payment.enrollment_fee_id` n'est plus renseignée depuis que le versement
    se fait sur l'inscription : filtrer ou sommer dessus ne remonte plus rien.
    Le lien vivant est `PaymentAllocation.enrollment_fee_id`.
    """
    fautifs = [
        f"{chemin.relative_to(_APP)}:{ligne} — {source}"
        for chemin in _fichiers_de_code()
        for ligne, source in _acces_attribut(chemin, "enrollment_fee_id")
        if source.startswith("Payment.")
    ]
    assert not fautifs, (
        "La colonne dépréciée `Payment.enrollment_fee_id` est requêtée. "
        "Le lien vivant est `PaymentAllocation.enrollment_fee_id` :\n  " + "\n  ".join(fautifs)
    )


def test_les_ecrans_qui_affichent_un_montant_passent_par_le_calcul_canonique() -> None:
    """Les modules qui montrent « payé » ou « reste à payer » à quelqu'un.

    Les portails parce que c'est la famille qui lit, l'administration parce
    qu'un caissier qui voit « 0 payé » sur une famille à jour la rappelle
    pour rien, et les inscriptions parce que le tri « ce frais porte-t-il de
    l'argent » décide d'une suppression.
    """
    for module in (
        "parent_portal_service",
        "student_portal_service",
        "admin_service",
        "enrollment_service",
    ):
        source = (_APP / "services" / f"{module}.py").read_text(encoding="utf-8")
        assert "fees_paid" in source, f"{module} doit passer par le calcul canonique"
