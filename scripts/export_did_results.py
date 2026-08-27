"""
Run the full DiD grid and persist it to Postgres for Power BI.

Every number in the results section of this project has so far existed only in
stdout and in MEASUREMENTS.md, which is gitignored. Nothing in the repo could
reproduce "+0.595, z +7.13, rank 1 of 14" without a human running three
commands and transcribing the output. This script closes that gap: it calls
the same estimate() the terminal output comes from, so the table Power BI
reads and the numbers on screen cannot drift apart.

    python scripts/export_did_results.py --db
    python scripts/export_did_results.py --db --dry-run

WRITE SEMANTICS. db.write_results() uses if_exists="replace", which drops and
rebuilds the whole table. That is only safe if the entire grid is written in a
single call - calling it once per treated unit would silently leave the table
holding the last unit alone, with no error. So results are accumulated in
memory and written ONCE, at the end, and only after a completeness check
passes. A run that fails halfway writes nothing and leaves the previous table
intact.

Every row carries run_ts. If a future estimate ever needs re-checking against
the dashboard, that stamp is what says whether they came from the same run.
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from did_dispersion import (  # noqa: E402
    CSV, ESTIMATORS, PANEL_START, PRETREND_LAG_MONTHS,
    estimate, load_panel, split_units,
)

# The three units the README reports. Each is estimated against the control
# set that split_units() derives for it - which, since the SHOCK fix, excludes
# the other two in every direction.
TREATED_UNITS = [
    "Cape of Good Hope",        # absorbing route - best identified, leads
    "Bab el-Mandeb Strait",     # abandoned route
    "Strait of Hormuz",         # AIS-degradation confound test
]

# Bab el-Mandeb's published numbers were estimated against 13 controls. If the
# control-set refactor changed that, the pooled betas for Bab should no longer
# match the README and the discrepancy needs explaining before anything is
# written. Set to None to skip the check.
EXPECTED_CONTROLS = {"Bab el-Mandeb Strait": 13}


def run_grid(panel, treated_units, pretrend_lag):
    frames, summary = [], []
    for unit in treated_units:
        if unit not in set(panel["chokepoint"]):
            raise SystemExit(
                f"'{unit}' is not in the panel. Present: "
                f"{sorted(panel['chokepoint'].unique())}"
            )
        _, controls, excl = split_units(panel, [unit])
        exp = EXPECTED_CONTROLS.get(unit)
        if exp is not None and len(controls) != exp:
            raise SystemExit(
                f"'{unit}' has {len(controls)} controls, expected {exp}. "
                "The control set changed - published numbers for this unit "
                "may no longer be reproducible. Nothing written."
            )
        print(f"  {unit:<24} {len(controls)} controls "
              f"(excluded {len(excl)}: {', '.join(sorted(excl))})")
        res = estimate(panel, [unit], controls, pretrend_lag=pretrend_lag)
        frames.append(res)
        summary.append((unit, len(controls)))
    return pd.concat(frames, ignore_index=True), summary


def check_complete(df, treated_units):
    """Refuse to write a partial grid. replace= makes partial writes silent."""
    pooled = df[df["spec"] == "pooled"]
    want = len(treated_units) * len(ESTIMATORS)
    got = int(pooled["beta"].notna().sum())
    if got != want:
        missing = [
            f"{t}/{e}" for t in treated_units for e in ESTIMATORS
            if pooled[(pooled["treated"] == t)
                      & (pooled["estimator"] == e)
                      & (pooled["beta"].notna())].empty
        ]
        raise SystemExit(
            f"Incomplete grid: {got}/{want} pooled betas estimated. "
            f"Missing: {', '.join(missing)}. Nothing written."
        )
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=CSV)
    ap.add_argument("--db", action="store_true",
                    help="read the panel from Postgres rather than the CSV")
    ap.add_argument("--pretrend-lag", type=int, default=PRETREND_LAG_MONTHS)
    ap.add_argument("--table", default="did_results")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and write the CSV, but do not touch Postgres")
    a = ap.parse_args()

    source = "db" if a.db else "csv"
    panel = load_panel(a.path, source)

    print("=" * 78)
    print("DID RESULTS EXPORT")
    print("=" * 78)
    print(f"  source      {'postgres (sql views)' if a.db else a.path}")
    print(f"  window      {PANEL_START} to {panel['month'].max()}")
    print(f"  panel       {len(panel)} chokepoint-months, "
          f"{panel['chokepoint'].nunique()} chokepoints")
    print(f"  pretrend    -{a.pretrend_lag} months")
    print()

    df, _ = run_grid(panel, TREATED_UNITS, a.pretrend_lag)
    n_pooled = check_complete(df, TREATED_UNITS)

    df["run_ts"] = pd.Timestamp.utcnow().tz_localize(None)
    df["source"] = "postgres" if a.db else "csv"
    df["panel_start"] = PANEL_START
    df["panel_end"] = str(pd.Timestamp(panel["month"].max()).date())
    df["pretrend_lag_months"] = a.pretrend_lag

    lead = ["run_ts", "treated", "estimator", "spec", "beta", "pct_change"]
    df = df[lead + [c for c in df.columns if c not in lead]]

    os.makedirs("outputs/tables", exist_ok=True)
    out_csv = "outputs/tables/did_results.csv"
    df.to_csv(out_csv, index=False)

    print(f"\n  {n_pooled} pooled betas, {len(df)} rows total")
    print(f"  saved {out_csv}")

    print("\n" + "-" * 78)
    print("POOLED")
    print("-" * 78)
    p = df[df["spec"] == "pooled"]
    for _, r in p.iterrows():
        z = f"{r['z']:+.2f}" if pd.notna(r.get("z")) else "  n/a"
        rk = (f"{int(r['rank'])} of {int(r['rank_of'])}"
              if pd.notna(r.get("rank")) else "n/a")
        print(f"  {r['treated']:<24} {r['estimator']:<9} "
              f"{r['beta']:+.3f}  ({r['pct_change']:+6.1%})  "
              f"z {z}  rank {rk}")

    if a.dry_run:
        print("\n  --dry-run: Postgres not written.")
        return

    from db import write_results
    n = write_results(df, table=a.table)
    print(f"\n  wrote {n} rows to Postgres table '{a.table}' (replaced)")
    print(f"  Power BI: refresh, then add '{a.table}'. Set beta, pct_change,")
    print("  z and placebo_sd to Average or Don't summarize - never Sum.")


if __name__ == "__main__":
    main()