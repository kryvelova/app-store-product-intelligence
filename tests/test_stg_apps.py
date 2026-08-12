from transform.build_staging import STG_APPS_SQL, run_checks

RAW_COLUMNS = """
    id TEXT,
    trackname TEXT,
    artistname TEXT,
    primarygenrename TEXT,
    releasedate TEXT,
    price TEXT,
    currency TEXT,
    averageuserrating TEXT,
    userratingcount TEXT,
    version TEXT,
    currentversionreleasedate TEXT,
    kind TEXT
"""

# Matches RAW_COLUMNS order. All-text, matching what a real COPY from CSV
# loads (see transform/load_raw.py) — nothing is typed until stg_apps casts it.
VALID_ROW = (
    "123",
    "Example App",
    "Example Dev",
    "Utilities",
    "2020-01-01T00:00:00Z",
    "4.99",
    "USD",
    "4.5",
    "100",
    "1.0",
    "2021-01-01T00:00:00Z",
    "mac-software",
)


def _build(pg_conn, rows):
    """Build stg_apps in the test's isolated schema from synthetic raw rows."""
    with pg_conn.cursor() as cur:
        cur.execute(f"CREATE TABLE raw_app_store_metadata ({RAW_COLUMNS})")
        if rows:
            placeholders = ", ".join(["%s"] * len(rows[0]))
            cur.executemany(
                f"INSERT INTO raw_app_store_metadata VALUES ({placeholders})", rows
            )
        cur.execute(STG_APPS_SQL.read_text())


def _describe(pg_conn, table):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s "
            "ORDER BY ordinal_position",
            (table,),
        )
        return cur.fetchall()


def test_stg_apps_renames_columns(pg_conn):
    _build(pg_conn, [VALID_ROW])

    columns = [name for name, _ in _describe(pg_conn, "stg_apps")]

    assert columns == [
        "app_id",
        "app_name",
        "developer_name",
        "primary_genre",
        "release_date",
        "price",
        "currency",
        "average_rating",
        "rating_count",
        "version",
        "current_version_release_date",
        "platform",
    ]


def test_stg_apps_drops_redundant_rating_column(pg_conn):
    _build(pg_conn, [VALID_ROW])

    columns = [name for name, _ in _describe(pg_conn, "stg_apps")]

    assert "averageuserratingforcurrentversion" not in columns


def test_stg_apps_casts_types(pg_conn):
    _build(pg_conn, [VALID_ROW])

    types = dict(_describe(pg_conn, "stg_apps"))

    assert types["app_id"] == "bigint"
    assert types["release_date"] == "timestamp without time zone"
    assert types["current_version_release_date"] == "timestamp without time zone"
    assert types["rating_count"] == "bigint"
    assert types["price"] == "numeric"


def test_stg_apps_is_one_row_per_source_row(pg_conn):
    other_row = ("456",) + VALID_ROW[1:]
    _build(pg_conn, [VALID_ROW, other_row])

    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stg_apps")
        assert cur.fetchone()[0] == 2


def test_checks_all_pass_on_valid_data(pg_conn):
    _build(pg_conn, [VALID_ROW])

    results = dict(run_checks(pg_conn))

    assert all(violations == 0 for violations in results.values())


def test_check_catches_duplicate_app_id(pg_conn):
    _build(pg_conn, [VALID_ROW, VALID_ROW])  # same app_id twice

    results = dict(run_checks(pg_conn))

    assert results["unique app_id"] == 1


def test_check_catches_null_app_id(pg_conn):
    row = (None,) + VALID_ROW[1:]
    _build(pg_conn, [row])

    results = dict(run_checks(pg_conn))

    assert results["non-null app_id"] == 1


def test_check_catches_negative_rating_count(pg_conn):
    row = VALID_ROW[:8] + ("-1",) + VALID_ROW[9:]
    _build(pg_conn, [row])

    results = dict(run_checks(pg_conn))

    assert results["rating_count >= 0"] == 1


def test_check_catches_out_of_range_average_rating(pg_conn):
    row = VALID_ROW[:7] + ("5.5",) + VALID_ROW[8:]
    _build(pg_conn, [row])

    results = dict(run_checks(pg_conn))

    assert results["average_rating between 0 and 5"] == 1


def test_check_allows_null_price(pg_conn):
    row = VALID_ROW[:5] + (None,) + VALID_ROW[6:]
    _build(pg_conn, [row])

    results = dict(run_checks(pg_conn))

    assert results["price >= 0 when not null"] == 0


def test_check_catches_negative_price(pg_conn):
    row = VALID_ROW[:5] + ("-5.0",) + VALID_ROW[6:]
    _build(pg_conn, [row])

    results = dict(run_checks(pg_conn))

    assert results["price >= 0 when not null"] == 1


def test_check_catches_current_version_release_date_before_release_date(pg_conn):
    row = VALID_ROW[:10] + ("2019-01-01T00:00:00Z",) + VALID_ROW[11:]
    _build(pg_conn, [row])

    results = dict(run_checks(pg_conn))

    assert results["current_version_release_date >= release_date"] == 1
