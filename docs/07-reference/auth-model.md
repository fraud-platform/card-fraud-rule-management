# Card Fraud Platform - Authentication & Authorization Model

> **IMPORTANT:** The platform repository is the canonical source of truth for suite-wide Auth0 ownership and Doppler naming.
> This file mirrors the portal-relevant contract and should stay synchronized with the platform auth docs.

**Version:** 2.0.0
**Last Updated:** 2026-03-22
**Status:** APPROVED — Unified audience migration complete

---

## 1. Purpose

This document defines the authoritative authentication and authorization model for the Card Fraud Platform, covering:

- Role definitions
- Permission model
- Machine-to-machine access
- Segregation of Duties (SoD)
- Token contract
- User onboarding
- Test user strategy
- Enforcement responsibilities across services

---

## 2. Platform Components

| Project                                                         | Type      | Responsibility                                     |
| --------------------------------------------------------------- | --------- | -------------------------------------------------- |
| `card-fraud-rule-management`                                    | FastAPI   | Rule authoring, governance, maker-checker workflow |
| `card-fraud-rule-engine-auth/card-fraud-rule-engine-monitoring` | Quarkus   | Runtime rule execution (machine only)              |
| `card-fraud-transaction-management`                             | FastAPI   | Fraud operations & case handling                   |
| `card-fraud-intelligence-portal`                                | React SPA | Unified human UI                                   |

---

## 3. Identity Provider

| Setting                  | Value                                      |
| ------------------------ | ------------------------------------------ |
| **IdP**                  | Auth0                                      |
| **Tenant**               | `$AUTH0_MGMT_DOMAIN` (from Doppler)        |
| **Environments**         | local, test, prod                          |
| **RBAC**                 | Enabled                                    |
| **Permissions in Token** | Yes                                        |

### API Audiences (Resource Servers)

| Name                             | Identifier (audience)                        | Purpose                                                        | Status     |
| -------------------------------- | -------------------------------------------- | -------------------------------------------------------------- | ---------- |
| Fraud Governance Unified API     | `https://fraud-governance-api`               | **Primary.** Single audience for all portal-issued human tokens. All 3 backend services validate this. | **Active** |
| Fraud Rule Management API        | `https://fraud-rule-management-api`          | Legacy per-service audience (M2M only, human tokens use unified) | Retained   |
| Fraud Rule Engine API            | `https://fraud-rule-engine-api`              | Runtime engine M2M audience                                     | Active     |
| Fraud Transaction Management API | `https://fraud-transaction-management-api`   | Legacy per-service audience (M2M only)                          | Retained   |
| Fraud Ops Analyst Agent API      | `https://fraud-ops-analyst-agent-api`        | Legacy per-service audience (M2M only)                          | Retained   |

> **Unified Audience:** All portal (SPA) tokens request `https://fraud-governance-api`. Backend services accept this audience for human-user JWTs. The per-service audiences remain for M2M client-credentials tokens.

### Auth0 Applications (Clients)

| Client Name                      | Type    | Doppler Key / Notes                                   | Purpose                                              |
| -------------------------------- | ------- | ----------------------------------------------------- | ---------------------------------------------------- |
| Fraud Intelligence Portal        | SPA     | `VITE_AUTH0_CLIENT_ID` (portal project)               | Browser login (PKCE)                                 |
| Local Test Client                | M2M     | `E2E_AUTH0_CLIENT_ID` / `AUTH0_TEST_CLIENT_ID`        | E2E password-realm tests                             |
| Auth0 Management Automation      | M2M     | `AUTH0_MGMT_CLIENT_ID` (all backend projects)         | Management API automation                            |
| Fraud Rule Management M2M        | M2M     | `AUTH0_CLIENT_ID` (rule-management project)           | Rule management service-to-service                   |
| Fraud Transaction Management M2M | M2M     | `AUTH0_CLIENT_ID` (transaction-management project)    | Transaction management service-to-service            |
| Fraud Ops Analyst Agent M2M      | M2M     | `AUTH0_CLIENT_ID` (ops-analyst-agent project)         | Ops analyst agent service-to-service                 |
| Fraud Rule Engine M2M            | M2M     | `AUTH0_CLIENT_ID` (rule-engine project)               | Rule engine runtime execution                        |
| Default App                      | Generic | Auth0 default (unused)                                | Auth0 default — not used                             |

