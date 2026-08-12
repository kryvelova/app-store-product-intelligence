-- Mart: engagement/rating signal per platform + category. One row per
-- (platform, primary_genre). Built from stg_apps only — no joins.
DROP TABLE IF EXISTS mart_app_category_engagement;
CREATE TABLE mart_app_category_engagement AS
SELECT
    platform,
    primary_genre,
    count(*)                                             AS app_count,
    count(*) FILTER (WHERE rating_count > 0)              AS rated_app_count,
    100.0 * count(*) FILTER (WHERE rating_count > 0)
        / NULLIF(count(*), 0)                             AS rating_coverage_pct,
    SUM(rating_count)                                     AS total_rating_count,
    AVG(average_rating) FILTER (WHERE rating_count > 0)   AS avg_rating
FROM stg_apps
GROUP BY platform, primary_genre;
