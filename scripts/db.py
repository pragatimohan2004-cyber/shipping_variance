"""
Postgres connection helper for shipping_variance.

Reads the analysis layer built by sql/01..04. The heavy work - rolling 28-day
dispersion with the weekday variance decomposition - happens in SQL; this
module just hands the monthly panel to Python for estimation.

Credentials come from the environment, never from source:

    $env:PGHOST     = "localhost"
    $env:PGDATABASE = "shipping_variance"
    $env:PGUSER     = "postgres"
    $env:PGPASSWORD = "..."

Set PGPASSWORD per session rather than with setx - a password living in a
permanent environment variable is worse than typing it.

Usage:
    from db import read_panel
    panel = read_panel()

Or check the connection directly:
    python scripts/db.py
"""

import os
import sys

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

DEFAULT_START = "2022-01-01"


def engine():
    """
    SQLAlchemy engine from PG* environment variables.

    URL.create escapes credentials properly. Building the connection string by
    hand with an f-string breaks on any password containing @, :, / or # - an
    '@' in the password splits the URL at the wrong place and the driver tries
    to resolve the tail of the password as a hostname.
    """
    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", ""),
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        database=os.environ.get("PGDATABASE", "shipping_variance"),
    )
    return create_engine(url)


def read_panel(start=DEFAULT_START):
    """
    Monthly chokepoint panel, ready for the DiD.

    Returns one row per chokepoint-month with d_raw, d_resid, d_weekly, cv and
    mean daily traffic. Column names and dtypes match what did_dispersion.py
    built from the CSV, so the two paths are interchangeable.
    """
    q = text(
        """
        SELECT portname AS chokepoint,
               month,
               d_raw,
               d_resid,
               d_weekly,
               cv,
               n
        FROM chokepoint_month
        WHERE month >= :start
        ORDER BY portname, month
        """
    )
    df = pd.read_sql(q, engine(), params={"start": start})
    # datetime64[M] so month comparisons match did_dispersion.py exactly
    df["month"] = pd.to_datetime(df["month"]).values.astype("datetime64[M]")
    return df


def read_daily(start=DEFAULT_START):
    """Daily dispersion series - for plots and Power BI, not the DiD."""
    q = text(
        """
        SELECT portname AS chokepoint,
               obs_date,
               n_container,
               mean_28,
               d_raw,
               d_resid,
               d_weekly,
               cv
        FROM dispersion_daily
        WHERE obs_date >= :start
        ORDER BY portname, obs_date
        """
    )
    df = pd.read_sql(q, engine(), params={"start": start})
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    return df


def write_results(df, table="did_results"):
    """Push DiD estimates back to Postgres for Power BI to read."""
    df.to_sql(table, engine(), if_exists="replace", index=False)
    return len(df)


def check():
    """Connection smoke test. Prints what came back, or a readable failure."""
    try:
        panel = read_panel()
    except Exception as exc:                      # noqa: BLE001
        print("CONNECTION FAILED\n")
        print(f"  {type(exc).__name__}: {exc}\n")
        print("  Checks:")
        print("    - is the server running?   Get-Service *postgres*")
        print("    - is PGPASSWORD set?       $env:PGPASSWORD")
        print("    - do the views exist?      psql -U postgres -d "
              "shipping_variance -c '\\dm'")
        return 1

    if panel.empty:
        print("Connected, but chokepoint_month returned no rows.")
        print("Run sql/03_dispersion_view.sql then sql/04_panel_view.sql.")
        return 1

    print(f"connected  ->  {len(panel)} rows, "
          f"{panel['chokepoint'].nunique()} chokepoints, "
          f"{panel['month'].min()} to {panel['month'].max()}")
    print()
    print(panel.head().to_string(index=False))

    bem = panel[panel["chokepoint"] == "Bab el-Mandeb Strait"]
    if not bem.empty:
        pre = bem[bem["month"] < pd.Timestamp("2023-12-01").to_numpy()
                  .astype("datetime64[M]")]
        if not pre.empty:
            print(f"\nBab el-Mandeb pre-event mean d_resid: "
                  f"{pre['d_resid'].mean():.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(check())