### Auth Model by User Type

| User Type     | Auth Method                         |
| ------------- | ----------------------------------- |
| Human users   | Roles + Permissions (via PKCE flow) |
| Machine users | Client Credentials + Scopes         |

---

## 4. Role Model (Human Users)

### 4.1 Platform Level

| Role             | Purpose                         | Notes                  |
| ---------------- | ------------------------------- | ---------------------- |
| `PLATFORM_ADMIN` | IAM, tenant config, break-glass | Very restricted access |

### 4.2 Rule Governance (Rule Management API)

| Role           | Purpose                             |
| -------------- | ----------------------------------- |
| `RULE_MAKER`   | Create & edit rule drafts           |
| `RULE_CHECKER` | Review & approve rules              |
| `RULE_VIEWER`  | Read-only access (audit/compliance) |

**Important Notes:**

- A user may have both `RULE_MAKER` and `RULE_CHECKER`
- Backend **must** enforce no self-approval (SoD)
- Rule-management backend dependencies return typed `AuthenticatedUser` objects, not raw JWT dicts.
- `AuthenticatedUser` exposes `is_fraud_analyst` and `is_fraud_supervisor` helpers; platform admins bypass both.
- Permission failures are sanitized by default via `sanitize_errors` to avoid leaking required scopes in 403 responses.

### 4.3 Fraud Operations (Transaction Management API)

| Role               | Purpose                             |
| ------------------ | ----------------------------------- |
| `FRAUD_ANALYST`    | Analyze alerts, recommend action    |
| `FRAUD_SUPERVISOR` | Final decision & override authority |

---

## 5. Permission Model

### 5.1 Rule Governance Permissions

| Permission     | Meaning                     |
| -------------- | --------------------------- |
| `rule:create`  | Create new rules / rulesets |
| `rule:update`  | Modify drafts               |
| `rule:submit`  | Submit for approval         |
| `rule:approve` | Approve rules               |
| `rule:reject`  | Reject rules                |
| `rule:read`    | View rules                  |

### 5.2 Fraud Operations Permissions

| Permission      | Meaning                  |
| --------------- | ------------------------ |
| `txn:view`      | View transactions        |
| `txn:comment`   | Add analyst comments     |
| `txn:flag`      | Flag suspicious activity |
| `txn:recommend` | Recommend action         |
| `txn:approve`   | Approve transaction      |
| `txn:block`     | Block transaction        |
| `txn:override`  | Override prior decision  |

### 5.3 Ops Analyst Agent Permissions

| Permission        | Meaning                              |
| ----------------- | ------------------------------------ |
| `ops_agent:read`  | Read ops analyst data & insights     |
| `ops_agent:run`   | Run investigations                   |
| `ops_agent:ack`   | Acknowledge recommendations          |
| `ops_agent:draft` | Create rule drafts from insights     |
| `ops_agent:admin` | Admin ops analyst operations         |

---

## 6. Role-to-Permission Mapping

### Rule Governance

| Role             | Permissions                                              |
| ---------------- | -------------------------------------------------------- |
| `PLATFORM_ADMIN` | All permissions; backend permission checks bypass       |
| `RULE_MAKER`     | `rule:create`, `rule:update`, `rule:submit`, `rule:read` |
| `RULE_CHECKER`   | `rule:approve`, `rule:reject`, `rule:read`               |
| `RULE_VIEWER`    | `rule:read`                                              |

`PLATFORM_ADMIN` is treated as an allow-all bypass in backend authorization helpers for defense in depth.

### Fraud Operations

| Role               | Permissions                                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------------------------------ |
| `PLATFORM_ADMIN`   | All permissions (rule + txn + ops_agent); backend permission checks bypass                                   |
| `FRAUD_ANALYST`    | `txn:view`, `txn:comment`, `txn:flag`, `txn:recommend`, `ops_agent:read`, `ops_agent:run`, `ops_agent:ack`, `rule:read`, `ruleset:read`, `rule_field:read` |
| `FRAUD_SUPERVISOR` | `txn:view`, `txn:comment`, `txn:flag`, `txn:recommend`, `txn:approve`, `txn:block`, `txn:override`, `ops_agent:read`, `ops_agent:run`, `ops_agent:ack`, `ops_agent:draft`, `rule:read`, `ruleset:read`, `rule_field:read` |

