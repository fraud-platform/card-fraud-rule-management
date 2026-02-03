-- ============================================================================
-- Manual Step: Create Database Users
-- ============================================================================
--
-- DEPRECATED: This script is kept for reference only.
--
-- RECOMMENDED: Use the automated setup instead:
--
--   doppler run --config <env> -- uv run python scripts/setup_database.py create-users --password-env
--
-- The automated approach:
--   - Reads passwords from Doppler secrets (FRAUD_GOV_APP_PASSWORD, FRAUD_GOV_ANALYTICS_PASSWORD)
--   - Creates both users with parameterized queries (no hardcoded passwords)
--   - Grants appropriate roles
--
-- If you still need manual setup for some reason:
--
-- 1. Replace 'YOUR_SECURE_PASSWORD' with actual strong passwords
-- 2. Run this script with admin connection:
--    psql "${DATABASE_URL_ADMIN}" -f db/create_users.sql
--
-- 3. Update your Doppler config with connection strings:
--    DATABASE_URL_APP=postgresql://fraud_gov_app_user:PASSWORD@host/db
--    DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:PASSWORD@host/db
--
-- ============================================================================

BEGIN;

-- Application runtime user
-- Has full CRUD access on governance tables
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fraud_gov_app_user') THEN
    CREATE ROLE fraud_gov_app_user LOGIN PASSWORD 'YOUR_SECURE_PASSWORD';
    COMMENT ON ROLE fraud_gov_app_user IS
        'Application database user - member of fraud_gov_app_role';
  END IF;
END$$;

-- Analytics user
-- Has read-only access to approved/active artifacts
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fraud_gov_analytics_user') THEN
    CREATE ROLE fraud_gov_analytics_user LOGIN PASSWORD 'YOUR_SECURE_PASSWORD';
    COMMENT ON ROLE fraud_gov_analytics_user IS
        'Analytics database user - member of fraud_gov_analytics_role';
  END IF;
END$$;

COMMIT;

-- ============================================================================
-- Connection Strings (after manual user creation):
-- ============================================================================

-- DATABASE_URL_APP=postgresql://fraud_gov_app_user:YOUR_SECURE_PASSWORD@host/db
-- DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:YOUR_SECURE_PASSWORD@host/db
