"""Add total_trips and predominant_age columns to district_mobility.

These two columns were added to the DistrictMobility ORM model
(backend/db/models.py) by the MITMA ETL PR, but the matching database
migration was never created -- this closes that gap.

Revision ID: 0006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable=True on both: existing rows (and any district without
    # MITMA data loaded yet) must not break just because these columns
    # now exist.
    op.add_column("district_mobility", sa.Column("total_trips", sa.Integer(), nullable=True))
    op.add_column("district_mobility", sa.Column("predominant_age", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("district_mobility", "predominant_age")
    op.drop_column("district_mobility", "total_trips")