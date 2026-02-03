#!/usr/bin/env python3
"""Debug script: call endpoints using FastAPI TestClient to capture exceptions and tracebacks."""

from __future__ import annotations

import os
import traceback

from fastapi.testclient import TestClient

from app.main import create_app

try:
    app = create_app()
    client = TestClient(app)

    # Call a failing endpoint that hits DB-backed code
    print("GET /api/v1/rules ->")
    r = client.get("/api/v1/rules")
    print(r.status_code, r.text)

    print("GET /api/v1/rule-fields (auth) ->")
    token = os.environ.get("AUTH0_TEST_TOKEN") or os.environ.get("AUTH0_ACCESS_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.get("/api/v1/rule-fields", headers=headers)
    print(r.status_code, r.text)

except Exception:
    print("Exception while calling endpoints:")
    traceback.print_exc()
    raise
