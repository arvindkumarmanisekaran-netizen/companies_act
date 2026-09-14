#!/usr/bin/env python3

from pathlib import Path

import psycopg

from backend.app.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def main() -> int:
    settings = get_settings()
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print("No migrations found")
        return 0

    with psycopg.connect(settings.database_url) as connection:
        for path in migration_files:
            sql = path.read_text(encoding="utf-8")
            print(f"Applying {path.name} ...")
            with connection.cursor() as cursor:
                cursor.execute(sql)
            connection.commit()

    print("Migrations complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
