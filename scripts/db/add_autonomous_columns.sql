-- Migration: Add autonomous publishing columns to shops table
-- These columns support Pro-tier autonomous execution features.

-- Meta (Facebook/Instagram) Graph API credentials
ALTER TABLE shops ADD COLUMN IF NOT EXISTS meta_access_token VARCHAR NULL;
ALTER TABLE shops ADD COLUMN IF NOT EXISTS meta_page_id VARCHAR NULL;

-- Price guardrails for PriceScout autonomous updates
-- JSON format: {"min_price": 0, "max_price": 9999}
ALTER TABLE shops ADD COLUMN IF NOT EXISTS price_guardrails JSONB NULL;
