-- =============================================================================
-- Production Indexes for Fraud Governance API (LOCKED)
--
-- Purpose:
--   Optimize query performance for:
--   - governance UI
--   - maker/checker workflows
--   - ruleset publishing
--   - transaction-management enrichment
--
-- Execution:
--   psql "${DATABASE_URL_ADMIN}" -v ON_ERROR_STOP=1 -f db/production_indexes.sql
--
-- Notes:
-- - All indexes are idempotent (IF NOT EXISTS)
-- - B-tree indexes only (Postgres default)
-- - DESC ordering used for time-based queries
-- - Partial indexes used for high-selectivity states
-- =============================================================================

BEGIN;

-- =============================================================================
-- RULES
-- =============================================================================

-- Filter rules by lifecycle and type (dashboard, search)
CREATE INDEX IF NOT EXISTS idx_rules_status_rule_type
    ON fraud_gov.rules(status, rule_type);

-- Optimistic locking / concurrency checks
CREATE INDEX IF NOT EXISTS idx_rules_current_version
    ON fraud_gov.rules(current_version);

-- "My rules" views
CREATE INDEX IF NOT EXISTS idx_rules_created_by
    ON fraud_gov.rules(created_by);

-- Recently modified rules
CREATE INDEX IF NOT EXISTS idx_rules_updated_at_desc
    ON fraud_gov.rules(updated_at DESC);

-- =============================================================================
-- RULE_VERSIONS
-- =============================================================================

-- Fetch all versions of a rule
CREATE INDEX IF NOT EXISTS idx_rule_versions_rule_id
    ON fraud_gov.rule_versions(rule_id);

-- Filter versions by rule + status (UI, approvals)
CREATE INDEX IF NOT EXISTS idx_rule_versions_rule_id_status
    ON fraud_gov.rule_versions(rule_id, status);

-- Global status filtering (approval queues)
CREATE INDEX IF NOT EXISTS idx_rule_versions_status
    ON fraud_gov.rule_versions(status);

-- Approval queue ordering
CREATE INDEX IF NOT EXISTS idx_rule_versions_status_created_at_desc
    ON fraud_gov.rule_versions(status, created_at DESC);

-- Recently created versions
CREATE INDEX IF NOT EXISTS idx_rule_versions_created_at_desc
    ON fraud_gov.rule_versions(created_at DESC);

-- Scope index for governance/migration queries (jsonb_path_ops for smaller size)
CREATE INDEX IF NOT EXISTS idx_rule_versions_scope
    ON fraud_gov.rule_versions USING GIN(scope jsonb_path_ops);

-- Approved rule versions used during compilation
CREATE INDEX IF NOT EXISTS idx_rule_versions_approved_by_rule_priority
    ON fraud_gov.rule_versions(rule_id, priority DESC)
    WHERE status = 'APPROVED';

-- =============================================================================
-- RULESETS (IDENTITY ONLY)
-- =============================================================================

-- Lookup ruleset identity by scope
CREATE INDEX IF NOT EXISTS idx_rulesets_env_region_country_type
    ON fraud_gov.rulesets(environment, region, country, rule_type);

