-- Migration: Add optimistic concurrency control (version column)
-- This adds a 'version' column to rules and rulesets tables for optimistic locking
--
-- Execute this with:
--   psql "${DATABASE_URL_ADMIN}" -v ON_ERROR_STOP=1 -f db/migrations/add_optimistic_locking.sql
--
-- The version column:
-- - Starts at 1 for all existing records
-- - Increments on every update
-- - Is checked in WHERE clause to detect concurrent modifications
-- - Raises ConflictError if version mismatch occurs

BEGIN;

-- Add version column to rules table
ALTER TABLE fraud_gov.rules
ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

-- Add version column to rulesets table
ALTER TABLE fraud_gov.rulesets
ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

-- Add comments for documentation
COMMENT ON COLUMN fraud_gov.rules.version IS
  'Optimistic locking version. Increments on each update to detect concurrent modifications.';

COMMENT ON COLUMN fraud_gov.rulesets.version IS
  'Optimistic locking version. Increments on each update to detect concurrent modifications.';

-- Create indexes on version for common query patterns
CREATE INDEX IF NOT EXISTS idx_rules_version ON fraud_gov.rules(rule_id, version);
CREATE INDEX IF NOT EXISTS idx_rulesets_version ON fraud_gov.rulesets(ruleset_id, version);

-- Update the trigger function to auto-increment version on updates
CREATE OR REPLACE FUNCTION fraud_gov.increment_version()
RETURNS TRIGGER AS $$
BEGIN
  -- Auto-increment version on update
  NEW.version := OLD.version + 1;
  -- Also update updated_at timestamp
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing triggers if they exist
DROP TRIGGER IF EXISTS trg_rules_updated_at ON fraud_gov.rules;
DROP TRIGGER IF EXISTS trg_rulesets_updated_at ON fraud_gov.rulesets;

-- Create new triggers that handle both version increment and updated_at
CREATE TRIGGER trg_rules_version_updated
BEFORE UPDATE ON fraud_gov.rules
FOR EACH ROW
EXECUTE FUNCTION fraud_gov.increment_version();

CREATE TRIGGER trg_rulesets_version_updated
BEFORE UPDATE ON fraud_gov.rulesets
FOR EACH ROW
EXECUTE FUNCTION fraud_gov.increment_version();

COMMIT;

-- Verification query (run separately to verify):
-- SELECT rule_id, rule_name, version FROM fraud_gov.rules LIMIT 5;
-- SELECT ruleset_id, name, version FROM fraud_gov.rulesets LIMIT 5;
