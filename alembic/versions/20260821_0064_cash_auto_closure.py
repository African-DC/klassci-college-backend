"""Clôture d'office des journées de caisse oubliées.

Ajoute `cash_sessions.regularized_at` : l'horodatage du comptage saisi APRÈS
une clôture d'office. Renseigné, il porte deux faits que le statut seul
perdrait — la journée a été clôturée d'office, et le caissier l'a régularisée
tel jour — puisque la régularisation la fait repasser en `closed`.

Le statut `auto_closed` n'exige AUCUN DDL : la 0043 a créé la colonne en
`VARCHAR(20)` et non en ENUM MySQL, et « auto_closed » y tient. Vérifié avant
d'écrire cette migration plutôt que déduit du type `ValueEnum` du modèle, qui
aurait laissé croire à un ENUM natif.

Rien à rétro-remplir : les journées ouvertes anciennes (dont celles créées par
la 0044) seront balayées par la tâche planifiée à sa première exécution, ce
qui produit au passage leur trace d'audit et la notification du caissier — ce
qu'un UPDATE de migration ne ferait pas.

Revision ID: 0064_cash_auto_closure
Revises: 0063_flexible_installment_grid
Create Date: 2026-08-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0064_cash_auto_closure"
down_revision = "0063_flexible_installment_grid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cash_sessions",
        sa.Column("regularized_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    # Les journées `auto_closed` restent telles quelles : les repasser en
    # `open` rouvrirait des caisses que la comptabilité a déjà arrêtées.
    op.drop_column("cash_sessions", "regularized_at")