---

## 7. Machine-to-Machine (Service Accounts)

### Key Rule

> **Service accounts do NOT use roles. Auth0 issues `scope`, and the shared credentials-exchange Action mirrors the issued access-token scopes into the top-level `permissions` claim for backend consistency.**

### M2M Clients

| Client                     | Purpose                | Auth Model                  |
| -------------------------- | ---------------------- | --------------------------- |
| Rule Engine M2M            | Runtime rule execution | Client Credentials + scopes |
| Transaction Ingestion M2M  | Kafka/API ingestion    | Client Credentials + scopes |
| Rule Management M2M        | Testing & automation   | Client Credentials + scopes |
| Transaction Management M2M | Testing & automation   | Client Credentials + scopes |

### M2M Scopes by API

**Rule Engine API:**

```
execute:rules
read:results
replay:transactions
read:metrics
```

**Rule Management API:**

```
rule:create
rule:update
rule:submit
rule:approve
rule:reject
rule:read
```

**Transaction Management API:**

```
txn:view
txn:comment
txn:flag
txn:recommend
txn:approve
txn:block
txn:override
```

---

## 8. JWT Token Contract

### 8.1 Human User Token (Example for Portal Access)

```json
{
  "sub": "auth0|user123",
  "iss": "https://$AUTH0_MGMT_DOMAIN (from Doppler)/",
  "aud": "https://fraud-governance-api",
  "https://fraud-governance-api/roles": ["RULE_MAKER", "RULE_CHECKER"],
  "permissions": ["rule:create", "rule:update", "rule:submit", "rule:approve", "rule:read"],
  "exp": 1737244800
}
```

### 8.2 M2M Token (Example for Rule Engine API)

```json
{
  "sub": "DYpzDimxqmuk0TCizexIdv19qWBJlZo8@clients",
  "iss": "https://$AUTH0_MGMT_DOMAIN (from Doppler)/",
  "aud": "https://fraud-rule-engine-api",
  "scope": "execute:rules read:results replay:transactions read:metrics",
  "gty": "client-credentials",
  "exp": 1737244800
}
```

### 8.3 Token Claims Reference

| Claim         | Human Token                     | M2M Token                 |
| ------------- | ------------------------------ | ------------------------- |
| `sub`         | User ID (`auth0\|xxx`)         | Client ID (`xxx@clients`) |
| `aud`         | Shared portal audience         | API audience              |
| `roles`       | `https://fraud-governance-api/roles` claim | Not present      |
| `permissions` | Array of permissions           | Array mirrored from issued scopes |
| `scope`       | Not present                    | Space-separated scopes    |
| `gty`         | Not present                    | `client-credentials`      |

---

## 9. User Onboarding

### 9.1 How Users Get Access

```
1. User requests access via IT ticket / manager request
        ↓
2. IAM Admin reviews request against job function
        ↓
3. IAM Admin assigns roles in Auth0 Dashboard:
   - Auth0 Dashboard → User Management → Users
   - Find user → Roles tab → Assign Roles
        ↓
4. User logs in via Google OAuth
        ↓
5. Token contains assigned roles + derived permissions
```

### 9.2 Role Assignment Matrix

| Job Function                          | Roles to Assign                     |
| ------------------------------------- | ----------------------------------- |
| Fraud Rule Author                     | `RULE_MAKER`                        |
| Senior Rule Author (can also approve) | `RULE_MAKER`, `RULE_CHECKER`        |
| Rule Approver (review only)           | `RULE_CHECKER`                      |
| Compliance Auditor                    | `RULE_VIEWER`                       |
| Fraud Analyst                         | `FRAUD_ANALYST`                     |
| Fraud Team Lead                       | `FRAUD_ANALYST`, `FRAUD_SUPERVISOR` |
| Fraud Operations Manager              | `FRAUD_SUPERVISOR`                  |
| Platform Administrator                | `PLATFORM_ADMIN`                    |

