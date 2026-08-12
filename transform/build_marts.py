"""Build the `mart_app_category_engagement` mart from `stg_apps`.

Third transformation step: staging -> mart. Rebuilds the raw table and
stg_apps first so this can be run on its own.

Usage:
    python3 -m transform.build_marts
"""

import sys
from pathlib import Path

from transform.build_staging import build_stg_apps
from transform.db import get_connection
from transform.load_raw import RAW_CSV, load_raw

MART_SQL = Path(__file__).resolve().parent / "sql" / "mart_app_category_engagement.sql"

# Each check is a query returning the number of rows that violate it — 0 means pass.
CHECKS = [
    (
        "unique (platform, primary_genre) grain",
        "SELECT count(*) FROM ("
        "  SELECT platform, primary_genre FROM mart_app_category_engagement"
        "  GROUP BY platform, primary_genre HAVING count(*) > 1"
        ") dup",
    ),
    (
        "rated_app_count <= app_count",
        "SELECT count(*) FROM mart_app_category_engagement WHERE rated_app_count > app_count",
    ),
    (
        "rating_coverage_pct between 0 and 100",
        "SELECT count(*) FROM mart_app_category_engagement "
        "WHERE rating_coverage_pct < 0 OR rating_coverage_pct > 100",
    ),
    (
        "avg_rating between 0 and 5",
        "SELECT count(*) FROM mart_app_category_engagement "
        "WHERE avg_rating < 0 OR avg_rating > 5",
    ),
    (
        "app_count sums to stg_apps row count",
        "SELECT abs("
        "  (SELECT SUM(app_count) FROM mart_app_category_engagement)"
        "  - (SELECT count(*) FROM stg_apps)"
        ")",
    ),
]


def build_mart(conn) -> None:
    """Run the mart SQL against whatever stg_apps already is."""
    with conn.cursor() as cur:
        cur.execute(MART_SQL.read_text())


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
        build_mart(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM mart_app_category_engagement")
            row_count = cur.fetchone()[0]
        print(f"Built mart_app_category_engagement: {row_count} row(s)")

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
