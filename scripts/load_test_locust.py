"""
Locust Load Test Script for Card Fraud Rule Management API

Install Locust:
    uv add locust

Run:
    locust -f scripts/load_test_locust.py --host=http://127.0.0.1:8000 --users=10 --spawn-rate=2 --run-time=2m

Or with Web UI:
    locust -f scripts/load_test_locust.py --host=http://127.0.0.1:8000

Headless mode with report:
    locust -f scripts/load_test_locust.py --host=http://127.0.0.1:8000 --users=20 --spawn-rate=5 --run-time=3m --csv=reports/load_test --csv-full-history
"""

import os
import random
import subprocess
import time
from datetime import datetime

import requests
from locust import HttpUser, between, events, task
from locust.runners import MasterRunner

# Configuration
AUTH0_DOMAIN = os.environ.get("AUTH0_DOMAIN", "")
AUTH0_AUDIENCE = os.environ.get("AUTH0_AUDIENCE", "")
AUTH0_TEST_CLIENT_ID = os.environ.get("AUTH0_TEST_CLIENT_ID", "")
AUTH0_TEST_CLIENT_SECRET = os.environ.get("AUTH0_TEST_CLIENT_SECRET", "")
TEST_USER_RULE_MAKER_PASSWORD = os.environ.get("TEST_USER_RULE_MAKER_PASSWORD", "")
TEST_USER_RULE_CHECKER_PASSWORD = os.environ.get("TEST_USER_RULE_CHECKER_PASSWORD", "")

BASE_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")

rule_templates = [
    {
        "name": "High Value Transaction",
        "type": "AUTH",
        "condition": {
            "logicalOperator": "AND",
            "conditions": [
                {"field": "amount", "operator": "GT", "value": 10000},
                {"field": "currency", "operator": "EQ", "value": "USD"},
            ],
        },
        "priority": 100,
    },
    {
        "name": "High Risk MCC",
        "type": "BLOCKLIST",
        "condition": {"field": "mcc", "operator": "IN", "value": ["5967", "7995", "5816"]},
        "priority": 200,
    },
    {
        "name": "International Transaction",
        "type": "MONITORING",
        "condition": {
            "logicalOperator": "AND",
            "conditions": [
                {"field": "country", "operator": "NE", "value": "US"},
                {"field": "amount", "operator": "GT", "value": 500},
            ],
        },
        "priority": 150,
    },
    {
        "name": "High Velocity Card",
        "type": "AUTH",
        "condition": {
            "logicalOperator": "AND",
            "conditions": [
                {"field": "velocity_txn_count_1h", "operator": "GT", "value": 10},
                {"field": "amount", "operator": "GT", "value": 1000},
            ],
        },
        "priority": 300,
    },
    {
        "name": "Card Not Present High Value",
        "type": "AUTH",
        "condition": {
            "logicalOperator": "AND",
            "conditions": [
                {"field": "card_present", "operator": "EQ", "value": False},
                {"field": "amount", "operator": "GT", "value": 5000},
            ],
        },
        "priority": 250,
    },
]


def get_auth0_token(domain, audience, client_id, client_secret, username, password):
    """Fetch Auth0 user token."""
    try:
        response = requests.post(
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
            timeout=10,
        )
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception:
        pass
    return None


def get_doppler_secret(secret_name):
    """Get secret from Doppler or environment."""
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


