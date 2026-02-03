# Neon API Reference

This document cross-references the Neon API calls used in `scripts/setup_neon.py` with the official Neon API documentation.

**Official API Docs:** https://api-docs.neon.tech/

## Environment Mapping

| Environment | Database | Doppler Config | Connection Source |
|-------------|----------|----------------|-------------------|
| **Local** | Docker PostgreSQL 18 | `local` | `localhost:5432` |
| **Test** | Neon `test` branch | `test` | `<test_endpoint_host>` |
| **Production** | Neon `production` branch | `prod` | `<prod_endpoint_host>` |

## API Endpoints Used

| Purpose | Method | Endpoint | Our Code | Neon API Docs |
|---------|--------|----------|----------|---------------|
| List Projects | GET | `/projects` | Line 173, 181 | [listprojects](https://api-docs.neon.tech/reference/listprojects) |
| Create Project | POST | `/projects` | Line 198 | [createproject](https://api-docs.neon.tech/reference/createproject) |
| Delete Project | DELETE | `/projects/{projectId}` | Line 96 | [deleteproject](https://api-docs.neon.tech/reference/deleteproject) |
| List Branches | GET | `/projects/{projectId}/branches` | Line 230 | [listprojectbranches](https://api-docs.neon.tech/reference/listprojectbranches) |
| Create Branch | POST | `/projects/{projectId}/branches` | Line 266 | [createprojectbranch](https://api-docs.neon.tech/reference/createprojectbranch) |
| Get Branch | GET | `/projects/{projectId}/branches/{branchId}` | Line 287 | [getprojectbranch](https://api-docs.neon.tech/reference/getprojectbranch) |
| List Endpoints | GET | `/projects/{projectId}/endpoints` | Line 154, 313 | [listprojectendpoints](https://api-docs.neon.tech/reference/listprojectendpoints) |
| Create Endpoint | POST | `/projects/{projectId}/endpoints` | Line 128 | [createprojectendpoint](https://api-docs.neon.tech/reference/createprojectendpoint) |
| Get Endpoint | GET | `/projects/{projectId}/endpoints/{endpointId}` | Line 154 | [getprojectendpoint](https://api-docs.neon.tech/reference/getprojectendpoint) |
| Get Role Password | GET | `/projects/{projectId}/branches/{branchId}/roles/{roleName}/reveal_password` | Line 333 | [getprojectbranchrolepassword](https://api-docs.neon.tech/reference/getprojectbranchrolepassword) |

## API Usage Examples

### 1. Create Project (PostgreSQL 18)

```python
response = client.post(
    f"{NEON_API_BASE}/projects",
    json={
        "project": {
            "name": "fraud-governance",
            "pg_version": 18,
        }
    },
)
```

**Request Body:**
- `name`: Project name
- `pg_version`: PostgreSQL version (18 for UUIDv7 support)

### 2. Create Branch

```python
response = client.post(
    f"{NEON_API_BASE}/projects/{project_id}/branches",
    json={"branch": {"name": "test"}},
)
```

**Request Body:**
- `name`: Branch name (e.g., "test", "production")

### 3. Create Compute Endpoint

```python
response = client.post(
    f"{NEON_API_BASE}/projects/{project_id}/endpoints",
    json={
        "endpoint": {
            "branch_id": branch_id,
            "type": "read_write",
            "autoscaling_limit": {
                "metric": "cpu",
                "target": 80,
                "min": "0.25",
                "max": "1",
            },
        }
    },
)
```

**Request Body:**
- `branch_id`: Branch ID to attach endpoint to
- `type`: "read_write" for read-write endpoints
- `autoscaling_limit`: Autoscaling configuration
  - `min`: "0.25" - scales to zero after 5 minutes idle (free tier)
  - `max`: "1" - max compute
  - `target`: 80 - scale up at 80% CPU

### 4. Get Endpoint Host

```python
response = client.get(f"{NEON_API_BASE}/projects/{project_id}/endpoints")
endpoints = response.json().get("endpoints", [])

for ep in endpoints:
    if ep.get("branch_id") == branch_id:
        host = ep.get("host")
        # host format: ep-xxx-ahpq61dw.c-3.us-east-1.aws.neon.tech
```

**Response:**
```json
{
  "endpoints": [
    {
      "id": "ep-cold-shape-ahpq61dw",
      "host": "ep-cold-shape-ahpq61dw.c-3.us-east-1.aws.neon.tech",
      "branch_id": "br-withered-rice-ah850ikq",
      ...
    }
  ]
}
```

### 5. Get Role Password (neondb_owner)

```python
response = client.get(
    f"{NEON_API_BASE}/projects/{project_id}/branches/{branch_id}/roles/neondb_owner/reveal_password"
)
owner_password = response.json().get("password")
```

**Response:**
```json
{
  "password": "npg_u4ErnovP1UGe"
}
```

## Connection String Format

All Neon connection strings use this format:

```
postgresql://<username>:<password>@<host>/neondb?sslmode=require
```

**Components:**
- `username`: User role (neondb_owner, fraud_gov_app_user, fraud_gov_analytics_user)
- `password`: Password for that user
- `host`: Endpoint host (from API)
- `database`: Always "neondb" (default Neon database)
- `sslmode`: Always "require" (Neon requires SSL)

## Password Workflow

### For Neon Databases (test/prod):

1. **DATABASE_URL_ADMIN**: Uses `neondb_owner` password from `reveal_password` API
2. **DATABASE_URL_APP**: Uses `FRAUD_GOV_APP_PASSWORD` from Doppler (per environment)
3. **DATABASE_URL_ANALYTICS**: Uses `FRAUD_GOV_ANALYTICS_PASSWORD` from Doppler (per environment)

### For Local Docker:

1. **DATABASE_URL_ADMIN**: Uses `POSTGRES_ADMIN_PASSWORD` from Doppler local config
2. **DATABASE_URL_APP**: Uses `FRAUD_GOV_APP_PASSWORD` from Doppler local config
3. **DATABASE_URL_ANALYTICS**: Uses `FRAUD_GOV_ANALYTICS_PASSWORD` from Doppler local config

## Base URL

**Neon API Base URL:** `https://console.neon.tech/api/v2`

All API calls use this base URL. In `scripts/setup_neon.py`:

```python
NEON_API_BASE = "https://console.neon.tech/api/v2"

client = httpx.Client(
    base_url=NEON_API_BASE,
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=30.0,
)
```

## Authentication

All API calls require Bearer token authentication:

```python
headers={"Authorization": f"Bearer {NEON_API_KEY}"}
```

**API Key Source:** Doppler `local` config → `NEON_API_KEY`

**Required API Key Type:** Organization API Key (not personal) for admin access

## PostgreSQL Version

**Version:** 18 (native UUIDv7 support)

When creating a project:
```python
json={"project": {"name": "...", "pg_version": 18}}
```

## Script Usage

```powershell
# Delete existing project
doppler run --config local -- uv run python scripts/setup_neon.py --delete-project --yes

# Create new project with branches and compute endpoints
doppler run --config local -- uv run python scripts/setup_neon.py --yes --create-compute
```

## Script Output

After running `setup_neon.py`, you will get:

```
TEST BRANCH - Copy to Doppler 'test' config:
DATABASE_URL_ADMIN=postgresql://neondb_owner:npg_xxx@ep-xxx-ahpq61dw.../neondb?sslmode=require
DATABASE_URL_APP=postgresql://fraud_gov_app_user:<local_password>@ep-xxx-ahpq61dw.../neondb?sslmode=require
DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:<local_password>@ep-xxx-ahpq61dw.../neondb?sslmode=require
```

**IMPORTANT:** The `DATABASE_URL_APP` and `DATABASE_URL_ANALYTICS` passwords shown above use the LOCAL config passwords. You must replace them with the correct environment-specific passwords when updating Doppler.
