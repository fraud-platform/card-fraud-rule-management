from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import urlopen

SERVICE_ID = "rule-management"
HEALTH_URL = "http://localhost:8000/api/v1/health"
SCHEMA_RESET_ACK_TOKEN = "RESET_SHARED_SCHEMA"

ACTION_MAP: dict[tuple[str, str], dict[str, object]] = {
    ("db", "verify"): {"cmd": ["uv", "run", "db-verify"], "destructive": False},
    ("db", "init"): {"cmd": ["uv", "run", "db-init"], "destructive": False},
    ("db", "db-reset-data"): {"cmd": ["uv", "run", "db-reset-data"], "destructive": True},
    ("db", "db-reset-schema"): {
        "cmd": [
            "uv",
            "run",
            "db-reset-schema",
            "--yes",
            "--schema-reset-ack",
            SCHEMA_RESET_ACK_TOKEN,
        ],
        "destructive": True,
    },
    ("db", "db-reset-tables"): {
        "cmd": ["uv", "run", "db-reset-tables"],
        "destructive": True,
    },
    ("auth", "verify"): {"cmd": ["uv", "run", "auth0-verify"], "destructive": False},
    ("auth", "bootstrap"): {
        "cmd": ["uv", "run", "auth0-bootstrap"],
        "destructive": False,
    },
    ("auth", "cleanup"): {"cmd": ["uv", "run", "auth0-cleanup"], "destructive": True},
    ("seed", "demo"): {"cmd": ["uv", "run", "db-seed-demo"], "destructive": False},
    ("storage", "verify"): {
        "cmd": ["uv", "run", "objstore-local-verify"],
        "destructive": False,
    },
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result(
    domain: str,
    action: str,
    status: str,
    summary: str,
    *,
    destructive: bool = False,
    details: list[str] | None = None,
    error: str | None = None,
    started_at: str,
    completed_at: str,
) -> dict[str, object]:
    return {
        "service": SERVICE_ID,
        "domain": domain,
        "action": action,
        "target": "service",
        "status": status,
        "summary": summary,
        "details": details or [],
        "destructive": destructive,
        "started_at": started_at,
        "completed_at": completed_at,
        "artifacts": [],
        "next_steps": [],
        "error": error,
    }


def _check_health() -> tuple[bool, str]:
    try:
        with urlopen(HEALTH_URL, timeout=5) as response:
            if 200 <= response.status < 300:
                return True, f"Health endpoint reachable at {HEALTH_URL}"
            return False, f"Health endpoint returned HTTP {response.status}"
    except URLError as exc:
        return False, f"Health endpoint unreachable: {exc}"


def _run_command(cmd: list[str]) -> tuple[bool, str, list[str], str | None]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = result.stdout.strip()
    err = result.stderr.strip()
    details = [line for line in (out, err) if line]
    if result.returncode == 0:
        return True, f"Command succeeded: {' '.join(cmd)}", details, None
    return False, f"Command failed ({result.returncode}): {' '.join(cmd)}", details, (err or out or None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rule management platform adapter")
    parser.add_argument("domain")
    parser.add_argument("action")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    args = parser.parse_args()

    started_at = _iso_now()

    if (args.domain, args.action) in {("service", "status"), ("service", "health")}:
        ok, summary = _check_health()
        completed_at = _iso_now()
        payload = _result(
            args.domain,
            args.action,
            "ok" if ok else "error",
            summary,
            started_at=started_at,
            completed_at=completed_at,
        )
        print(json.dumps(payload))
        return 0 if ok else 1

    if (args.domain, args.action) == ("service", "logs"):
        completed_at = _iso_now()
        payload = _result(
            args.domain,
            args.action,
            "ok",
            "Use docker compose logs for rule-management logs",
            details=[
                "docker compose -f docker-compose.yml -f docker-compose.apps.yml logs rule-management"
            ],
            started_at=started_at,
            completed_at=completed_at,
        )
        print(json.dumps(payload))
        return 0

    spec = ACTION_MAP.get((args.domain, args.action))
    if spec is None:
        completed_at = _iso_now()
        payload = _result(
            args.domain,
            args.action,
            "error",
            f"Unsupported action: {args.domain}:{args.action}",
            started_at=started_at,
            completed_at=completed_at,
        )
        print(json.dumps(payload))
        return 2

    ok, summary, details, error = _run_command(spec["cmd"])  # type: ignore[index]
    completed_at = _iso_now()
    payload = _result(
        args.domain,
        args.action,
        "ok" if ok else "error",
        summary,
        destructive=bool(spec["destructive"]),
        details=details,
        error=error,
        started_at=started_at,
        completed_at=completed_at,
    )
    print(json.dumps(payload))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
