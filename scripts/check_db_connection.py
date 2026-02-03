#!/usr/bin/env python3
"""Check DB connection using SQLAlchemy and report DB/session state.

Useful for debugging Neon credentials and schema/search_path issues.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine


def main() -> int:
    url = os.environ.get("DATABASE_URL_APP")

    if not url:
        print(
            "DATABASE_URL_APP not set. Run with Doppler, for example: "
            "`doppler run -- uv run python scripts/check_db_connection.py`.",
            file=sys.stderr,
        )
        return 2

    try:
        # Align with application DB engine (use psycopg driver)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        # Prefer the application's engine setup so we can validate its
        # connect-time search_path behavior.
        engine = None
        try:
            from app.core.db import get_engine as get_app_engine

            engine = get_app_engine()
            print("Using app.core.db.get_engine()")
        except Exception:
            engine = create_engine(url, pool_pre_ping=True)
            print("Using standalone create_engine()")
        conn = engine.connect()
        try:
            from sqlalchemy import text

            def scalar(sql: str) -> str | None:
                return conn.execute(text(sql)).scalar_one_or_none()

            # Basic identity and session state
            print("Session info:")
            print("- current_database:", scalar("select current_database()"))
            print("- current_user:", scalar("select current_user"))
            print("- current_schema:", scalar("select current_schema()"))
            print("- search_path:", scalar("show search_path"))
            print("- to_regclass('rulesets'):", scalar("select to_regclass('rulesets')"))
            print(
                "- to_regclass('fraud_gov.rulesets'):",
                scalar("select to_regclass('fraud_gov.rulesets')"),
            )

            # Apply search_path and re-check resolution
            conn.execute(text("SET search_path TO fraud_gov, public"))
            print("After SET search_path TO fraud_gov, public:")
            print("- current_schema:", scalar("select current_schema()"))
            print("- search_path:", scalar("show search_path"))
            print("- to_regclass('rulesets'):", scalar("select to_regclass('rulesets')"))

            # If the table is visible, try a tiny query to confirm
            try:
                conn.execute(text("select 1 from rulesets limit 1")).fetchone()
                print("- select from rulesets: OK")
            except Exception as exc:
                print("- select from rulesets: FAILED:", type(exc).__name__, exc)

            # Check both public and fraud_gov schemas
            stmt = text(
                "select schemaname, tablename from pg_tables where schemaname in ('public','fraud_gov') order by schemaname, tablename"
            )
            rows = conn.execute(stmt).fetchall()
            if rows:
                print("OK: connection successful; tables found:")
                for schemaname, tablename in rows:
                    print(f"- {schemaname}.{tablename}")
            else:
                print("OK: connection successful; no tables found in public or fraud_gov schema")
        except Exception as exc:
            print("Connected but failed to list tables:", exc)
        finally:
            conn.close()
        return 0
    except Exception as exc:
        print("ERROR: failed to connect:")
        print(type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
