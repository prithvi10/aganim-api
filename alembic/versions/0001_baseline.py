"""baseline: capture existing schema

Revision ID: 0001
Revises:
Create Date: 2026-04-16

Baseline migration representing the production schema as of this commit.
On an existing database run ``alembic stamp head`` instead of ``alembic upgrade head``
so Alembic records this revision without re-executing the DDL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- plans ----
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("price_usd_monthly", sa.Numeric(10, 2), nullable=True),
        sa.Column("monthly_token_quota", sa.BigInteger(), nullable=True),
        sa.Column("max_request_rate", sa.Integer(), nullable=True),
        sa.Column("product_limit", sa.Integer(), nullable=True),
        sa.Column("max_locales", sa.Integer(), nullable=True),
        sa.Column("features_json", sa.Text(), nullable=True),
        sa.Column("billing_cycle_type", sa.String(), nullable=True),
        sa.Column("can_access_live_currency", sa.Boolean(), server_default="false"),
        sa.Column("can_stream_responses", sa.Boolean(), server_default="false"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="plans_name_key"),
    )
    op.create_index("ix_plans_id", "plans", ["id"])
    op.create_index("ix_plans_name", "plans", ["name"])

    # ---- users ----
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=True),
        sa.UniqueConstraint("username", name="users_username_key"),
        sa.UniqueConstraint("email", name="users_email_key"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    # ---- shops ----
    op.create_table(
        "shops",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("access_token", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("monthly_rewrites_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_rewrites_remaining", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("welcome_back_pending", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_plan_name", sa.String(), nullable=True),
        sa.Column("last_plan_name", sa.String(), nullable=True),
        sa.Column("last_uninstalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reset_anchor_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_reset_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fair_use_last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("monthly_cost_accumulated", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("onboarding_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_onboarding_finished", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("brand_context", postgresql.JSONB(), nullable=True),
        sa.Column("brand_context_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("brand_context_status", sa.String(), nullable=True),
        sa.Column("brand_context_last_error", sa.Text(), nullable=True),
        sa.Column("brand_context_job_id", sa.String(), nullable=True),
        sa.Column("strategic_intelligence", postgresql.JSONB(), nullable=True),
        sa.Column("strategic_intelligence_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_plan_name", sa.String(), nullable=True),
        sa.Column("pending_plan_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_plan_change_type", sa.String(), nullable=True),
        sa.Column("last_plan_change_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_shopify_subscription_status", sa.String(), nullable=True),
        sa.Column("price_guardrails", postgresql.JSONB(), nullable=True),
        sa.Column("logo_url", sa.String(), nullable=True),
        sa.Column("ui_language", sa.String(5), nullable=False, server_default="en"),
        sa.Column("default_target_locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column("free_trial_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifetime_missions_remaining", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("lifetime_image_credits_remaining", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("monthly_missions_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monthly_image_generations_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brand_soul_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.UniqueConstraint("domain", name="shops_domain_key"),
    )
    op.create_index("ix_shops_id", "shops", ["id"])
    op.create_index("ix_shops_domain", "shops", ["domain"])

    # ---- usage_records ----
    op.create_table(
        "usage_records",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("billing_cycle_start", sa.Date(), primary_key=True),
        sa.Column("token_count", sa.BigInteger(), server_default="0"),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ---- feature_usage ----
    op.create_table(
        "feature_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shop_domain", sa.String(), nullable=False),
        sa.Column("feature", sa.String(), nullable=False),
        sa.Column("billing_cycle_start", sa.Date(), nullable=False),
        sa.Column("usage_count", sa.Integer(), server_default="0"),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_feature_usage_id", "feature_usage", ["id"])
    op.create_index("ix_feature_usage_shop_domain", "feature_usage", ["shop_domain"])

    # ---- usage_event_log ----
    op.create_table(
        "usage_event_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shop_domain", sa.String(), nullable=False),
        sa.Column("plan_name", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("feature", sa.String(), nullable=False),
        sa.Column("product_count", sa.Integer(), server_default="0"),
        sa.Column("image_count", sa.Integer(), server_default="0"),
        sa.Column("prompt_tokens", sa.BigInteger(), server_default="0"),
        sa.Column("completion_tokens", sa.BigInteger(), server_default="0"),
        sa.Column("reasoning_tokens", sa.BigInteger(), server_default="0"),
        sa.Column("total_tokens", sa.BigInteger(), server_default="0"),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 6), server_default="0"),
        sa.Column("product_id", sa.String(), nullable=True),
        sa.Column("mission_id", sa.String(), nullable=True),
        sa.Column("agent_name", sa.String(), nullable=True),
        sa.Column("model_used", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_usage_event_log_id", "usage_event_log", ["id"])
    op.create_index("ix_usage_event_log_shop_domain", "usage_event_log", ["shop_domain"])
    op.create_index("ix_usage_event_log_event_type", "usage_event_log", ["event_type"])
    op.create_index("ix_usage_event_log_feature", "usage_event_log", ["feature"])
    op.create_index("ix_usage_event_log_created_at", "usage_event_log", ["created_at"])

    # ---- missions (agentic_core) ----
    op.create_table(
        "missions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("current_state", postgresql.JSONB(), nullable=True),
        sa.Column("logs", postgresql.JSONB(), nullable=True),
        sa.Column("tier", sa.String(), nullable=True),
        sa.Column("bulk_mission_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("missions_tenant_id_idx", "missions", ["tenant_id"])
    op.create_index("missions_resource_id_idx", "missions", ["resource_id"])
    op.create_index("missions_bulk_mission_id_idx", "missions", ["bulk_mission_id"])

    # ---- agent_corrections (agentic_core, uses pgvector) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_corrections (
            id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            agent_role VARCHAR NOT NULL,
            original_output TEXT NOT NULL,
            user_correction TEXT NOT NULL,
            embedding vector(1536),
            resource_id VARCHAR,
            context_metadata JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.create_index("agent_corrections_tenant_id_idx", "agent_corrections", ["tenant_id"])
    op.create_index("agent_corrections_resource_id_idx", "agent_corrections", ["resource_id"])

    # ---- context_chunks (agentic_core, uses pgvector) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS context_chunks (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            content TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            metadata JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.create_index("ix_context_chunks_id", "context_chunks", ["id"])
    op.create_index("context_chunks_tenant_id_idx", "context_chunks", ["tenant_id"])

    # ---- brand_entities ----
    op.create_table(
        "brand_entities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.Column("relation", sa.String(), nullable=False),
        sa.Column("object", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), server_default="1.0"),
        sa.Column("source_chunk_id", sa.Integer(), sa.ForeignKey("context_chunks.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_brand_entities_id", "brand_entities", ["id"])
    op.create_index("ix_brand_entities_tenant_id", "brand_entities", ["tenant_id"])

    # ---- outreach_log ----
    op.create_table(
        "outreach_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recipient_email", sa.String(), nullable=False),
        sa.Column("recipient_shop", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="sent"),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_outreach_log_id", "outreach_log", ["id"])

    # ---- concern_log ----
    op.create_table(
        "concern_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shop_domain", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="open"),
        sa.Column("admin_reply", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_concern_log_id", "concern_log", ["id"])
    op.create_index("concern_log_shop_idx", "concern_log", ["shop_domain"])

    # pgvector HNSW indexes — managed outside Alembic autogenerate.
    # The include_object filter in env.py excludes them from `alembic check`.
    op.execute(
        "CREATE INDEX IF NOT EXISTS context_chunks_embedding_idx "
        "ON context_chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS agent_corrections_embedding_idx "
        "ON agent_corrections USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("concern_log")
    op.drop_table("outreach_log")
    op.drop_table("brand_entities")
    op.drop_table("context_chunks")
    op.drop_table("agent_corrections")
    op.drop_table("missions")
    op.drop_table("usage_event_log")
    op.drop_table("feature_usage")
    op.drop_table("usage_records")
    op.drop_table("shops")
    op.drop_table("users")
    op.drop_table("plans")
    op.execute("DROP EXTENSION IF EXISTS vector")
