"""Unified Auth0 bootstrap automation - REFERENCE IMPLEMENTATION.

================================================================================
THIS IS A REFERENCE IMPLEMENTATION FOR FUTURE USE - NOT CURRENTLY ACTIVE
================================================================================

The current PRODUCTION approach uses SEPARATE scripts per project:
- card-fraud-rule-management/scripts/setup_auth0.py  (creates all shared resources)
- card-fraud-rule-engine/scripts/setup_auth0.py      (creates API + M2M only)
- card-fraud-transaction-management/scripts/setup_auth0.py (creates API + M2M only)

This unified script is kept as a REFERENCE for potential future consolidation.
It demonstrates how a single script could handle all projects by detecting
DOPPLER_PROJECT and creating only the appropriate resources.

================================================================================
DESIGN RATIONALE (Why separate scripts is RECOMMENDED over this unified script):
================================================================================

1. CLEAR OWNERSHIP: Each project's script creates only what IT owns.
   - rule-management owns: roles, SPA, actions, test users
   - Other projects own: their own API + M2M only

2. SIMPLER MAINTENANCE: Each script is small (~200-300 lines) and focused.
   - Easy to understand what a project creates
   - Easy to modify without affecting other projects

3. DECOUPLED DEPLOYMENT: Projects can be deployed independently.
   - Run rule-management first, then others in any order
   - No single point of failure

4. IDEMPOTENT: Run any script multiple times safely.
   - Creates if not exists, updates if exists, never duplicates

================================================================================
AUTH0 PLATFORM ARCHITECTURE:
================================================================================

The Card Fraud Platform consists of 4 projects sharing a single Auth0 tenant:

┌─────────────────────────────────────────────────────────────────────────────┐
│                         AUTH0 TENANT                                        │
│                  (dev-gix6qllz7yvs0rl8.us.auth0.com)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SHARED RESOURCES (created by rule-management ONLY):                       │
│  ├── Roles: PLATFORM_ADMIN, RULE_MAKER, RULE_CHECKER, RULE_VIEWER,        │
│  │          FRAUD_ANALYST, FRAUD_SUPERVISOR                                │
│  ├── SPA App: "Fraud Intelligence Portal" (used by React frontend)        │
│  ├── Actions: "Add Roles to Token" (post-login trigger)                   │
│  └── Test Users: 6 users for Playwright E2E                               │
│                                                                             │
│  PROJECT-SPECIFIC RESOURCES:                                               │
│  ├── rule-management: API + M2M + permissions (rule:*)                    │
│  ├── rule-engine: API + M2M + scopes (execute:*, read:*, replay:*)        │
│  └── transaction-management: API + M2M + permissions (txn:*)              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

BOOTSTRAP ORDER (CRITICAL):
1. card-fraud-rule-management (FIRST - creates shared resources)
2. card-fraud-rule-engine (creates its own API + M2M)
3. card-fraud-transaction-management (creates its own API + M2M)
4. card-fraud-intelligence-portal (no Auth0 setup needed - uses SPA from step 1)

================================================================================
IF ADOPTING THIS UNIFIED SCRIPT:
================================================================================

1. Copy this file to each project's scripts/ directory
2. Register in pyproject.toml: auth0-bootstrap = "cli.auth0_bootstrap:main"
3. Update auth0_bootstrap.py CLI wrapper to point to this script
4. Run: uv run auth0-bootstrap --yes --verbose

The script detects DOPPLER_PROJECT env var and creates only appropriate resources.

Required environment variables:
- DOPPLER_PROJECT                    Determines which project config to use
- AUTH0_MGMT_DOMAIN                  e.g. dev-xxxx.us.auth0.com
- AUTH0_MGMT_CLIENT_ID
- AUTH0_MGMT_CLIENT_SECRET
- AUTH0_AUDIENCE                     e.g. https://fraud-rule-management-api

Notes:
- This script avoids printing secrets.
- It is designed to be safe to re-run (idempotent).
- Run with card-fraud-rule-management FIRST to create shared resources.
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import subprocess
import sys
import time
from dataclasses import dataclass, field

import httpx

# =============================================================================
# PROJECT CONFIGURATION
# =============================================================================


@dataclass
class ProjectConfig:
    """Configuration for what each project creates in Auth0."""

    project_name: str
    api_audience: str
    api_name: str
    m2m_name: str
    scopes: list[dict[str, str]]

    # What this project creates (True = creates, False = skips)
    creates_roles: bool = False
    creates_spa: bool = False
    creates_actions: bool = False
    creates_test_users: bool = False

    # Optional SPA config (only if creates_spa=True)
    spa_name: str = ""

    # Roles to create (only if creates_roles=True)
    roles: list[tuple[str, str, list[str]]] = field(
        default_factory=list
    )  # (name, description, permissions)


# Platform-wide roles and their permissions (created by rule-management only)
PLATFORM_ROLES = [
    (
        "PLATFORM_ADMIN",
        "Full platform administrator",
        ["rule:create", "rule:update", "rule:submit", "rule:approve", "rule:reject", "rule:read"],
    ),
    (
        "RULE_MAKER",
        "Can create and submit rules",
        ["rule:create", "rule:update", "rule:submit", "rule:read"],
    ),
    ("RULE_CHECKER", "Can approve or reject rules", ["rule:approve", "rule:reject", "rule:read"]),
    ("RULE_VIEWER", "Read-only access to rules", ["rule:read"]),
    (
        "FRAUD_ANALYST",
        "Transaction analyst role",
        [],
    ),  # Permissions assigned by transaction-management
    (
        "FRAUD_SUPERVISOR",
        "Fraud supervisor role",
        [],
    ),  # Permissions assigned by transaction-management
]

# Test users for Playwright (created by rule-management only)
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
        "name": "Test Maker+Checker",
        "password_env": "TEST_USER_RULE_MAKER_PASSWORD",
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


# Project configurations
PROJECT_CONFIGS: dict[str, ProjectConfig] = {
    "card-fraud-rule-management": ProjectConfig(
        project_name="card-fraud-rule-management",
        api_audience="https://fraud-rule-management-api",
        api_name="Fraud Rule Management API",
        m2m_name="Fraud Rule Management M2M",
        scopes=[
            {"value": "rule:create", "description": "Create new rules"},
            {"value": "rule:update", "description": "Update existing rules"},
            {"value": "rule:submit", "description": "Submit rules for approval"},
            {"value": "rule:approve", "description": "Approve pending rules"},
            {"value": "rule:reject", "description": "Reject pending rules"},
            {"value": "rule:read", "description": "Read rules"},
        ],
        creates_roles=True,
        creates_spa=True,
        creates_actions=True,
        creates_test_users=True,
        spa_name="Fraud Intelligence Portal",
        roles=PLATFORM_ROLES,
    ),
    "card-fraud-rule-engine": ProjectConfig(
        project_name="card-fraud-rule-engine",
        api_audience="https://fraud-rule-engine-api",
        api_name="Fraud Rule Engine API",
        m2m_name="Fraud Rule Engine M2M",
        scopes=[
            {"value": "execute:rules", "description": "Execute rules for evaluation"},
            {"value": "read:results", "description": "Read execution results"},
            {"value": "replay:transactions", "description": "Replay historical transactions"},
            {"value": "read:metrics", "description": "Read execution metrics"},
        ],
        # M2M-only service - no roles, no SPA, no actions, no test users
    ),
    "card-fraud-transaction-management": ProjectConfig(
        project_name="card-fraud-transaction-management",
        api_audience="https://fraud-transaction-management-api",
        api_name="Fraud Transaction Management API",
        m2m_name="Fraud Transaction Management M2M",
        scopes=[
            {"value": "txn:view", "description": "View transactions"},
            {"value": "txn:comment", "description": "Add analyst comments"},
            {"value": "txn:flag", "description": "Flag suspicious activity"},
            {"value": "txn:recommend", "description": "Recommend action"},
            {"value": "txn:approve", "description": "Approve transaction"},
            {"value": "txn:block", "description": "Block transaction"},
            {"value": "txn:override", "description": "Override prior decision"},
        ],
        # Uses shared roles from rule-management
    ),
    "card-fraud-intelligence-portal": ProjectConfig(
        project_name="card-fraud-intelligence-portal",
        api_audience="",  # Frontend doesn't have its own API
        api_name="",
        m2m_name="",
        scopes=[],
        # Frontend - nothing to create, uses SPA from rule-management
    ),
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def generate_secure_password(length: int = 24) -> str:
    """Generate a secure random password for test users."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    password.extend(secrets.choice(alphabet) for _ in range(length - 4))
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def sync_secrets_to_doppler(
    secrets_dict: dict[str, str],
    *,
    project: str,
    config: str = "local",
    verbose: bool = False,
) -> bool:
    """Sync secrets to Doppler using CLI."""
    if not secrets_dict:
        return True

    try:
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


