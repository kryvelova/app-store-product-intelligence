"""Build the `stg_apps` staging table from the raw Postgres table.

Second transformation step: raw -> staging. Loads the raw table first (via
transform.load_raw) so this can be run on its own.

Usage:
    python3 -m transform.build_staging
"""

import sys
from pathlib import Path

from transform.db import get_connection
from transform.load_raw import RAW_CSV, load_raw

STG_APPS_SQL = Path(__file__).resolve().parent / "sql" / "stg_apps.sql"

# Each check is a query returning the number of rows that violate it — 0 means pass.
CHECKS = [
    (
        "unique app_id",
        "SELECT count(*) FROM ("
        "  SELECT app_id FROM stg_apps GROUP BY app_id HAVING count(*) > 1"
        ") dup",
    ),
    ("non-null app_id", "SELECT count(*) FROM stg_apps WHERE app_id IS NULL"),
    ("rating_count >= 0", "SELECT count(*) FROM stg_apps WHERE rating_count < 0"),
    (
        "average_rating between 0 and 5",
        "SELECT count(*) FROM stg_apps WHERE average_rating < 0 OR average_rating > 5",
    ),
    (
        "price >= 0 when not null",
        "SELECT count(*) FROM stg_apps WHERE price IS NOT NULL AND price < 0",
    ),
    (
        "current_version_release_date >= release_date",
        "SELECT count(*) FROM stg_apps WHERE current_version_release_date < release_date",
    ),
]


def build_stg_apps(conn) -> None:
    """Run the staging model SQL against whatever raw_app_store_metadata is."""
    with conn.cursor() as cur:
        cur.execute(STG_APPS_SQL.read_text())


def run_checks(conn) -> list[tuple[str, int]]:
    """Run each data-quality check and return (name, violation_count) pairs."""
    results = []
    with conn.cursor() as cur:
        for name, query in CHECKS:
            cur.execute(query)
            results.append((name, cur.fetchone()[0]))
    return results


def main() -> None:
    if not RAW_CSV.exists():
        print(f"Error: raw CSV not found at {RAW_CSV}", file=sys.stderr)
        sys.exit(1)

    conn = get_connection()
    try:
        load_raw(conn, RAW_CSV)
        build_stg_apps(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM stg_apps")
            row_count = cur.fetchone()[0]
        print(f"Built stg_apps: {row_count} row(s)")

        results = run_checks(conn)
        for name, violations in results:
            status = "PASS" if violations == 0 else "FAIL"
            print(f"[{status}] {name} ({violations} violation(s))")

        if any(violations != 0 for _, violations in results):
            print("Error: one or more data-quality checks failed.", file=sys.stderr)
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
