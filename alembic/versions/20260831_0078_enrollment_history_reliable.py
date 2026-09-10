"""L'ecole declare elle-meme si son historique d'inscriptions est exploitable.

La deduction « aucune inscription anterieure, donc nouvel eleve » ne vaut que
dans une base qui porte reellement les annees passees. Un etablissement qui
vient d'etre deploye n'a que l'annee en cours : le vide n'y distingue pas un
arrivant d'un ancien pas encore ressaisi, et la deduction facturerait le droit
d'entree a toute l'ecole.

`enrollment_history_is_reliable` fait de cette question un reglage, declare par
l'ecole et par personne d'autre. Il vaut `0` pour tout le monde, y compris les
etablissements deja en service : c'est le seul defaut qui ne facture rien par
surprise. Tant qu'il vaut `0`, le serveur laisse la case « nouvel eleve » a
cocher au guichet.

Ce defaut ne se leve pas tout seul a la premiere ligne d'historique
reconstituee. Une reprise d'annee est progressive, et un garde-fou qui bascule
au milieu ferait facturer differemment le matin et l'apres-midi.

Revision ID: 0078_enrollment_history
Revises: 0077_new_student_fees
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0078_enrollment_history"
down_revision: str | None = "0077_new_student_fees"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "school_settings",
        sa.Column(
            "enrollment_history_is_reliable",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    # Le downgrade tourne avec le code de la revision precedente, qui ne lit
    # pas ce reglage : la suggestion y retombe sur la seule lecture de
    # l'historique. Aucune inscription n'est touchee, aucun frais n'est
    # reecrit, aucun profil deja saisi n'est perdu.
    op.drop_column("school_settings", "enrollment_history_is_reliable")