def sync_test_passwords_to_all_projects(
    passwords: dict[str, str],
    *,
    verbose: bool = False,
) -> None:
    """Sync test user passwords to all Doppler projects (local + test configs)."""
    projects = [
        "card-fraud-rule-management",
        "card-fraud-rule-engine",
        "card-fraud-transaction-management",
        "card-fraud-intelligence-portal",
    ]
    configs = ["local", "test"]

    for project in projects:
        for config in configs:
            sync_secrets_to_doppler(passwords, project=project, config=config, verbose=verbose)


# =============================================================================
# AUTH0 MANAGEMENT CLIENT
# =============================================================================


class Auth0Mgmt:
    """Auth0 Management API client with retry logic."""

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
                sleep_s = float(retry_after) if retry_after else base_sleep * attempt
                time.sleep(sleep_s)
                continue

            resp.raise_for_status()
            if resp.status_code == 204:
                return None
            return resp.json()

        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected request retry state")

    # Resource Server (API) methods
    def find_resource_server_by_identifier(self, identifier: str) -> dict | None:
        results = self._request("GET", "resource-servers", params={"identifier": identifier})
        if isinstance(results, list):
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

    # Role methods
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

    def get_role_permissions(self, *, role_id: str) -> list[dict]:
        perms = self._request("GET", f"roles/{role_id}/permissions")
        return perms if isinstance(perms, list) else []

    def assign_permissions_to_role(self, *, role_id: str, permissions: list[dict]) -> None:
        if permissions:
            self._request("POST", f"roles/{role_id}/permissions", json={"permissions": permissions})

    # Client methods
    def list_clients(self, *, page: int = 0, per_page: int = 50) -> list[dict]:
        clients = self._request(
            "GET",
            "clients",
            params={
                "page": page,
                "per_page": per_page,
                "fields": "client_id,name,app_type,client_secret",
            },
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

    # Client Grant methods
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

    # Action methods
    def list_actions(self, *, page: int = 0, per_page: int = 50) -> list[dict]:
        result = self._request(
            "GET", "actions/actions", params={"page": page, "per_page": per_page}
        )
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

    def create_action(
        self, *, name: str, trigger_id: str, code: str, runtime: str = "node18"
    ) -> dict:
        version = "v2" if trigger_id == "credentials-exchange" else "v3"
        return self._request(
            "POST",
            "actions/actions",
            json={
                "name": name,
                "supported_triggers": [{"id": trigger_id, "version": version}],
                "code": code,
                "runtime": runtime,
                "secrets": [],
            },
        )

    def update_action(
        self, *, action_id: str, code: str, trigger_id: str, runtime: str = "node18"
    ) -> dict:
        version = "v2" if trigger_id == "credentials-exchange" else "v3"
        return self._request(
            "PATCH",
            f"actions/actions/{action_id}",
            json={
                "supported_triggers": [{"id": trigger_id, "version": version}],
                "code": code,
                "runtime": runtime,
                "secrets": [],
            },
        )

    def deploy_action(self, *, action_id: str) -> None:
        self._request("POST", f"actions/actions/{action_id}/deploy")

    def get_trigger_bindings(self, *, trigger_id: str) -> list[dict]:
        result = self._request("GET", f"actions/triggers/{trigger_id}/bindings")
        if isinstance(result, dict) and "bindings" in result:
            return result["bindings"]
        return result if isinstance(result, list) else []

    def set_trigger_bindings(self, *, trigger_id: str, bindings: list[dict]) -> None:
        self._request(
            "PATCH", f"actions/triggers/{trigger_id}/bindings", json={"bindings": bindings}
        )

    # User methods
    def find_user_by_email(self, email: str) -> dict | None:
        users = self._request("GET", "users-by-email", params={"email": email})
        return users[0] if users else None

    def create_user(self, *, email: str, name: str, password: str, connection: str) -> dict:
        return self._request(
            "POST",
            "users",
            json={
                "email": email,
                "name": name,
                "password": password,
                "connection": connection,
                "email_verified": True,
            },
        )

    def get_user_roles(self, *, user_id: str) -> list[dict]:
        roles = self._request("GET", f"users/{user_id}/roles")
        return roles if isinstance(roles, list) else []

    def assign_roles_to_user(self, *, user_id: str, role_ids: list[str]) -> None:
        if role_ids:
            self._request("POST", f"users/{user_id}/roles", json={"roles": role_ids})


# =============================================================================
# BOOTSTRAP FUNCTIONS
# =============================================================================


def ensure_resource_server(mgmt: Auth0Mgmt, *, config: ProjectConfig, verbose: bool) -> dict:
    """Create or update the API (Resource Server)."""
    existing = mgmt.find_resource_server_by_identifier(config.api_audience)
    if not existing:
        created = mgmt.create_resource_server(
            name=config.api_name, identifier=config.api_audience, scopes=config.scopes
        )
        if verbose:
            print(f"Created resource server: {created.get('id')} ({config.api_audience})")
        return created

    updated = mgmt.update_resource_server(
        resource_server_id=existing["id"], name=config.api_name, scopes=config.scopes
    )
    if verbose:
        print(f"Updated resource server: {updated.get('id')} ({config.api_audience})")
    return updated


def ensure_roles(mgmt: Auth0Mgmt, *, config: ProjectConfig, verbose: bool) -> dict[str, str]:
    """Create or update platform roles. Returns role_name -> role_id mapping."""
    role_map: dict[str, str] = {}

    for role_name, description, _ in config.roles:
        existing = mgmt.find_role_by_name(role_name)
        if not existing:
            created = mgmt.create_role(name=role_name, description=description)
            role_map[role_name] = created["id"]
            if verbose:
                print(f"Created role: {created['id']} ({role_name})")
        else:
            mgmt.update_role(role_id=existing["id"], description=description)
            role_map[role_name] = existing["id"]
            if verbose:
                print(f"Updated role: {existing['id']} ({role_name})")

    return role_map


def assign_permissions_to_roles(
    mgmt: Auth0Mgmt, *, config: ProjectConfig, role_map: dict[str, str], verbose: bool
) -> None:
    """Assign permissions to roles."""
    for role_name, _, permission_values in config.roles:
        if not permission_values:
            continue

        role_id = role_map.get(role_name)
        if not role_id:
            continue

        # Get current permissions
        current_perms = mgmt.get_role_permissions(role_id=role_id)
        current_perm_values = {p.get("permission_name") for p in current_perms}

        # Build permissions to assign
        permissions_to_assign = []
        for perm in permission_values:
            if perm not in current_perm_values:
                permissions_to_assign.append(
                    {
                        "resource_server_identifier": config.api_audience,
                        "permission_name": perm,
                    }
                )

        if permissions_to_assign:
            mgmt.assign_permissions_to_role(role_id=role_id, permissions=permissions_to_assign)

        if verbose:
            print(f"  {role_name}: {', '.join(permission_values)}")


def ensure_spa_client(mgmt: Auth0Mgmt, *, config: ProjectConfig, verbose: bool) -> dict:
    """Create or update SPA application."""
    callbacks = os.getenv(
        "AUTH0_SPA_CALLBACK_URLS", "http://localhost:3000,http://localhost:5173"
    ).split(",")
    origins = os.getenv(
        "AUTH0_SPA_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"
    ).split(",")
    logout_urls = os.getenv(
        "AUTH0_SPA_ALLOWED_LOGOUT_URLS", "http://localhost:3000,http://localhost:5173"
    ).split(",")

    existing = mgmt.find_client_by_name(config.spa_name)
    payload = {
        "app_type": "spa",
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "callbacks": [c.strip() for c in callbacks],
        "allowed_logout_urls": [u.strip() for u in logout_urls],
        "web_origins": [o.strip() for o in origins],
        "allowed_origins": [o.strip() for o in origins],
        "oidc_conformant": True,
        "is_first_party": True,
    }

    if not existing:
        created = mgmt.create_client(name=config.spa_name, app_type="spa", payload=payload)
        if verbose:
            print(f"Created SPA client: {created.get('client_id')} ({config.spa_name})")
        return created

    updated = mgmt.update_client(client_id=existing["client_id"], payload=payload)
    if verbose:
        print(f"Updated SPA client: {existing.get('client_id')} ({config.spa_name})")
    return updated


def ensure_m2m_client(mgmt: Auth0Mgmt, *, config: ProjectConfig, verbose: bool) -> dict:
    """Create or update M2M application."""
    existing = mgmt.find_client_by_name(config.m2m_name)
    payload = {
        "app_type": "non_interactive",
        "grant_types": ["client_credentials"],
        "token_endpoint_auth_method": "client_secret_post",
        "oidc_conformant": True,
        "is_first_party": True,
    }

    if not existing:
        created = mgmt.create_client(
            name=config.m2m_name, app_type="non_interactive", payload=payload
        )
        if verbose:
            print(f"Created M2M client: {created.get('client_id')} ({config.m2m_name})")
        return created

    updated = mgmt.update_client(client_id=existing["client_id"], payload=payload)
    if verbose:
        print(f"Updated M2M client: {existing.get('client_id')} ({config.m2m_name})")
    return updated


def ensure_client_grant(
    mgmt: Auth0Mgmt, *, client_id: str, audience: str, scopes: list[str], verbose: bool
) -> dict:
    """Create or update client grant."""
    grants = mgmt.list_client_grants(client_id=client_id)
    existing = next((g for g in grants if g.get("audience") == audience), None)

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
    mgmt: Auth0Mgmt, *, action_name: str, trigger_id: str, code: str, verbose: bool
) -> dict:
    """Create or update action and bind to trigger."""
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

    # Bind to trigger if not already bound
    bindings = mgmt.get_trigger_bindings(trigger_id=trigger_id)
    if any(b.get("action", {}).get("id") == action["id"] for b in bindings):
        if verbose:
            print(f"Action already bound to trigger: {trigger_id}")
        return action

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


