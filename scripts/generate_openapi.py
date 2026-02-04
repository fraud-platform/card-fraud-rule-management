#!/usr/bin/env python3
"""
Generate OpenAPI JSON schema for the FastAPI application.

Usage:
  uv run python scripts/generate_openapi.py
"""

import json
import os
from pathlib import Path

# Set minimal environment for OpenAPI generation (no DB required)
os.environ.setdefault("DATABASE_URL_APP", "postgresql://localhost/db")
os.environ.setdefault("AUTH0_DOMAIN", "test.local")
os.environ.setdefault("AUTH0_AUDIENCE", "test-audience")

from app.main import create_app


def main():
    """Generate OpenAPI JSON and save to docs/03-api/openapi.json."""
    app = create_app()
    openapi_schema = app.openapi()

    # Ensure docs directory exists
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)

    # Write OpenAPI JSON
    output_file = docs_dir / "openapi.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2)
        f.write("\n")  # Add trailing newline

    print(f"[OK] OpenAPI schema generated: {output_file}")
    print(f"   Title: {openapi_schema['info']['title']}")
    print(f"   Version: {openapi_schema['info']['version']}")
    print(f"   Endpoints: {len(openapi_schema['paths'])} paths")

    # Print summary
    print("\nEndpoint Summary (first 10):")
    for path, methods in list(openapi_schema["paths"].items())[:10]:
        for method, details in methods.items():
            tags = details.get("tags", [""])
            summary = details.get("summary", "No summary")
            print(f"   {method.upper():6} {path:40} [{tags[0]}] {summary}")

    if len(openapi_schema["paths"]) > 10:
        print(f"\n   ... and {len(openapi_schema['paths']) - 10} more paths")


if __name__ == "__main__":
    main()
