"""add beta_enrollment table and is_beta_tester column

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shops",
        sa.Column("is_beta_tester", sa.Boolean(), nullable=False, server_default="0"),
    )

    op.create_table(
        "beta_enrollment",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shop_domain", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="invited"),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback_score", sa.Numeric(3, 1), nullable=True),
        sa.Column("willingness_to_pay", sa.String(), nullable=True),
        sa.Column("testimonial_text", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("target_market", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("ix_beta_enrollment_id", "beta_enrollment", ["id"])
    op.create_index("ix_beta_enrollment_shop_domain", "beta_enrollment", ["shop_domain"])
    op.create_unique_constraint(
        "beta_enrollment_shop_domain_key", "beta_enrollment", ["shop_domain"]
    )


def downgrade() -> None:
    op.drop_table("beta_enrollment")
    op.drop_column("shops", "is_beta_tester")
