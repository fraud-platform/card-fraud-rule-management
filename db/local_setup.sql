-- ============================================================================
-- Local Development Database User Setup
-- ============================================================================
--
-- Creates BOTH application and analytics users with local dev passwords.
-- ONLY for local Docker - never use these passwords in Neon/production.
--
-- Usage:
--   This script is automatically mounted and run by docker-compose.local.yml
--   No manual execution needed for local development.
--
-- Credentials (LOCAL DEVELOPMENT ONLY):
--   User: fraud_gov_app_user       Password: localdevpass
--   User: fraud_gov_analytics_user Password: localdevpass
--
-- Connection strings for Doppler 'local' config:
--   DATABASE_URL_APP=postgresql://fraud_gov_app_user:localdevpass@localhost:5432/fraud_gov
--   DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:localdevpass@localhost:5432/fraud_gov
-- ============================================================================

DO $$
BEGIN
    -- Create application user if doesn't exist
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fraud_gov_app_user') THEN
        CREATE ROLE fraud_gov_app_user WITH LOGIN PASSWORD 'localdevpass';
        COMMENT ON ROLE fraud_gov_app_user IS
            'Local development application user - member of fraud_gov_app_role';
    END IF;

    -- Create analytics user if doesn't exist
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fraud_gov_analytics_user') THEN
        CREATE ROLE fraud_gov_analytics_user WITH LOGIN PASSWORD 'localdevpass';
        COMMENT ON ROLE fraud_gov_analytics_user IS
            'Local development analytics user - member of fraud_gov_analytics_role';
    END IF;
END
$$;

-- Grants will be applied by fraud_governance_schema.sql after it creates the roles
-- The schema DDL creates the roles (fraud_gov_app_role, fraud_gov_analytics_role)
-- and grants them to users

SELECT 'Local database users created!' AS status;