### 9.3 Auth0 Dashboard Steps

1. **Navigate to Users:**

   ```
   Auth0 Dashboard → User Management → Users
   ```

2. **Find User:**
   - Search by email or name
   - Click on user to open details

3. **Assign Roles:**

   ```
   User Details → Roles tab → Assign Roles → Select roles → Assign
   ```

4. **Verify Assignment:**
   - User's Roles tab shows assigned roles
   - User can log in and access appropriate features

### 9.4 Programmatic Role Assignment (via Management API)

```bash
# Get Management API token
TOKEN=$(curl -s --request POST \
  --url "https://$AUTH0_MGMT_DOMAIN/oauth/token" \
  --header 'content-type: application/json' \
  --data '{"client_id":"<mgmt-client-id>","client_secret":"<mgmt-secret>","audience":"https://$AUTH0_MGMT_DOMAIN/api/v2/","grant_type":"client_credentials"}' \
  | jq -r '.access_token')

# Assign role to user
curl --request POST \
  --url "https://$AUTH0_MGMT_DOMAIN/api/v2/users/<user-id>/roles" \
  --header "Authorization: Bearer $TOKEN" \
  --header 'content-type: application/json' \
  --data '{"roles": ["<role-id>"]}'
```

---

## 10. Test Users for Automation

### 10.1 Test User Strategy

Each project has dedicated test users for Playwright/E2E testing:

| Test User                 | Email                                         | Roles                        | Used By                        |
| ------------------------- | --------------------------------------------- | ---------------------------- | ------------------------------ |
| `test-platform-admin`     | `test-platform-admin@fraud-platform.test`     | `PLATFORM_ADMIN`             | All projects                   |
| `test-rule-maker`         | `test-rule-maker@fraud-platform.test`         | `RULE_MAKER`                 | rule-management, portal        |
| `test-rule-checker`       | `test-rule-checker@fraud-platform.test`       | `RULE_CHECKER`               | rule-management, portal        |
| `test-rule-maker-checker` | `test-rule-maker-checker@fraud-platform.test` | `RULE_MAKER`, `RULE_CHECKER` | rule-management, portal        |
| `test-fraud-analyst`      | `test-fraud-analyst@fraud-platform.test`      | `FRAUD_ANALYST`              | transaction-management, portal |
| `test-fraud-supervisor`   | `test-fraud-supervisor@fraud-platform.test`   | `FRAUD_SUPERVISOR`           | transaction-management, portal |

### 10.2 Test User Credentials

Test users use **Username-Password-Authentication** connection (not Google OAuth).

Store credentials in Doppler per project:

```yaml
# Doppler secrets for testing
TEST_USER_PLATFORM_ADMIN_EMAIL: test-platform-admin@fraud-platform.test
TEST_USER_PLATFORM_ADMIN_PASSWORD: <secure-password>

TEST_USER_RULE_MAKER_EMAIL: test-rule-maker@fraud-platform.test
TEST_USER_RULE_MAKER_PASSWORD: <secure-password>

TEST_USER_RULE_CHECKER_EMAIL: test-rule-checker@fraud-platform.test
TEST_USER_RULE_CHECKER_PASSWORD: <secure-password>

# ... etc
```

### 10.3 Creating Test Users (Bootstrap Script)

Test users are created by the rule-management bootstrap script:

```python
TEST_USERS = [
    {
        "email": "test-platform-admin@fraud-platform.test",
        "password": os.getenv("TEST_USER_PLATFORM_ADMIN_PASSWORD"),
        "roles": ["PLATFORM_ADMIN"],
    },
    {
        "email": "test-rule-maker@fraud-platform.test",
        "password": os.getenv("TEST_USER_RULE_MAKER_PASSWORD"),
        "roles": ["RULE_MAKER"],
    },
    # ... etc
]
```

### 10.4 Using Test Users in Playwright

