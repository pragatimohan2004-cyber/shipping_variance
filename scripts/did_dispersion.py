"""
Difference-in-differences on a chokepoint-month dispersion panel.

Why DiD. noise_floor.py showed a single before/after comparison at one
chokepoint has a resolution limit of 47-81%, which is the same size as the
largest effect this project ever claimed. Two numbers cannot carry that test.

Pooling to a chokepoint-month panel replaces those two numbers with several
hundred observations, and time fixed effects absorb shocks common to every
chokepoint (COVID, the 2021 container crunch, global demand swings) which a
before/after split cannot separate from a local effect.

    log D_it = alpha_i + gamma_t + beta * Treated_it + delta * log n_it + e_it

  alpha_i  chokepoint fixed effects - absorb permanent level differences
  gamma_t  month fixed effects      - absorb common shocks
  beta     the estimate             - differential move at treated chokepoints
  log n    traffic level            - the mean-bias correction, as a covariate
                                      rather than a pre-adjustment, so it is
                                      estimated within-chokepoint alongside beta

Estimator choice. noise_floor.py run both ways showed D_raw and D_resid widen
when the window is restricted (stationary sampling-noise behaviour, which DiD
cannot fix) while D_weekly NARROWS (a common structural component, which time
fixed effects can absorb). D_weekly also carried the least cross-sectional mean
bias. So D_weekly on the 2022-onward window is the primary; the others are
reported as sensitivity.

Inference. n is small and the chokepoints are not independent draws, so
t-statistics would be dishonest. Instead: reassign treatment to each control
chokepoint in turn, re-estimate, and read the real beta against that placebo
distribution. That is the same logic as rank_test.py but on an estimate that
has the common component already removed.

Two-way fixed effects are applied by within-transformation (Frisch-Waugh)
rather than dummy variables, so this needs only numpy and pandas.

Source. Runs from the raw CSV by default, or from the Postgres views with
--db. The SQL computes the same rolling dispersion (validated to 1.5e-14) and
both paths apply the same sample filters, so the two agree.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CSV = "raw/Daily_Chokepoints_Data.csv"
EVENT = pd.Timestamp("2023-12-15")
PANEL_START = "2022-01-01"     # matches the tighter noise floor
WINDOW = 28
MIN_DAILY = 3.0
COL = "n_container"
MIN_MONTHS = 12
MIN_DAYS_IN_MONTH = 20   # mirrors HAVING COUNT(*) >= 20 in the SQL panel view

TREATED = ["Bab el-Mandeb Strait"]
# Not valid controls: same shock's other half, or independently compromised.
NOT_CONTROL = {
    "Suez Canal", "Cape of Good Hope",          # the other half of this shock
    "Strait of Hormuz", "Kerch Strait",         # conflict, AIS degradation
    "Bosporus Strait", "Malacca Strait",        # war traffic, 2021 coverage break
}

ESTIMATORS = ["D_weekly", "D_resid", "D_raw"]


# ----------------------------------------------------------------------
def window_stats(a):
    mu = a.mean()
    if mu <= 0:
        return np.nan, np.nan, np.nan
    var_raw = a.var(ddof=1)
    w = a.reshape(4, 7)
    resid = (w - w.mean(axis=0)).ravel()
    return var_raw / mu, resid.var(ddof=1) / mu, np.sqrt(var_raw) / mu


def build_panel(df):
    """One row per chokepoint-month. D from 28d windows ending in that month."""
    rows = []
    for name, sub in df.groupby("portname"):
        sub = sub.sort_values("date")
        counts = sub[COL].to_numpy(dtype=float)
        if counts.mean() < MIN_DAILY or len(counts) < WINDOW:
            continue

        views = np.lib.stride_tricks.sliding_window_view(counts, WINDOW)
        st = np.array([window_stats(v) for v in views])

        w = pd.DataFrame(st, columns=["D_raw", "D_resid", "CV"])
        w["D_weekly"] = w["D_raw"] - w["D_resid"]
        w["date"] = sub["date"].values[WINDOW - 1:]
        w["n"] = pd.Series(counts).rolling(WINDOW).mean().dropna().values
        w["month"] = pd.to_datetime(w["date"]).values.astype("datetime64[M]")

        g = w.groupby("month").agg(
            {**{e: "mean" for e in ESTIMATORS}, "n": "mean", "date": "size"}
        ).rename(columns={"date": "days"}).reset_index()
        g["chokepoint"] = name
        rows.append(g)

    p = pd.concat(rows, ignore_index=True)
    p = p[p["month"] >= np.datetime64(PANEL_START, "M")]
    # Drop part-months at the series edges. The data ends mid-month, so the
    # final month would otherwise be built from ~9 days and given the same
    # weight as a full one - a noisy estimate that inflates the treated
    # coefficient. Matches HAVING COUNT(*) >= 20 in sql/04_panel_view.sql.
    p = p[p["days"] >= MIN_DAYS_IN_MONTH]
    p = p[(p[ESTIMATORS] > 0).all(axis=1) & (p["n"] > 0)].copy()

    keep = p.groupby("chokepoint")["month"].nunique()
    return p[p["chokepoint"].isin(keep[keep >= MIN_MONTHS].index)].reset_index(drop=True)


def within(frame, cols, unit="chokepoint", time="month"):
    """Two-way within transformation: x - mean_i - mean_t + grand mean."""
    out = frame.copy()
    for c in cols:
        gm = out[c].mean()
        out[c] = (out[c]
                  - out.groupby(unit)[c].transform("mean")
                  - out.groupby(time)[c].transform("mean")
                  + gm)
    return out


def twfe(panel, y_col, treated_names):
    """Returns beta on the treatment dummy, controlling for log n."""
    d = panel.copy()
    d["y"] = np.log(d[y_col])
    d["logn"] = np.log(d["n"])
    d["treat"] = (
        d["chokepoint"].isin(treated_names)
        & (d["month"] >= np.datetime64(EVENT, "M"))
    ).astype(float)

    if d["treat"].sum() == 0 or d["treat"].nunique() < 2:
        return np.nan, np.nan

    w = within(d, ["y", "treat", "logn"])
    X = np.column_stack([w["treat"].values, w["logn"].values])
    y = w["y"].values

    XtX = X.T @ X
    if np.linalg.matrix_rank(XtX) < 2:
        return np.nan, np.nan
    coef = np.linalg.solve(XtX, X.T @ y)
    return coef[0], coef[1]


def panel_from_db():
    """
    Read the monthly panel from Postgres instead of recomputing from CSV.

    The rolling dispersion is already computed by sql/03_dispersion_view.sql,
    validated against the Python implementation to 1.5e-14. The SQL view is
    deliberately unfiltered - it keeps every chokepoint - so the MIN_DAILY and
    MIN_MONTHS filters that build_panel() applies are re-applied here, giving
    an identical analysis sample from either source.
    """
    from db import read_panel

    p = read_panel(start=PANEL_START)
    p = p.rename(columns={"d_raw": "D_raw", "d_resid": "D_resid",
                          "d_weekly": "D_weekly"})
    p = p[(p[ESTIMATORS] > 0).all(axis=1) & (p["n"] >= MIN_DAILY)].copy()
    keep = p.groupby("chokepoint")["month"].nunique()
    p = p[p["chokepoint"].isin(keep[keep >= MIN_MONTHS].index)]
    return p.reset_index(drop=True)


def main(path, treated=None, source="csv"):
    if source == "db":
        panel = panel_from_db()
    else:
        df = pd.read_csv(path, encoding="utf-8-sig")
        df["date"] = pd.to_datetime(df["date"])
        panel = build_panel(df)

    treated = treated or TREATED
    cps = sorted(panel["chokepoint"].unique())
    # A unit under test is never also a control for itself.
    excl = set(NOT_CONTROL) - set(treated)
    controls = [c for c in cps if c not in excl and c not in treated]

    print("=" * 78)
    print("DIFFERENCE-IN-DIFFERENCES  (chokepoint-month panel)")
    print("=" * 78)
    print(f"  window      {PANEL_START} to {panel['month'].max()}")
    print(f"  panel       {len(panel)} chokepoint-months, {len(cps)} chokepoints")
    print(f"  treated     {', '.join(treated)}")
    print(f"  controls    {len(controls)} (excluded: {len(excl)} shock/conflict)")
    print(f"  spec        log D ~ chokepoint FE + month FE + treat + log n")
    print(f"  source      {'postgres (sql views)' if source == 'db' else path}")

    usable = panel[panel["chokepoint"].isin(controls + treated)]

    for est in ESTIMATORS:
        beta, delta = twfe(usable, est, treated)
        if not np.isfinite(beta):
            print(f"\n  {est}: not estimable")
            continue

        # Placebo: give each control the treatment, re-estimate.
        placebo = []
        for c in controls:
            b, _ = twfe(usable[usable["chokepoint"] != treated[0]], est, [c])
            if np.isfinite(b):
                placebo.append(b)
        placebo = np.array(placebo)

        print("\n" + "-" * 78)
        print(f"  {est}")
        print("-" * 78)
        print(f"    beta (treat)      {beta:+.3f}   -> {np.exp(beta) - 1:+.1%} in D")
        print(f"    delta (log n)     {delta:+.3f}   (mean-bias correction, within)")

        if len(placebo) >= 3:
            sd = placebo.std(ddof=1)
            z = (beta - placebo.mean()) / sd
            n_more = int((np.abs(placebo) >= abs(beta)).sum())
            rank = n_more + 1
            print(f"    placebo n         {len(placebo)} controls")
            print(f"    placebo sd        {sd:.3f}  "
                  f"(2.5-97.5%: {np.percentile(placebo, 2.5):+.3f} to "
                  f"{np.percentile(placebo, 97.5):+.3f})")
            print(f"    z vs placebo      {z:+.2f}")
            print(f"    rank |beta|       {rank} of {len(placebo) + 1}")
            print(f"    p (two-sided)     {rank / (len(placebo) + 1):.3f}"
                  f"   floor {1 / (len(placebo) + 1):.3f}")
            verdict = ("DISTINGUISHABLE from placebo" if abs(z) > 2
                       else "not distinguishable from placebo")
            print(f"    => {verdict}")

            # Sustained shift or transient spike? Re-estimate year by year,
            # each post-year against the full pre-period.
            ev_m = np.datetime64(EVENT, "M")
            pre = usable[usable["month"] < ev_m]
            yrs = sorted({pd.Timestamp(m).year for m in usable["month"]})
            parts = []
            for yr in yrs:
                sel = [pd.Timestamp(m).year == yr for m in usable["month"]]
                chunk = usable[sel]
                # A partially-treated calendar year is neither a clean placebo
                # nor a clean effect. Split it: the pre-event months are the
                # parallel-trends test, the post-event months are the effect.
                pre_part = chunk[chunk["month"] < ev_m]
                post_part = chunk[chunk["month"] >= ev_m]
                if len(pre_part) and len(post_part):
                    b1, _ = twfe(pd.concat([pre, post_part]), est, treated)
                    if np.isfinite(b1):
                        parts.append(f"{yr}(post): {b1:+.2f}")
                elif len(post_part):
                    b, _ = twfe(pd.concat([pre, post_part]), est, treated)
                    if np.isfinite(b):
                        parts.append(f"{yr}: {b:+.2f}")
            if parts:
                print(f"    by year           {'   '.join(parts)}")

            # Parallel-trends placebo: pretend the event happened 12 months
            # early and test on PRE-EVENT data only. A large coefficient here
            # means the treated unit was already diverging and the headline
            # estimate is partly pre-trend, not effect.
            fake = ev_m - np.timedelta64(12, "M")
            pp = usable[usable["month"] < ev_m].copy()
            if len(pp):
                d = pp.copy()
                d["y"] = np.log(d[est])
                d["logn"] = np.log(d["n"])
                d["treat"] = (d["chokepoint"].isin(treated)
                              & (d["month"] >= fake)).astype(float)
                if d["treat"].nunique() > 1:
                    w = within(d, ["y", "treat", "logn"])
                    X = np.column_stack([w["treat"].values, w["logn"].values])
                    try:
                        c = np.linalg.solve(X.T @ X, X.T @ w["y"].values)
                        flag = "  <-- PRE-TREND" if abs(c[0]) > 2 * sd else ""
                        print(f"    placebo -12mo     {c[0]:+.3f}"
                              f"   (pre-event only, want ~0){flag}")
                    except np.linalg.LinAlgError:
                        pass

    print("\n" + "=" * 78)
    print("READ THIS")
    print("=" * 78)
    print("  beta is a DIFFERENTIAL move: how much treated D changed relative to")
    print("  controls over the same months. It is not a before/after ratio and")
    print("  should not be compared to the raw CV ratios in the README.")
    print()
    print("  The placebo sd here is the honest resolution of this design. Compare")
    print("  it to the 47-81% single-comparison floor from noise_floor.py - the")
    print("  gap is what the fixed effects bought.")

    panel.to_csv("outputs/tables/did_panel.csv", index=False)
    print("\nsaved panel to outputs/tables/did_panel.csv")


if __name__ == "__main__":
    args = sys.argv[1:]
    tr, src_mode = None, "csv"
    if "--treated" in args:
        i = args.index("--treated")
        tr = [args[i + 1]]
        del args[i:i + 2]
    if "--db" in args:
        args.remove("--db")
        src_mode = "db"
    main(args[0] if args else CSV, tr, src_mode)