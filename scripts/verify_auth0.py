"""Auth0 setup verification script.

Verifies that Auth0 is correctly configured for this project by checking:
1. API (Resource Server) exists with correct audience
2. API has all expected scopes
3. M2M application exists
4. Client grant exists with correct scopes
5. Actions are deployed
6. Trigger bindings are correct

Usage:
    uv run auth0-verify
    # or
    doppler run -- python scripts/verify_auth0.py

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import httpx

# Expected permissions for this project (rule-management)
# As defined in AUTH_MODEL.md
EXPECTED_SCOPES = [
    "rule:create",
    "rule:update",
    "rule:submit",
    "rule:approve",
    "rule:reject",
    "rule:read",
]

# Platform-wide roles (as defined in AUTH_MODEL.md)
EXPECTED_ROLES = [
    "PLATFORM_ADMIN",
    "RULE_MAKER",
    "RULE_CHECKER",
    "RULE_VIEWER",
    "FRAUD_ANALYST",
    "FRAUD_SUPERVISOR",
]


@dataclass
class VerificationResult:
    """Result of a verification check."""

    name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)


class Auth0Verifier:
    """Verifies Auth0 configuration."""

    def __init__(self, domain: str, token: str, audience: str, m2m_name: str):
        self.domain = domain
        self.audience = audience
        self.m2m_name = m2m_name
        self.client = httpx.Client(
            base_url=f"https://{domain}/api/v2/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        self.results: list[VerificationResult] = []

    def verify_api_exists(self) -> VerificationResult:
        """Check if API exists with correct audience."""
        try:
            resp = self.client.get("resource-servers")
            resp.raise_for_status()
            apis = resp.json()

            for api in apis:
                if api.get("identifier") == self.audience:
                    return VerificationResult(
                        name="API Exists",
                        passed=True,
                        message=f"API found: {api.get('name')} ({self.audience})",
                        details=[f"ID: {api.get('id')}"],
                    )

            return VerificationResult(
                name="API Exists",
                passed=False,
                message=f"API with audience '{self.audience}' not found",
                details=[f"Found {len(apis)} APIs, none match expected audience"],
            )
        except Exception as e:
            return VerificationResult(
                name="API Exists",
                passed=False,
                message=f"Error checking API: {e}",
            )

    def verify_api_scopes(self) -> VerificationResult:
        """Check if API has all expected scopes."""
        try:
            resp = self.client.get("resource-servers")
            resp.raise_for_status()
            apis = resp.json()

            for api in apis:
                if api.get("identifier") == self.audience:
                    api_scopes = [s.get("value") for s in api.get("scopes", [])]
                    missing = [s for s in EXPECTED_SCOPES if s not in api_scopes]
                    extra = [s for s in api_scopes if s not in EXPECTED_SCOPES]

                    if missing:
                        return VerificationResult(
                            name="API Scopes",
                            passed=False,
                            message=f"Missing {len(missing)} scope(s)",
                            details=[f"Missing: {', '.join(missing)}"]
                            + ([f"Extra: {', '.join(extra)}"] if extra else []),
                        )

                    return VerificationResult(
                        name="API Scopes",
                        passed=True,
                        message=f"All {len(EXPECTED_SCOPES)} expected scopes present",
                        details=[f"Scopes: {', '.join(api_scopes)}"]
                        + ([f"Extra (OK): {', '.join(extra)}"] if extra else []),
                    )

            return VerificationResult(
                name="API Scopes",
                passed=False,
                message="Cannot check scopes - API not found",
            )
        except Exception as e:
            return VerificationResult(
                name="API Scopes",
                passed=False,
                message=f"Error checking scopes: {e}",
            )

    def verify_roles_exist(self) -> VerificationResult:
        """Check if expected roles exist."""
        try:
            resp = self.client.get("roles")
            resp.raise_for_status()
            roles = resp.json()

            role_names = [r.get("name") for r in roles]
            missing = [r for r in EXPECTED_ROLES if r not in role_names]

            if missing:
                return VerificationResult(
                    name="Roles Exist",
                    passed=False,
                    message=f"Missing {len(missing)} role(s)",
                    details=[f"Missing: {', '.join(missing)}"],
                )

            return VerificationResult(
                name="Roles Exist",
                passed=True,
                message=f"All {len(EXPECTED_ROLES)} expected roles present",
                details=[f"Roles: {', '.join(EXPECTED_ROLES)}"],
            )
        except Exception as e:
            return VerificationResult(
                name="Roles Exist",
                passed=False,
                message=f"Error checking roles: {e}",
            )

    def verify_m2m_app_exists(self) -> VerificationResult:
        """Check if M2M application exists."""
        try:
            resp = self.client.get("clients")
            resp.raise_for_status()
            clients = resp.json()

            for client in clients:
                if client.get("name") == self.m2m_name:
                    app_type = client.get("app_type", "unknown")
                    return VerificationResult(
                        name="M2M App Exists",
                        passed=True,
                        message=f"M2M app found: {self.m2m_name}",
                        details=[f"Client ID: {client.get('client_id')}", f"App Type: {app_type}"],
                    )

            return VerificationResult(
                name="M2M App Exists",
                passed=False,
                message=f"M2M app '{self.m2m_name}' not found",
                details=[f"Found {len(clients)} clients, none match expected name"],
            )
        except Exception as e:
            return VerificationResult(
                name="M2M App Exists",
                passed=False,
                message=f"Error checking M2M app: {e}",
            )

    def verify_client_grant(self) -> VerificationResult:
        """Check if client grant exists for M2M app."""
        try:
            # First find the M2M client ID
            resp = self.client.get("clients")
            resp.raise_for_status()
            clients = resp.json()

            m2m_client_id = None
            for client in clients:
                if client.get("name") == self.m2m_name:
                    m2m_client_id = client.get("client_id")
                    break

            if not m2m_client_id:
                return VerificationResult(
                    name="Client Grant",
                    passed=False,
                    message="Cannot check grant - M2M app not found",
                )

            # Check for grants
            resp = self.client.get("client-grants", params={"client_id": m2m_client_id})
            resp.raise_for_status()
            grants = resp.json()

            for grant in grants:
                if grant.get("audience") == self.audience:
                    grant_scopes = grant.get("scope", [])
                    missing = [s for s in EXPECTED_SCOPES if s not in grant_scopes]

                    if missing:
                        return VerificationResult(
                            name="Client Grant",
                            passed=False,
                            message=f"Grant exists but missing {len(missing)} scope(s)",
                            details=[f"Missing: {', '.join(missing)}"],
                        )

                    return VerificationResult(
                        name="Client Grant",
                        passed=True,
                        message="Client grant exists with all expected scopes",
                        details=[f"Scopes: {', '.join(grant_scopes)}"],
                    )

            return VerificationResult(
                name="Client Grant",
                passed=False,
                message=f"No grant found for audience '{self.audience}'",
            )
        except Exception as e:
            return VerificationResult(
                name="Client Grant",
                passed=False,
                message=f"Error checking client grant: {e}",
            )

    def verify_actions_deployed(self) -> VerificationResult:
        """Check if role injection actions are deployed."""
        try:
            resp = self.client.get("actions/actions")
            resp.raise_for_status()
            data = resp.json()
            actions = data.get("actions", data) if isinstance(data, dict) else data

            # Note: M2M tokens use scopes only, so we only check for the post-login action
            expected_actions = ["Add Roles to Token"]
            found = []
            deployed = []

            for action in actions:
                name = action.get("name", "")
                if name in expected_actions:
                    found.append(name)
                    status = action.get("status", "unknown")
                    if status == "built":
                        deployed.append(name)

            missing = [a for a in expected_actions if a not in found]
            not_deployed = [a for a in found if a not in deployed]

            if missing:
                return VerificationResult(
                    name="Actions Deployed",
                    passed=False,
                    message=f"Missing {len(missing)} action(s)",
                    details=[f"Missing: {', '.join(missing)}"],
                )

            if not_deployed:
                return VerificationResult(
                    name="Actions Deployed",
                    passed=False,
                    message=f"{len(not_deployed)} action(s) not deployed",
                    details=[f"Not deployed: {', '.join(not_deployed)}"],
                )

            return VerificationResult(
                name="Actions Deployed",
                passed=True,
                message=f"All {len(expected_actions)} actions deployed",
                details=[f"Actions: {', '.join(deployed)}"],
            )
        except Exception as e:
            return VerificationResult(
                name="Actions Deployed",
                passed=False,
                message=f"Error checking actions: {e}",
            )

    def verify_trigger_bindings(self) -> VerificationResult:
        """Check if actions are bound to correct triggers."""
        try:
            # Note: M2M tokens use scopes only, so we only check post-login trigger
            triggers_to_check = ["post-login"]
            bound_triggers = []

            for trigger in triggers_to_check:
                resp = self.client.get(f"actions/triggers/{trigger}/bindings")
                resp.raise_for_status()
                data = resp.json()
                bindings = data.get("bindings", data) if isinstance(data, dict) else data

                for binding in bindings:
                    action = binding.get("action", {})
                    action_name = action.get("name", "")
                    if "Roles" in action_name:
                        bound_triggers.append(trigger)
                        break

            missing = [t for t in triggers_to_check if t not in bound_triggers]

            if missing:
                return VerificationResult(
                    name="Trigger Bindings",
                    passed=False,
                    message=f"Missing bindings for {len(missing)} trigger(s)",
                    details=[f"Missing: {', '.join(missing)}"],
                )

            return VerificationResult(
                name="Trigger Bindings",
                passed=True,
                message=f"Actions bound to all {len(triggers_to_check)} triggers",
                details=[f"Triggers: {', '.join(bound_triggers)}"],
            )
        except Exception as e:
            return VerificationResult(
                name="Trigger Bindings",
                passed=False,
                message=f"Error checking trigger bindings: {e}",
            )

    def verify_spa_app_exists(self) -> VerificationResult:
        """Check if SPA application exists (rule-management hosts the SPA)."""
        try:
            spa_name = os.getenv("AUTH0_SPA_APP_NAME", "Fraud Intelligence Portal")
            resp = self.client.get("clients")
            resp.raise_for_status()
            clients = resp.json()

            for client in clients:
                if client.get("name") == spa_name:
                    app_type = client.get("app_type", "unknown")
                    return VerificationResult(
                        name="SPA App Exists",
                        passed=True,
                        message=f"SPA app found: {spa_name}",
                        details=[f"Client ID: {client.get('client_id')}", f"App Type: {app_type}"],
                    )

            return VerificationResult(
                name="SPA App Exists",
                passed=False,
                message=f"SPA app '{spa_name}' not found",
                details=["This is expected if SPA URLs are not configured"],
            )
        except Exception as e:
            return VerificationResult(
                name="SPA App Exists",
                passed=False,
                message=f"Error checking SPA app: {e}",
            )

    def run_all_checks(self) -> list[VerificationResult]:
        """Run all verification checks."""
        self.results = [
            self.verify_api_exists(),
            self.verify_api_scopes(),
            self.verify_roles_exist(),
            self.verify_m2m_app_exists(),
            self.verify_client_grant(),
            self.verify_spa_app_exists(),
            self.verify_actions_deployed(),
            self.verify_trigger_bindings(),
        ]
        return self.results


def print_results(results: list[VerificationResult]) -> bool:
    """Print verification results and return overall pass/fail."""
    print("\n" + "=" * 60)
    print("AUTH0 VERIFICATION RESULTS")
    print("=" * 60 + "\n")

    all_passed = True

    for result in results:
        status = "[PASS]" if result.passed else "[FAIL]"

        print(f"{status} | {result.name}")
        print(f"        {result.message}")
        for detail in result.details:
            print(f"        > {detail}")
        print()

        if not result.passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("[OK] ALL CHECKS PASSED")
    else:
        print("[ERROR] SOME CHECKS FAILED")
        print("\nTo fix issues, re-run the bootstrap:")
        print("  uv run auth0-bootstrap --yes --verbose")
    print("=" * 60 + "\n")

    return all_passed


def main():
    """Main entry point."""
    # Get required environment variables
    mgmt_domain = os.getenv("AUTH0_MGMT_DOMAIN")
    mgmt_client_id = os.getenv("AUTH0_MGMT_CLIENT_ID")
    mgmt_client_secret = os.getenv("AUTH0_MGMT_CLIENT_SECRET")
    audience = os.getenv("AUTH0_AUDIENCE")
    m2m_name = os.getenv("AUTH0_M2M_APP_NAME", "Fraud Rule Management M2M")

    missing = []
    if not mgmt_domain:
        missing.append("AUTH0_MGMT_DOMAIN")
    if not mgmt_client_id:
        missing.append("AUTH0_MGMT_CLIENT_ID")
    if not mgmt_client_secret:
        missing.append("AUTH0_MGMT_CLIENT_SECRET")
    if not audience:
        missing.append("AUTH0_AUDIENCE")

    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        print("\nRun with Doppler:")
        print("  doppler run -- python scripts/verify_auth0.py")
        sys.exit(1)

    print("Verifying Auth0 configuration...")
    print(f"  Domain: {mgmt_domain}")
    print(f"  Audience: {audience}")
    print(f"  M2M App: {m2m_name}")

    # Get management token
    try:
        token_resp = httpx.post(
            f"https://{mgmt_domain}/oauth/token",
            json={
                "client_id": mgmt_client_id,
                "client_secret": mgmt_client_secret,
                "audience": f"https://{mgmt_domain}/api/v2/",
                "grant_type": "client_credentials",
            },
            timeout=30.0,
        )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]
    except Exception as e:
        print(f"ERROR: Failed to get management token: {e}")
        sys.exit(1)

    # Run verification
    verifier = Auth0Verifier(mgmt_domain, token, audience, m2m_name)
    results = verifier.run_all_checks()

    all_passed = print_results(results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
