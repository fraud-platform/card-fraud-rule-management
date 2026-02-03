-- Fraud Governance — RuleField seed data with versioning (v1)
--
-- Run after db/fraud_governance_schema.sql
--
-- This creates 26 standard fields matching engine FieldRegistry.java
-- Field IDs 1-26 are reserved for standard fields
--
-- Recommended execution:
--   psql "${DATABASE_URL_ADMIN}" -v ON_ERROR_STOP=1 -f db/seed_rule_fields.sql

BEGIN;

-- =============================================================================
-- 1. Insert 26 standard rule fields (identity table)
-- Field IDs 1-26 matching engine FieldRegistry.java
-- =============================================================================

INSERT INTO fraud_gov.rule_fields (field_key, field_id, display_name, description, data_type, allowed_operators, multi_value_allowed, is_sensitive, current_version, version, created_by, created_at, updated_at)
VALUES
  -- Core Transaction Fields (IDs 1-5)
  ('transaction_id', 1, 'Transaction ID', 'Unique transaction identifier', 'STRING', ARRAY['EQ','NE'], false, false, 1, 1, 'system', now(), now()),
  ('card_hash', 2, 'Card Hash', 'Hashed card number for privacy', 'STRING', ARRAY['EQ','IN','NE'], true, true, 1, 1, 'system', now(), now()),
  ('amount', 3, 'Amount', 'Transaction amount in minor currency units', 'NUMBER', ARRAY['EQ','GT','GTE','LT','LTE','BETWEEN'], false, false, 1, 1, 'system', now(), now()),
  ('currency', 4, 'Currency', 'ISO 4217 currency code', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),
  ('merchant_id', 5, 'Merchant ID', 'Merchant identifier', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),

  -- Merchant Fields (IDs 6-9)
  ('merchant_name', 6, 'Merchant Name', 'Merchant legal name', 'STRING', ARRAY['EQ','IN','NE','CONTAINS'], false, false, 1, 1, 'system', now(), now()),
  ('merchant_category', 7, 'Merchant Category', 'Merchant business category', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),
  ('merchant_category_code', 8, 'MCC', 'Merchant category code', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),
  ('merchant_city', 9, 'Merchant City', 'Merchant city location', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),

  -- Card & Transaction Details (IDs 10-14)
  ('card_present', 10, 'Card Present', 'Whether card was physically present', 'BOOLEAN', ARRAY['EQ','NE'], false, false, 1, 1, 'system', now(), now()),
  ('transaction_type', 11, 'Transaction Type', 'Transaction type (purchase, refund, etc.)', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),
  ('entry_mode', 12, 'Entry Mode', 'POS entry mode (chip, swipe, contactless)', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),
  ('country_code', 13, 'Country Code', 'ISO 3166 country code', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),
  ('pos_entry_mode', 14, 'POS Entry Mode', 'Point of sale entry mode', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),

  -- Customer/Device Fields (IDs 15-18)
  ('ip_address', 15, 'IP Address', 'Client IP address', 'STRING', ARRAY['EQ','IN','NE'], false, true, 1, 1, 'system', now(), now()),
  ('device_id', 16, 'Device ID', 'Device fingerprint', 'STRING', ARRAY['EQ','IN','NE'], false, true, 1, 1, 'system', now(), now()),
  ('email', 17, 'Email', 'Customer email address', 'STRING', ARRAY['EQ','IN','NE'], false, true, 1, 1, 'system', now(), now()),
  ('phone', 18, 'Phone', 'Customer phone number', 'STRING', ARRAY['EQ','IN','NE'], false, true, 1, 1, 'system', now(), now()),

  -- Time Fields (ID 19)
  ('timestamp', 19, 'Timestamp', 'Transaction timestamp', 'DATE', ARRAY['EQ','GT','GTE','LT','LTE','BETWEEN'], false, false, 1, 1, 'system', now(), now()),

  -- Billing Address Fields (IDs 20-23)
  ('billing_city', 20, 'Billing City', 'Billing address city', 'STRING', ARRAY['EQ','IN','NE'], false, false, 1, 1, 'system', now(), now()),
  ('billing_country', 21, 'Billing Country', 'Billing address country', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),
  ('billing_postal_code', 22, 'Billing Postal Code', 'Billing postal/zip code', 'STRING', ARRAY['EQ','IN','NE'], false, true, 1, 1, 'system', now(), now()),
  ('billing_line1', 23, 'Billing Address Line 1', 'Billing street address', 'STRING', ARRAY['EQ','IN','NE'], false, true, 1, 1, 'system', now(), now()),

  -- Shipping Address Fields (IDs 24-26)
  ('shipping_city', 24, 'Shipping City', 'Shipping address city', 'STRING', ARRAY['EQ','IN','NE'], false, false, 1, 1, 'system', now(), now()),
  ('shipping_country', 25, 'Shipping Country', 'Shipping address country', 'STRING', ARRAY['EQ','IN','NE'], true, false, 1, 1, 'system', now(), now()),
  ('shipping_postal_code', 26, 'Shipping Postal Code', 'Shipping postal/zip code', 'STRING', ARRAY['EQ','IN','NE'], false, true, 1, 1, 'system', now(), now())
ON CONFLICT (field_key) DO UPDATE
SET
  field_id = EXCLUDED.field_id,
  display_name = EXCLUDED.display_name,
  description = EXCLUDED.description,
  data_type = EXCLUDED.data_type,
  allowed_operators = EXCLUDED.allowed_operators,
  multi_value_allowed = EXCLUDED.multi_value_allowed,
  is_sensitive = EXCLUDED.is_sensitive,
  current_version = EXCLUDED.current_version,
  version = EXCLUDED.version,
  updated_at = EXCLUDED.updated_at;

-- =============================================================================
-- 2. Create initial APPROVED versions for all standard fields
-- =============================================================================

INSERT INTO fraud_gov.rule_field_versions (
  rule_field_version_id, field_key, version, field_id, display_name, description,
  data_type, allowed_operators, multi_value_allowed, is_sensitive, status,
  created_by, created_at, approved_by, approved_at
)
SELECT
  gen_random_uuid(),
  field_key,
  1,
  field_id,
  display_name,
  description,
  data_type,
  allowed_operators,
  multi_value_allowed,
  is_sensitive,
  'APPROVED',
  'system',
  now(),
  'system',
  now()
FROM fraud_gov.rule_fields
WHERE field_id BETWEEN 1 AND 26;

-- =============================================================================
-- 3. Create initial field registry manifest
-- =============================================================================

INSERT INTO fraud_gov.field_registry_manifest (
  manifest_id,
  registry_version,
  artifact_uri,
  checksum,
  field_count,
  created_by,
  created_at
)
VALUES (
  gen_random_uuid(),
  1,
  'fields/registry/v1/fields.json',
  'sha256:0000000000000000000000000000000000000000000000000000000000000000',  -- Placeholder checksum
  26,
  'system',
  now()
);

COMMIT;
