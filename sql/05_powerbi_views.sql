-- Presentation layer for Power BI.
--
-- Power BI's PostgreSQL connector does not list materialized views in
-- Navigator, so dispersion_daily is exposed through an ordinary view.
-- Nothing is computed here - 03 and 04 remain the analytical files.
--
-- The pre/post cut lives in SQL rather than DAX so that the event date
-- appears once, in a file a reviewer reads, instead of inside a measure
-- nobody opens.

CREATE OR REPLACE VIEW dispersion_daily_v AS
SELECT * FROM dispersion_daily;

CREATE OR REPLACE VIEW chokepoint_month_pbi AS
SELECT
    m.*,
    CASE WHEN m.month >= DATE '2023-12-01' THEN 'post' ELSE 'pre' END
        AS period,
    (m.month >= DATE '2022-01-01') AS in_estimation_window
FROM chokepoint_month_labelled m;