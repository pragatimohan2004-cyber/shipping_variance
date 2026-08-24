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
DROP VIEW IF EXISTS chokepoint_month_labelled;

CREATE VIEW chokepoint_month_labelled AS
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
        ELSE 'control'
    END AS role
FROM chokepoint_month m;