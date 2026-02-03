-- Migration: Add idempotency_key to approvals table
-- Purpose: Support idempotent submit operations to prevent duplicate processing
-- Date: 2025-01-13
--
-- Run this migration after updating the application code
-- psql "${DATABASE_URL_ADMIN}" -v ON_ERROR_STOP=1 -f db/migrations/add_idempotency_key.sql

BEGIN;

-- Add idempotency_key column (nullable initially for backwards compatibility)
ALTER TABLE fraud_gov.approvals
ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

-- Add unique constraint on (entity_type, entity_id, idempotency_key)
-- This ensures that for a given entity, the same idempotency key can only be used once
ALTER TABLE fraud_gov.approvals
ADD CONSTRAINT approvals_idempotency_key_unique
UNIQUE (entity_type, entity_id, idempotency_key);

-- Add index for efficient idempotency lookups
CREATE INDEX IF NOT EXISTS idx_approvals_idempotency
ON fraud_gov.approvals(entity_type, entity_id, idempotency_key);

-- Add comment
COMMENT ON COLUMN fraud_gov.approvals.idempotency_key IS
'Optional client-provided key for idempotent submit operations. Unique per entity_type + entity_id.';

COMMIT;
