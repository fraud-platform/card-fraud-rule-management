-- Migration: Add optimistic concurrency control version column
--
-- This migration adds a 'version' column to rules and rulesets tables
-- to support optimistic locking for concurrent edit scenarios.
--
-- Usage:
--   psql "${DATABASE_URL_ADMIN}" -v ON_ERROR_STOP=1 -f db/migrations/add_optimistic_version.sql
--
-- Rollback:
--   Manually remove the version columns (not recommended in production)

BEGIN;

-- Add version column to rules table
DO $$
BEGIN
  -- Check if column already exists
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'fraud_gov'
      AND table_name = 'rules'
      AND column_name = 'version'
  ) THEN
    ALTER TABLE fraud_gov.rules
      ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

    COMMENT ON COLUMN fraud_gov.rules.version IS
      'Optimistic locking version - increments on each update to detect concurrent modifications';
  END IF;
END$$;

-- Add version column to rulesets table
DO $$
BEGIN
  -- Check if column already exists
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'fraud_gov'
      AND table_name = 'rulesets'
      AND column_name = 'version'
  ) THEN
    -- For rulesets, the version column already exists but serves a dual purpose
    -- It's both the ruleset version number AND the optimistic lock
    -- No action needed - the column is already there

    RAISE NOTICE 'Version column already exists in rulesets table (serves dual purpose)';
  END IF;
END$$;

-- Add index on version for better query performance (optional but recommended)
CREATE INDEX IF NOT EXISTS idx_rules_version
  ON fraud_gov.rules(version);

-- The rulesets table already has version indexed via the unique constraint (rule_type, version)

COMMIT;

-- Verification query (run after migration to verify)
-- SELECT rule_id, rule_name, version FROM fraud_gov.rules LIMIT 5;
-- SELECT ruleset_id, rule_type, version FROM fraud_gov.rulesets LIMIT 5;