-- Governance dashboards
CREATE INDEX IF NOT EXISTS idx_rulesets_created_at_desc
    ON fraud_gov.rulesets(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rulesets_updated_at_desc
    ON fraud_gov.rulesets(updated_at DESC);

-- =============================================================================
-- RULESET_VERSIONS (EXECUTION SNAPSHOTS)
-- =============================================================================

-- Find all versions of a ruleset
CREATE INDEX IF NOT EXISTS idx_ruleset_versions_ruleset_id
    ON fraud_gov.ruleset_versions(ruleset_id);

-- Active ruleset lookup (runtime control-plane contract)
CREATE INDEX IF NOT EXISTS idx_ruleset_versions_active
    ON fraud_gov.ruleset_versions(ruleset_id, activated_at DESC)
    WHERE status = 'ACTIVE';

-- Governance / approval filtering
CREATE INDEX IF NOT EXISTS idx_ruleset_versions_status
    ON fraud_gov.ruleset_versions(status);

-- Approval queues
CREATE INDEX IF NOT EXISTS idx_ruleset_versions_status_created_at_desc
    ON fraud_gov.ruleset_versions(status, created_at DESC);

-- =============================================================================
-- RULESET_VERSION_RULES (SNAPSHOT MEMBERSHIP)
-- =============================================================================

-- Resolve rules for a ruleset version (TM / explain / audit)
CREATE INDEX IF NOT EXISTS idx_rsvr_ruleset_version_id
    ON fraud_gov.ruleset_version_rules(ruleset_version_id);

-- Reverse lookup: which rulesets include this rule version
CREATE INDEX IF NOT EXISTS idx_rsvr_rule_version_id
    ON fraud_gov.ruleset_version_rules(rule_version_id);

-- =============================================================================
-- RULESET_MANIFEST (PUBLISHED ARTIFACTS)
-- =============================================================================

-- Fetch published artifact for a given scope + version
CREATE INDEX IF NOT EXISTS idx_ruleset_manifest_scope_version
    ON fraud_gov.ruleset_manifest(
        environment,
        region,
        country,
        rule_type,
        ruleset_version
    );

-- Recent publishes (ops / debugging)
CREATE INDEX IF NOT EXISTS idx_ruleset_manifest_created_at_desc
    ON fraud_gov.ruleset_manifest(created_at DESC);

-- =============================================================================
-- APPROVALS
-- =============================================================================

-- Pending approvals (checker inbox)
CREATE INDEX IF NOT EXISTS idx_approvals_status_entity_type
    ON fraud_gov.approvals(status, entity_type);

-- Maker activity
CREATE INDEX IF NOT EXISTS idx_approvals_maker
    ON fraud_gov.approvals(maker);

-- Entity-specific approval history
CREATE INDEX IF NOT EXISTS idx_approvals_entity_id
    ON fraud_gov.approvals(entity_id);

-- Recently created approvals
CREATE INDEX IF NOT EXISTS idx_approvals_created_at_desc
    ON fraud_gov.approvals(created_at DESC);

-- =============================================================================
-- AUDIT_LOG
-- =============================================================================

-- Entity audit trail (primary access pattern)
CREATE INDEX IF NOT EXISTS idx_audit_log_entity_time_desc
    ON fraud_gov.audit_log(entity_type, entity_id, performed_at DESC);

-- User activity tracking
CREATE INDEX IF NOT EXISTS idx_audit_log_performed_by
    ON fraud_gov.audit_log(performed_by);

-- Time-based audit queries
CREATE INDEX IF NOT EXISTS idx_audit_log_performed_at_desc
    ON fraud_gov.audit_log(performed_at DESC);

-- =============================================================================
-- RULE_FIELDS
-- =============================================================================

-- Field ID lookup (O(1) for engine compatibility)
CREATE INDEX IF NOT EXISTS idx_rule_fields_field_id
    ON fraud_gov.rule_fields(field_id);

-- "My fields" views
CREATE INDEX IF NOT EXISTS idx_rule_fields_created_by
    ON fraud_gov.rule_fields(created_by);

-- Recently modified fields
CREATE INDEX IF NOT EXISTS idx_rule_fields_updated_at_desc
    ON fraud_gov.rule_fields(updated_at DESC);

-- Field data type filtering
CREATE INDEX IF NOT EXISTS idx_rule_fields_data_type
    ON fraud_gov.rule_fields(data_type);

-- =============================================================================
-- RULE_FIELD_VERSIONS
-- =============================================================================

-- Fetch all versions of a field
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_field_key
    ON fraud_gov.rule_field_versions(field_key);

-- Filter versions by field + status (UI, approvals)
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_field_key_status
    ON fraud_gov.rule_field_versions(field_key, status);

-- Global status filtering (approval queues)
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_status
    ON fraud_gov.rule_field_versions(status);

-- Approval queue ordering
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_status_created_at_desc
    ON fraud_gov.rule_field_versions(status, created_at DESC);

-- Recently created versions
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_created_at_desc
    ON fraud_gov.rule_field_versions(created_at DESC);

-- =============================================================================
-- FIELD_REGISTRY_MANIFEST
-- =============================================================================

-- Latest registry version lookup
CREATE INDEX IF NOT EXISTS idx_field_registry_manifest_version
    ON fraud_gov.field_registry_manifest(registry_version DESC);

-- Recent publishes (ops / debugging)
CREATE INDEX IF NOT EXISTS idx_field_registry_manifest_created_at_desc
    ON fraud_gov.field_registry_manifest(created_at DESC);

COMMIT;

-- =============================================================================
-- ADDITIONAL STATUS-SPECIFIC PARTIAL INDEXES
-- =============================================================================

-- Rule approval queue
CREATE INDEX IF NOT EXISTS idx_rule_versions_pending_approval
ON fraud_gov.rule_versions(created_at DESC)
WHERE status = 'PENDING_APPROVAL';

-- Ruleset publish approval queue
CREATE INDEX IF NOT EXISTS idx_ruleset_versions_pending_approval
ON fraud_gov.ruleset_versions(created_at DESC)
WHERE status = 'PENDING_APPROVAL';

-- Field version approval queue
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_pending_approval
ON fraud_gov.rule_field_versions(created_at DESC)
WHERE status = 'PENDING_APPROVAL';

-- Approval checker inbox
CREATE INDEX IF NOT EXISTS idx_approvals_pending
ON fraud_gov.approvals(created_at DESC)
WHERE status = 'PENDING';