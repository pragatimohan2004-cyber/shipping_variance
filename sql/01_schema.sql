-- Schema for shipping_variance.
-- Run once:  psql -U postgres -d shipping_variance -f sql/01_schema.sql

DROP TABLE IF EXISTS port_daily CASCADE;

CREATE TABLE port_daily (
    portid              TEXT        NOT NULL,
    portname            TEXT        NOT NULL,
    obs_date            DATE        NOT NULL,
    n_container         DOUBLE PRECISION,
    n_dry_bulk          DOUBLE PRECISION,
    n_general_cargo     DOUBLE PRECISION,
    n_roro              DOUBLE PRECISION,
    n_tanker            DOUBLE PRECISION,
    n_cargo             DOUBLE PRECISION,
    n_total             DOUBLE PRECISION,
    PRIMARY KEY (portid, obs_date)
);

-- The dispersion view scans by (portid, obs_date) order constantly.
CREATE INDEX idx_port_daily_date ON port_daily (obs_date);

COMMENT ON TABLE port_daily IS
  'IMF PortWatch daily chokepoint transit calls. One row per chokepoint per day.
   Source: portwatch.imf.org. Vintage matters - the publisher restates history.';