```typescript
// playwright/auth.setup.ts
import { test as setup } from "@playwright/test";

const testUsers = {
  ruleMaker: {
    email: process.env.TEST_USER_RULE_MAKER_EMAIL,
    password: process.env.TEST_USER_RULE_MAKER_PASSWORD,
  },
  ruleChecker: {
    email: process.env.TEST_USER_RULE_CHECKER_EMAIL,
    password: process.env.TEST_USER_RULE_CHECKER_PASSWORD,
  },
  // ... etc
};

setup("authenticate as rule maker", async ({ page }) => {
  await page.goto("/login");
  await page.fill('[name="email"]', testUsers.ruleMaker.email);
  await page.fill('[name="password"]', testUsers.ruleMaker.password);
  await page.click('[type="submit"]');
  await page.waitForURL("/dashboard");

  // Save auth state
  await page.context().storageState({ path: ".auth/rule-maker.json" });
});
```

---

## 11. Segregation of Duties (SoD)

### 11.1 Rule Governance SoD

**Rule:** A user cannot approve a rule they created.

**Enforcement:** Backend logic (not Auth0 roles)

```python
# FastAPI example
if ruleset.created_by == current_user.sub:
    raise HTTPException(
        status_code=403,
        detail="Self-approval is not allowed"
    )
```

### 11.2 Fraud Operations SoD

- Analyst cannot finalize decisions
- Supervisor actions always override prior recommendations
- All overrides must be audited with reason

---

## 12. Project-Specific Enforcement

### card-fraud-rule-management

- Enforce `rule:*` permissions
- Enforce no self-approval (SoD)
- Audit all state transitions
- Create shared roles + permissions in Auth0

### card-fraud-rule-engine-auth/card-fraud-rule-engine-monitoring

- **No human tokens allowed**
- Accept only M2M tokens with execution scopes
- Validate `scope` claim (not roles)

### card-fraud-transaction-management

- Enforce `txn:*` permissions
- Supervisor overrides logged explicitly
- Does not create roles (uses shared roles)

### card-fraud-intelligence-portal

- UI visibility based on `permissions` claim
- Disable actions user is not authorized to perform
- Disable approve button for self-created rules
- Request the shared portal user token and reuse it for rule, transaction, and ops-analyst API calls

---

## 13. Authorization Flow Diagrams

### Human User Flow

```
User (Google OAuth)
        ↓
    Auth0 Login
        ↓
    ID Token + Access Token (shared portal audience, roles + permissions)
        ↓
    React SPA (Intelligence Portal)
        ├─→ Rule Management API
        ├─→ Transaction Management API
        └─→ Ops Analyst Agent API
```

### M2M Flow

```
Backend Service
        ↓
    Client Credentials Grant
        ↓
    Access Token (with scopes)
        ↓
    Rule Engine API (checks scopes)
```

---

## 14. Prohibited Practices

- Reusing generic roles (MAKER/CHECKER) across domains
- Encoding business logic into Auth0 rules/actions
- Using roles instead of permissions in backend authorization
- Giving roles to service accounts
- Silent privilege escalation
- Self-approval without backend validation
- Hardcoding role names in frontend (use permissions)

---

## 15. Change Management

1. Any change to this file requires review
2. Role or permission changes must be reflected in:
   - Auth0 Dashboard
   - All backend services
   - UI authorization logic
   - Bootstrap scripts
3. The platform auth docs are the **single source of truth**
4. This file must remain synchronized with the platform auth contract

---

## 16. Migration from Old Role Model

**Status:** COMPLETE (2026-03-22)

The migration from per-service audiences to a unified audience is complete:
- Unified API `https://fraud-governance-api` has 30 scopes (rule + txn + ops_agent)
- API renamed to "Fraud Governance Unified API" in Auth0
- All 6 roles have correct permission assignments on the unified API
- All 3 backend services accept the unified audience for human tokens
- SPA client has correct callback URLs (`/callback` path)
- E2E test client has password-realm grants for unified audience
- Per-service audiences retained for M2M tokens only

### Legacy Roles (already removed)

| Old Role  | Replacement                                            |
| --------- | ------------------------------------------------------ |
| `ADMIN`   | `PLATFORM_ADMIN`                                       |
| `MAKER`   | `RULE_MAKER` or `FRAUD_ANALYST` (domain-specific)      |
| `CHECKER` | `RULE_CHECKER` or `FRAUD_SUPERVISOR` (domain-specific) |

