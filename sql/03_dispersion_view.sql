-- Rolling dispersion, computed in SQL.
--
-- Per chokepoint-day, over a trailing 28-day window:
--   d_raw    = var(n) / mean(n)        index of dispersion (1.0 = Poisson)
--   d_resid  = within-weekday variance / mean(n)
--   d_weekly = between-weekday variance / mean(n)
--   d_raw = d_resid + d_weekly by construction
--
-- Method. A 28-day window holds exactly 4 observations of each weekday, so
-- the window is a balanced one-way layout grouped by day-of-week. Standard
-- variance decomposition:
--
--     SS_total = SS_between_weekday + SS_within_weekday
--
-- SS_between is the weekly sailing rhythm (container lines run weekly
-- service strings). SS_within is everything else - irregularity not
-- explained by which day of the week it is.
--
-- What makes this a pure window-function problem: because every weekday
-- appears exactly 4 times, the grand mean equals the mean of the 7 weekday
-- means, so
--
--     SS_between = 4 * ( SUM(weekday_mean^2) - 7 * window_mean^2 )
--
-- and the 7 weekday means for a window ending at date d are exactly the
-- trailing-4-same-weekday averages of the last 7 rows. Both are rolling
-- aggregates. No self-join, no correlated subquery.
--
-- Validated against the Python implementation in scripts/validate_dispersion.py:
-- max absolute difference 1.5e-14 across all four output columns.

DROP MATERIALIZED VIEW IF EXISTS dispersion_daily CASCADE;

CREATE MATERIALIZED VIEW dispersion_daily AS
WITH weekday_means AS (
    SELECT
        portid,
        portname,
        obs_date,
        n_container,
        AVG(n_container) OVER (
            PARTITION BY portid, EXTRACT(DOW FROM obs_date)
            ORDER BY obs_date
            ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
        ) AS wd_mean,
        COUNT(*) OVER (
            PARTITION BY portid, EXTRACT(DOW FROM obs_date)
            ORDER BY obs_date
            ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
        ) AS wd_n
    FROM port_daily
),
windowed AS (
    SELECT
        portid,
        portname,
        obs_date,
        n_container,
        AVG(n_container)       OVER w28 AS mean_28,
        VAR_SAMP(n_container)  OVER w28 AS var_28,
        COUNT(*)               OVER w28 AS obs_28,
        SUM(wd_mean * wd_mean) OVER w7  AS sum_wd_sq,
        COUNT(*)               OVER w7  AS obs_7,
        MIN(wd_n)              OVER w28 AS min_wd_n
    FROM weekday_means
    WINDOW
        w28 AS (PARTITION BY portid ORDER BY obs_date
                ROWS BETWEEN 27 PRECEDING AND CURRENT ROW),
        w7  AS (PARTITION BY portid ORDER BY obs_date
                ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
),
decomposed AS (
    SELECT
        *,
        4.0 * (sum_wd_sq - 7.0 * mean_28 * mean_28) AS ss_between,
        var_28 * 27.0                               AS ss_total
    FROM windowed
    WHERE obs_28 = 28 AND obs_7 = 7 AND min_wd_n = 4 AND mean_28 > 0
)
SELECT
    portid,
    portname,
    obs_date,
    n_container,
    mean_28,
    var_28 / mean_28                            AS d_raw,
    ((ss_total - ss_between) / 27.0) / mean_28  AS d_resid,
    (ss_between / 27.0) / mean_28               AS d_weekly,
    SQRT(var_28) / mean_28                      AS cv
FROM decomposed;

CREATE INDEX ON dispersion_daily (portid, obs_date);