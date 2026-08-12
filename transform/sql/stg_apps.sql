-- Staging model: one row per app, selected/renamed/cast from the raw App
-- Store metadata table (raw_app_store_metadata). No aggregation, no joins.
-- Postgres has no CREATE OR REPLACE TABLE, hence the explicit DROP.
DROP TABLE IF EXISTS stg_apps;
CREATE TABLE stg_apps AS
SELECT
    CAST(id AS BIGINT)                              AS app_id,
    trackname                                       AS app_name,
    artistname                                      AS developer_name,
    primarygenrename                                AS primary_genre,
    CAST(releasedate AS TIMESTAMP)                  AS release_date,
    CAST(price AS DECIMAL(10, 2))                   AS price,
    currency,
    CAST(averageuserrating AS DOUBLE PRECISION)     AS average_rating,
    CAST(userratingcount AS BIGINT)                 AS rating_count,
    version,
    CAST(currentversionreleasedate AS TIMESTAMP)    AS current_version_release_date,
    kind                                            AS platform
FROM raw_app_store_metadata;
