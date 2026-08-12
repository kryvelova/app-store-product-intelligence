#!/bin/sh
# Runs once, only when the Postgres data directory is first initialized
# (fresh volume) — this is the official Postgres image's convention
# (docker-entrypoint-initdb.d). Creates a second database for Metabase's
# own application metadata, kept separate from the analytics database
# (POSTGRES_DB), on the same Postgres instance/credentials.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE "${MB_DB_NAME}";
EOSQL
