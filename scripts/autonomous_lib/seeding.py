"""
Seeding module for autonomous testing.

Provides deterministic, idempotent data seeding for:
- API-based seeding (uses real API endpoints)
- DB-based seeding (direct database insertion)
- Hybrid seeding (combination of both)

All seeding operations use fixed UUIDs for determinism and
ON CONFLICT patterns for idempotency.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

try:
    import psycopg

    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False

import httpx


class SeedingMode(str, Enum):
    """Seeding strategy modes."""

    API = "api"  # Use API endpoints (slower but validates business logic)
    DB = "db"  # Direct database insertion (faster, good for large datasets)
    HYBRID = "hybrid"  # Combine both approaches


# Fixed test UUIDs for deterministic seeding
TEST_UUIDS = {
    "rule_field_001": "00000000-0000-0001-0000-000000000001",
    "rule_field_002": "00000000-0000-0001-0000-000000000002",
    "rule_001": "00000000-0000-0002-0000-000000000001",
    "rule_002": "00000000-0000-0002-0000-000000000002",
    "ruleset_001": "00000000-0000-0003-0000-000000000001",
    "ruleset_002": "00000000-0000-0003-0000-000000000002",
}


@dataclass
class SeedResult:
    """Result of a seeding operation."""

    success: bool
    entities_created: int = 0
    entities_skipped: int = 0  # Already existed
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


class DbSeeder:
    """Direct database seeding with idempotency."""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.environ.get("DATABASE_URL_APP", "")
        self._conn = None

    def connect(self) -> bool:
        """Establish database connection."""
        if not PSYCOPG_AVAILABLE:
            return False

        if not self.database_url:
            return False

        try:
            from urllib.parse import urlparse

            parsed = urlparse(self.database_url)
            self._conn = psycopg.connect(
                host=parsed.hostname or "localhost",
                port=parsed.port or 5432,
                user=parsed.username or "postgres",
                password=parsed.password or "",
                dbname=parsed.path.lstrip("/") if parsed.path else "fraud_gov",
            )
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def seed_rule_fields(self) -> SeedResult:
        """Seed core rule field definitions with ON CONFLICT DO NOTHING."""
        result = SeedResult(success=False)

        if not self._conn and not self.connect():
            result.errors.append("Could not connect to database")
            return result

        # Core rule fields that should exist
        rule_fields = [
            {
                "field_key": "amount",
                "display_name": "Transaction Amount",
                "data_type": "NUMBER",
                "allowed_operators": ["EQ", "GT", "LT", "GTE", "LTE", "BETWEEN"],
                "multi_value_allowed": False,
                "is_sensitive": False,
            },
            {
                "field_key": "currency",
                "display_name": "Transaction Currency",
                "data_type": "STRING",
                "allowed_operators": ["EQ", "IN"],
                "multi_value_allowed": True,
                "is_sensitive": False,
            },
            {
                "field_key": "mcc",
                "display_name": "Merchant Category Code",
                "data_type": "STRING",
                "allowed_operators": ["EQ", "IN", "NOT_IN"],
                "multi_value_allowed": True,
                "is_sensitive": False,
            },
            {
                "field_key": "network",
                "display_name": "Card Network",
                "data_type": "ENUM",
                "allowed_operators": ["EQ", "IN"],
                "multi_value_allowed": True,
                "is_sensitive": False,
            },
            {
                "field_key": "country",
                "display_name": "Country Code",
                "data_type": "STRING",
                "allowed_operators": ["EQ", "IN", "NOT_IN"],
                "multi_value_allowed": True,
                "is_sensitive": False,
            },
        ]

        try:
            cursor = self._conn.cursor()

            for field in rule_fields:
                # Use ON CONFLICT DO NOTHING for idempotency
                query = """
                    INSERT INTO fraud_gov.rule_fields
                    (field_key, display_name, data_type, allowed_operators,
                     multi_value_allowed, is_sensitive, is_active, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (field_key) DO NOTHING
                    RETURNING field_key
                """
                cursor.execute(
                    query,
                    (
                        field["field_key"],
                        field["display_name"],
                        field["data_type"],
                        field["allowed_operators"],
                        field["multi_value_allowed"],
                        field["is_sensitive"],
                        True,
                        datetime.now(UTC),
                    ),
                )

                if cursor.fetchone():
                    result.entities_created += 1
                else:
                    result.entities_skipped += 1

            self._conn.commit()
            result.success = True

        except Exception as e:
            result.errors.append(str(e))
            if self._conn:
                try:
                    self._conn.rollback()
                except Exception:
                    pass

        return result

    def seed_bulk_rules(self, count: int = 1000) -> SeedResult:
        """Seed a large number of rules for pagination testing.

        Uses fixed UUIDs and batched inserts for performance.
        All rules are in DRAFT state to avoid triggering workflows.
        """
        result = SeedResult(success=False)

        if not self._conn and not self.connect():
            result.errors.append("Could not connect to database")
            return result

        try:
            cursor = self._conn.cursor()

            # Batch insert rules
            batch_size = 100
            for batch_start in range(0, count, batch_size):
                batch_end = min(batch_start + batch_size, count)
                batch_data = []

                for i in range(batch_start, batch_end):
                    # Generate deterministic UUID based on index
                    rule_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"test-rule-{i}")

                    batch_data.append(
                        (
                            str(rule_uuid),
                            f"TEST_BULK_RULE_{i:04d}",
                            f"Auto-generated test rule {i}",
                            "AUTH",
                            1,  # current_version
                            "DRAFT",  # status
                            1,  # version (optimistic lock)
                            "autonomous-test",  # created_by
                            datetime.now(UTC),
                        )
                    )

                # Batch insert with ON CONFLICT
                query = """
                    INSERT INTO fraud_gov.rules
                    (rule_id, rule_name, description, rule_type, current_version,
                     status, version, created_by, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (rule_id) DO NOTHING
                """
                cursor.executemany(query, batch_data)
                result.entities_created += cursor.rowcount
                result.entities_skipped += (batch_end - batch_start) - cursor.rowcount

            self._conn.commit()
            result.success = True

        except Exception as e:
            result.errors.append(str(e))
            if self._conn:
                try:
                    self._conn.rollback()
                except Exception:
                    pass

        return result


class ApiSeeder:
    """API-based seeding for validating business logic."""

    def __init__(self, base_url: str, auth_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.client = httpx.Client(timeout=30.0)

    def close(self) -> None:
        """Close HTTP client."""
        self.client.close()

    def seed_rule_fields(self) -> SeedResult:
        """Seed rule fields via API.

        Creates fields using POST /api/v1/rule-fields.
        Idempotent: skips if field already exists (409).
        """
        result = SeedResult(success=False)

        rule_fields = [
            {
                "field_key": "test_amount",
                "display_name": "Test Amount Field",
                "data_type": "NUMBER",
                "allowed_operators": ["GT", "LT", "EQ"],
                "multi_value_allowed": False,
                "is_sensitive": False,
            },
            {
                "field_key": "test_currency",
                "display_name": "Test Currency Field",
                "data_type": "STRING",
                "allowed_operators": ["EQ", "IN"],
                "multi_value_allowed": True,
                "is_sensitive": False,
            },
        ]

        headers = {}
        if self.auth_token:
            headers["Authorization"] = self.auth_token

        for field_data in rule_fields:
            try:
                response = self.client.post(
                    f"{self.base_url}/api/v1/rule-fields",
                    json=field_data,
                    headers=headers,
                )

                if response.status_code == 201:
                    result.entities_created += 1
                elif response.status_code == 409:  # Already exists
                    result.entities_skipped += 1
                else:
                    result.errors.append(
                        f"Failed to create {field['field_key']}: {response.status_code}"
                    )

            except Exception as e:
                result.errors.append(f"Error creating {field['field_key']}: {e}")

        result.success = len(result.errors) == 0
        return result

    def seed_rules(self, count: int = 10) -> SeedResult:
        """Seed rules via API.

        Creates rule identities and versions.
        """
        result = SeedResult(success=False)

        headers = {}
        if self.auth_token:
            headers["Authorization"] = self.auth_token

        for i in range(count):
            try:
                # Create rule identity
                response = self.client.post(
                    f"{self.base_url}/api/v1/rules",
                    json={
                        "rule_name": f"TEST_API_SEED_RULE_{i:03d}",
                        "description": f"Auto-generated test rule {i}",
                        "rule_type": "AUTH",
                    },
                    headers=headers,
                )

                if response.status_code == 201:
                    rule_id = response.json().get("rule_id")
                    result.entities_created += 1

                    # Create version
                    self.client.post(
                        f"{self.base_url}/api/v1/rules/{rule_id}/versions",
                        json={
                            "condition_tree": {
                                "logicalOperator": "AND",
                                "conditions": [
                                    {
                                        "field": "amount",
                                        "operator": "GT",
                                        "value": 1000 + i,
                                    }
                                ],
                            },
                            "priority": 100 + i,
                            "scope": {},
                        },
                        headers=headers,
                    )
                elif response.status_code == 409:
                    result.entities_skipped += 1
                else:
                    result.errors.append(f"Failed to create rule {i}: {response.status_code}")

            except Exception as e:
                result.errors.append(f"Error creating rule {i}: {e}")

        result.success = len(result.errors) == 0
        return result


class HybridSeeder:
    """Hybrid seeding combining API and DB approaches.

    Strategy:
    - Use DB seeding for catalog data (rule_fields) - fast and stable
    - Use API seeding for entities (rules, rulesets) - validates business logic
    """

    def __init__(
        self,
        base_url: str,
        auth_token: str | None = None,
        database_url: str | None = None,
    ):
        self.api_seeder = ApiSeeder(base_url, auth_token)
        self.db_seeder = DbSeeder(database_url)

    def close(self) -> None:
        """Close all connections."""
        self.api_seeder.close()
        self.db_seeder.close()

    def seed_all(self, rules_count: int = 10) -> dict[str, SeedResult]:
        """Seed all test data using hybrid approach.

        Returns:
            Dictionary with results for each seeding operation.
        """
        results = {}

        # 1. Seed rule fields via DB (fast, stable)
        results["rule_fields_db"] = self.db_seeder.seed_rule_fields()

        # 2. Seed rules via API (validates business logic)
        results["rules_api"] = self.api_seeder.seed_rules(rules_count)

        return results


def create_seeder(
    mode: SeedingMode = SeedingMode.HYBRID,
    base_url: str = "http://127.0.0.1:8000",
    auth_token: str | None = None,
    database_url: str | None = None,
) -> DbSeeder | ApiSeeder | HybridSeeder:
    """Factory function to create a seeder.

    Args:
        mode: Seeding mode (API, DB, or HYBRID)
        base_url: Base URL for API-based seeding
        auth_token: Auth token for API requests
        database_url: Database URL for DB-based seeding

    Returns:
        Appropriate seeder instance based on mode
    """
    if mode == SeedingMode.DB:
        return DbSeeder(database_url)
    elif mode == SeedingMode.API:
        return ApiSeeder(base_url, auth_token)
    else:  # HYBRID
        return HybridSeeder(base_url, auth_token, database_url)
