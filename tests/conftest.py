"""Shared pytest fixtures for tests that need a real PostgreSQL connection."""

import uuid

import pytest

from transform.db import get_connection


@pytest.fixture
def pg_conn():
    """A Postgres connection scoped to a fresh, isolated schema per test.

    Requires a reachable Postgres (see docker-compose.yml — `docker compose
    up -d`). Each test gets its own schema so it can freely CREATE/DROP
    tables like stg_apps/mart_app_category_engagement without touching the
    real pipeline's data in the `public` schema.
    """
    conn = get_connection()
    schema = f"test_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA {schema}")
        cur.execute(f"SET search_path TO {schema}")

    try:
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.close()
