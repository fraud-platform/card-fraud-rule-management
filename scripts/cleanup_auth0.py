"""Auth0 cleanup script - Delete all automated resources.

This script deletes all Auth0 resources EXCEPT:
- Management M2M Application (used for bootstrap scripts)
- Google OAuth Connection (manually configured)
- Username-Password-Authentication Connection (for test users)

Use this to start fresh before re-running bootstrap scripts.

Required environment variables:
- AUTH0_MGMT_DOMAIN
- AUTH0_MGMT_CLIENT_ID
- AUTH0_MGMT_CLIENT_SECRET

Usage:
    uv run auth0-cleanup --yes --verbose

    # Or with Doppler
    doppler run --project card-fraud-rule-management --config local -- python scripts/cleanup_auth0.py --yes --verbose
"""

from __future__ import annotations

import argparse
import os
import time

import httpx

# =============================================================================
# PRESERVE LIST - These will NEVER be deleted
# =============================================================================

# System/Management apps to preserve (exact names)
PRESERVE_CLIENTS = [
    "Auth0 Management API (Test Application)",  # System app
    "Default App",  # System app created by Auth0
    "All Applications",  # System
    "Auth0 Management Automation",  # Our Management M2M for bootstrap scripts
]

# System APIs to preserve
PRESERVE_APIS = [
    "Auth0 Management API",  # System API
]

# =============================================================================
# DELETE LIST - Platform resources created by bootstrap scripts
# =============================================================================

# Old roles from previous auth model (to be deleted during migration)
OLD_ROLES_TO_DELETE = [
    "ADMIN",
    "MAKER",
    "CHECKER",
]

# Current platform roles (deleted for fresh setup, recreated by bootstrap)
PLATFORM_ROLES_TO_DELETE = [
    "PLATFORM_ADMIN",
    "RULE_MAKER",
    "RULE_CHECKER",
    "RULE_VIEWER",
    "FRAUD_ANALYST",
    "FRAUD_SUPERVISOR",
]

# APIs created by our platform (deleted for fresh setup)
PLATFORM_APIS = [
    "https://fraud-rule-management-api",
    "https://fraud-rule-engine-api",
    "https://fraud-transaction-management-api",
]

# M2M Apps created by our platform (exact names - deleted for fresh setup)
PLATFORM_M2M_APPS = [
    "Fraud Rule Management M2M",
    "Fraud Rule Engine M2M",
    "Fraud Transaction Management M2M",
]

# SPA Apps created by our platform (exact names - deleted for fresh setup)
PLATFORM_SPA_APPS = [
    "Fraud Intelligence Portal",
    "Fraud Governance UI",  # Old SPA name (legacy cleanup)
]

# Actions created by our platform
PLATFORM_ACTIONS = [
    "Add Roles to Token",
    "Add Roles to M2M Token",
]

# Test user email domains (users matching these will be deleted)
TEST_USER_DOMAINS = [
    "fraud-platform.test",  # Current test user domain
    "fraud-governance.test",  # Old test user domain (legacy cleanup)
]


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