class AuthTokenManager:
    """Manages Auth0 tokens for maker and checker."""

    _instance = None
    _maker_token = None
    _checker_token = None

    @classmethod
    def get_tokens(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance.get_maker_token(), cls._instance.get_checker_token()

    def get_maker_token(self):
        if self._maker_token:
            return self._maker_token

        domain = AUTH0_DOMAIN or get_doppler_secret("AUTH0_DOMAIN")
        audience = AUTH0_AUDIENCE or get_doppler_secret("AUTH0_AUDIENCE")
        client_id = AUTH0_TEST_CLIENT_ID or get_doppler_secret("AUTH0_TEST_CLIENT_ID")
        client_secret = AUTH0_TEST_CLIENT_SECRET or get_doppler_secret("AUTH0_TEST_CLIENT_SECRET")
        password = TEST_USER_RULE_MAKER_PASSWORD or get_doppler_secret(
            "TEST_USER_RULE_MAKER_PASSWORD"
        )

        if all([domain, audience, client_id, client_secret, password]):
            self._maker_token = get_auth0_token(
                domain,
                audience,
                client_id,
                client_secret,
                "test-rule-maker@fraud-platform.test",
                password,
            )
        return self._maker_token

    def get_checker_token(self):
        if self._checker_token:
            return self._checker_token

        domain = AUTH0_DOMAIN or get_doppler_secret("AUTH0_DOMAIN")
        audience = AUTH0_AUDIENCE or get_doppler_secret("AUTH0_AUDIENCE")
        client_id = AUTH0_TEST_CLIENT_ID or get_doppler_secret("AUTH0_TEST_CLIENT_ID")
        client_secret = AUTH0_TEST_CLIENT_SECRET or get_doppler_secret("AUTH0_TEST_CLIENT_SECRET")
        password = TEST_USER_RULE_CHECKER_PASSWORD or get_doppler_secret(
            "TEST_USER_RULE_CHECKER_PASSWORD"
        )

        if all([domain, audience, client_id, client_secret, password]):
            self._checker_token = get_auth0_token(
                domain,
                audience,
                client_id,
                client_secret,
                "test-rule-checker@fraud-platform.test",
                password,
            )
        return self._checker_token


class RuleManagementUser(HttpUser):
    """User that performs complete rule management workflow."""

    wait_time = between(1, 3)

    def on_start(self):
        """Get auth tokens on start."""
        self.token_manager = AuthTokenManager.get_tokens()
        self.maker_token = self.token_manager[0]
        self.checker_token = self.token_manager[1]
        self.headers = {
            "Authorization": f"Bearer {self.maker_token}",
            "Content-Type": "application/json",
        }
        self.checker_headers = {
            "Authorization": f"Bearer {self.checker_token}",
            "Content-Type": "application/json",
        }
        self.created_rules = []
        self.created_rulesets = []

    @task(10)
    def list_rules(self):
        """List rules with pagination."""
        page = random.randint(1, 10)
        limit = random.choice([10, 20, 50])
        with self.client.get(
            f"/api/v1/rules?page={page}&limit={limit}",
            headers=self.headers,
            name="/api/v1/rules [list]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(8)
    def list_rulesets(self):
        """List rulesets."""
        with self.client.get(
            "/api/v1/rulesets?limit=20",
            headers=self.headers,
            name="/api/v1/rulesets [list]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(5)
    def get_rule_fields(self):
        """Get rule fields catalog."""
        with self.client.get(
            "/api/v1/rule-fields",
            headers=self.headers,
            name="/api/v1/rule-fields",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(3)
    def create_and_publish_rule(self):
        """Create a rule and optionally publish it."""
        if not self.maker_token or not self.checker_token:
            return

        template = random.choice(rule_templates)
        rule_name = f"LoadTest {template['name']} {int(time.time())} {random.randint(1000, 9999)}"

        # Create rule
        with self.client.post(
            "/api/v1/rules",
            json={
                "rule_name": rule_name,
                "description": f"Load test - {template['name']}",
                "rule_type": template["type"],
            },
            headers=self.headers,
            name="/api/v1/rules [create]",
            catch_response=True,
        ) as response:
            if response.status_code not in [201, 409]:
                response.failure(f"Failed to create rule: {response.status_code}")
                return

            if response.status_code == 201:
                rule_id = response.json().get("rule_id")
                self.created_rules.append(rule_id)

                # Create version
                version_response = self.client.post(
                    f"/api/v1/rules/{rule_id}/versions",
                    json={
                        "condition_tree": template["condition"],
                        "priority": template["priority"],
                        "scope": {"network": ["VISA", "MASTERCARD", "AMEX"]},
                    },
                    headers=self.headers,
                    name="/api/v1/rules/{id}/versions [create]",
                    catch_response=True,
                )

                if version_response.status_code == 201:
                    rule_version_id = version_response.json().get("rule_version_id")

                    # Create ruleset if we don't have one
                    if random.random() < 0.3 or len(self.created_rulesets) == 0:
                        ruleset_name = f"LoadTest AUTH {int(time.time())}"
                        ruleset_response = self.client.post(
                            "/api/v1/rulesets",
                            json={
                                "environment": "local",
                                "region": "LOADTEST",
                                "country": "XX",
                                "rule_type": "AUTH",
                                "name": ruleset_name,
                                "description": "Load test ruleset",
                            },
                            headers=self.headers,
                            name="/api/v1/rulesets [create]",
                            catch_response=True,
                        )

                        if ruleset_response.status_code == 201:
                            ruleset_id = ruleset_response.json().get("ruleset_id")

                            # Create version with rule
                            rs_version_response = self.client.post(
                                f"/api/v1/rulesets/{ruleset_id}/versions",
                                json={"rule_version_ids": [rule_version_id]},
                                headers=self.headers,
                                name="/api/v1/rulesets/{id}/versions [create]",
                                catch_response=True,
                            )

                            if rs_version_response.status_code == 201:
                                rs_version_id = rs_version_response.json().get("ruleset_version_id")
                                self.created_rulesets.append(rs_version_id)

    @task(2)
    def compile_and_approve(self):
        """Compile and approve ruleset versions."""
        if not self.maker_token or not self.checker_token:
            return

        # Find DRAFT versions
        with self.client.get(
            "/api/v1/ruleset-versions?status=DRAFT&limit=5",
            headers=self.headers,
            name="/api/v1/ruleset-versions [list DRAFT]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                return

            versions = response.json().get("items", [])
            if not versions:
                return

            for version in versions[:2]:  # Process max 2 per user
                rs_version_id = version.get("ruleset_version_id")

                # Compile
                compile_response = self.client.post(
                    f"/api/v1/ruleset-versions/{rs_version_id}/compile",
                    headers=self.headers,
                    name="/api/v1/ruleset-versions/{id}/compile",
                    catch_response=True,
                )

                if compile_response.status_code != 200:
                    continue

                # Submit
                submit_response = self.client.post(
                    f"/api/v1/ruleset-versions/{rs_version_id}/submit",
                    json={"idempotency_key": f"submit_{rs_version_id}"},
                    headers=self.headers,
                    name="/api/v1/ruleset-versions/{id}/submit",
                    catch_response=True,
                )

                if submit_response.status_code not in [200, 409]:
                    continue

                # Approve (checker)
                approve_response = self.client.post(
                    f"/api/v1/ruleset-versions/{rs_version_id}/approve",
                    json={"idempotency_key": f"approve_{rs_version_id}"},
                    headers=self.checker_headers,
                    name="/api/v1/ruleset-versions/{id}/approve",
                    catch_response=True,
                )

                if approve_response.status_code == 200:
                    self.client.post(
                        f"/api/v1/ruleset-versions/{rs_version_id}",
                        headers=self.headers,
                        name="/api/v1/ruleset-versions/{id} [verify]",
                    )

    @task(4)
    def read_single_resources(self):
        """Get single rule/ruleset details."""
        if not self.created_rules:
            return

        rule_id = random.choice(self.created_rules)
        with self.client.get(
            f"/api/v1/rules/{rule_id}",
            headers=self.headers,
            name="/api/v1/rules/{id} [get]",
            catch_response=True,
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")


class ReadOnlyUser(HttpUser):
    """User that only performs read operations for high-load testing."""

    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.headers = {"Content-Type": "application/json"}

    @task(5)
    def list_rules(self):
        with self.client.get(
            "/api/v1/rules?limit=20",
            headers=self.headers,
            name="/api/v1/rules [list]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()

    @task(4)
    def list_rulesets(self):
        with self.client.get(
            "/api/v1/rulesets?limit=20",
            headers=self.headers,
            name="/api/v1/rulesets [list]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()

    @task(3)
    def get_rule_fields(self):
        with self.client.get(
            "/api/v1/rule-fields",
            headers=self.headers,
            name="/api/v1/rule-fields",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()

    @task(2)
    def get_manifest(self):
        with self.client.get(
            "/api/v1/ruleset-versions?status=APPROVED&limit=5",
            headers=self.headers,
            name="/api/v1/ruleset-versions [list APPROVED]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    """Initialize on Locust start."""
    if isinstance(environment.runner, MasterRunner):
        print("Locust master initialized")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Log test start."""
    print(f"Starting load test against {BASE_URL}")
    print(f"Time: {datetime.now().isoformat()}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Log test end."""
    print(f"Load test completed at {datetime.now().isoformat()}")
    print(f"Total requests: {environment.stats.total.num_requests}")
    print(f"Total failures: {environment.stats.total.num_failures}")
