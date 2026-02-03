#!/usr/bin/env python3
"""
Local API test runner

- Starts the app server (using `uv run uvicorn app.main:app`) unless --no-server is used
- Waits for readiness on `/api/v1/health`
- Executes a set of HTTP checks described in `scripts/local_endpoints.json` (or a custom file)
- Prints a summary and exits with non-zero code if any check fails

Usage (from repo root, inside `uv` environment):
  uv run python scripts/local_api_tests.py --port 8000
  uv run python scripts/local_api_tests.py --no-server --base-url http://127.0.0.1:8000
  uv run python scripts/local_api_tests.py --endpoints scripts/local_endpoints.json --auth-token "Bearer ..."

This script is intended for quick, repeatable 'live local' checks. For CI and deterministic integration tests, prefer pytest test cases.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# Add app to path for imports
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.dotenv import (  # noqa: E402 (import after path setup)
    find_env_file,
    load_env_file,
)

DEFAULT_ENDPOINTS = Path(__file__).resolve().parent / "local_endpoints.json"


def _normalize_bearer_token(token: str | None) -> str | None:
    if token is None:
        return None
    t = token.strip()
    if not t:
        return None
    # Accept either a full "Bearer ..." string or a raw JWT.
    if t.lower().startswith("bearer "):
        return "Bearer " + t.split(None, 1)[1].strip()
    if t.count(".") == 2:
        return f"Bearer {t}"
    return t


def _default_env_file() -> str | None:
    candidate = find_env_file()
    return str(candidate) if candidate else None


def start_server(port: int) -> subprocess.Popen:
    # Start uvicorn via the 'uv' helper so the virtual env and dev deps are present
    cmd = ["uv", "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    print("Starting server:", " ".join(cmd))
    # Important: do NOT pipe stdout/stderr without draining them.
    # On Windows, uvicorn logs can fill the pipe buffer and deadlock the server,
    # causing downstream requests to time out.
    proc = subprocess.Popen(cmd)
    return proc


def fetch_auth0_token(
    *,
    domain: str,
    audience: str,
    client_id: str,
    client_secret: str,
) -> str:
    """Fetch an Auth0 access token via Client Credentials grant.

    Requires a Machine-to-Machine app in Auth0 with access to the API identified
    by AUTH0_AUDIENCE.
    """
    url = f"https://{domain}/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": audience,
    }
    r = httpx.post(url, json=payload, timeout=10.0)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Auth0 token response missing access_token")
    normalized = _normalize_bearer_token(token)
    if not normalized:
        raise RuntimeError("Auth0 token normalization failed")
    return normalized


def load_endpoints(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data


def _is_expected(actual_status: int, expected: Any) -> bool:
    if isinstance(expected, int):
        return actual_status == expected
    if isinstance(expected, list):
        return actual_status in expected
    return actual_status == 200


def _token_for_endpoint(
    ep: dict[str, Any],
    user_token: str | None,
    admin_token: str | None,
    maker_token: str | None,
    checker_token: str | None,
) -> str | None:
    auth = ep.get("auth")
    if auth is None:
        return None
    if auth == "user":
        return user_token
    if auth == "admin":
        return admin_token or user_token
    if auth == "maker":
        return maker_token or user_token
    if auth == "checker":
        return checker_token or user_token
    return user_token


def wait_for_ready(base_url: str, timeout: int = 20) -> bool:
    deadline = time.time() + timeout
    client = httpx.Client()
    health_url = base_url.rstrip("/") + "/api/v1/health"
    print("Waiting for server readiness at", health_url)
    while time.time() < deadline:
        try:
            r = client.get(health_url, timeout=2.0)
            if r.status_code == 200:
                print("Server is ready")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    print("Timed out waiting for server readiness")
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8000, help="Port to start the server on")
    p.add_argument(
        "--endpoints",
        type=str,
        default=str(DEFAULT_ENDPOINTS),
        help="JSON file with endpoints to check",
    )
    p.add_argument(
        "--env-file",
        type=str,
        default=None,
        help="Optional .env file path to pass to the server via ENV_FILE (defaults to ./.env if present)",
    )
    p.add_argument("--auth-token", type=str, default=None, help="Alias for --user-token")
    p.add_argument(
        "--user-token",
        type=str,
        default=None,
        help="Authorization token for authenticated read endpoints (e.g. 'Bearer ...')",
    )
    p.add_argument(
        "--admin-token",
        type=str,
        default=None,
        help="Authorization token with ADMIN role (optional)",
    )
    p.add_argument(
        "--maker-token",
        type=str,
        default=None,
        help="Authorization token with MAKER role (optional)",
    )
    p.add_argument(
        "--checker-token",
        type=str,
        default=None,
        help="Authorization token with CHECKER role (optional)",
    )
    p.add_argument(
        "--auth0-client-id",
        type=str,
        default=None,
        help="Auth0 M2M client id (optional; falls back to env AUTH0_CLIENT_ID)",
    )
    p.add_argument(
        "--auth0-client-secret",
        type=str,
        default=None,
        help="Auth0 M2M client secret (optional; falls back to env AUTH0_CLIENT_SECRET)",
    )
    p.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="If provided, skip server start and target this base URL (use with --no-server)",
    )
    p.add_argument(
        "--no-server",
        action="store_true",
        help="Do not start the server; assume a server is already running at --base-url or http://127.0.0.1:PORT",
    )
    p.add_argument("--timeout", type=int, default=20, help="Timeout waiting for server readiness")
    p.add_argument(
        "--request-timeout", type=float, default=10.0, help="Timeout (seconds) for each request"
    )
    args = p.parse_args(argv)

    base_url = args.base_url or f"http://127.0.0.1:{args.port}"
    proc = None
    started_server = False

    env_file = args.env_file or os.environ.get("ENV_FILE") or _default_env_file()

    # Load vars from env_file into THIS process too (so token fetching works),
    # without overwriting existing env vars.
    if env_file:
        load_env_file(env_file)

    user_token = _normalize_bearer_token(args.user_token or args.auth_token)
    admin_token = _normalize_bearer_token(args.admin_token)
    maker_token = _normalize_bearer_token(args.maker_token)
    checker_token = _normalize_bearer_token(args.checker_token)

    # If user token wasn't provided, optionally fetch via Auth0 client credentials.
    if not user_token:
        client_id = (
            args.auth0_client_id or os.environ.get("AUTH0_CLIENT_ID") or ""
        ).strip() or None
        client_secret = (
            args.auth0_client_secret or os.environ.get("AUTH0_CLIENT_SECRET") or ""
        ).strip() or None
        domain = (os.environ.get("AUTH0_DOMAIN") or "").strip() or None
        audience = (os.environ.get("AUTH0_AUDIENCE") or "").strip() or None
        if client_id and client_secret and domain and audience:
            try:
                user_token = fetch_auth0_token(
                    domain=domain,
                    audience=audience,
                    client_id=client_id,
                    client_secret=client_secret,
                )
                print("Obtained Auth0 access token via client credentials")
            except Exception as exc:
                print(f"WARNING: failed to fetch Auth0 token: {exc}")

    try:
        if not args.no_server:
            if env_file:
                # Pass ENV_FILE to the server process so Pydantic Settings can load your .env.
                os.environ["ENV_FILE"] = env_file

            proc = start_server(args.port)
            started_server = True
            # wait for readiness
            ok = wait_for_ready(base_url, timeout=args.timeout)
            if not ok:
                if proc:
                    proc.kill()
                return 2

            # Optional: perform a quick DB connectivity check to surface auth/connection
            try:
                from sqlalchemy.exc import OperationalError

                from app.core.db import get_engine

                try:
                    eng = get_engine()
                    conn = eng.connect()
                    conn.close()
                except RuntimeError:
                    # DATABASE_URL_APP not set; don't block tests but warn
                    print("WARNING: DATABASE_URL_APP is not set; DB-backed endpoints will fail.")
                except OperationalError as exc:
                    print("ERROR: database connectivity/authentication check failed:", exc)
                    print(
                        "Hint: verify your DATABASE_URL_APP credentials and that the user has permissions; try connecting with psql to confirm."
                    )
                    if proc:
                        proc.kill()
                    return 3
            except Exception:
                # SQLAlchemy might not be available or import failed; skip silently
                pass
        else:
            print("Skipping server start; targeting:", base_url)

        endpoints = load_endpoints(Path(args.endpoints))
        client = httpx.Client()
        results = []

        # Variable store for templating and saved values from responses
        variables: dict[str, str] = {}
        variables.setdefault("ts", str(int(time.time())))
        variables.setdefault("run_id", str(int(time.time() * 1000)))

        # Teardown actions to run after checks (LIFO)
        teardowns: list[dict] = []

        def _format_value(val: str) -> str:
            # Safe formatting that doesn't error on missing keys
            class SafeDict(dict):
                def __missing__(self, key):
                    return "{" + key + "}"

            try:
                return val.format_map(SafeDict(variables))
            except Exception:
                return val

        def _format_json(obj):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return {k: _format_json(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_format_json(v) for v in obj]
            if isinstance(obj, str):
                return _format_value(obj)
            return obj

        import re

        def _extract_json_path(data: dict | list, path: str):
            """
            Extract a value from nested JSON using a simple path syntax.

            Supported syntax examples:
              - "rule_id" -> top-level field
              - "data.id" -> nested dict
              - "items[0].id" -> list index

            Returns the found value (could be dict, list, str, number) or None.
            """
            if not path:
                return None
            cur = data
            # Split on dots but keep array indexes attached to the token (e.g., items[0])
            tokens = path.split(".")
            for tok in tokens:
                m = re.match(r"^(?P<key>[^\[]+)(?:\[(?P<idx>\d+)\])?$", tok)
                if not m:
                    return None
                key = m.group("key")
                idx = m.group("idx")

                # Traverse dict by key or list by numeric key
                if isinstance(cur, dict):
                    if key not in cur:
                        return None
                    cur = cur[key]
                elif isinstance(cur, list):
                    # When current node is a list, the token key should be an integer index
                    try:
                        i = int(key)
                        cur = cur[i]
                    except Exception:
                        return None
                else:
                    return None

                # If an index like [0] was present, apply it
                if idx is not None:
                    if not isinstance(cur, list):
                        return None
                    try:
                        cur = cur[int(idx)]
                    except Exception:
                        return None

            return cur

        # Discover an available field to use for idempotent metadata tests
        try:
            # Use user auth if available, otherwise skip discovery
            if user_token:
                fh = httpx.Client()
                r = fh.get(
                    base_url.rstrip("/") + "/api/v1/rule-fields",
                    headers={"Authorization": user_token},
                    timeout=3.0,
                )
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list) and data:
                        variables.setdefault("any_field", data[0].get("field_key"))
                        print("Discovered field for metadata tests:", variables.get("any_field"))
        except Exception:
            pass

        for ep in endpoints:
            raw_path = ep.get("path", "")
            url = base_url.rstrip("/") + _format_value(raw_path)
            method = ep.get("method", "GET").upper()

            token = _token_for_endpoint(ep, user_token, admin_token, maker_token, checker_token)
            if ep.get("auth") and not token:
                print(
                    f"{ep.get('name', '?'):30s} {method:6s} {ep.get('path', ''):40s} -> SKIP (no token)"
                )
                results.append((ep.get("name", "?"), True, None, "SKIPPED"))
                continue

            token = _normalize_bearer_token(token)
            headers = {"Authorization": token} if token else None

            payload = _format_json(ep.get("json"))

            # Skip endpoints that reference variables we haven't saved yet (e.g., {field_key})
            tokens = re.findall(r"\{([^}]+)\}", raw_path or "")
            # Also scan the JSON payload for variable tokens
            try:
                payload_str = json.dumps(ep.get("json") or {})
            except Exception:
                payload_str = ""
            tokens += re.findall(r"\{([^}]+)\}", payload_str)
            missing = [t for t in set(tokens) if t not in variables]
            if missing:
                print(
                    f"{ep.get('name', '?'):30s} {method:6s} {ep.get('path', ''):40s} -> SKIP (missing vars: {', '.join(missing)})"
                )
                results.append(
                    (ep.get("name", "?"), True, None, f"SKIPPED (missing: {','.join(missing)})")
                )
                continue

            try:
                r = client.request(
                    method, url, json=payload, headers=headers, timeout=args.request_timeout
                )

                ok = _is_expected(r.status_code, ep.get("expected_status", 200))

                # If endpoint is optional, treat non-expected as SKIP (not failure)
                if not ok and ep.get("optional"):
                    print(
                        f"{ep.get('name', '?'):30s} {method:6s} {ep.get('path', ''):40s} -> SKIP (optional) {r.status_code}"
                    )
                    results.append((ep.get("name", "?"), True, r.status_code, "SKIPPED (optional)"))
                    # Do not register teardown when optional failed
                    continue

                # Register teardown only on success (so we don't attempt teardown for failed create)
                teardown_spec = ep.get("teardown")
                if teardown_spec and ok:
                    tb = {
                        "method": teardown_spec.get("method", "DELETE").upper(),
                        "path": teardown_spec.get("path", raw_path),
                        "auth": teardown_spec.get("auth", ep.get("auth")),
                    }
                    teardowns.append(tb)

                results.append((ep.get("name", "?"), ok, r.status_code, r.text[:400]))
                status = "OK" if ok else f"FAIL ({r.status_code})"
                print(f"{ep.get('name', '?'):30s} {method:6s} {ep.get('path', ''):40s} -> {status}")
                if not ok:
                    print("  Response:", r.text[:400])

                # Save values from JSON response if requested
                save_spec = ep.get("save")
                if save_spec and r is not None and r.status_code < 400:
                    try:
                        j = r.json()
                        specs = save_spec if isinstance(save_spec, list) else [save_spec]
                        for s in specs:
                            name = s.get("name")
                            json_path = s.get("json_path", name)
                            as_list = s.get("as_list", False)
                            if not name or not json_path:
                                continue
                            value = _extract_json_path(j, json_path)
                            if value is None:
                                continue
                            # If a list is returned and as_list is True, join values; otherwise pick first
                            if isinstance(value, list):
                                if as_list:
                                    variables[name] = ",".join(str(x) for x in value)
                                else:
                                    variables[name] = str(value[0]) if value else ""
                            else:
                                variables[name] = str(value)
                            print(f"  Saved variable: {name}={variables[name]}")
                    except Exception:
                        pass

            except Exception as exc:
                print(
                    f"{ep.get('name', '?'):30s} {method:6s} {ep.get('path', ''):40s} -> ERROR ({exc})"
                )
                results.append((ep.get("name", "?"), False, None, str(exc)))

        # Run teardowns in reverse order (best-effort)
        if teardowns:
            print("Running teardown actions...")
            for tb in reversed(teardowns):
                tb_method = tb.get("method", "DELETE")
                tb_path = tb.get("path", "")
                tb_auth = tb.get("auth")
                tb_url = base_url.rstrip("/") + _format_value(tb_path)
                tb_token = _token_for_endpoint(
                    {"auth": tb_auth}, user_token, admin_token, maker_token, checker_token
                )
                tb_token = _normalize_bearer_token(tb_token)
                tb_headers = {"Authorization": tb_token} if tb_token else None
                try:
                    tr = client.request(
                        tb_method, tb_url, headers=tb_headers, timeout=args.request_timeout
                    )
                    print(f"TEARDOWN {tb_method} {tb_path} -> {tr.status_code}")
                except Exception as exc:
                    print(f"TEARDOWN {tb_method} {tb_path} -> ERROR ({exc})")

        failed = [r for r in results if not r[1]]
        print(f"\nSummary: {len(results)} checks, {len(failed)} failed")
        return 1 if failed else 0

    finally:
        if started_server and proc:
            print(f"Stopping server (PID {proc.pid})")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
