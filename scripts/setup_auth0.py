"""Auth0 bootstrap automation (idempotent) - Card Fraud Platform.

This script is the CENTRAL HUB for Auth0 configuration. It provisions:
- Resource Server (API) with permissions (Auth0 RBAC)
- Platform-wide roles (PLATFORM_ADMIN, RULE_MAKER, RULE_CHECKER, etc.)
- Role-to-permission assignments
- SPA application (Fraud Intelligence Portal)
- M2M application for testing
- Actions to inject roles into tokens
- Test users for Playwright automation

See AUTH_MODEL.md for the complete authentication and authorization specification.

Required environment variables:
- AUTH0_MGMT_DOMAIN              e.g. dev-xxxx.us.auth0.com
- AUTH0_MGMT_CLIENT_ID           Management M2M client ID
- AUTH0_MGMT_CLIENT_SECRET       Management M2M client secret
- AUTH0_AUDIENCE                 e.g. https://fraud-rule-management-api

Optional environment variables:
- AUTH0_API_NAME                 default: Fraud Rule Management API
- AUTH0_SPA_APP_NAME             default: Fraud Intelligence Portal
- AUTH0_M2M_APP_NAME             default: Fraud Rule Management M2M
- AUTH0_SPA_CALLBACK_URLS        comma-separated
- AUTH0_SPA_ALLOWED_ORIGINS      comma-separated
- AUTH0_SPA_ALLOWED_LOGOUT_URLS  comma-separated

Test user passwords (optional - for Playwright automation):
- TEST_USER_PLATFORM_ADMIN_PASSWORD
- TEST_USER_RULE_MAKER_PASSWORD
- TEST_USER_RULE_CHECKER_PASSWORD
- TEST_USER_FRAUD_ANALYST_PASSWORD
- TEST_USER_FRAUD_SUPERVISOR_PASSWORD

Usage:
  uv run auth0-bootstrap --yes --verbose

Notes:
- This script avoids printing secrets.
- It is designed to be safe to re-run (idempotent).
- Run auth0-cleanup first if you want to start fresh.
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import subprocess
import time
from dataclasses import dataclass

import httpx

# =============================================================================
# PASSWORD GENERATION AND DOPPLER SYNC
# =============================================================================


def generate_secure_password(length: int = 24) -> str:
    """Generate a secure random password for test users."""
    # Use a mix of letters, digits, and safe special characters
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    # Ensure at least one of each type
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    # Fill the rest randomly
    password.extend(secrets.choice(alphabet) for _ in range(length - 4))
    # Shuffle to randomize position of guaranteed characters
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def sync_secrets_to_doppler(
    secrets_dict: dict[str, str],
    *,
    project: str = "card-fraud-rule-management",
    config: str = "local",
    verbose: bool = False,
) -> bool:
    """Sync secrets to Doppler using CLI."""
    if not secrets_dict:
        return True

    try:
        # Build the doppler secrets set command
        cmd = ["doppler", "secrets", "set", "--project", project, "--config", config]
        for key, value in secrets_dict.items():
            cmd.append(f"{key}={value}")

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)

        if result.returncode != 0:
            print(f"  Warning: Failed to sync to Doppler: {result.stderr}")
            return False

        if verbose:
            print(f"  Synced {len(secrets_dict)} secret(s) to Doppler ({project}/{config})")
        return True
    except subprocess.TimeoutExpired:
        print("  Warning: Doppler sync timed out")
        return False
    except FileNotFoundError:
        print("  Warning: Doppler CLI not found - skipping secret sync")
        return False
    except Exception as e:
        print(f"  Warning: Doppler sync error: {e}")
        return False


# =============================================================================
# PERMISSIONS (API Scopes) - As defined in AUTH_MODEL.md
# =============================================================================

# Rule Management API permissions (unified - covers rules, rulesets, and rule_fields)
RULE_MANAGEMENT_PERMISSIONS: list[dict[str, str]] = [
    # Rule permissions
    {"value": "rule:create", "description": "Create new rules"},
    {"value": "rule:update", "description": "Modify rule drafts"},
    {"value": "rule:submit", "description": "Submit rules for approval"},
    {"value": "rule:approve", "description": "Approve rules"},
    {"value": "rule:reject", "description": "Reject rules"},
    {"value": "rule:read", "description": "View rules"},
    # RuleSet permissions
    {"value": "ruleset:create", "description": "Create new rulesets"},
    {"value": "ruleset:update", "description": "Modify ruleset drafts"},
    {"value": "ruleset:submit", "description": "Submit rulesets for approval"},
    {"value": "ruleset:approve", "description": "Approve rulesets (triggers publishing)"},
    {"value": "ruleset:reject", "description": "Reject rulesets"},
    {"value": "ruleset:activate", "description": "Activate approved rulesets"},
    {"value": "ruleset:compile", "description": "Compile rulesets to AST"},
    {"value": "ruleset:read", "description": "View rulesets"},
    # RuleField permissions
    {"value": "rule_field:create", "description": "Create rule fields"},
    {"value": "rule_field:update", "description": "Modify rule fields"},
    {"value": "rule_field:delete", "description": "Delete rule field metadata"},
    {"value": "rule_field:read", "description": "View rule fields"},
]

# Transaction Management API permissions (created here for shared roles)
TRANSACTION_MANAGEMENT_PERMISSIONS: list[dict[str, str]] = [
    {"value": "txn:view", "description": "View transactions"},
    {"value": "txn:comment", "description": "Add analyst comments"},
    {"value": "txn:flag", "description": "Flag suspicious activity"},
    {"value": "txn:recommend", "description": "Recommend action"},
    {"value": "txn:approve", "description": "Approve transaction"},
    {"value": "txn:block", "description": "Block transaction"},
    {"value": "txn:override", "description": "Override prior decision"},
]

# Use Rule Management permissions as default for this API
DEFAULT_SCOPES = RULE_MANAGEMENT_PERMISSIONS

# =============================================================================
# ROLES - As defined in AUTH_MODEL.md
# =============================================================================

# Platform-wide roles (created by this script, used by all projects)
PLATFORM_ROLES: list[tuple[str, str]] = [
    ("PLATFORM_ADMIN", "Platform administrator with full access to all systems"),
    ("RULE_MAKER", "Create and edit rule drafts in Rule Management"),
    ("RULE_CHECKER", "Review and approve rules in Rule Management"),
    ("RULE_VIEWER", "Read-only access to rules for audit and compliance"),
    ("FRAUD_ANALYST", "Analyze fraud alerts and recommend actions"),
    ("FRAUD_SUPERVISOR", "Final decision authority for fraud cases"),
]

# =============================================================================
# ROLE-TO-PERMISSION MAPPING - As defined in AUTH_MODEL.md
# =============================================================================

# Maps role names to their permissions for each API
ROLE_PERMISSIONS = {
    # Rule Management API permissions - PLATFORM_ADMIN gets everything
    "PLATFORM_ADMIN": [
        # Rule permissions
        "rule:create",
        "rule:update",
        "rule:submit",
        "rule:approve",
        "rule:reject",
        "rule:read",
        # RuleSet permissions
        "ruleset:create",
        "ruleset:update",
        "ruleset:submit",
        "ruleset:approve",
        "ruleset:reject",
        "ruleset:activate",
        "ruleset:compile",
        "ruleset:read",
        # RuleField permissions
        "rule_field:create",
        "rule_field:update",
        "rule_field:delete",
        "rule_field:read",
        # Transaction permissions
        "txn:view",
        "txn:comment",
        "txn:flag",
        "txn:recommend",
        "txn:approve",
        "txn:block",
        "txn:override",
    ],
    # RULE_MAKER: Create and edit rules, rulesets, and rule_fields
    "RULE_MAKER": [
        "rule:create",
        "rule:update",
        "rule:submit",
        "rule:read",
        "ruleset:create",
        "ruleset:update",
        "ruleset:submit",
        "ruleset:read",
        "rule_field:create",
        "rule_field:update",
        "rule_field:read",
    ],
    # RULE_CHECKER: Approve/reject rules and rulesets
    "RULE_CHECKER": [
        "rule:approve",
        "rule:reject",
        "rule:read",
        "ruleset:approve",
        "ruleset:reject",
        "ruleset:activate",
        "ruleset:read",
    ],
    # RULE_VIEWER: Read-only access
    "RULE_VIEWER": [
        "rule:read",
        "ruleset:read",
        "rule_field:read",
    ],
    # Transaction permissions for fraud team
    "FRAUD_ANALYST": ["txn:view", "txn:comment", "txn:flag", "txn:recommend"],
    "FRAUD_SUPERVISOR": ["txn:view", "txn:approve", "txn:block", "txn:override"],
}

# =============================================================================
# TEST USERS - For Playwright automation (as defined in AUTH_MODEL.md)
# =============================================================================

TEST_USERS = [
    {
        "email": "test-platform-admin@fraud-platform.test",
        "name": "Test Platform Admin",
        "password_env": "TEST_USER_PLATFORM_ADMIN_PASSWORD",
        "roles": ["PLATFORM_ADMIN"],
    },
    {
        "email": "test-rule-maker@fraud-platform.test",
        "name": "Test Rule Maker",
        "password_env": "TEST_USER_RULE_MAKER_PASSWORD",
        "roles": ["RULE_MAKER"],
    },
    {
        "email": "test-rule-checker@fraud-platform.test",
        "name": "Test Rule Checker",
        "password_env": "TEST_USER_RULE_CHECKER_PASSWORD",
        "roles": ["RULE_CHECKER"],
    },
    {
        "email": "test-rule-maker-checker@fraud-platform.test",
        "name": "Test Rule Maker and Checker",
        "password_env": "TEST_USER_RULE_MAKER_PASSWORD",  # Same password as maker
        "roles": ["RULE_MAKER", "RULE_CHECKER"],
    },
    {
        "email": "test-fraud-analyst@fraud-platform.test",
        "name": "Test Fraud Analyst",
        "password_env": "TEST_USER_FRAUD_ANALYST_PASSWORD",
        "roles": ["FRAUD_ANALYST"],
    },
    {
        "email": "test-fraud-supervisor@fraud-platform.test",
        "name": "Test Fraud Supervisor",
        "password_env": "TEST_USER_FRAUD_SUPERVISOR_PASSWORD",
        "roles": ["FRAUD_SUPERVISOR"],
    },
]


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    mgmt_domain: str
    mgmt_client_id: str
    mgmt_client_secret: str
    audience: str

    api_name: str
    spa_name: str
    m2m_name: str

    spa_callbacks: list[str]
    spa_origins: list[str]
    spa_logout_urls: list[str]

    m2m_default_roles: list[str]


class Auth0Mgmt:
    def __init__(self, *, domain: str, token: str, timeout_s: float = 30.0, verbose: bool = False):
        self._domain = domain
        self._verbose = verbose
        self._client = httpx.Client(
            base_url=f"https://{domain}/api/v2/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_s,
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self, method: str, path: str, *, params: dict | None = None, json: dict | list | None = None
    ):
        # Conservative retry policy: handle transient 429/5xx.
        max_attempts = 6
        base_sleep = 0.8
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self._client.request(method, path, params=params, json=json)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt == max_attempts:
                    raise
                time.sleep(base_sleep * attempt)
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt == max_attempts:
                    resp.raise_for_status()
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        sleep_s = float(retry_after)
                    except ValueError:
                        sleep_s = base_sleep * attempt
                else:
                    sleep_s = base_sleep * attempt
                time.sleep(sleep_s)
                continue

            # Non-retriable
            resp.raise_for_status()
            if resp.status_code == 204:
                return None
            return resp.json()

        # Should not reach here, but keep mypy happy.
        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected request retry state")

    def find_resource_server_by_identifier(self, identifier: str) -> dict | None:
        # Auth0 supports filtering by identifier.
        results = self._request("GET", "resource-servers", params={"identifier": identifier})
        if isinstance(results, list) and results:
            for rs in results:
                if rs.get("identifier") == identifier:
                    return rs
        return None

    def create_resource_server(
        self, *, name: str, identifier: str, scopes: list[dict[str, str]]
    ) -> dict:
        return self._request(
            "POST",
            "resource-servers",
            json={
                "name": name,
                "identifier": identifier,
                "scopes": scopes,
                "signing_alg": "RS256",
                "allow_offline_access": True,
                "token_lifetime": 7200,
                "token_lifetime_for_web": 7200,
                # Enable RBAC so role assignment matters.
                "enforce_policies": True,
                "token_dialect": "access_token_authz",
            },
        )

    def update_resource_server(
        self, *, resource_server_id: str, name: str, scopes: list[dict[str, str]]
    ) -> dict:
        return self._request(
            "PATCH",
            f"resource-servers/{resource_server_id}",
            json={
                "name": name,
                "scopes": scopes,
                "allow_offline_access": True,
                "enforce_policies": True,
                "token_dialect": "access_token_authz",
            },
        )

    def list_roles(self, *, page: int = 0, per_page: int = 50) -> list[dict]:
        roles = self._request("GET", "roles", params={"page": page, "per_page": per_page})
        return roles if isinstance(roles, list) else []

    def find_role_by_name(self, name: str) -> dict | None:
        page = 0
        while True:
            roles = self.list_roles(page=page)
            if not roles:
                return None
            for role in roles:
                if role.get("name") == name:
                    return role
            if len(roles) < 50:
                return None
            page += 1

    def create_role(self, *, name: str, description: str) -> dict:
        return self._request("POST", "roles", json={"name": name, "description": description})

    def update_role(self, *, role_id: str, description: str) -> dict:
        return self._request("PATCH", f"roles/{role_id}", json={"description": description})

    def list_clients(self, *, page: int = 0, per_page: int = 50) -> list[dict]:
        clients = self._request(
            "GET",
            "clients",
            params={"page": page, "per_page": per_page, "fields": "client_id,name,app_type"},
        )
        return clients if isinstance(clients, list) else []

    def find_client_by_name(self, name: str) -> dict | None:
        page = 0
        while True:
            clients = self.list_clients(page=page)
            if not clients:
                return None
            for client in clients:
                if client.get("name") == name:
                    return client
            if len(clients) < 50:
                return None
            page += 1

    def create_client(self, *, name: str, app_type: str, payload: dict) -> dict:
        body = {"name": name, "app_type": app_type, **payload}
        return self._request("POST", "clients", json=body)

    def update_client(self, *, client_id: str, payload: dict) -> dict:
        return self._request("PATCH", f"clients/{client_id}", json=payload)

    def list_client_grants(self, *, client_id: str) -> list[dict]:
        grants = self._request("GET", "client-grants", params={"client_id": client_id})
        return grants if isinstance(grants, list) else []

    def create_client_grant(self, *, client_id: str, audience: str, scope: list[str]) -> dict:
        return self._request(
            "POST",
            "client-grants",
            json={"client_id": client_id, "audience": audience, "scope": scope},
        )

    def update_client_grant(self, *, grant_id: str, scope: list[str]) -> dict:
        return self._request("PATCH", f"client-grants/{grant_id}", json={"scope": scope})

    def list_actions(self, *, page: int = 0, per_page: int = 50) -> list[dict]:
        result = self._request(
            "GET", "actions/actions", params={"page": page, "per_page": per_page}
        )
        # Auth0 returns {"actions": [...], "total": N, "per_page": N, "page": N}
        if isinstance(result, dict) and "actions" in result:
            return result["actions"]
        return result if isinstance(result, list) else []

    def find_action_by_name(self, name: str) -> dict | None:
        page = 0
        while True:
            actions = self.list_actions(page=page)
            if not actions:
                return None
            for action in actions:
                if action.get("name") == name:
                    return action
            if len(actions) < 50:
                return None
            page += 1

    def _trigger_version(self, trigger_id: str) -> str:
        # Auth0 trigger versions vary by trigger type
        # post-login uses v3, credentials-exchange uses v2
        if trigger_id == "credentials-exchange":
            return "v2"
        return "v3"

    def create_action(
        self, *, name: str, trigger_id: str, code: str, runtime: str = "node18"
    ) -> dict:
        return self._request(
            "POST",
            "actions/actions",
            json={
                "name": name,
                "supported_triggers": [
                    {"id": trigger_id, "version": self._trigger_version(trigger_id)}
                ],
                "code": code,
                "runtime": runtime,
                "secrets": [],
            },
        )

    def update_action(
        self, *, action_id: str, code: str, trigger_id: str, runtime: str = "node18"
    ) -> dict:
        return self._request(
            "PATCH",
            f"actions/actions/{action_id}",
            json={
                "supported_triggers": [
                    {"id": trigger_id, "version": self._trigger_version(trigger_id)}
                ],
                "code": code,
                "runtime": runtime,
                "secrets": [],
            },
        )

    def deploy_action(self, *, action_id: str) -> None:
        self._request("POST", f"actions/actions/{action_id}/deploy")

    def get_trigger_bindings(self, *, trigger_id: str) -> list[dict]:
        result = self._request("GET", f"actions/triggers/{trigger_id}/bindings")
        # Auth0 returns {"bindings": [...], "total": N}
        if isinstance(result, dict) and "bindings" in result:
            return result["bindings"]
        return result if isinstance(result, list) else []

    def set_trigger_bindings(self, *, trigger_id: str, bindings: list[dict]) -> None:
        # Auth0 expects {"bindings": [...]}
        self._request(
            "PATCH", f"actions/triggers/{trigger_id}/bindings", json={"bindings": bindings}
        )

    # -------------------------------------------------------------------------
    # User Management (for test users)
    # -------------------------------------------------------------------------

    def find_user_by_email(self, email: str) -> dict | None:
        """Find a user by email address."""
        users = self._request(
            "GET",
            "users",
            params={"q": f'email:"{email}"', "search_engine": "v3"},
        )
        if users and isinstance(users, list):
            for user in users:
                if user.get("email") == email:
                    return user
        return None

    def create_user(self, *, email: str, name: str, password: str, connection: str) -> dict:
        """Create a new user."""
        return self._request(
            "POST",
            "users",
            json={
                "email": email,
                "name": name,
                "password": password,
                "connection": connection,
                "email_verified": True,  # Skip email verification for test users
            },
        )

    def assign_roles_to_user(self, *, user_id: str, role_ids: list[str]) -> None:
        """Assign roles to a user."""
        self._request(
            "POST",
            f"users/{user_id}/roles",
            json={"roles": role_ids},
        )

    def get_user_roles(self, *, user_id: str) -> list[dict]:
        """Get roles assigned to a user."""
        roles = self._request("GET", f"users/{user_id}/roles")
        return roles if isinstance(roles, list) else []

    # -------------------------------------------------------------------------
    # Role Permissions (for Auth0 RBAC)
    # -------------------------------------------------------------------------

    def get_role_permissions(self, *, role_id: str) -> list[dict]:
        """Get permissions assigned to a role."""
        perms = self._request("GET", f"roles/{role_id}/permissions")
        return perms if isinstance(perms, list) else []

    def assign_permissions_to_role(self, *, role_id: str, permissions: list[dict]) -> None:
        """Assign permissions to a role.

        permissions: list of {"resource_server_identifier": "...", "permission_name": "..."}
        """
        if not permissions:
            return
        self._request(
            "POST",
            f"roles/{role_id}/permissions",
            json={"permissions": permissions},
        )


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
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise SystemExit("Auth0 token response missing access_token")
    return token


def _action_code_post_login(audience: str) -> str:
    # Keep JS minimal and deterministic.
    return (
        "exports.onExecutePostLogin = async (event, api) => {\n"
        f"  const namespace = {audience!r};\n"
        "  const roles = (event.authorization && event.authorization.roles) ? event.authorization.roles : [];\n"
        "  api.accessToken.setCustomClaim(`${namespace}/roles`, roles);\n"
        "};\n"
    )


def _action_code_credentials_exchange(audience: str, m2m_roles: list[str]) -> str:
    roles_js = str(m2m_roles)
    return (
        "exports.onExecuteCredentialsExchange = async (event, api) => {\n"
        f"  const namespace = {audience!r};\n"
        f"  api.accessToken.setCustomClaim(`${{namespace}}/roles`, {roles_js});\n"
        "};\n"
    )


def ensure_resource_server(
    mgmt: Auth0Mgmt, *, identifier: str, name: str, scopes: list[dict[str, str]], verbose: bool
) -> dict:
    existing = mgmt.find_resource_server_by_identifier(identifier)
    if not existing:
        created = mgmt.create_resource_server(name=name, identifier=identifier, scopes=scopes)
        if verbose:
            print(f"Created resource server: {created.get('id')} ({identifier})")
        return created

    updated = mgmt.update_resource_server(
        resource_server_id=existing["id"], name=name, scopes=scopes
    )
    if verbose:
        print(f"Updated resource server: {updated.get('id')} ({identifier})")
    return updated


def ensure_roles(mgmt: Auth0Mgmt, *, roles: list[tuple[str, str]], verbose: bool) -> list[dict]:
    out: list[dict] = []
    for role_name, description in roles:
        existing = mgmt.find_role_by_name(role_name)
        if not existing:
            created = mgmt.create_role(name=role_name, description=description)
            if verbose:
                print(f"Created role: {created.get('id')} ({role_name})")
            out.append(created)
            continue

        updated = mgmt.update_role(role_id=existing["id"], description=description)
        if verbose:
            print(f"Updated role: {updated.get('id')} ({role_name})")
        out.append(updated)
    return out


def ensure_spa_client(
    mgmt: Auth0Mgmt,
    *,
    name: str,
    callbacks: list[str],
    origins: list[str],
    logout_urls: list[str],
    verbose: bool,
) -> dict:
    existing = mgmt.find_client_by_name(name)

    payload = {
        "app_type": "spa",
        # SPA best-practice: no client secret.
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "callbacks": callbacks,
        "allowed_logout_urls": logout_urls,
        "web_origins": origins,
        "allowed_origins": origins,
        "oidc_conformant": True,
        "is_first_party": True,
    }

    if not existing:
        created = mgmt.create_client(name=name, app_type="spa", payload=payload)
        if verbose:
            print(f"Created SPA client: {created.get('client_id')} ({name})")
        return created

    updated = mgmt.update_client(client_id=existing["client_id"], payload=payload)
    if verbose:
        print(f"Updated SPA client: {existing.get('client_id')} ({name})")
    return updated


def ensure_m2m_client(mgmt: Auth0Mgmt, *, name: str, verbose: bool) -> dict:
    existing = mgmt.find_client_by_name(name)

    payload = {
        "app_type": "non_interactive",
        "grant_types": ["client_credentials"],
        "token_endpoint_auth_method": "client_secret_post",
        "oidc_conformant": True,
        "is_first_party": True,
    }

    if not existing:
        created = mgmt.create_client(name=name, app_type="non_interactive", payload=payload)
        if verbose:
            print(f"Created M2M client: {created.get('client_id')} ({name})")
        return created

    updated = mgmt.update_client(client_id=existing["client_id"], payload=payload)
    if verbose:
        print(f"Updated M2M client: {existing.get('client_id')} ({name})")
    return updated


def ensure_client_grant(
    mgmt: Auth0Mgmt, *, client_id: str, audience: str, scopes: list[str], verbose: bool
) -> dict:
    grants = mgmt.list_client_grants(client_id=client_id)
    existing = None
    for grant in grants:
        if grant.get("audience") == audience:
            existing = grant
            break

    if not existing:
        created = mgmt.create_client_grant(client_id=client_id, audience=audience, scope=scopes)
        if verbose:
            print(f"Created client grant: {created.get('id')} (client={client_id})")
        return created

    updated = mgmt.update_client_grant(grant_id=existing["id"], scope=scopes)
    if verbose:
        print(f"Updated client grant: {updated.get('id')} (client={client_id})")
    return updated


def ensure_action_and_binding(
    mgmt: Auth0Mgmt,
    *,
    action_name: str,
    trigger_id: str,
    code: str,
    verbose: bool,
) -> dict:
    existing = mgmt.find_action_by_name(action_name)
    if not existing:
        created = mgmt.create_action(name=action_name, trigger_id=trigger_id, code=code)
        mgmt.deploy_action(action_id=created["id"])
        action = created
        if verbose:
            print(f"Created+deployed action: {action.get('id')} ({action_name})")
    else:
        updated = mgmt.update_action(action_id=existing["id"], trigger_id=trigger_id, code=code)
        mgmt.deploy_action(action_id=existing["id"])
        action = updated
        if verbose:
            print(f"Updated+deployed action: {existing.get('id')} ({action_name})")

    bindings = mgmt.get_trigger_bindings(trigger_id=trigger_id)
    # Auth0 returns bindings with {"action": {"id": "...", "name": "..."}} structure
    if any(b.get("action", {}).get("id") == action["id"] for b in bindings):
        if verbose:
            print(f"Action already bound to trigger: {trigger_id}")
        return action

    # Build new binding list in the format Auth0 expects for PATCH
    # Auth0 requires ref type "action_id" (not "action")
    new_bindings = [
        {"ref": {"type": "action_id", "value": b.get("action", {}).get("id")}}
        for b in bindings
        if b.get("action", {}).get("id")
    ]
    new_bindings.append({"ref": {"type": "action_id", "value": action["id"]}})
    mgmt.set_trigger_bindings(trigger_id=trigger_id, bindings=new_bindings)
    if verbose:
        print(f"Bound action to trigger: {trigger_id}")
    return action


def load_settings() -> Settings:
    mgmt_domain = _required_env("AUTH0_MGMT_DOMAIN").strip()
    mgmt_client_id = _required_env("AUTH0_MGMT_CLIENT_ID").strip()
    mgmt_client_secret = _required_env("AUTH0_MGMT_CLIENT_SECRET").strip()
    audience = _required_env("AUTH0_AUDIENCE").strip()

    return Settings(
        mgmt_domain=mgmt_domain,
        mgmt_client_id=mgmt_client_id,
        mgmt_client_secret=mgmt_client_secret,
        audience=audience,
        api_name=os.getenv("AUTH0_API_NAME", "Fraud Rule Management API"),
        spa_name=os.getenv("AUTH0_SPA_APP_NAME", "Fraud Intelligence Portal"),
        m2m_name=os.getenv("AUTH0_M2M_APP_NAME", "Fraud Rule Management M2M"),
        spa_callbacks=_split_csv(os.getenv("AUTH0_SPA_CALLBACK_URLS")),
        spa_origins=_split_csv(os.getenv("AUTH0_SPA_ALLOWED_ORIGINS")),
        spa_logout_urls=_split_csv(os.getenv("AUTH0_SPA_ALLOWED_LOGOUT_URLS")),
        # New role model - no M2M roles needed (M2M uses scopes only)
        m2m_default_roles=[],
    )


# =============================================================================
# TEST USER MANAGEMENT
# =============================================================================


def ensure_test_users(
    mgmt: Auth0Mgmt,
    *,
    role_map: dict[str, str],  # role_name -> role_id
    verbose: bool,
    auto_generate_passwords: bool = True,
    sync_to_doppler: bool = True,
) -> list[dict]:
    """Create test users for Playwright automation.

    Test users use Username-Password-Authentication connection.
    Passwords are auto-generated if not set in environment, then synced to Doppler.
    """
    created_users = []
    passwords_to_sync: dict[str, str] = {}

    for user_config in TEST_USERS:
        email = user_config["email"]
        name = user_config["name"]
        password_env = user_config["password_env"]
        role_names = user_config["roles"]

        # Get password from environment or auto-generate
        password = os.getenv(password_env)
        password_was_generated = False

        if not password:
            if auto_generate_passwords:
                password = generate_secure_password()
                password_was_generated = True
                passwords_to_sync[password_env] = password
                if verbose:
                    print(f"  Generated password for {email}")
            else:
                if verbose:
                    print(f"  Skipping test user {email} (no password in {password_env})")
                continue

        # Check if user exists
        existing = mgmt.find_user_by_email(email)

        if existing:
            user = existing
            if verbose:
                print(f"  Test user exists: {email}")
            # Note: We cannot update password for existing users easily
            # If password was generated, warn that it won't apply to existing user
            if password_was_generated:
                print("    Warning: Generated password won't apply to existing user")
                # Remove from sync since user already exists with different password
                passwords_to_sync.pop(password_env, None)
        else:
            # Create user with password
            user = mgmt.create_user(
                email=email,
                name=name,
                password=password,
                connection="Username-Password-Authentication",
            )
            if verbose:
                print(f"  Created test user: {email}")

        # Assign roles to user
        role_ids = [role_map[r] for r in role_names if r in role_map]
        if role_ids:
            # Get current roles to avoid re-assigning
            current_roles = mgmt.get_user_roles(user_id=user["user_id"])
            current_role_ids = {r["id"] for r in current_roles}
            new_role_ids = [rid for rid in role_ids if rid not in current_role_ids]

            if new_role_ids:
                mgmt.assign_roles_to_user(user_id=user["user_id"], role_ids=new_role_ids)
                if verbose:
                    print(f"    Assigned roles: {', '.join(role_names)}")
            elif verbose:
                print(f"    Roles already assigned: {', '.join(role_names)}")

        created_users.append(user)

    # Sync generated passwords to Doppler
    if passwords_to_sync and sync_to_doppler:
        if verbose:
            print(f"\n  Syncing {len(passwords_to_sync)} password(s) to Doppler...")
        sync_secrets_to_doppler(passwords_to_sync, verbose=verbose)

    return created_users


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap Auth0 objects for Card Fraud Platform (idempotent)"
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Run without prompting")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print details")
    parser.add_argument(
        "--skip-test-users",
        action="store_true",
        help="Skip test user creation (useful if passwords not set)",
    )
    args = parser.parse_args()

    settings = load_settings()

    if not args.yes:
        print("=" * 60)
        print("AUTH0 BOOTSTRAP - Card Fraud Platform")
        print("=" * 60)
        print(f"\nTenant: {settings.mgmt_domain}")
        print(f"Audience: {settings.audience}")
        print("\nThis will create/update:")
        print("  - API (Resource Server) with permissions")
        print("  - Platform roles (PLATFORM_ADMIN, RULE_MAKER, etc.)")
        print("  - SPA application (Fraud Intelligence Portal)")
        print("  - M2M application for testing")
        print("  - Actions for token enrichment")
        if not args.skip_test_users:
            print("  - Test users for Playwright automation")
        print("\nRe-run is safe (idempotent). Continue? [y/N] ", end="")
        answer = input().strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    print("\n[1/7] Getting management token...")
    token = _get_management_token(
        domain=settings.mgmt_domain,
        client_id=settings.mgmt_client_id,
        client_secret=settings.mgmt_client_secret,
    )

    mgmt = Auth0Mgmt(domain=settings.mgmt_domain, token=token, verbose=args.verbose)
    try:
        # Step 2: Create/update API with permissions
        print("[2/7] Creating/updating API (Resource Server)...")
        ensure_resource_server(
            mgmt,
            identifier=settings.audience,
            name=settings.api_name,
            scopes=DEFAULT_SCOPES,
            verbose=args.verbose,
        )

        # Step 3: Create/update platform roles
        print("[3/7] Creating/updating platform roles...")
        created_roles = ensure_roles(mgmt, roles=PLATFORM_ROLES, verbose=args.verbose)

        # Build role_name -> role_id map for later use
        role_map: dict[str, str] = {}
        for role in created_roles:
            role_map[role["name"]] = role["id"]

        # Step 4: Assign permissions to roles (Auth0 RBAC)
        print("[4/7] Assigning permissions to roles...")
        for role_name, permissions in ROLE_PERMISSIONS.items():
            if role_name not in role_map:
                continue
            role_id = role_map[role_name]

            # Filter permissions to only those that exist in this API
            api_permissions = [s["value"] for s in DEFAULT_SCOPES]
            valid_perms = [
                {
                    "resource_server_identifier": settings.audience,
                    "permission_name": p,
                }
                for p in permissions
                if p in api_permissions
            ]

            if valid_perms:
                mgmt.assign_permissions_to_role(role_id=role_id, permissions=valid_perms)
                if args.verbose:
                    perm_names = [p["permission_name"] for p in valid_perms]
                    print(f"  {role_name}: {', '.join(perm_names)}")

        # Step 5: Create/update SPA client
        print("[5/7] Creating/updating SPA application...")
        if settings.spa_callbacks or settings.spa_origins or settings.spa_logout_urls:
            ensure_spa_client(
                mgmt,
                name=settings.spa_name,
                callbacks=settings.spa_callbacks,
                origins=settings.spa_origins,
                logout_urls=settings.spa_logout_urls,
                verbose=args.verbose,
            )
        elif args.verbose:
            print("  Skipping SPA client setup (no SPA URL env vars set).")

        # Step 6: Create/update M2M client and grant
        print("[6/7] Creating/updating M2M application...")
        m2m_client = ensure_m2m_client(mgmt, name=settings.m2m_name, verbose=args.verbose)
        ensure_client_grant(
            mgmt,
            client_id=m2m_client["client_id"],
            audience=settings.audience,
            scopes=[s["value"] for s in DEFAULT_SCOPES],
            verbose=args.verbose,
        )

        # Sync M2M client credentials to Doppler
        # Note: client_secret is only returned on creation, not on update
        m2m_secrets = {"AUTH0_CLIENT_ID": m2m_client["client_id"]}
        if "client_secret" in m2m_client:
            m2m_secrets["AUTH0_CLIENT_SECRET"] = m2m_client["client_secret"]
            if args.verbose:
                print("  Syncing M2M credentials to Doppler...")
            sync_secrets_to_doppler(m2m_secrets, verbose=args.verbose)
        elif args.verbose:
            print("  M2M client_secret not in response (existing client)")
            print(
                "  To get secret: Auth0 Dashboard → Applications → Fraud Rule Management M2M → Settings"
            )

        # Step 7: Create/update Actions
        print("[7/7] Creating/updating Actions...")
        ensure_action_and_binding(
            mgmt,
            action_name="Add Roles to Token",
            trigger_id="post-login",
            code=_action_code_post_login(settings.audience),
            verbose=args.verbose,
        )

        # Note: M2M tokens use scopes, not roles - skip M2M role injection
        if args.verbose:
            print("  Skipping M2M role injection (M2M uses scopes only)")

        # Optional: Create test users
        if not args.skip_test_users:
            print("\n[Optional] Creating test users for Playwright...")
            ensure_test_users(
                mgmt,
                role_map=role_map,
                verbose=args.verbose,
                auto_generate_passwords=True,
                sync_to_doppler=True,
            )

    finally:
        mgmt.close()

    print("\n" + "=" * 60)
    print("AUTH0 BOOTSTRAP COMPLETED")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Verify: uv run auth0-verify")
    print("  2. Get SPA Client ID from Auth0 Dashboard for React app")
    print("  3. Update Doppler with M2M credentials if needed")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