def ensure_test_users(
    mgmt: Auth0Mgmt, *, config: ProjectConfig, role_map: dict[str, str], verbose: bool
) -> dict[str, str]:
    """Create test users for Playwright. Returns dict of password_env -> password for syncing."""
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
            password = generate_secure_password()
            password_was_generated = True
            passwords_to_sync[password_env] = password
            if verbose:
                print(f"  Generated password for {email}")

        # Check if user exists
        existing = mgmt.find_user_by_email(email)

        if existing:
            if verbose:
                print(f"  Test user exists: {email}")
            if password_was_generated:
                print("    Warning: Generated password won't apply to existing user")
                passwords_to_sync.pop(password_env, None)
        else:
            mgmt.create_user(
                email=email,
                name=name,
                password=password,
                connection="Username-Password-Authentication",
            )
            if verbose:
                print(f"  Created test user: {email}")

        # Get user for role assignment
        user = existing or mgmt.find_user_by_email(email)
        if not user:
            continue

        # Assign roles
        role_ids = [role_map[r] for r in role_names if r in role_map]
        if role_ids:
            current_roles = mgmt.get_user_roles(user_id=user["user_id"])
            current_role_ids = {r["id"] for r in current_roles}
            new_role_ids = [rid for rid in role_ids if rid not in current_role_ids]
            if new_role_ids:
                mgmt.assign_roles_to_user(user_id=user["user_id"], role_ids=new_role_ids)
                if verbose:
                    print(f"    Assigned roles: {', '.join(role_names)}")

    return passwords_to_sync


