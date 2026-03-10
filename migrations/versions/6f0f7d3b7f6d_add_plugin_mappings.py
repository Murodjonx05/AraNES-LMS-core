"""add plugin mappings

Revision ID: 6f0f7d3b7f6d
Revises: e8484413100f
Create Date: 2026-03-09 18:30:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6f0f7d3b7f6d"
down_revision: Union[str, Sequence[str], None] = "e8484413100f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plugin_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plugin_name", sa.String(length=128), nullable=False),
        sa.Column("service_name", sa.String(length=128), nullable=False),
        sa.Column("mount_prefix", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plugin_name"),
        sa.UniqueConstraint("service_name"),
        sa.UniqueConstraint("mount_prefix"),
    )


def downgrade() -> None:
    op.drop_table("plugin_mappings")
