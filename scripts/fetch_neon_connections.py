#!/usr/bin/env python3
"""Fetch Neon connection strings using the connection_uri endpoint."""

import os
import sys
import urllib.parse

import httpx

NEON_API_BASE = "https://console.neon.tech/api/v2"
PROJECT_NAME = "fraud-governance"

api_key = os.getenv("NEON_API_KEY")
if not api_key:
    print("ERROR: NEON_API_KEY not found")
    sys.exit(1)

app_password = os.getenv("FRAUD_GOV_APP_PASSWORD", "YOUR_PASSWORD")
analytics_password = os.getenv("FRAUD_GOV_ANALYTICS_PASSWORD", "YOUR_PASSWORD")

client = httpx.Client(
    base_url=NEON_API_BASE,
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=30.0,
)

# Find project
response = client.get(f"{NEON_API_BASE}/projects")
response.raise_for_status()
projects = response.json().get("projects", [])

project = None
for p in projects:
    if p.get("name") == PROJECT_NAME:
        project = p
        break

if not project:
    print(f"ERROR: Project '{PROJECT_NAME}' not found")
    sys.exit(1)

project_id = project["id"]
print(f"Project: {PROJECT_NAME} (ID: {project_id})")
print()

# Get branches
response = client.get(f"{NEON_API_BASE}/projects/{project_id}/branches")
response.raise_for_status()
branches = response.json().get("branches", [])

target_branches = {"test", "production"}

for branch in branches:
    branch_name = branch.get("name")
    branch_id = branch.get("id")

    if branch_name not in target_branches:
        continue

    # Get connection URI from the API
    # GET /projects/{projectId}/connection_uri?branch_id={branch_id}&database_name={database_name}&role_name={role_name}
    response = client.get(
        f"{NEON_API_BASE}/projects/{project_id}/connection_uri",
        params={"branch_id": branch_id, "database_name": "neondb", "role_name": "neondb_owner"},
    )

    if response.status_code != 200:
        print(f"[ERROR] Failed to get connection URI for branch {branch_name}")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        continue

    conn_data = response.json()
    uri = conn_data.get("uri", "")

    if not uri:
        print(f"[ERROR] No URI in response: {conn_data}")
        continue

    # Parse the connection URI to extract host, password, database
    # Format: postgresql://user:password@host/database?params
    parsed = urllib.parse.urlparse(uri)
    host = parsed.hostname or ""
    database = parsed.path.lstrip("/") if parsed.path else "neondb"
    password = parsed.password or ""

    # Remove extra query params from original URI, keep only sslmode
    ssl = "?sslmode=require"

    print("=" * 78)
    print(f"BRANCH: {branch_name}")
    print("=" * 78)
    print()

    print(f"DATABASE_URL_ADMIN=postgresql://neondb_owner:{password}@{host}/{database}{ssl}")
    print(f"DATABASE_URL_APP=postgresql://fraud_gov_app_user:{app_password}@{host}/{database}{ssl}")
    print(
        f"DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:{analytics_password}@{host}/{database}{ssl}"
    )

    print()
    print()
