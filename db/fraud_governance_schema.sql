-- Fraud Governance (FastAPI) — Neon Postgres bootstrap DDL
--
-- FINAL LOCKED DDL — Fraud Governance (v1)
--
-- Run this script with an ADMIN/OWNER connection (bootstrap only).
-- You said you will set passwords manually; placeholders are included.
--
-- Recommended execution:
--   psql "${DATABASE_URL_ADMIN}" -v ON_ERROR_STOP=1 -f db/fraud_governance_schema.sql
--
-- Notes:
-- - This creates a dedicated schema `fraud_gov`.
-- - It creates roles/users for: app runtime and read-only analytics.
-- - It enables Row-Level Security (RLS) and applies simple policies.
-- - Maker/checker separation is enforced at the API layer (not in SQL).
--
-- UUID policy:
-- - Do NOT add `DEFAULT gen_random_uuid()` (or other DB-side UUID defaults) to ID columns.
-- - The application is responsible for generating UUIDv7 identifiers.
-- - Reason: UUIDv7 is time-ordered, which improves index locality and reduces B-tree page churn
--   compared to purely-random UUIDs; keeping generation in-app also ensures consistent IDs across
--   environments (SQLite tests vs Postgres).
--
-- All timestamps stored in UTC (TIMESTAMPTZ).

BEGIN;

-- 1) Schema
CREATE SCHEMA IF NOT EXISTS fraud_gov;

COMMENT ON SCHEMA fraud_gov IS
  'Fraud Rule Governance API - Control plane for fraud detection rules';

-- 2) Types (enums)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                 WHERE t.typname='rule_type' AND n.nspname='fraud_gov') THEN
    CREATE TYPE fraud_gov.rule_type AS ENUM ('ALLOWLIST','BLOCKLIST','AUTH','MONITORING');
    COMMENT ON TYPE fraud_gov.rule_type IS
        'Rule evaluation type: ALLOWLIST/BLOCKLIST=FIRST_MATCH, AUTH=FIRST_MATCH, MONITORING=ALL_MATCHING';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                 WHERE t.typname='entity_status' AND n.nspname='fraud_gov') THEN
    -- RuleVersion and RuleSet lifecycle. ACTIVE exists for RuleSetVersions.
    CREATE TYPE fraud_gov.entity_status AS ENUM (
      'DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','SUPERSEDED','ACTIVE'
    );
    COMMENT ON TYPE fraud_gov.entity_status IS
        'Governance lifecycle: DRAFT → PENDING_APPROVAL → APPROVED/REJECTED. SUPERSEDED for old versions. ACTIVE for deployed ruleset versions.';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                 WHERE t.typname='approval_status' AND n.nspname='fraud_gov') THEN
    CREATE TYPE fraud_gov.approval_status AS ENUM ('PENDING','APPROVED','REJECTED');
    COMMENT ON TYPE fraud_gov.approval_status IS
        'Approval workflow state transitions: PENDING → APPROVED or REJECTED';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                 WHERE t.typname='approval_entity_type' AND n.nspname='fraud_gov') THEN
    CREATE TYPE fraud_gov.approval_entity_type AS ENUM ('RULE_VERSION','RULESET_VERSION','FIELD_VERSION');
    COMMENT ON TYPE fraud_gov.approval_entity_type IS
        'Entities subject to maker-checker workflow';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                 WHERE t.typname='audit_entity_type' AND n.nspname='fraud_gov') THEN
    CREATE TYPE fraud_gov.audit_entity_type AS ENUM (
      'RULE_FIELD','RULE_FIELD_METADATA','RULE','RULE_VERSION','RULESET','RULESET_VERSION','APPROVAL','FIELD_VERSION','FIELD_REGISTRY_MANIFEST'
    );
    COMMENT ON TYPE fraud_gov.audit_entity_type IS
        'Entities with append-only audit trail';
  END IF;
END$$;

-- 3) Roles + users
-- NOTE: Database users must be created MANUALLY first.
-- Run db/create_users.sql BEFORE this script.
-- Neon may already have some users; these blocks are idempotent.

-- Group roles (no login) - these are safe to auto-create
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fraud_gov_app_role') THEN
    CREATE ROLE fraud_gov_app_role NOLOGIN;
    COMMENT ON ROLE fraud_gov_app_role IS
        'Application runtime role - full CRUD on governance tables';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fraud_gov_analytics_role') THEN
    CREATE ROLE fraud_gov_analytics_role NOLOGIN;
    COMMENT ON ROLE fraud_gov_analytics_role IS
        'Analytics role - read-only access to approved/active artifacts';
  END IF;
