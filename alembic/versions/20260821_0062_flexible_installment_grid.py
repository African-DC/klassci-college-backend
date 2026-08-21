"""Autorise les tranches en montant ferme a cote des tranches en pourcentage.

Jusqu'ici une grille ne savait dire qu'une chose : « telle part du total ». Or
la brochure de l'ecole pilote annonce un montant, pas une part : « Inscription
37 000 F, aucun eleve ne sera admis en classe sans l'avoir payee », puis un
tableau de tranches qui ne couvre que la scolarite. Traduite en pourcentages,
cette grille reclamait 43 750 F fin novembre la ou l'ecole attend 37 000 F a la
rentree puis 25 000 F fin novembre. Comme l'echeancier commande la retenue des
documents administratifs, une famille pouvait se voir refuser un certificat sur
la foi d'un calendrier que l'ecole n'a jamais annonce.

`kind` dit desormais laquelle des deux ecritures porte la ligne. `percentage`
devient donc nullable — une ligne en francs n'a pas de part — et `amount`
apparait a cote.

Rien ne bouge pour les grilles deja saisies : le defaut serveur `percentage`
les qualifie toutes, leur pourcentage reste en place, et le calcul retombe au
franc pres sur l'ancien resultat puisqu'aucun montant ferme ne se prelevera
avant elles.

Revision ID: 0062_flexible_installment_grid
Revises: 0061_school_life_reference_width
Create Date: 2026-08-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0062_flexible_installment_grid"
down_revision = "0061_school_life_reference_width"
branch_labels = None
depends_on = None

_KIND = sa.Enum("percentage", "fixed", name="fee_installment_kind")


def upgrade() -> None:
    op.add_column(
        "fee_installments",
        sa.Column("kind", _KIND, nullable=False, server_default="percentage"),
    )
    op.add_column(
        "fee_installments",
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
    )
    # Une tranche en francs n'a pas de pourcentage : la colonne doit pouvoir
    # rester vide. Les lignes existantes gardent la leur.
    op.alter_column(
        "fee_installments",
        "percentage",
        existing_type=sa.Numeric(5, 2),
        nullable=True,
    )


def downgrade() -> None:
    # Les tranches en montant ferme n'ont pas d'equivalent dans l'ancien
    # modele. Les convertir en pourcentage demanderait une assiette qui n'existe
    # qu'au niveau d'un eleve, donc un chiffre invente ; on les retire, et
    # l'ecole retrouve la grille en pourcentages qu'elle avait avant.
    op.execute(sa.text("DELETE FROM fee_installments WHERE kind = 'fixed'"))
    op.execute(sa.text("UPDATE fee_installments SET percentage = 0 WHERE percentage IS NULL"))
    op.alter_column(
        "fee_installments",
        "percentage",
        existing_type=sa.Numeric(5, 2),
        nullable=False,
    )
    op.drop_column("fee_installments", "amount")
    op.drop_column("fee_installments", "kind")
