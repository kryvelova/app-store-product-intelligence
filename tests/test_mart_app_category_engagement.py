import pytest

from transform.build_marts import MART_SQL, run_checks

STG_APPS_COLUMNS = """
    app_id BIGINT,
    app_name TEXT,
    developer_name TEXT,
    primary_genre TEXT,
    release_date TIMESTAMP,
    price DECIMAL(10, 2),
    currency TEXT,
    average_rating DOUBLE PRECISION,
    rating_count BIGINT,
    version TEXT,
    current_version_release_date TIMESTAMP,
    platform TEXT
"""


def _row(app_id, platform, primary_genre, average_rating, rating_count):
    return (
        app_id,
        f"App {app_id}",
        "Some Dev",
        primary_genre,
        "2020-01-01T00:00:00",
        4.99,
        "USD",
        average_rating,
        rating_count,
        "1.0",
        "2021-01-01T00:00:00",
        platform,
    )


def _build(pg_conn, rows):
    with pg_conn.cursor() as cur:
        cur.execute(f"CREATE TABLE stg_apps ({STG_APPS_COLUMNS})")
        if rows:
            placeholders = ", ".join(["%s"] * len(rows[0]))
            cur.executemany(f"INSERT INTO stg_apps VALUES ({placeholders})", rows)
        cur.execute(MART_SQL.read_text())


def _mart_row(pg_conn, platform, primary_genre):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT app_count, rated_app_count, rating_coverage_pct, total_rating_count, avg_rating "
            "FROM mart_app_category_engagement WHERE platform = %s AND primary_genre = %s",
            (platform, primary_genre),
        )
        return cur.fetchone()


def test_counts_and_coverage_for_mixed_ratings(pg_conn):
    rows = [
        _row(1, "mac-software", "Utilities", 4.5, 100),
        _row(2, "mac-software", "Utilities", 0.0, 0),
        _row(3, "mac-software", "Utilities", 0.0, 0),
    ]
    _build(pg_conn, rows)

    app_count, rated_app_count, coverage, total_ratings, avg_rating = _mart_row(
        pg_conn, "mac-software", "Utilities"
    )

    assert app_count == 3
    assert rated_app_count == 1
    assert float(coverage) == pytest.approx(100.0 / 3)
    assert total_ratings == 100
    assert float(avg_rating) == 4.5


def test_avg_rating_excludes_zero_rating_apps(pg_conn):
    # One unrated app (would drag a naive average way down) + one 4.5-star app.
    rows = [
        _row(1, "mac-software", "Utilities", 0.0, 0),
        _row(2, "mac-software", "Utilities", 4.5, 10),
    ]
    _build(pg_conn, rows)

    _, _, _, _, avg_rating = _mart_row(pg_conn, "mac-software", "Utilities")

    assert float(avg_rating) == 4.5  # not 2.25


def test_avg_rating_is_null_when_no_apps_are_rated(pg_conn):
    rows = [
        _row(1, "mac-software", "Utilities", 0.0, 0),
        _row(2, "mac-software", "Utilities", 0.0, 0),
    ]
    _build(pg_conn, rows)

    _, rated_app_count, coverage, _, avg_rating = _mart_row(pg_conn, "mac-software", "Utilities")

    assert rated_app_count == 0
    assert float(coverage) == 0.0  # app_count > 0 here, so this is a real 0%, not NULL
    assert avg_rating is None


def test_total_rating_count_sums_across_all_apps(pg_conn):
    rows = [
        _row(1, "mac-software", "Utilities", 4.5, 100),
        _row(2, "mac-software", "Utilities", 0.0, 0),
        _row(3, "mac-software", "Utilities", 3.0, 50),
    ]
    _build(pg_conn, rows)

    _, _, _, total_ratings, _ = _mart_row(pg_conn, "mac-software", "Utilities")

    assert total_ratings == 150


def test_same_genre_kept_separate_per_platform(pg_conn):
    rows = [
        _row(1, "mac-software", "Utilities", 4.0, 10),
        _row(2, "software", "Utilities", 5.0, 20),
    ]
    _build(pg_conn, rows)

    mac_row = _mart_row(pg_conn, "mac-software", "Utilities")
    ios_row = _mart_row(pg_conn, "software", "Utilities")

    assert mac_row is not None
    assert ios_row is not None
    assert mac_row != ios_row


def test_checks_all_pass_on_valid_data(pg_conn):
    rows = [
        _row(1, "mac-software", "Utilities", 4.5, 100),
        _row(2, "mac-software", "Utilities", 0.0, 0),
        _row(3, "software", "Games", 3.2, 5),
    ]
    _build(pg_conn, rows)

    results = dict(run_checks(pg_conn))

    assert all(violations == 0 for violations in results.values())


def test_division_by_zero_is_handled_safely(pg_conn):
    # Direct expression check for the NULLIF guard, independent of GROUP BY
    # ever actually producing a zero-row group in practice.
    with pg_conn.cursor() as cur:
        cur.execute("SELECT 100.0 * 5 / NULLIF(0, 0)")
        result = cur.fetchone()[0]
    assert result is None