END$$;

-- Users with passwords are created MANUALLY in db/create_users.sql
-- This ensures passwords are never hardcoded in automated scripts.

DO $$
BEGIN
  -- Verify users exist before granting roles
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fraud_gov_app_user') THEN
    RAISE EXCEPTION 'fraud_gov_app_user does not exist. Run db/create_users.sql first.';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fraud_gov_analytics_user') THEN
    RAISE EXCEPTION 'fraud_gov_analytics_user does not exist. Run db/create_users.sql first.';
  END IF;
END$$;

GRANT fraud_gov_app_role TO fraud_gov_app_user;
GRANT fraud_gov_analytics_role TO fraud_gov_analytics_user;

-- 4) Tables

-- =============================================================================
-- 4.1 Rule Authoring Layer
-- =============================================================================

-- 4.1.1 rule_fields (identity table - versioned)
CREATE TABLE IF NOT EXISTS fraud_gov.rule_fields (
  field_key           TEXT PRIMARY KEY,
  field_id            INTEGER NOT NULL UNIQUE,
  display_name        TEXT NOT NULL,
  description         TEXT,
  data_type           TEXT NOT NULL,
  allowed_operators   TEXT[] NOT NULL,
  multi_value_allowed BOOLEAN NOT NULL DEFAULT FALSE,
  is_sensitive        BOOLEAN NOT NULL DEFAULT FALSE,
  current_version     INTEGER NOT NULL DEFAULT 1,
  version             INTEGER NOT NULL DEFAULT 1,
  created_by          TEXT NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_rule_fields_data_type
    CHECK (data_type IN ('STRING','NUMBER','BOOLEAN','DATE','ENUM'))
);

COMMENT ON TABLE fraud_gov.rule_fields IS
  'Field definitions for rule conditions (identity table). field_id maps to engine FieldRegistry for O(1) lookup. Versioning tracked in rule_field_versions.';

COMMENT ON COLUMN fraud_gov.rule_fields.field_id IS
  'Integer ID matching engine FieldRegistry. Stable once assigned.';

COMMENT ON COLUMN fraud_gov.rule_fields.current_version IS
  'Points to latest version in rule_field_versions.';

COMMENT ON COLUMN fraud_gov.rule_fields.version IS
  'Optimistic locking version - increments on each update.';

-- 4.1.2 rule_field_metadata (with description)
CREATE TABLE IF NOT EXISTS fraud_gov.rule_field_metadata (
  field_key   TEXT NOT NULL REFERENCES fraud_gov.rule_fields(field_key) ON DELETE CASCADE,
  meta_key    TEXT NOT NULL,
  meta_value  JSONB NOT NULL,
  description TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (field_key, meta_key),
  CONSTRAINT chk_rule_field_metadata_meta_key CHECK (length(meta_key) > 0)
);

COMMENT ON TABLE fraud_gov.rule_field_metadata IS
  'Extensible metadata for rule fields (e.g., enum_values, min/max, regex). Stores additional configuration as key-value pairs in JSONB format.';

