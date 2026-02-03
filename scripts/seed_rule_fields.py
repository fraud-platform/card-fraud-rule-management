import os
import sys
from pathlib import Path

import psycopg


def main() -> int:
    database_url = os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL")
    if not database_url:
        print("Missing DATABASE_URL_ADMIN (or DATABASE_URL)", file=sys.stderr)
        return 2

    sql_path = Path(__file__).resolve().parents[1] / "db" / "seed_rule_fields.sql"
    sql = sql_path.read_text(encoding="utf-8")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    print(f"Seeded rule fields via {sql_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