# =============================================================================
# MAIN
# =============================================================================


def get_management_token(*, domain: str, client_id: str, client_secret: str) -> str:
    """Get Auth0 Management API token."""
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
    parser = argparse.ArgumentParser(description="Bootstrap Auth0 objects (idempotent, unified)")
    parser.add_argument("--yes", "-y", action="store_true", help="Run without prompting")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print details")
    parser.add_argument("--skip-test-users", action="store_true", help="Skip test user creation")
    args = parser.parse_args()

    # Detect project from Doppler
    project_name = os.getenv("DOPPLER_PROJECT", "")
    if not project_name:
        print("ERROR: DOPPLER_PROJECT env var not set. Run via Doppler:")
        print("  uv run auth0-bootstrap --yes --verbose")
        return 1

    config = PROJECT_CONFIGS.get(project_name)
    if not config:
        print(f"ERROR: Unknown project '{project_name}'")
        print(f"Known projects: {', '.join(PROJECT_CONFIGS.keys())}")
        return 1

    # Check if this project has anything to create
    if not config.api_audience:
        print(f"Project '{project_name}' has no Auth0 resources to create.")
        print("This is expected for frontend projects.")
        return 0

    # Get required env vars
    mgmt_domain = os.getenv("AUTH0_MGMT_DOMAIN", "").strip()
    mgmt_client_id = os.getenv("AUTH0_MGMT_CLIENT_ID", "").strip()
    mgmt_client_secret = os.getenv("AUTH0_MGMT_CLIENT_SECRET", "").strip()

    missing = []
    if not mgmt_domain:
        missing.append("AUTH0_MGMT_DOMAIN")
    if not mgmt_client_id:
        missing.append("AUTH0_MGMT_CLIENT_ID")
    if not mgmt_client_secret:
        missing.append("AUTH0_MGMT_CLIENT_SECRET")
    if missing:
        print(f"ERROR: Missing required env vars: {', '.join(missing)}")
        return 1

    # Confirmation prompt
    if not args.yes:
        print("=" * 60)
        print(f"AUTH0 BOOTSTRAP - {project_name}")
        print("=" * 60)
        print(f"\nTenant: {mgmt_domain}")
        print(f"API: {config.api_audience}")
        print("\nThis project creates:")
        print("  - API (Resource Server): Yes")
        print("  - M2M Application: Yes")
        print(f"  - Roles: {'Yes' if config.creates_roles else 'No (uses shared roles)'}")
        print(f"  - SPA Application: {'Yes' if config.creates_spa else 'No'}")
        print(f"  - Actions: {'Yes' if config.creates_actions else 'No'}")
        print(f"  - Test Users: {'Yes' if config.creates_test_users else 'No'}")
        print("\nRe-run is safe (idempotent). Continue? [y/N] ", end="")
        if input().strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 1

    # Get management token
    print("\n[1/7] Getting management token...")
    token = get_management_token(
        domain=mgmt_domain, client_id=mgmt_client_id, client_secret=mgmt_client_secret
    )

    mgmt = Auth0Mgmt(domain=mgmt_domain, token=token, verbose=args.verbose)
    try:
        # Step 2: Create/update API
        print("[2/7] Creating/updating API (Resource Server)...")
        ensure_resource_server(mgmt, config=config, verbose=args.verbose)

        # Step 3: Create/update roles (if this project creates them)
        role_map: dict[str, str] = {}
        if config.creates_roles:
            print("[3/7] Creating/updating platform roles...")
            role_map = ensure_roles(mgmt, config=config, verbose=args.verbose)
        else:
            print("[3/7] Skipping roles (managed by rule-management)")
            # Get existing role IDs for test user assignment
            for role_name, _, _ in PLATFORM_ROLES:
                existing = mgmt.find_role_by_name(role_name)
                if existing:
                    role_map[role_name] = existing["id"]

        # Step 4: Assign permissions to roles
        if config.creates_roles:
            print("[4/7] Assigning permissions to roles...")
            assign_permissions_to_roles(
                mgmt, config=config, role_map=role_map, verbose=args.verbose
            )
        else:
            print("[4/7] Skipping permission assignment (managed by rule-management)")

        # Step 5: Create/update SPA
        if config.creates_spa:
            print("[5/7] Creating/updating SPA application...")
            ensure_spa_client(mgmt, config=config, verbose=args.verbose)
        else:
            print("[5/7] Skipping SPA (managed by rule-management)")

        # Step 6: Create/update M2M
        print("[6/7] Creating/updating M2M application...")
        m2m_client = ensure_m2m_client(mgmt, config=config, verbose=args.verbose)
        ensure_client_grant(
            mgmt,
            client_id=m2m_client["client_id"],
            audience=config.api_audience,
            scopes=[s["value"] for s in config.scopes],
            verbose=args.verbose,
        )

        # Sync M2M credentials to Doppler
        m2m_secrets = {"AUTH0_CLIENT_ID": m2m_client["client_id"]}
        if "client_secret" in m2m_client:
            m2m_secrets["AUTH0_CLIENT_SECRET"] = m2m_client["client_secret"]
            if args.verbose:
                print("  Syncing M2M credentials to Doppler...")
            sync_secrets_to_doppler(m2m_secrets, project=project_name, verbose=args.verbose)
        elif args.verbose:
            print("  M2M client_secret not in response (existing client)")

        # Step 7: Create/update Actions
        if config.creates_actions:
            print("[7/7] Creating/updating Actions...")
            action_code = (
                "exports.onExecutePostLogin = async (event, api) => {\n"
                f"  const namespace = {config.api_audience!r};\n"
                "  const roles = (event.authorization && event.authorization.roles) ? event.authorization.roles : [];\n"
                "  api.accessToken.setCustomClaim(`${namespace}/roles`, roles);\n"
                "};\n"
            )
            ensure_action_and_binding(
                mgmt,
                action_name="Add Roles to Token",
                trigger_id="post-login",
                code=action_code,
                verbose=args.verbose,
            )
            if args.verbose:
                print("  Skipping M2M role injection (M2M uses scopes only)")
        else:
            print("[7/7] Skipping Actions (managed by rule-management)")

        # Optional: Create test users
        if config.creates_test_users and not args.skip_test_users:
            print("\n[Optional] Creating test users for Playwright...")
            passwords_to_sync = ensure_test_users(
                mgmt,
                config=config,
                role_map=role_map,
                verbose=args.verbose,
            )
            if passwords_to_sync:
                print(
                    f"\n  Syncing {len(passwords_to_sync)} password(s) to all Doppler projects..."
                )
                sync_test_passwords_to_all_projects(passwords_to_sync, verbose=args.verbose)

    finally:
        mgmt.close()

    print("\n" + "=" * 60)
    print(f"AUTH0 BOOTSTRAP COMPLETED - {project_name}")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Verify: uv run auth0-verify")
    if config.creates_roles:
        print("  2. Enable RBAC in Auth0 Dashboard for each API")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