-- 4.1.3 rule_field_versions (immutable versions)
CREATE TABLE IF NOT EXISTS fraud_gov.rule_field_versions (
  rule_field_version_id UUID PRIMARY KEY,
  field_key            TEXT NOT NULL REFERENCES fraud_gov.rule_fields(field_key) ON DELETE CASCADE,
  version              INTEGER NOT NULL,
  field_id             INTEGER NOT NULL,
  display_name         TEXT NOT NULL,
  description          TEXT,
  data_type            TEXT NOT NULL,
  allowed_operators    TEXT[] NOT NULL,
  multi_value_allowed  BOOLEAN NOT NULL DEFAULT FALSE,
  is_sensitive         BOOLEAN NOT NULL DEFAULT FALSE,
  status               fraud_gov.entity_status NOT NULL,
  created_by           TEXT NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_by          TEXT,
  approved_at          TIMESTAMPTZ,
  UNIQUE (field_key, version),
  CONSTRAINT chk_rule_field_versions_status
    CHECK (status IN ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','SUPERSEDED')),
  CONSTRAINT chk_rule_field_versions_approved_fields
    CHECK (
      (status = 'APPROVED' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
      OR status <> 'APPROVED'
    )
);

COMMENT ON TABLE fraud_gov.rule_field_versions IS
  'Immutable versions of field definitions. Governance layer for approvals and audit. Runtime consumes from S3.';

-- 4.1.4 rules (logical identity)
-- current_version is metadata only - execution NEVER depends on this column
CREATE TABLE IF NOT EXISTS fraud_gov.rules (
  rule_id         UUID PRIMARY KEY,
  rule_name       TEXT NOT NULL,
  description     TEXT,
  rule_type       fraud_gov.rule_type NOT NULL,
  status          fraud_gov.entity_status NOT NULL,
  current_version INTEGER NOT NULL,
  version         INTEGER NOT NULL DEFAULT 1,
  created_by      TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_rules_status
    CHECK (status IN ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','SUPERSEDED'))
);

COMMENT ON TABLE fraud_gov.rules IS
  'Logical identity of a fraud rule. Tracks the current version and overall status. The actual rule logic is stored in rule_versions (immutable versions).';

COMMENT ON COLUMN fraud_gov.rules.current_version IS
  'Metadata only - indicates the latest version number. Execution NEVER depends on this column.';

COMMENT ON COLUMN fraud_gov.rules.version IS
  'Optimistic locking version - increments on each update for concurrent modification detection.';

-- 4.1.5 rule_versions (immutable, scoped)
CREATE TABLE IF NOT EXISTS fraud_gov.rule_versions (
  rule_version_id UUID PRIMARY KEY,
  rule_id         UUID NOT NULL REFERENCES fraud_gov.rules(rule_id) ON DELETE CASCADE,
  version         INTEGER NOT NULL,
  condition_tree  JSONB NOT NULL,
  description     TEXT,
  scope           JSONB NOT NULL DEFAULT '{}',
  priority        INTEGER NOT NULL,
  action          TEXT NOT NULL DEFAULT 'REVIEW',
  status          fraud_gov.entity_status NOT NULL,
  created_by      TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_by     TEXT,
  approved_at     TIMESTAMPTZ,
  UNIQUE (rule_id, version),
  CONSTRAINT chk_rule_versions_status
    CHECK (status IN ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','SUPERSEDED')),
  CONSTRAINT chk_rule_versions_approved_fields
    CHECK (
      (status = 'APPROVED' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
      OR status <> 'APPROVED'
    ),
  CONSTRAINT chk_rule_versions_priority_range
    CHECK (priority BETWEEN 1 AND 1000),
  CONSTRAINT chk_rule_versions_action
    CHECK (action IN ('APPROVE','DECLINE','REVIEW'))
);

COMMENT ON TABLE fraud_gov.rule_versions IS
  'Immutable version of a rule with condition tree and scope. Each version goes through maker-checker workflow independently. Scope lives here, not in rulesets.';

COMMENT ON COLUMN fraud_gov.rule_versions.scope IS
  'Scope dimensions for this rule version (e.g., {"network": ["VISA"], "mcc": ["7995"]}). Empty object {} means applies to all transactions in the country.';

COMMENT ON COLUMN fraud_gov.rule_versions.action IS
  'Action when rule matches: APPROVE, DECLINE, or REVIEW. Must match runtime Decision.java values. MONITORING rules should be REVIEW only.';

-- =============================================================================
-- 4.2 Ruleset Identity vs Snapshot (CRITICAL FIX)
-- =============================================================================

-- 4.2.1 rulesets (identity only — no versioning)
-- This table defines WHAT the ruleset is, not which snapshot.
CREATE TABLE IF NOT EXISTS fraud_gov.rulesets (
  ruleset_id UUID PRIMARY KEY,
  environment TEXT NOT NULL,
  region      TEXT NOT NULL,
  country     TEXT NOT NULL,
  rule_type   fraud_gov.rule_type NOT NULL,
  name        TEXT,
  description TEXT,
  created_by  TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (environment, region, country, rule_type)
);

COMMENT ON TABLE fraud_gov.rulesets IS
  'Ruleset identity only - immutable metadata. No version here, no compiled AST here. This table defines WHAT the ruleset is, not which snapshot.';

COMMENT ON COLUMN fraud_gov.rulesets.environment IS
  'Environment name (local, dev, test, prod).';

COMMENT ON COLUMN fraud_gov.rulesets.region IS
  'Infrastructure boundary (APAC, EMEA, INDIA, AMERICAS).';

COMMENT ON COLUMN fraud_gov.rulesets.country IS
  'Logical and data-residency boundary (IN, SG, HK, UK, etc.). Rules are always country-scoped.';

-- 4.2.2 ruleset_versions (immutable snapshots)
-- This is what runtime & TM reference - immutable execution contract
-- Runtime consumes compiled artifacts from S3, not DB
CREATE TABLE IF NOT EXISTS fraud_gov.ruleset_versions (
  ruleset_version_id UUID PRIMARY KEY,
  ruleset_id UUID NOT NULL REFERENCES fraud_gov.rulesets(ruleset_id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  description TEXT,
  status fraud_gov.entity_status NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_by TEXT,
  approved_at TIMESTAMPTZ,
  activated_at TIMESTAMPTZ,
  UNIQUE (ruleset_id, version),
  CONSTRAINT chk_ruleset_versions_status
    CHECK (status IN ('DRAFT','PENDING_APPROVAL','APPROVED','ACTIVE','SUPERSEDED')),
  CONSTRAINT chk_ruleset_versions_approved_fields
    CHECK (
      (status IN ('APPROVED','ACTIVE') AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
      OR status NOT IN ('APPROVED','ACTIVE')
    ),
  CONSTRAINT chk_ruleset_versions_activated
    CHECK (
      (status = 'ACTIVE' AND activated_at IS NOT NULL)
      OR status <> 'ACTIVE'
    )
);

COMMENT ON TABLE fraud_gov.ruleset_versions IS
  'Immutable snapshot of a ruleset. This is what runtime & transaction-management reference. No rule drift possible, no partial updates. Runtime consumes compiled artifacts from S3, not from this table.';

-- 4.2.3 ruleset_version_rules (snapshot-bound membership)
CREATE TABLE IF NOT EXISTS fraud_gov.ruleset_version_rules (
  ruleset_version_id UUID NOT NULL
    REFERENCES fraud_gov.ruleset_versions(ruleset_version_id)
    ON DELETE CASCADE,
  rule_version_id UUID NOT NULL
    REFERENCES fraud_gov.rule_versions(rule_version_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ruleset_version_id, rule_version_id)
);

COMMENT ON TABLE fraud_gov.ruleset_version_rules IS
  'Join table linking ruleset versions to specific rule versions. Membership is snapshot-bound - no rule drift possible.';

-- =============================================================================
-- 4.3 Publishing / Artifact Traceability
-- =============================================================================

-- 4.3.1 ruleset_manifest (published artifact traceability)
CREATE TABLE IF NOT EXISTS fraud_gov.ruleset_manifest (
  ruleset_manifest_id UUID PRIMARY KEY,
  environment TEXT NOT NULL,
  region TEXT NOT NULL,
  country TEXT NOT NULL,
  rule_type fraud_gov.rule_type NOT NULL,
  ruleset_version INTEGER NOT NULL,
  ruleset_version_id UUID NOT NULL,
  description TEXT,
  field_registry_version INTEGER,
  artifact_uri TEXT NOT NULL,
  checksum TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by TEXT NOT NULL,
  UNIQUE (environment, region, country, rule_type, ruleset_version),
  CONSTRAINT chk_ruleset_manifest_ruleset_version
    CHECK (ruleset_version >= 1),
  CONSTRAINT chk_ruleset_manifest_checksum_len
    CHECK (length(checksum) = 71),
  CONSTRAINT fk_manifest_ruleset_version
    FOREIGN KEY (ruleset_version_id)
    REFERENCES fraud_gov.ruleset_versions(ruleset_version_id)
);

COMMENT ON COLUMN fraud_gov.ruleset_manifest.field_registry_version IS
  'Links ruleset to specific field registry version. Enables reproducibility for debugging.';

COMMENT ON TABLE fraud_gov.ruleset_manifest IS
  'Published ruleset artifact manifest. Tracks ruleset artifacts published to S3-compatible storage. Matches exactly the runtime S3 layout.';

COMMENT ON COLUMN fraud_gov.ruleset_manifest.checksum IS
  'SHA-256 checksum in format: sha256:<lowercase-hex> (64 hex chars after prefix, total 71 chars).';

-- 4.3.2 field_registry_manifest (published field registry artifacts)
CREATE TABLE IF NOT EXISTS fraud_gov.field_registry_manifest (
  manifest_id         UUID PRIMARY KEY,
  registry_version    INTEGER NOT NULL UNIQUE,
  artifact_uri        TEXT NOT NULL,
  checksum            TEXT NOT NULL,
  field_count         INTEGER NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by          TEXT NOT NULL,
  CONSTRAINT chk_field_registry_manifest_checksum_len
    CHECK (length(checksum) = 71)
);

COMMENT ON TABLE fraud_gov.field_registry_manifest IS
  'Published field registry artifacts. Tracks versions published to S3 for runtime consumption.';

COMMENT ON COLUMN fraud_gov.field_registry_manifest.checksum IS
  'SHA-256 checksum in format: sha256:<lowercase-hex> (64 hex chars after prefix, total 71 chars).';

-- =============================================================================
-- 4.4 Approvals & Audit
-- =============================================================================

-- 4.4.1 approvals
CREATE TABLE IF NOT EXISTS fraud_gov.approvals (
  approval_id UUID PRIMARY KEY,
  entity_type fraud_gov.approval_entity_type NOT NULL,
  entity_id UUID NOT NULL,
  action TEXT NOT NULL,
  status fraud_gov.approval_status NOT NULL,
  maker TEXT NOT NULL,
  checker TEXT,
  remarks TEXT,
  idempotency_key TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ,
  CONSTRAINT chk_approvals_action CHECK (action IN ('SUBMIT','APPROVE','REJECT')),
  CONSTRAINT chk_approvals_maker_checker CHECK (checker IS NULL OR maker <> checker),
  CONSTRAINT chk_approvals_decided_at
    CHECK (
      (status IN ('APPROVED','REJECTED') AND decided_at IS NOT NULL)
      OR status = 'PENDING'
    )
);

COMMENT ON TABLE fraud_gov.approvals IS
  'Maker-checker workflow tracking for rule versions and ruleset versions. Enforces separation of duties: maker cannot be checker.';

-- 4.4.2 audit_log (append-only)
CREATE TABLE IF NOT EXISTS fraud_gov.audit_log (
  audit_id UUID PRIMARY KEY,
  entity_type fraud_gov.audit_entity_type NOT NULL,
  entity_id UUID NOT NULL,
  action TEXT NOT NULL,
  old_value JSONB,
  new_value JSONB,
  performed_by TEXT NOT NULL,
  performed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_audit_log_action CHECK (length(action) > 0)
);

COMMENT ON TABLE fraud_gov.audit_log IS
  'Append-only audit trail for all entity changes. Captures before/after state for compliance and debugging.';

-- =============================================================================
-- 5) Triggers
-- =============================================================================

-- updated_at trigger for rules and rulesets (identity table)
CREATE OR REPLACE FUNCTION fraud_gov.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_rules_updated_at ON fraud_gov.rules;
CREATE TRIGGER trg_rules_updated_at
BEFORE UPDATE ON fraud_gov.rules
FOR EACH ROW
EXECUTE FUNCTION fraud_gov.update_updated_at();

DROP TRIGGER IF EXISTS trg_rulesets_updated_at ON fraud_gov.rulesets;
CREATE TRIGGER trg_rulesets_updated_at
BEFORE UPDATE ON fraud_gov.rulesets
FOR EACH ROW
EXECUTE FUNCTION fraud_gov.update_updated_at();

-- Rule type consistency enforcement trigger
-- Prevents adding rules of wrong type to a ruleset (e.g., AUTH rule to MONITORING ruleset)
CREATE OR REPLACE FUNCTION fraud_gov.check_rule_type_match()
RETURNS TRIGGER AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM fraud_gov.rule_versions rv
    JOIN fraud_gov.rules r ON r.rule_id = rv.rule_id
    JOIN fraud_gov.ruleset_versions rsv ON rsv.ruleset_version_id = NEW.ruleset_version_id
    JOIN fraud_gov.rulesets rs ON rs.ruleset_id = rsv.ruleset_id
    WHERE rv.rule_version_id = NEW.rule_version_id
      AND r.rule_type = rs.rule_type
  ) THEN
    RAISE EXCEPTION 'Rule type mismatch: cannot add rule to ruleset of different type. Check rule.rule_type matches ruleset.rule_type.';
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ruleset_version_rules_type_check ON fraud_gov.ruleset_version_rules;
CREATE TRIGGER trg_ruleset_version_rules_type_check
BEFORE INSERT ON fraud_gov.ruleset_version_rules
FOR EACH ROW
EXECUTE FUNCTION fraud_gov.check_rule_type_match();

COMMENT ON FUNCTION fraud_gov.check_rule_type_match() IS
  'Enforces that rules can only be added to rulesets of the same rule_type. Prevents entire classes of silent production bugs.';

-- =============================================================================
-- 6) Indexes
-- =============================================================================

-- Rules indexes
CREATE INDEX IF NOT EXISTS idx_rules_status ON fraud_gov.rules(status, rule_type);
CREATE INDEX IF NOT EXISTS idx_rules_rule_type ON fraud_gov.rules(rule_type);
CREATE INDEX IF NOT EXISTS idx_rules_created_by ON fraud_gov.rules(created_by);
CREATE INDEX IF NOT EXISTS idx_rules_updated_at ON fraud_gov.rules(updated_at DESC);

-- Rule versions indexes
CREATE INDEX IF NOT EXISTS idx_rule_versions_rule ON fraud_gov.rule_versions(rule_id);
CREATE INDEX IF NOT EXISTS idx_rule_versions_status ON fraud_gov.rule_versions(status);
CREATE INDEX IF NOT EXISTS idx_rule_versions_rule_id_status ON fraud_gov.rule_versions(rule_id, status);
CREATE INDEX IF NOT EXISTS idx_rule_versions_created_at ON fraud_gov.rule_versions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rule_versions_status_created_at ON fraud_gov.rule_versions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rule_versions_scope ON fraud_gov.rule_versions USING GIN(scope jsonb_path_ops);

-- Partial indexes for approval queues (optimized for common query patterns)
CREATE INDEX IF NOT EXISTS idx_rule_versions_pending_approval
  ON fraud_gov.rule_versions(created_at DESC)
  WHERE status = 'PENDING_APPROVAL';

CREATE INDEX IF NOT EXISTS idx_ruleset_versions_pending_approval
  ON fraud_gov.ruleset_versions(created_at DESC)
  WHERE status = 'PENDING_APPROVAL';

-- Rulesets (identity) indexes
CREATE INDEX IF NOT EXISTS idx_rulesets_environment_region_country ON fraud_gov.rulesets(environment, region, country);
CREATE INDEX IF NOT EXISTS idx_rulesets_rule_type ON fraud_gov.rulesets(rule_type);
CREATE INDEX IF NOT EXISTS idx_rulesets_updated_at ON fraud_gov.rulesets(updated_at DESC);

-- Ruleset versions indexes
CREATE INDEX IF NOT EXISTS idx_ruleset_versions_ruleset_id ON fraud_gov.ruleset_versions(ruleset_id);
CREATE INDEX IF NOT EXISTS idx_ruleset_versions_status ON fraud_gov.ruleset_versions(status);
CREATE INDEX IF NOT EXISTS idx_ruleset_versions_ruleset_id_status ON fraud_gov.ruleset_versions(ruleset_id, status);

-- Ruleset version rules (membership) indexes
CREATE INDEX IF NOT EXISTS idx_ruleset_version_rules_ruleset_version_id ON fraud_gov.ruleset_version_rules(ruleset_version_id);
CREATE INDEX IF NOT EXISTS idx_ruleset_version_rules_rule_version_id ON fraud_gov.ruleset_version_rules(rule_version_id);

-- Ruleset manifest indexes
CREATE INDEX IF NOT EXISTS idx_ruleset_manifest_region_country ON fraud_gov.ruleset_manifest(region, country);
CREATE INDEX IF NOT EXISTS idx_ruleset_manifest_environment ON fraud_gov.ruleset_manifest(environment);

-- Approvals indexes
CREATE INDEX IF NOT EXISTS idx_approvals_status_entity_type ON fraud_gov.approvals(status, entity_type);
CREATE INDEX IF NOT EXISTS idx_approvals_maker ON fraud_gov.approvals(maker);
CREATE INDEX IF NOT EXISTS idx_approvals_entity_id ON fraud_gov.approvals(entity_id);
CREATE INDEX IF NOT EXISTS idx_approvals_maker_status ON fraud_gov.approvals(maker, status);
CREATE INDEX IF NOT EXISTS idx_approvals_created_at ON fraud_gov.approvals(created_at DESC);

-- Audit log indexes
CREATE INDEX IF NOT EXISTS idx_audit_entity_time ON fraud_gov.audit_log(entity_type, performed_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_performed_by ON fraud_gov.audit_log(performed_by);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON fraud_gov.audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_performed_at ON fraud_gov.audit_log(performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity_performed_at ON fraud_gov.audit_log(entity_type, entity_id, performed_at DESC);

-- Rule field indexes
CREATE INDEX IF NOT EXISTS idx_rule_fields_field_id ON fraud_gov.rule_fields(field_id);
CREATE INDEX IF NOT EXISTS idx_rule_fields_created_by ON fraud_gov.rule_fields(created_by);
CREATE INDEX IF NOT EXISTS idx_rule_fields_updated_at ON fraud_gov.rule_fields(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_rule_fields_data_type ON fraud_gov.rule_fields(data_type);
CREATE INDEX IF NOT EXISTS idx_rule_field_metadata_key ON fraud_gov.rule_field_metadata(meta_key);

-- Rule field versions indexes
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_field_key ON fraud_gov.rule_field_versions(field_key);
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_status ON fraud_gov.rule_field_versions(status);
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_field_key_status ON fraud_gov.rule_field_versions(field_key, status);
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_created_at ON fraud_gov.rule_field_versions(created_at DESC);

-- Partial index for field version approval queue
CREATE INDEX IF NOT EXISTS idx_rule_field_versions_pending_approval
  ON fraud_gov.rule_field_versions(created_at DESC)
  WHERE status = 'PENDING_APPROVAL';

-- Field registry manifest indexes
CREATE INDEX IF NOT EXISTS idx_field_registry_manifest_version ON fraud_gov.field_registry_manifest(registry_version);
CREATE INDEX IF NOT EXISTS idx_field_registry_manifest_created_at ON fraud_gov.field_registry_manifest(created_at DESC);

-- =============================================================================
-- 7) Privileges
-- =============================================================================

-- Schema usage
GRANT USAGE ON SCHEMA fraud_gov TO fraud_gov_app_role, fraud_gov_analytics_role;

-- App role: full CRUD on governance tables (control-plane); RLS still applies.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA fraud_gov TO fraud_gov_app_role;

-- Analytics role: read-only
GRANT SELECT ON ALL TABLES IN SCHEMA fraud_gov TO fraud_gov_analytics_role;

-- Ensure future tables get same grants
ALTER DEFAULT PRIVILEGES IN SCHEMA fraud_gov
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fraud_gov_app_role;

ALTER DEFAULT PRIVILEGES IN SCHEMA fraud_gov
  GRANT SELECT ON TABLES TO fraud_gov_analytics_role;

-- =============================================================================
-- 8) Row Level Security (RLS)
-- =============================================================================
--
-- Policy model:
-- - The app role can access all rows (we rely on API auth for maker/checker).
-- - The analytics role can only read APPROVED/ACTIVE artifacts.
--
-- If you later want per-user RLS, implement `SET LOCAL app.user = '...'` and policies accordingly.

-- Enable RLS
ALTER TABLE fraud_gov.rule_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.ruleset_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.rulesets ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.rule_fields ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.rule_field_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.rule_field_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.ruleset_version_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.ruleset_manifest ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_gov.field_registry_manifest ENABLE ROW LEVEL SECURITY;

-- App: allow all
DROP POLICY IF EXISTS rule_versions_app_all ON fraud_gov.rule_versions;
CREATE POLICY rule_versions_app_all ON fraud_gov.rule_versions
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS ruleset_versions_app_all ON fraud_gov.ruleset_versions;
CREATE POLICY ruleset_versions_app_all ON fraud_gov.ruleset_versions
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS rulesets_app_all ON fraud_gov.rulesets;
CREATE POLICY rulesets_app_all ON fraud_gov.rulesets
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS rules_app_all ON fraud_gov.rules;
CREATE POLICY rules_app_all ON fraud_gov.rules
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS approvals_app_all ON fraud_gov.approvals;
CREATE POLICY approvals_app_all ON fraud_gov.approvals
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS audit_log_app_all ON fraud_gov.audit_log;
CREATE POLICY audit_log_app_all ON fraud_gov.audit_log
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS rule_fields_app_all ON fraud_gov.rule_fields;
CREATE POLICY rule_fields_app_all ON fraud_gov.rule_fields
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS rule_field_metadata_app_all ON fraud_gov.rule_field_metadata;
CREATE POLICY rule_field_metadata_app_all ON fraud_gov.rule_field_metadata
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS ruleset_version_rules_app_all ON fraud_gov.ruleset_version_rules;
CREATE POLICY ruleset_version_rules_app_all ON fraud_gov.ruleset_version_rules
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS ruleset_manifest_app_all ON fraud_gov.ruleset_manifest;
CREATE POLICY ruleset_manifest_app_all ON fraud_gov.ruleset_manifest
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS rule_field_versions_app_all ON fraud_gov.rule_field_versions;
CREATE POLICY rule_field_versions_app_all ON fraud_gov.rule_field_versions
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS field_registry_manifest_app_all ON fraud_gov.field_registry_manifest;
CREATE POLICY field_registry_manifest_app_all ON fraud_gov.field_registry_manifest
  FOR ALL TO fraud_gov_app_role
  USING (true) WITH CHECK (true);

-- Analytics: read-only views of approved artifacts
DROP POLICY IF EXISTS rule_versions_analytics_read ON fraud_gov.rule_versions;
CREATE POLICY rule_versions_analytics_read ON fraud_gov.rule_versions
  FOR SELECT TO fraud_gov_analytics_role
  USING (status = 'APPROVED');

DROP POLICY IF EXISTS ruleset_versions_analytics_read ON fraud_gov.ruleset_versions;
CREATE POLICY ruleset_versions_analytics_read ON fraud_gov.ruleset_versions
  FOR SELECT TO fraud_gov_analytics_role
  USING (status IN ('APPROVED','ACTIVE'));

DROP POLICY IF EXISTS rulesets_analytics_read ON fraud_gov.rulesets;
CREATE POLICY rulesets_analytics_read ON fraud_gov.rulesets
  FOR SELECT TO fraud_gov_analytics_role
  USING (true);

DROP POLICY IF EXISTS rules_analytics_read ON fraud_gov.rules;
CREATE POLICY rules_analytics_read ON fraud_gov.rules
  FOR SELECT TO fraud_gov_analytics_role
  USING (status = 'APPROVED');

-- Audit log: allow analytics read (can be restricted later)
DROP POLICY IF EXISTS audit_log_analytics_read ON fraud_gov.audit_log;
CREATE POLICY audit_log_analytics_read ON fraud_gov.audit_log
  FOR SELECT TO fraud_gov_analytics_role
  USING (true);

-- approvals: allow analytics read pending/decided workflow for dashboards
DROP POLICY IF EXISTS approvals_analytics_read ON fraud_gov.approvals;
CREATE POLICY approvals_analytics_read ON fraud_gov.approvals
  FOR SELECT TO fraud_gov_analytics_role
  USING (true);

-- rule_fields + metadata are safe to read
DROP POLICY IF EXISTS rule_fields_analytics_read ON fraud_gov.rule_fields;
CREATE POLICY rule_fields_analytics_read ON fraud_gov.rule_fields
  FOR SELECT TO fraud_gov_analytics_role
  USING (true);

DROP POLICY IF EXISTS rule_field_metadata_analytics_read ON fraud_gov.rule_field_metadata;
CREATE POLICY rule_field_metadata_analytics_read ON fraud_gov.rule_field_metadata
  FOR SELECT TO fraud_gov_analytics_role
  USING (true);

-- rule_field_versions: analytics can read APPROVED versions only
DROP POLICY IF EXISTS rule_field_versions_analytics_read ON fraud_gov.rule_field_versions;
CREATE POLICY rule_field_versions_analytics_read ON fraud_gov.rule_field_versions
  FOR SELECT TO fraud_gov_analytics_role
  USING (status = 'APPROVED');

-- field_registry_manifest: analytics can read all published manifests
DROP POLICY IF EXISTS field_registry_manifest_analytics_read ON fraud_gov.field_registry_manifest;
CREATE POLICY field_registry_manifest_analytics_read ON fraud_gov.field_registry_manifest
  FOR SELECT TO fraud_gov_analytics_role
  USING (true);

-- ruleset_version_rules: analytics can see membership of approved/active ruleset versions only
DROP POLICY IF EXISTS ruleset_version_rules_analytics_read ON fraud_gov.ruleset_version_rules;
CREATE POLICY ruleset_version_rules_analytics_read ON fraud_gov.ruleset_version_rules
  FOR SELECT TO fraud_gov_analytics_role
  USING (
    EXISTS (
      SELECT 1 FROM fraud_gov.ruleset_versions rv
      WHERE rv.ruleset_version_id = ruleset_version_rules.ruleset_version_id
        AND rv.status IN ('APPROVED','ACTIVE')
    )
  );

-- ruleset_manifest: analytics can read all published artifacts
DROP POLICY IF EXISTS ruleset_manifest_analytics_read ON fraud_gov.ruleset_manifest;
CREATE POLICY ruleset_manifest_analytics_read ON fraud_gov.ruleset_manifest
  FOR SELECT TO fraud_gov_analytics_role
  USING (true);

COMMIT;
