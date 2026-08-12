"""Shared PostgreSQL connection helper.

Connection settings come from the environment / .env (see .env.example) —
same pattern as ingestion.config. Local Postgres is provided by the root
docker-compose.yml (`docker compose up -d`).
"""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)  # no-op if the file doesn't exist; real env vars still apply

_REQUIRED_VARS = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")


def get_connection():
    """Open a psycopg2 connection (autocommit) using env-configured settings.

    Raises:
        RuntimeError: If any required POSTGRES_* variable is missing/empty.
    """
    values = {name: os.environ.get(name) for name in _REQUIRED_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            f"{', '.join(missing)}. Copy .env.example to .env and fill them in "
            "(and run `docker compose up -d` to start Postgres)."
        )

    conn = psycopg2.connect(
        host=values["POSTGRES_HOST"],
        port=values["POSTGRES_PORT"],
        dbname=values["POSTGRES_DB"],
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
    )
    conn.autocommit = True
    return conn
