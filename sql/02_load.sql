-- Load raw CSV.
-- Run:  psql -U postgres -d shipping_variance -f sql/02_load.sql
--
-- \copy (client-side) not COPY (server-side): COPY needs the file readable
-- by the postgres server process plus superuser rights. \copy reads through
-- the client and works with an ordinary account.
--
-- The CSV carries 21 columns; port_daily keeps the 10 the analysis uses.
-- Staging mirrors the file exactly so \copy's column list matches the header,
-- then the INSERT selects the subset and renames date -> obs_date.

DROP TABLE IF EXISTS stg_chokepoints;

CREATE TABLE stg_chokepoints (
    date                    TEXT,
    year                    TEXT,
    month                   TEXT,
    day                     TEXT,
    portid                  TEXT,
    portname                TEXT,
    n_container             TEXT,
    n_dry_bulk              TEXT,
    n_general_cargo         TEXT,
    n_roro                  TEXT,
    n_tanker                TEXT,
    n_cargo                 TEXT,
    n_total                 TEXT,
    capacity_container      TEXT,
    capacity_dry_bulk       TEXT,
    capacity_general_cargo  TEXT,
    capacity_roro           TEXT,
    capacity_tanker         TEXT,
    capacity_cargo          TEXT,
    capacity                TEXT,
    ObjectId                TEXT
);

-- Every column staged as TEXT so a malformed value fails at the cast below,
-- where the error names the column, rather than aborting mid-load.
\copy stg_chokepoints FROM 'raw/Daily_Chokepoints_Data.csv' WITH (FORMAT csv, HEADER true, NULL '')

TRUNCATE port_daily;

INSERT INTO port_daily (
    portid, portname, obs_date,
    n_container, n_dry_bulk, n_general_cargo,
    n_roro, n_tanker, n_cargo, n_total
)
SELECT
    portid,
    portname,
    date::DATE,
    NULLIF(n_container,     '')::DOUBLE PRECISION,
    NULLIF(n_dry_bulk,      '')::DOUBLE PRECISION,
    NULLIF(n_general_cargo, '')::DOUBLE PRECISION,
    NULLIF(n_roro,          '')::DOUBLE PRECISION,
    NULLIF(n_tanker,        '')::DOUBLE PRECISION,
    NULLIF(n_cargo,         '')::DOUBLE PRECISION,
    NULLIF(n_total,         '')::DOUBLE PRECISION
FROM stg_chokepoints
ON CONFLICT (portid, obs_date) DO NOTHING;

DROP TABLE stg_chokepoints;

-- Expect 77,784 rows across 28 chokepoints, 2019-01-01 to 2026-08-09.
SELECT COUNT(*) AS rows,
       COUNT(DISTINCT portname) AS chokepoints,
       MIN(obs_date) AS first_date,
       MAX(obs_date) AS last_date
FROM port_daily;

-- The dispersion view's weekday logic assumes one row per day with no gaps.
-- This should return zero rows.
SELECT portname,
       COUNT(*) AS rows,
       (MAX(obs_date) - MIN(obs_date) + 1) - COUNT(*) AS missing_days
FROM port_daily
GROUP BY portname
HAVING (MAX(obs_date) - MIN(obs_date) + 1) - COUNT(*) <> 0
ORDER BY missing_days DESC;