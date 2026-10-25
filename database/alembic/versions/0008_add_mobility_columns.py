"""
==============================================================================
PLANTILLA BASE DE MIGRACIONES (ALEMBIC / MAKO)
==============================================================================
Este archivo sirve como molde inmutable para la generación automática de
scripts de migración. Al ejecutar 'alembic revision', el motor de plantillas
Mako inyecta los metadatos (revision_id, timestamps y código autogenerado)
en las variables marcadas con Ellipsis.

No modificar la estructura de este archivo a menos que se requiera alterar
el comportamiento global de todas las migraciones futuras del proyecto.
"""
"""Add mobility columns

# ----------------------------------------------------------------------------
# METADATOS DE ENRUTAMIENTO (Árbol de migraciones)
# ----------------------------------------------------------------------------
Revision ID: bc017c2708a3
Revises: 0005
Create Date: 2026-10-08 17:15:05.002299

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc017c2708a3'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ----------------------------------------------------------------------------
# OPERACIONES DE CAMBIO DE ESQUEMA (Forward & Backward)
# ----------------------------------------------------------------------------
def upgrade() -> None:
    """Aplica los cambios en el esquema hacia adelante."""
    op.add_column('district_mobility', sa.Column('total_trips', sa.Integer(), nullable=True))
    op.add_column('district_mobility', sa.Column('predominant_age', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Revierte los cambios en el esquema hacia atrás (Rollback)."""
    op.drop_column('district_mobility', 'predominant_age')
    op.drop_column('district_mobility', 'total_trips')
