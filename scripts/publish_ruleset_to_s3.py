#!/usr/bin/env python3
"""
Publish Rule Fields, Rules, and RuleSets to MinIO S3

This script executes the complete workflow to populate S3 with compiled rulesets
so the fraud rule engine can start consuming rules.

Workflow:
1. Get Auth0 tokens (maker + checker)
2. Seed rule fields (core fields for fraud detection)
3. Create rules with condition trees
4. Create rulesets and add rules
5. Submit ruleset for approval (maker)
6. Approve ruleset (checker) -> triggers compilation + S3 publish

Usage:
    uv run python scripts/publish_ruleset_to_s3.py [--reset] [--rules <count>] [--rulesets <count>]

Prerequisites:
    - Local infrastructure running: uv run platform-up
    - Auth0 configured with test users (test-rule-maker, test-rule-checker)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field

import httpx

API_DELAY = 1.0  # Delay between API calls to avoid rate limiting (60/min = 1s per request)


@dataclass
class Config:
    """Configuration for the publish script."""

    base_url: str = "http://127.0.0.1:8000"
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_test_client_id: str = ""
    auth0_test_client_secret: str = ""
    maker_username: str = "test-rule-maker@fraud-platform.test"
    checker_username: str = "test-rule-checker@fraud-platform.test"
    rules_count: int = 10
    rulesets_count: int = 2
    reset_first: bool = False
    verbose: bool = False


@dataclass
class PublishResult:
    """Result of the publish operation."""

    success: bool = False
    rule_fields_created: int = 0
    rules_created: int = 0
    rulesets_published: int = 0
    errors: list[str] = field(default_factory=list)
    manifest_uris: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


def log(msg: str, level: str = "info") -> None:
    """Print a log message."""
    timestamp = time.strftime("%H:%M:%S")
    symbols = {
        "info": "[INFO]",
        "warn": "[WARN]",
        "error": "[ERROR]",
        "success": "[OK]",
        "step": "[STEP]",
    }
    symbol = symbols.get(level, "[INFO]")
    print(f"[{timestamp}] {symbol} {msg}")


def get_doppler_secret(secret_name: str) -> str | None:
    """Get a secret from Doppler if available."""
    try:
        result = subprocess.run(
            ["doppler", "secrets", "get", secret_name, "--plain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return os.environ.get(secret_name)


def fetch_auth0_user_token(
    domain: str,
    audience: str,
    client_id: str,
    client_secret: str,
    username: str,
    password: str,
) -> str | None:
    """Fetch Auth0 user token using Resource Owner Password Credentials grant."""
    try:
        response = httpx.post(
            f"https://{domain}/oauth/token",
            json={
                "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
                "username": username,
                "password": password,
                "audience": audience,
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "openid profile email",
            },
            timeout=30.0,
        )
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception:
        pass
    return None


def get_auth0_tokens(config: Config) -> dict[str, str | None]:
    """Get Auth0 tokens for maker and checker."""
    tokens: dict[str, str | None] = {"maker": None, "checker": None, "admin": None}

    domain = config.auth0_domain or get_doppler_secret("AUTH0_DOMAIN") or ""
    audience = config.auth0_audience or get_doppler_secret("AUTH0_AUDIENCE") or ""

    m2m_client_id = get_doppler_secret("AUTH0_CLIENT_ID") or ""
    m2m_client_secret = get_doppler_secret("AUTH0_CLIENT_SECRET") or ""

    test_client_id = get_doppler_secret("AUTH0_TEST_CLIENT_ID") or ""
    test_client_secret = get_doppler_secret("AUTH0_TEST_CLIENT_SECRET") or ""

    maker_password = get_doppler_secret("TEST_USER_RULE_MAKER_PASSWORD") or ""
    checker_password = get_doppler_secret("TEST_USER_RULE_CHECKER_PASSWORD") or ""
    admin_password = get_doppler_secret("TEST_USER_PLATFORM_ADMIN_PASSWORD") or ""

    if not all([domain, audience]):
        log("Auth0 credentials not fully configured", "warn")
        return tokens

    user_tokens_fetched = False

    if test_client_id and test_client_secret and maker_password:
        token = fetch_auth0_user_token(
            domain,
            audience,
            test_client_id,
            test_client_secret,
            config.maker_username,
            maker_password,
        )
        if token:
            tokens["maker"] = token
            user_tokens_fetched = True
            log(f"Got maker token for {config.maker_username}", "success")
        else:
            log(
                "Failed to get maker token - check AUTH0_TEST_CLIENT_ID/SECRET and password grant",
                "warn",
            )

    if test_client_id and test_client_secret and checker_password:
        token = fetch_auth0_user_token(
            domain,
            audience,
            test_client_id,
            test_client_secret,
            config.checker_username,
            checker_password,
        )
        if token:
            tokens["checker"] = token
            user_tokens_fetched = True
            log(f"Got checker token for {config.checker_username}", "success")

    if test_client_id and test_client_secret and admin_password:
        token = fetch_auth0_user_token(
            domain,
            audience,
            test_client_id,
            test_client_secret,
            "test-platform-admin@fraud-platform.test",
            admin_password,
        )
        if token:
            tokens["admin"] = token
            user_tokens_fetched = True

    # Fallback to M2M if user tokens weren't fetched
    if not user_tokens_fetched and m2m_client_id and m2m_client_secret:
        try:
            token = fetch_auth0_client_credentials(
                domain, audience, m2m_client_id, m2m_client_secret
            )
            if token:
                for key in tokens:
                    tokens[key] = token
                log("Using M2M token (maker=checker - cannot test full approval flow)", "warn")
        except Exception as e:
            log(f"Failed to fetch M2M token: {e}", "warn")

    if not any(tokens.values()):
        log("No Auth0 tokens obtained", "warn")

    return tokens


def fetch_auth0_client_credentials(
    domain: str,
    audience: str,
    client_id: str,
    client_secret: str,
) -> str | None:
    """Fetch Auth0 M2M token using client credentials grant."""
    try:
        response = httpx.post(
            f"https://{domain}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "audience": audience,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=30.0,
        )
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception:
        pass
    return None


def ensure_rule_fields(client: httpx.Client, token: str | None, config: Config) -> int:
    """Ensure core rule fields exist, create if missing. Returns count created."""
    if not token:
        log("No token provided for rule fields", "warn")
        return 0

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
            "allowed_operators": ["EQ", "IN", "NE"],
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
        {
            "field_key": "card_hash",
            "display_name": "Card Hash",
            "data_type": "STRING",
            "allowed_operators": ["EQ", "IN", "NE"],
            "multi_value_allowed": True,
            "is_sensitive": True,
        },
        {
            "field_key": "merchant_id",
            "display_name": "Merchant ID",
            "data_type": "STRING",
            "allowed_operators": ["EQ", "IN", "NE"],
            "multi_value_allowed": True,
            "is_sensitive": False,
        },
        {
            "field_key": "velocity_txn_count_1h",
            "display_name": "Transaction Count (1 hour)",
            "data_type": "NUMBER",
            "allowed_operators": ["EQ", "GT", "GTE", "LT", "LTE"],
            "multi_value_allowed": False,
            "is_sensitive": False,
        },
        {
            "field_key": "velocity_amount_24h",
            "display_name": "Amount (24 hours)",
            "data_type": "NUMBER",
            "allowed_operators": ["EQ", "GT", "GTE", "LT", "LTE"],
            "multi_value_allowed": False,
            "is_sensitive": False,
        },
        {
            "field_key": "card_present",
            "display_name": "Card Present",
            "data_type": "BOOLEAN",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_sensitive": False,
        },
    ]

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    created = 0

    for field_data in rule_fields:
        try:
            response = client.post(
                f"{config.base_url}/api/v1/rule-fields",
                json=field_data,
                headers=headers,
            )
            if response.status_code == 201:
                created += 1
                log(f"Created rule field: {field_data['field_key']}")
            elif response.status_code == 409:
                log(f"Rule field exists: {field_data['field_key']}", "info")
            else:
                log(f"Failed to create {field_data['field_key']}: {response.status_code}", "warn")
        except Exception as e:
            log(f"Error creating {field_data['field_key']}: {e}", "error")

    return created


def create_realistic_rules(
    client: httpx.Client, token: str | None, count: int, config: Config
) -> list[dict]:
    """Create realistic production-like rules."""
    if not token:
        log("No token provided for creating rules", "warn")
        return []

    rules: list[dict] = []

    rule_templates = [
        {
            "rule_name": "High Value Transaction Review",
            "description": "Decline transactions above $10,000",
            "rule_type": "AUTH",
            "condition": {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 10000},
            "condition_extra": {
                "type": "CONDITION",
                "field": "currency",
                "operator": "EQ",
                "value": "USD",
            },
            "priority": 100,
            "action": "DECLINE",
        },
        {
            "rule_name": "High Risk MCC Block",
            "description": "Block known high-risk merchant categories",
            "rule_type": "AUTH",
            "condition": {
                "type": "CONDITION",
                "field": "mcc",
                "operator": "IN",
                "value": ["5967", "7995", "5816", "4111", "5411"],
            },
            "priority": 200,
            "action": "DECLINE",
        },
        {
            "rule_name": "International Transaction Alert",
            "description": "Decline international transactions",
            "rule_type": "AUTH",
            "condition": {"type": "CONDITION", "field": "country", "operator": "NE", "value": "US"},
            "condition_extra": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 500,
            },
            "priority": 150,
            "action": "DECLINE",
        },
        {
            "rule_name": "High Velocity Card",
            "description": "Decline cards with high transaction frequency",
            "rule_type": "AUTH",
            "condition": {
                "type": "CONDITION",
                "field": "velocity_txn_count_1h",
                "operator": "GT",
                "value": 10,
            },
            "condition_extra": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            "priority": 300,
            "action": "DECLINE",
        },
        {
            "rule_name": "Card Not Present High Value",
            "description": "Decline CNP transactions over $5000",
            "rule_type": "AUTH",
            "condition": {
                "type": "CONDITION",
                "field": "card_present",
                "operator": "EQ",
                "value": False,
            },
            "condition_extra": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 5000,
            },
            "priority": 250,
            "action": "DECLINE",
        },
        {
            "rule_name": "Trusted Merchant Pass",
            "description": "Approve known trusted merchants",
            "rule_type": "AUTH",
            "condition": {
                "type": "CONDITION",
                "field": "merchant_id",
                "operator": "IN",
                "value": ["MERCHANT_001", "MERCHANT_002", "MERCHANT_003"],
            },
            "priority": 500,
            "action": "APPROVE",
        },
        {
            "rule_name": "Large International Wire",
            "description": "Decline large international transfers",
            "rule_type": "AUTH",
            "condition": {
                "type": "CONDITION",
                "field": "country",
                "operator": "NOT_IN",
                "value": ["US", "CA", "GB"],
            },
            "condition_extra": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 25000,
            },
            "priority": 175,
            "action": "DECLINE",
        },
        {
            "rule_name": "Same Country High Value",
            "description": "Decline high value domestic transactions",
            "rule_type": "AUTH",
            "condition": {"type": "CONDITION", "field": "country", "operator": "EQ", "value": "US"},
            "condition_extra": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 15000,
            },
            "priority": 120,
            "action": "DECLINE",
        },
        {
            "rule_name": "24h Velocity Limit",
            "description": "Decline cards exceeding $50k in 24 hours",
            "rule_type": "AUTH",
            "condition": {
                "type": "CONDITION",
                "field": "velocity_amount_24h",
                "operator": "GT",
                "value": 50000,
            },
            "condition_extra": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 2000,
            },
            "priority": 350,
            "action": "DECLINE",
        },
        {
            "rule_name": "Premium Card High Value",
            "description": "Decline premium card high-value transactions",
            "rule_type": "AUTH",
            "condition": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 100000,
            },
            "condition_extra": {
                "type": "CONDITION",
                "field": "currency",
                "operator": "EQ",
                "value": "USD",
            },
            "priority": 100,
            "action": "DECLINE",
        },
    ]

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    for i in range(count):
        template = rule_templates[i % len(rule_templates)]
        rule_data = {
            "rule_name": f"{template['rule_name']} #{i + 1:03d}",
            "description": f"{template['description']} - Auto-generated",
            "rule_type": template["rule_type"],
        }

        try:
            response = client.post(
                f"{config.base_url}/api/v1/rules",
                json=rule_data,
                headers=headers,
            )

            if response.status_code == 201:
                rule = response.json()
                rule_id = rule["rule_id"]
                rules.append({"rule_id": rule_id, **template})
                log(f"Created rule: {rule_data['rule_name']}", "success")

                # Build condition_tree - wrap in AND if condition_extra exists
                condition = template["condition"].copy()
                if "condition_extra" in template:
                    condition = {
                        "type": "AND",
                        "conditions": [condition, template["condition_extra"]],
                    }

                version_data = {
                    "condition_tree": condition,
                    "priority": template["priority"] + i,
                    "scope": {"network": ["VISA", "MASTERCARD", "AMEX"]},
                    "action": template["action"],
                }

                version_response = client.post(
                    f"{config.base_url}/api/v1/rules/{rule_id}/versions",
                    json=version_data,
                    headers=headers,
                )

                if version_response.status_code in [201, 409]:
                    version_data = version_response.json()
                    log(f"    Version response: {version_data}", "info")
                    rule_version_id = version_data.get("rule_version_id")
                    if rule_version_id:
                        # Update the last rule with the version_id
                        rules[-1]["rule_version_id"] = rule_version_id
                        log(
                            f"  Created rule version for {rule_data['rule_name']}: {rule_version_id}",
                            "info",
                        )
                    else:
                        log("  Version created but no version_id returned", "info")
                else:
                    log(
                        f"  Failed to create version: {version_response.status_code} - {version_response.text[:200]}",
                        "warn",
                    )

                if version_response.status_code in [201, 409]:
                    log(f"  Created rule version for {rule_data['rule_name']}", "info")
                else:
                    log(
                        f"  Failed to create version: {version_response.status_code} - {version_response.text[:200]}",
                        "warn",
                    )

            elif response.status_code == 409:
                log(f"Rule exists: {rule_data['rule_name']}", "info")
            else:
                log(f"Failed to create rule: {response.status_code}", "warn")

        except Exception as e:
            log(f"Error creating rule: {e}", "error")
            time.sleep(API_DELAY)

    return rules


def create_ruleset(
    client: httpx.Client,
    token: str | None,
    name: str,
    rule_type: str,
    rule_ids: list[str],
    config: Config,
    environment: str = "local",
    region: str = "TEST",
    country: str = "XX",
) -> str | None:
    """Create a ruleset and add rules, return ruleset_version_id or None."""
    if not token:
        log("No token provided for creating ruleset", "warn")
        return None

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    ruleset_data = {
        "environment": environment,
        "region": region,
        "country": country,
        "rule_type": rule_type,
        "name": name,
        "description": f"Auto-generated ruleset for {rule_type} rules",
    }

    try:
        response = client.post(
            f"{config.base_url}/api/v1/rulesets",
            json=ruleset_data,
            headers=headers,
        )

        if response.status_code not in [201, 409]:
            log(f"Failed to create ruleset: {response.status_code}", "warn")
            return None

        if response.status_code == 201:
            ruleset_id = response.json()["ruleset_id"]
        else:
            existing = client.get(
                f"{config.base_url}/api/v1/rulesets?environment={environment}&region={region}&country={country}&rule_type={rule_type}&name={name}",
                headers=headers,
            )
            if existing.status_code == 200 and existing.json().get("items"):
                ruleset_id = existing.json()["items"][0]["ruleset_id"]
            else:
                return None

        log(f"Created ruleset: {name} ({ruleset_id})", "success")

        version_data = {"rule_version_ids": rule_ids[:50]}
        log(f"  Attaching rule versions: {version_data}", "info")

        version_response = client.post(
            f"{config.base_url}/api/v1/rulesets/{ruleset_id}/versions",
            json=version_data,
            headers=headers,
        )

        log(
            f"  Version response: {version_response.status_code} - {version_response.text[:200]}",
            "warn",
        )

        if version_response.status_code in [201, 409]:
            version = version_response.json()
            ruleset_version_id = version.get("ruleset_version_id") or version.get(
                "details", {}
            ).get("existing_ruleset_version_id")
            log(f"  Created ruleset version: {version.get('version', '?')}", "info")
            return ruleset_version_id
        else:
            log(
                f"Failed to create ruleset version: {version_response.status_code} - {version_response.text[:200]}",
                "warn",
            )

    except Exception as e:
        log(f"Error creating ruleset: {e}", "error")

    return None


def submit_ruleset_version(
    client: httpx.Client, token: str | None, ruleset_version_id: str, base_url: str
) -> bool:
    """Submit a ruleset version for approval."""
    if not token:
        return False

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        response = client.post(
            f"{base_url}/api/v1/ruleset-versions/{ruleset_version_id}/submit",
            json={"idempotency_key": f"submit_{ruleset_version_id}"},
            headers=headers,
        )
        if response.status_code in [200, 409]:
            log("Submitted ruleset version for approval", "success")
            return True
        else:
            log(f"Failed to submit: {response.status_code}", "warn")
    except Exception as e:
        log(f"Error submitting: {e}", "error")

    return False


def approve_ruleset_version(
    client: httpx.Client, token: str | None, ruleset_version_id: str, base_url: str
) -> bool:
    """Approve a ruleset version (triggers compile + publish to S3)."""
    if not token:
        return False

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        response = client.post(
            f"{base_url}/api/v1/ruleset-versions/{ruleset_version_id}/approve",
            json={"idempotency_key": f"approve_{ruleset_version_id}"},
            headers=headers,
        )
        if response.status_code == 200:
            log("Approved ruleset version - compiled and published to S3!", "success")
            return True
        elif response.status_code == 409:
            error_data = response.json()
            if (
                "maker" in error_data.get("message", "").lower()
                or "checker" in error_data.get("message", "").lower()
            ):
                log("Maker=Checker violation - cannot approve own work", "warn")
            else:
                log(f"Conflict: {error_data}", "warn")
        else:
            log(f"Failed to approve: {response.status_code}", "warn")
    except Exception as e:
        log(f"Error approving: {e}", "error")

    return False


def verify_s3_publish(client: httpx.Client, ruleset_version_id: str, base_url: str) -> str | None:
    """Verify the ruleset was published to S3 and return the manifest URI."""
    try:
        response = client.get(
            f"{base_url}/api/v1/ruleset-versions/{ruleset_version_id}",
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("status") in ["APPROVED", "ACTIVE"]:
                log(f"Ruleset version status: {data.get('status')}", "success")
                return data.get("manifest_uri")
    except Exception as e:
        log(f"Error verifying S3 publish: {e}", "error")

    return None


def reset_database_if_requested(config: Config) -> None:
    """Reset the database if --reset flag is set."""
    if not config.reset_first:
        return

    log("Resetting database...", "warn")
    try:
        result = subprocess.run(
            ["uv", "run", "python", "scripts/reset_schema.py"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            log("Database reset complete", "success")
        else:
            log(f"Database reset failed: {result.stderr}", "error")
    except Exception as e:
        log(f"Error resetting database: {e}", "error")


def reset_rate_limiter() -> None:
    """Reset the in-memory rate limiter to avoid 429 from previous runs."""
    try:
        import httpx

        # Call the rate limiter reset endpoint if it exists, or reset via direct DB
        # For now, try to make a request to trigger cleanup
        httpx.get("http://127.0.0.1:8000/api/v1/health", timeout=5)
    except Exception:
        pass


async def run_publish(config: Config) -> PublishResult:
    """Main async function to run the complete publish workflow."""
    start_time = time.time()
    result = PublishResult()

    log("=" * 60)
    log("Starting RuleSet Publish to S3 Workflow")
    log("=" * 60)

    tokens = get_auth0_tokens(config)

    if not tokens.get("maker") or not tokens.get("checker"):
        log("Failed to get Auth0 tokens - cannot proceed", "error")
        if not tokens.get("maker"):
            result.errors.append("No maker token")
        if not tokens.get("checker"):
            result.errors.append("No checker token")
        return result

    reset_database_if_requested(config)
    reset_rate_limiter()

    client = httpx.Client(timeout=30.0)

    try:
        log("\n--- Step 1: Ensure Rule Fields Exist ---")
        result.rule_fields_created = ensure_rule_fields(client, tokens["maker"], config)

        log("\n--- Step 2: Create Realistic Production Rules ---")
        rules = create_realistic_rules(client, tokens["maker"], config.rules_count, config)
        result.rules_created = len(rules)
        rule_ids = [r["rule_id"] for r in rules]

        if not rule_ids:
            result.errors.append("No rules created")
            return result

        log("\n--- Step 3: Create Rulesets ---")

        # Filter rules by rule_type - AUTH ruleset can only contain AUTH rules
        auth_rules = [r for r in rules if r["rule_type"] == "AUTH" and r.get("rule_version_id")]

        ruleset_version_ids = []

        if auth_rules:
            rule_version_ids = [r["rule_version_id"] for r in auth_rules]
            log(f"  AUTH rules with versions: {len(rule_version_ids)}", "info")

            if rule_version_ids:
                auth_ruleset_v1 = create_ruleset(
                    client,
                    tokens["maker"],
                    "CARD_AUTH Production Rules",
                    "AUTH",
                    rule_version_ids,
                    config,
                )
                if auth_ruleset_v1:
                    ruleset_version_ids.append(auth_ruleset_v1)
            else:
                log("  No AUTH rule versions available", "warn")
        else:
            log("  No AUTH-compatible rules found", "warn")

        log("\n--- Summary ---")
        log(f"Total rules: {len(rules)}")
        log(f"AUTH rules: {len(auth_rules)}")
        log(f"Created {len(ruleset_version_ids)} ruleset versions")

        log("\n--- Step 4: Submit Rulesets for Approval ---")
        for rs_version_id in ruleset_version_ids:
            if rs_version_id:
                submit_ruleset_version(client, tokens["maker"], rs_version_id, config.base_url)

        log("\n--- Step 5: Approve Rulesets (Compile + Publish to S3) ---")
        for rs_version_id in ruleset_version_ids:
            if rs_version_id and tokens["maker"] != tokens.get("checker"):
                if approve_ruleset_version(
                    client, tokens["checker"], rs_version_id, config.base_url
                ):
                    result.rulesets_published += 1
                    uri = verify_s3_publish(client, rs_version_id, config.base_url)
                    if uri:
                        result.manifest_uris.append(uri)
                        log(f"S3 Manifest URI: {uri}", "success")
            else:
                log("Skipping approval - maker=checker or no version ID", "warn")
                log(
                    "To enable full workflow, configure AUTH0_TEST_CLIENT with password grant",
                    "info",
                )

        log("\n--- Summary ---")
        log(f"Rule Fields Created: {result.rule_fields_created}")
        log(f"Rules Created: {result.rules_created}")
        log(f"Rulesets Published: {result.rulesets_published}")
        log(f"Manifest URIs: {result.manifest_uris}")

        result.success = result.rulesets_published > 0

    except Exception as e:
        log(f"Error in publish workflow: {e}", "error")
        result.errors.append(str(e))

    finally:
        client.close()

    result.duration_ms = (time.time() - start_time) * 1000

    log(f"\nTotal time: {result.duration_ms / 1000:.2f}s")
    log("=" * 60)

    return result


def main() -> int:
    """Main entry point."""
    config = Config()

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--reset":
            config.reset_first = True
        elif arg == "--rules" and i + 1 < len(args):
            config.rules_count = int(args[i + 1])
            i += 1
        elif arg == "--rulesets" and i + 1 < len(args):
            config.rulesets_count = int(args[i + 1])
            i += 1
        elif arg == "--url" and i + 1 < len(args):
            config.base_url = args[i + 1]
            i += 1
        elif arg == "--verbose":
            config.verbose = True
        elif arg == "--help":
            print(__doc__)
            return 0
        i += 1

    result = asyncio.run(run_publish(config))

    if result.success:
        log("Publish workflow completed successfully!", "success")
        print("\nRulesets are now available in S3 at:")
        for uri in result.manifest_uris:
            print(f"  - {uri}")
        return 0
    else:
        log("Publish workflow failed!", "error")
        for error in result.errors:
            print(f"  - {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
