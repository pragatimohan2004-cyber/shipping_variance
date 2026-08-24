-- Monthly chokepoint panel: the analysis unit for the DiD.
-- Depends on dispersion_daily.

DROP MATERIALIZED VIEW IF EXISTS chokepoint_month CASCADE;

CREATE MATERIALIZED VIEW chokepoint_month AS
SELECT
    portid,
    portname,
    DATE_TRUNC('month', obs_date)::DATE AS month,
    AVG(d_raw)    AS d_raw,
    AVG(d_resid)  AS d_resid,
    AVG(d_weekly) AS d_weekly,
    AVG(cv)       AS cv,
    AVG(mean_28)  AS n,
    COUNT(*)      AS days
FROM dispersion_daily
GROUP BY portid, portname, DATE_TRUNC('month', obs_date)
HAVING COUNT(*) >= 20;   -- drop part-months at the series edges

CREATE INDEX ON chokepoint_month (portname, month);

-- Convenience view for Power BI: adds treatment flags so the report does not
-- have to hardcode chokepoint names in DAX.
--
-- 'role' must reproduce the DiD's sample exactly, or a chart averaging over
-- "control" would include chokepoints the analysis never used. Two filters
-- apply: the explicit exclusions below, and MIN_DAILY = 3.0 in
-- did_dispersion.py, which drops low-traffic chokepoints (Bering, Lombok,
-- Magellan and similar) where the index of dispersion is dominated by
-- discreteness rather than by dispersion.
--
-- Traffic is averaged over the chokepoint's whole history rather than tested
-- month by month, so a chokepoint cannot flip categories mid-series and the
-- legend stays stable.

DROP VIEW IF EXISTS chokepoint_month_labelled;

CREATE VIEW chokepoint_month_labelled AS
WITH traffic AS (
    SELECT portname, AVG(n) AS mean_n
    FROM chokepoint_month
    GROUP BY portname
)
SELECT
    m.*,
    (m.month >= DATE '2023-12-01') AS post_event,
    m.portname IN ('Bab el-Mandeb Strait', 'Cape of Good Hope') AS is_treated,
    CASE
        WHEN m.portname = 'Bab el-Mandeb Strait' THEN 'abandoned route'
        WHEN m.portname = 'Cape of Good Hope'    THEN 'absorbing route'
        WHEN m.portname IN ('Suez Canal', 'Strait of Hormuz',
                            'Kerch Strait', 'Bosporus Strait',
                            'Malacca Strait')    THEN 'excluded'
        WHEN t.mean_n < 3.0                      THEN 'low traffic'
        ELSE 'control'
    END AS role
FROM chokepoint_month m
JOIN traffic t USING (portname);