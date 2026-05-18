"""add beta enrollment signup fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("beta_enrollment", sa.Column("invite_token", sa.String(), nullable=True))
    op.add_column("beta_enrollment", sa.Column("store_name", sa.String(), nullable=True))
    op.add_column("beta_enrollment", sa.Column("contact_email", sa.String(), nullable=True))
    op.add_column("beta_enrollment", sa.Column("purpose", sa.Text(), nullable=True))
    op.add_column("beta_enrollment", sa.Column("product_category", sa.String(), nullable=True))
    op.add_column("beta_enrollment", sa.Column("target_markets", sa.String(), nullable=True))

    op.create_index("ix_beta_enrollment_invite_token", "beta_enrollment", ["invite_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_beta_enrollment_invite_token", table_name="beta_enrollment")
    op.drop_column("beta_enrollment", "target_markets")
    op.drop_column("beta_enrollment", "product_category")
    op.drop_column("beta_enrollment", "purpose")
    op.drop_column("beta_enrollment", "contact_email")
    op.drop_column("beta_enrollment", "store_name")
    op.drop_column("beta_enrollment", "invite_token")
