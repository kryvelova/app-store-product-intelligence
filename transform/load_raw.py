"""Load metadata-US.csv into PostgreSQL as a raw landing table.

First step: CSV -> PostgreSQL. The table is dropped and recreated on every
run (this is a full-snapshot load, not incremental), with every column as
TEXT — no type inference at this layer, on purpose: staging is where
explicit, intentional casting happens (see transform/sql/stg_apps.sql). The
CSV is only ever read, never modified.

Usage:
    python3 -m transform.load_raw
"""

import csv
import sys
from pathlib import Path

from transform.db import get_connection

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = REPO_ROOT / "metadata-US.csv"
RAW_TABLE = "raw_app_store_metadata"


def _read_csv_header(csv_path: Path) -> list[str]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


def load_raw(conn, csv_path: Path) -> int:
    """(Re)create the raw table from the CSV and return the row count loaded.

    Column names come straight from the CSV header, so this stays correct
    if Apple's export gains/reorders columns. Postgres folds unquoted
    identifiers to lowercase (e.g. `trackName` -> `trackname`) — downstream
    SQL refers to the lowercased names.
    """
    columns = _read_csv_header(csv_path)
    column_defs = ", ".join(f"{col} TEXT" for col in columns)
    column_list = ", ".join(columns)

    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {RAW_TABLE}")
        cur.execute(f"CREATE TABLE {RAW_TABLE} ({column_defs})")
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            cur.copy_expert(
                f"COPY {RAW_TABLE} ({column_list}) FROM STDIN WITH (FORMAT csv, HEADER true)",
                f,
            )
        cur.execute(f"SELECT count(*) FROM {RAW_TABLE}")
        return cur.fetchone()[0]


def main() -> None:
    if not RAW_CSV.exists():
        print(f"Error: raw CSV not found at {RAW_CSV}", file=sys.stderr)
        sys.exit(1)

    conn = get_connection()
    try:
        row_count = load_raw(conn, RAW_CSV)
        print(f"Loaded {RAW_TABLE}: {row_count} row(s)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