class Auth0Cleanup:
    def __init__(self, *, domain: str, token: str, verbose: bool = False):
        self._domain = domain
        self._verbose = verbose
        self._client = httpx.Client(
            base_url=f"https://{domain}/api/v2/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        self._deleted_count = 0

    def close(self):
        self._client.close()

    def _request(self, method: str, path: str, **kwargs):
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                resp = self._client.request(method, path, **kwargs)
                if resp.status_code == 429:
                    time.sleep(1.0 * attempt)
                    continue
                if resp.status_code == 204:
                    return None
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError:
                if attempt == max_attempts:
                    raise
                time.sleep(0.5)
        return None

    def delete_roles(self) -> int:
        """Delete platform roles (old and current)."""
        count = 0
        all_roles_to_delete = OLD_ROLES_TO_DELETE + PLATFORM_ROLES_TO_DELETE

        roles = self._request("GET", "roles", params={"per_page": 100})
        if not roles:
            return 0

        for role in roles:
            role_name = role.get("name", "")
            role_id = role.get("id")

            if role_name in all_roles_to_delete:
                try:
                    self._request("DELETE", f"roles/{role_id}")
                    if self._verbose:
                        print(f"  Deleted role: {role_name}")
                    count += 1
                except Exception as e:
                    print(f"  Failed to delete role {role_name}: {e}")

        return count

    def delete_platform_apis(self) -> int:
        """Delete APIs created by our platform."""
        count = 0
        apis = self._request("GET", "resource-servers", params={"per_page": 100})
        if not apis:
            return 0

        for api in apis:
            identifier = api.get("identifier", "")
            api_name = api.get("name", "")
            api_id = api.get("id")

            # Skip system APIs
            if api_name in PRESERVE_APIS:
                continue

            # Delete platform APIs
            if identifier in PLATFORM_APIS:
                try:
                    self._request("DELETE", f"resource-servers/{api_id}")
                    if self._verbose:
                        print(f"  Deleted API: {api_name} ({identifier})")
                    count += 1
                except Exception as e:
                    print(f"  Failed to delete API {api_name}: {e}")

        return count

    def delete_platform_clients(self) -> int:
        """Delete M2M and SPA apps created by our platform."""
        count = 0
        clients = self._request("GET", "clients", params={"per_page": 100})
        if not clients:
            return 0

        apps_to_delete = PLATFORM_M2M_APPS + PLATFORM_SPA_APPS

        for client in clients:
            client_name = client.get("name", "")
            client_id = client.get("client_id")

            # Skip preserved apps (system + management)
            if client_name in PRESERVE_CLIENTS:
                if self._verbose:
                    print(f"  Preserving: {client_name}")
                continue

            # Delete platform apps (exact name match)
            if client_name in apps_to_delete:
                try:
                    self._request("DELETE", f"clients/{client_id}")
                    if self._verbose:
                        print(f"  Deleted client: {client_name}")
                    count += 1
                except Exception as e:
                    print(f"  Failed to delete client {client_name}: {e}")

        return count

    def delete_platform_actions(self) -> int:
        """Delete Actions created by our platform."""
        count = 0
        result = self._request("GET", "actions/actions", params={"per_page": 100})
        actions = result.get("actions", []) if isinstance(result, dict) else result or []

        for action in actions:
            action_name = action.get("name", "")
            action_id = action.get("id")

            if action_name in PLATFORM_ACTIONS:
                try:
                    self._request("DELETE", f"actions/actions/{action_id}")
                    if self._verbose:
                        print(f"  Deleted action: {action_name}")
                    count += 1
                except Exception as e:
                    print(f"  Failed to delete action {action_name}: {e}")

        return count

    def delete_client_grants(self) -> int:
        """Delete client grants for platform APIs."""
        count = 0
        grants = self._request("GET", "client-grants", params={"per_page": 100})
        if not grants:
            return 0

        for grant in grants:
            audience = grant.get("audience", "")
            grant_id = grant.get("id")

            if audience in PLATFORM_APIS:
                try:
                    self._request("DELETE", f"client-grants/{grant_id}")
                    if self._verbose:
                        print(f"  Deleted grant for: {audience}")
                    count += 1
                except Exception as e:
                    print(f"  Failed to delete grant: {e}")

        return count

    def delete_test_users(self) -> int:
        """Delete test users created for automation (matching TEST_USER_DOMAINS)."""
        count = 0

        for domain in TEST_USER_DOMAINS:
            users = self._request(
                "GET",
                "users",
                params={"per_page": 100, "q": f"email:*@{domain}", "search_engine": "v3"},
            )

            if not users:
                continue

            for user in users:
                user_email = user.get("email", "")
                user_id = user.get("user_id")

                # Verify domain match (defensive check)
                if domain in user_email:
                    try:
                        self._request("DELETE", f"users/{user_id}")
                        if self._verbose:
                            print(f"  Deleted test user: {user_email}")
                        count += 1
                    except Exception as e:
                        print(f"  Failed to delete user {user_email}: {e}")

        return count

    def run_cleanup(self) -> dict:
        """Run full cleanup and return counts."""
        results = {}

        print("\n[1/6] Deleting client grants...")
        results["grants"] = self.delete_client_grants()

        print("[2/6] Deleting platform Actions...")
        results["actions"] = self.delete_platform_actions()

        print("[3/6] Deleting platform clients (M2M + SPA)...")
        results["clients"] = self.delete_platform_clients()

        print("[4/6] Deleting platform APIs...")
        results["apis"] = self.delete_platform_apis()

        print("[5/6] Deleting roles...")
        results["roles"] = self.delete_roles()

        print("[6/6] Deleting test users...")
        results["users"] = self.delete_test_users()

        return results


def _get_management_token(*, domain: str, client_id: str, client_secret: str) -> str:
    resp = httpx.post(
        f"https://{domain}/oauth/token",
        timeout=30.0,
        json={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "audience": f"https://{domain}/api/v2/",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean up Auth0 resources (preserves Management M2M app)"
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show details")
    args = parser.parse_args()

    domain = _required_env("AUTH0_MGMT_DOMAIN")
    client_id = _required_env("AUTH0_MGMT_CLIENT_ID")
    client_secret = _required_env("AUTH0_MGMT_CLIENT_SECRET")

    print("=" * 60)
    print("AUTH0 CLEANUP SCRIPT")
    print("=" * 60)
    print(f"\nTenant: {domain}")
    print("\nThis will DELETE:")
    print("  - Old roles (ADMIN, MAKER, CHECKER)")
    print("  - New roles (PLATFORM_ADMIN, RULE_MAKER, etc.)")
    print("  - Platform APIs (rule-management, rule-engine, transaction-management)")
    print("  - Platform M2M Apps")
    print("  - Platform SPA App (Fraud Intelligence Portal)")
    print("  - Platform Actions")
    print("  - Test users (*@fraud-platform.test)")
    print("\nThis will PRESERVE:")
    print("  - Management M2M Application")
    print("  - Google OAuth Connection")
    print("  - Username-Password-Authentication Connection")
    print("  - Auth0 Management API (system)")

    if not args.yes:
        print("\nContinue? [y/N] ", end="")
        answer = input().strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    print("\nGetting management token...")
    token = _get_management_token(
        domain=domain,
        client_id=client_id,
        client_secret=client_secret,
    )

    cleanup = Auth0Cleanup(domain=domain, token=token, verbose=args.verbose)
    try:
        results = cleanup.run_cleanup()
    finally:
        cleanup.close()

    print("\n" + "=" * 60)
    print("CLEANUP COMPLETE")
    print("=" * 60)
    print(f"  Grants deleted:  {results['grants']}")
    print(f"  Actions deleted: {results['actions']}")
    print(f"  Clients deleted: {results['clients']}")
    print(f"  APIs deleted:    {results['apis']}")
    print(f"  Roles deleted:   {results['roles']}")
    print(f"  Users deleted:   {results['users']}")
    print("\nYou can now run the bootstrap scripts to recreate everything fresh:")
    print("  uv run auth0-bootstrap --yes --verbose")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