---

## 17. Quick Reference

### Auth0 Dashboard URLs

- Tenant: https://manage.auth0.com/dashboard/us/your-tenant
- Users: https://manage.auth0.com/dashboard/us/your-tenant/users
- Roles: https://manage.auth0.com/dashboard/us/your-tenant/roles
- APIs: https://manage.auth0.com/dashboard/us/your-tenant/apis

### Bootstrap Commands

```powershell
# Rule Management (creates shared roles + permissions and deploys the shared
# credentials-exchange Action that mirrors issued M2M scopes into `permissions`)
cd <path-to>/card-fraud-rule-management
uv run auth0-bootstrap --yes --verbose

# Rule Engine (scope-based only)
cd <path-to>/card-fraud-rule-engine-auth/card-fraud-rule-engine-monitoring
uv run auth0-bootstrap --yes --verbose

# Transaction Management (uses shared roles)
cd <path-to>/card-fraud-transaction-management
uv run auth0-bootstrap --yes --verbose
```

### Verification Commands

```powershell
uv run auth0-verify
```

---

## Appendix A: Doppler Secrets Reference

### Shared Across All Backend Projects

```yaml
AUTH0_MGMT_DOMAIN: $AUTH0_MGMT_DOMAIN (from Doppler)
AUTH0_MGMT_CLIENT_ID: <management-m2m-id>
AUTH0_MGMT_CLIENT_SECRET: <management-m2m-secret>
AUTH0_DOMAIN: $AUTH0_MGMT_DOMAIN (from Doppler)
```

### Project-Specific

```yaml
# card-fraud-rule-management
AUTH0_AUDIENCE: https://fraud-governance-api          # Unified audience (human + M2M)
AUTH0_USER_AUDIENCE: https://fraud-governance-api     # Same — portal tokens use this
AUTH0_CLIENT_ID: <rule-mgmt-m2m-id>                  # From Doppler
AUTH0_CLIENT_SECRET: <rule-mgmt-m2m-secret>           # From Doppler

# card-fraud-rule-engine-auth/card-fraud-rule-engine-monitoring
AUTH0_AUDIENCE: https://fraud-rule-engine-api          # Engine uses its own M2M audience
AUTH0_CLIENT_ID: <rule-engine-m2m-id>
AUTH0_CLIENT_SECRET: <rule-engine-m2m-secret>

# card-fraud-transaction-management
AUTH0_AUDIENCE: https://fraud-governance-api           # Unified audience
AUTH0_USER_AUDIENCE: https://fraud-governance-api
AUTH0_CLIENT_ID: <txn-mgmt-m2m-id>
AUTH0_CLIENT_SECRET: <txn-mgmt-m2m-secret>

# card-fraud-ops-analyst-agent
AUTH0_AUDIENCE: https://fraud-governance-api           # Unified audience
AUTH0_USER_AUDIENCE: https://fraud-governance-api
AUTH0_CLIENT_ID: <ops-analyst-m2m-id>
AUTH0_CLIENT_SECRET: <ops-analyst-m2m-secret>
```

> **Note:** All backend services that accept portal (human) tokens validate `AUTH0_AUDIENCE = https://fraud-governance-api`. The rule engine is M2M-only and retains its own audience.

---

## Appendix B: Code Change Checklist

When implementing this auth model, the following code changes are required:

### Backend Services (FastAPI/Quarkus)

- [ ] Update role checks from `ADMIN/MAKER/CHECKER` to new role names
- [ ] Implement permission-based authorization (not role-based)
- [ ] Add SoD enforcement for self-approval
- [ ] Update OpenAPI security schemes

### React UI (Intelligence Portal)

- [ ] Update `useRoles` hook for shared portal role claims
- [ ] Update permission-based UI visibility
- [ ] Implement self-approval button disable logic
- [ ] Keep the shared portal audience in the SPA token path

### Bootstrap Scripts

- [ ] Update `DEFAULT_ROLES` to new role definitions
- [ ] Add permission creation logic
- [ ] Add test user creation logic
- [ ] Update verification scripts

---

**End of Document**
