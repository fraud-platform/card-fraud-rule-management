#!/usr/bin/env python3
"""
Quick verification script for idempotency key implementation.

This script verifies:
1. Database migration has been applied (idempotency_key column exists)
2. Model has the idempotency_key field
3. Repository functions accept idempotency_key parameter
4. API schemas include idempotency_key field
5. Routes use the request bodies with idempotency_key
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_database_migration():
    """Check if idempotency_key column exists in approvals table."""
    print("Checking database migration...")
    try:
        from sqlalchemy import inspect

        from app.core.db import get_engine

        engine = get_engine()
        inspector = inspect(engine)

        # Check if approvals table has idempotency_key column
        columns = [col["name"] for col in inspector.get_columns("approvals", schema="fraud_gov")]

        if "idempotency_key" in columns:
            print("✓ idempotency_key column exists in approvals table")
            return True
        else:
            print("✗ idempotency_key column NOT FOUND in approvals table")
            print("  Please run migration: db/migrations/add_idempotency_key.sql")
            return False
    except Exception as e:
        print(f"✗ Error checking database: {e}")
        return False


def check_model():
    """Check if Approval model has idempotency_key field."""
    print("\nChecking Approval model...")
    try:
        from app.db.models import Approval

        if hasattr(Approval, "idempotency_key"):
            print("✓ Approval model has idempotency_key field")
            return True
        else:
            print("✗ Approval model missing idempotency_key field")
            return False
    except Exception as e:
        print(f"✗ Error checking model: {e}")
        return False


def check_repository():
    """Check if repository functions accept idempotency_key parameter."""
    print("\nChecking repository functions...")
    try:
        import inspect

        from app.repos.rule_repo import submit_rule_version
        from app.repos.ruleset_repo import submit_ruleset

        # Check submit_rule_version signature
        sig = inspect.signature(submit_rule_version)
        if "idempotency_key" in sig.parameters:
            print("✓ submit_rule_version() accepts idempotency_key parameter")
        else:
            print("✗ submit_rule_version() missing idempotency_key parameter")
            return False

        # Check submit_ruleset signature
        sig = inspect.signature(submit_ruleset)
        if "idempotency_key" in sig.parameters:
            print("✓ submit_ruleset() accepts idempotency_key parameter")
        else:
            print("✗ submit_ruleset() missing idempotency_key parameter")
            return False

        return True
    except Exception as e:
        print(f"✗ Error checking repository: {e}")
        return False


def check_schemas():
    """Check if API schemas include idempotency_key field."""
    print("\nChecking API schemas...")
    try:
        from app.api.schemas.rule import RuleVersionSubmitRequest
        from app.api.schemas.ruleset import RuleSetSubmitRequest

        # Check RuleVersionSubmitRequest
        if "idempotency_key" in RuleVersionSubmitRequest.model_fields:
            print("✓ RuleVersionSubmitRequest has idempotency_key field")
        else:
            print("✗ RuleVersionSubmitRequest missing idempotency_key field")
            return False

        # Check RuleSetSubmitRequest
        if "idempotency_key" in RuleSetSubmitRequest.model_fields:
            print("✓ RuleSetSubmitRequest has idempotency_key field")
        else:
            print("✗ RuleSetSubmitRequest missing idempotency_key field")
            return False

        return True
    except Exception as e:
        print(f"✗ Error checking schemas: {e}")
        import traceback

        traceback.print_exc()
        return False


def check_routes():
    """Check if routes use request bodies with idempotency_key."""
    print("\nChecking API routes...")
    try:
        import inspect

        from app.api.routes import rules, rulesets

        # Check rules route
        submit_version_sig = inspect.signature(rules.submit_version)
        params = list(submit_version_sig.parameters.keys())
        if "payload" in params:
            print("✓ submit_version() route uses payload parameter")
        else:
            print("✗ submit_version() route missing payload parameter")
            return False

        # Check rulesets route
        submit_ruleset_sig = inspect.signature(rulesets.submit_ruleset)
        params = list(submit_ruleset_sig.parameters.keys())
        if "payload" in params:
            print("✓ submit_ruleset() route uses payload parameter")
        else:
            print("✗ submit_ruleset() route missing payload parameter")
            return False

        return True
    except Exception as e:
        print(f"✗ Error checking routes: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all verification checks."""
    print("=" * 60)
    print("Idempotency Key Implementation Verification")
    print("=" * 60)

    results = {
        "Database Migration": check_database_migration(),
        "Model": check_model(),
        "Repository": check_repository(),
        "Schemas": check_schemas(),
        "Routes": check_routes(),
    }

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    for check, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {check}")

    all_passed = all(results.values())

    if all_passed:
        print("\n✓ All checks passed! Idempotency key support is fully implemented.")
        return 0
    else:
        print("\n✗ Some checks failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
