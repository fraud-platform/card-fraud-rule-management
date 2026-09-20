-- Fraud Governance — full-table seed data (for dev/testing)
--
-- Purpose:
-- - Load a small, consistent dataset across all governance tables so engineers
--   can test list/detail/compile flows without creating data manually.
--
-- Prerequisites:
-- - Run db/fraud_governance_schema.sql
-- - Run db/seed_rule_fields.sql (provides RuleFields referenced by condition trees)
--
-- Recommended execution:
--   psql "${DATABASE_URL_ADMIN}" -v ON_ERROR_STOP=1 -f db/seed_all_tables.sql
--
-- Notes:
-- - UUIDs are hard-coded so the seed is deterministic.
-- - Inserts are idempotent via ON CONFLICT DO NOTHING.

BEGIN;

-- ------------------------------------------------------------
-- Rules + RuleVersions
-- ------------------------------------------------------------

-- Approved rule (version 1)
INSERT INTO fraud_gov.rules (
  rule_id,
  rule_name,
  description,
  rule_type,
  current_version,
  status,
  created_by
)
VALUES (
  '11111111-1111-1111-1111-111111111111',
  'High Amount Flag',
  'Flags transactions above a threshold',
  'MONITORING',
  1,
  'APPROVED',
  'seed@system'
)
ON CONFLICT (rule_id) DO NOTHING;

INSERT INTO fraud_gov.rule_versions (
  rule_version_id,
  rule_id,
  version,
  condition_tree,
  priority,
  created_by,
  approved_by,
  approved_at,
  status
)
VALUES (
  '22222222-2222-2222-2222-222222222222',
  '11111111-1111-1111-1111-111111111111',
  1,
  '{"field":"amount","op":"GT","value":3000}'::jsonb,
  100,
  'seed@system',
  'checker@system',
  now(),
  'APPROVED'
)
ON CONFLICT (rule_version_id) DO NOTHING;

-- Draft rule (version 1)
INSERT INTO fraud_gov.rules (
  rule_id,
  rule_name,
  description,
  rule_type,
  current_version,
  status,
  created_by
)
VALUES (
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  'MCC Blocklist',
  'Blocks specific MCCs (draft example)',
  'MONITORING',
  1,
  'DRAFT',
  'maker@system'
)
ON CONFLICT (rule_id) DO NOTHING;

INSERT INTO fraud_gov.rule_versions (
  rule_version_id,
  rule_id,
  version,
  condition_tree,
  priority,
  created_by,
  status
)
VALUES (
  'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  1,
  '{"field":"merchant_category_code","op":"IN","value":["5967","7995"]}'::jsonb,
  50,
  'maker@system',
  'DRAFT'
)
ON CONFLICT (rule_version_id) DO NOTHING;

-- ------------------------------------------------------------
-- RuleSets + membership
-- ------------------------------------------------------------

INSERT INTO fraud_gov.rulesets (
  ruleset_id,
  environment,
  region,
  country,
  rule_type,
  name,
  description,
  created_by
)
VALUES (
  '33333333-3333-3333-3333-333333333333',
  'local',
  'APAC',
  'IN',
  'MONITORING',
  'Monitoring Ruleset v1',
  'Seeded ruleset for dev/testing',
  'seed@system'
)
ON CONFLICT (ruleset_id) DO NOTHING;

INSERT INTO fraud_gov.ruleset_versions (
  ruleset_version_id,
  ruleset_id,
  version,
  description,
  status,
  created_by,
  approved_by,
  approved_at,
  activated_at
)
VALUES (
  '33333333-3333-3333-3333-333333333334',
  '33333333-3333-3333-3333-333333333333',
  1,
  'Seeded ruleset snapshot for dev/testing',
  'ACTIVE',
  'seed@system',
  'checker@system',
  now(),
  now()
)
ON CONFLICT (ruleset_version_id) DO NOTHING;

INSERT INTO fraud_gov.ruleset_version_rules (ruleset_version_id, rule_version_id)
VALUES
  ('33333333-3333-3333-3333-333333333334', '22222222-2222-2222-2222-222222222222')
ON CONFLICT (ruleset_version_id, rule_version_id) DO NOTHING;

-- ------------------------------------------------------------
-- Approvals
-- ------------------------------------------------------------

INSERT INTO fraud_gov.approvals (
  approval_id,
  entity_type,
  entity_id,
  action,
  maker,
  checker,
  status,
  remarks,
  decided_at
)
VALUES (
  '44444444-4444-4444-4444-444444444444',
  'RULE_VERSION',
  '22222222-2222-2222-2222-222222222222',
  'APPROVE',
  'seed@system',
  'checker@system',
  'APPROVED',
  'Seed approval for testing',
  now()
)
ON CONFLICT (approval_id) DO NOTHING;

INSERT INTO fraud_gov.approvals (
  approval_id,
  entity_type,
  entity_id,
  action,
  maker,
  checker,
  status,
  remarks,
  decided_at
)
VALUES (
  '55555555-5555-5555-5555-555555555555',
  'RULESET_VERSION',
  '33333333-3333-3333-3333-333333333334',
  'APPROVE',
  'seed@system',
  'checker@system',
  'APPROVED',
  'Seed approval for testing',
  now()
)
ON CONFLICT (approval_id) DO NOTHING;

-- ------------------------------------------------------------
-- Audit log
-- ------------------------------------------------------------

INSERT INTO fraud_gov.audit_log (
  audit_id,
  entity_type,
  entity_id,
  action,
  old_value,
  new_value,
  performed_by,
  performed_at
)
VALUES
  (
    '66666666-6666-6666-6666-666666666666',
    'RULE',
    '11111111-1111-1111-1111-111111111111',
    'SEED_CREATE',
    NULL,
    jsonb_build_object('rule_name','High Amount Flag','rule_type','MONITORING','status','APPROVED'),
    'seed@system',
    now()
  ),
  (
    '77777777-7777-7777-7777-777777777777',
    'RULE_VERSION',
    '22222222-2222-2222-2222-222222222222',
    'SEED_APPROVE',
    NULL,
    jsonb_build_object('status','APPROVED','approved_by','checker@system'),
    'checker@system',
    now()
  ),
  (
    '88888888-8888-8888-8888-888888888888',
    'RULESET_VERSION',
    '33333333-3333-3333-3333-333333333334',
    'SEED_ACTIVATE',
    NULL,
    jsonb_build_object('status','ACTIVE'),
    'checker@system',
    now()
  ),
  (
    '99999999-9999-9999-9999-999999999999',
    'APPROVAL',
    '55555555-5555-5555-5555-555555555555',
    'SEED_CREATE',
    NULL,
    jsonb_build_object('entity_type','RULESET','status','APPROVED'),
    'seed@system',
    now()
  )
ON CONFLICT (audit_id) DO NOTHING;

COMMIT;
