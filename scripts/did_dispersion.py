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

Structure. estimate() computes; main() prints. Nothing is calculated inside
the print path, so export_did_results.py persists exactly the numbers that
appear on screen rather than recomputing them by a second route.
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

# Units that can never serve as controls, split by reason.
#
# SHOCK is the three-sided Red Sea event itself: the abandoned route, the
# canal it fed, and the route that absorbed the diverted traffic. Whichever
# one is under test, the other two are downstream of the same event and their
# post-period behaviour is not a counterfactual. This must include the treated
# unit's siblings in BOTH directions - when Cape is the treated unit,
# Bab el-Mandeb is not a valid control for it, and previously it was one.
SHOCK = {
    "Bab el-Mandeb Strait",
    "Suez Canal",
    "Cape of Good Hope",
}

# Independently compromised: conflict traffic, AIS/GPS degradation, or a known
# coverage break. Unrelated to the Red Sea, but not clean controls either.
COMPROMISED = {
    "Strait of Hormuz",
    "Kerch Strait",
    "Bosporus Strait",
    "Malacca Strait",
}

ESTIMATORS = ["D_weekly", "D_resid", "D_raw"]

PRETREND_LAG_MONTHS = 12   # --pretrend-lag overrides


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


def twfe(panel, y_col, treated_names, event_month=None):
    """Returns beta on the treatment dummy, controlling for log n."""
    ev = np.datetime64(EVENT, "M") if event_month is None else event_month
    d = panel.copy()
    d["y"] = np.log(d[y_col])
    d["logn"] = np.log(d["n"])
    d["treat"] = (
        d["chokepoint"].isin(treated_names)
        & (d["month"] >= ev)
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


def load_panel(path=CSV, source="csv"):
    if source == "db":
        return panel_from_db()
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"])
    return build_panel(df)


def split_units(panel, treated):
    """Controls for a given treated unit, and the exclusions that produced them."""
    cps = sorted(panel["chokepoint"].unique())
    # A unit under test is never also a control for itself.
    excl = (SHOCK | COMPROMISED) - set(treated)
    controls = [c for c in cps if c not in excl and c not in treated]
    return cps, controls, excl


# ----------------------------------------------------------------------
def estimate(panel, treated, controls, estimators=None,
             pretrend_lag=PRETREND_LAG_MONTHS):
    """
    Run the DiD for one treated unit across all estimators.

    Returns a long DataFrame, one row per (treated, estimator, spec):

        spec = 'pooled'         the headline beta, with placebo inference
               'annual_YYYY'    that year's post months against the full pre
               'pretrend_-Nmo'  fake event N months early, pre-event data only

    Inference columns (z, rank, placebo_sd, ...) are populated on 'pooled'
    rows only; the annual and pretrend rows carry beta alone, because they are
    read against the pooled placebo distribution rather than their own.

    This is the ONLY place a beta is computed. main() prints from it and
    export_did_results.py persists it, so the screen and the database cannot
    disagree the way the CSV and SQL panels once did.
    """
    estimators = estimators or ESTIMATORS
    ev_m = np.datetime64(EVENT, "M")
    usable = panel[panel["chokepoint"].isin(controls + list(treated))]
    rows = []

    for est in estimators:
        beta, delta = twfe(usable, est, treated)
        if not np.isfinite(beta):
            rows.append({"treated": treated[0], "estimator": est,
                         "spec": "pooled", "beta": np.nan,
                         "note": "not estimable"})
            continue

        # Placebo: give each control the treatment, re-estimate.
        placebo = []
        for c in controls:
            b, _ = twfe(usable[usable["chokepoint"] != treated[0]], est, [c])
            if np.isfinite(b):
                placebo.append(b)
        placebo = np.array(placebo)

        row = {
            "treated": treated[0],
            "estimator": est,
            "spec": "pooled",
            "beta": beta,
            "pct_change": np.exp(beta) - 1,
            "delta_logn": delta,
            "n_obs": int(len(usable)),
            "n_controls": len(controls),
            "note": "",
        }

        sd = np.nan
        if len(placebo) >= 3:
            sd = placebo.std(ddof=1)
            rank = int((np.abs(placebo) >= abs(beta)).sum()) + 1
            row.update({
                "n_placebo": len(placebo),
                "placebo_sd": sd,
                "placebo_mean": placebo.mean(),
                "placebo_lo": np.percentile(placebo, 2.5),
                "placebo_hi": np.percentile(placebo, 97.5),
                "z": (beta - placebo.mean()) / sd,
                "rank": rank,
                "rank_of": len(placebo) + 1,
                "p_two_sided": rank / (len(placebo) + 1),
                "p_floor": 1 / (len(placebo) + 1),
            })
        rows.append(row)

        if len(placebo) < 3:
            continue

        # Sustained shift or transient spike? Re-estimate year by year,
        # each post-year against the full pre-period.
        pre = usable[usable["month"] < ev_m]
        for yr in sorted({pd.Timestamp(m).year for m in usable["month"]}):
            sel = [pd.Timestamp(m).year == yr for m in usable["month"]]
            chunk = usable[sel]
            # A partially-treated calendar year is neither a clean placebo
            # nor a clean effect. Split it: the pre-event months are the
            # parallel-trends test, the post-event months are the effect.
            post_part = chunk[chunk["month"] >= ev_m]
            if not len(post_part):
                continue
            b, _ = twfe(pd.concat([pre, post_part]), est, treated)
            if not np.isfinite(b):
                continue
            partial = bool(len(chunk[chunk["month"] < ev_m]))
            rows.append({
                "treated": treated[0], "estimator": est,
                "spec": f"annual_{yr}", "beta": b,
                "pct_change": np.exp(b) - 1,
                "note": "partial year (post months only)" if partial else "",
            })

        # Parallel-trends placebo: pretend the event happened N months early
        # and test on PRE-EVENT data only. A large coefficient here means the
        # treated unit was already diverging and the headline estimate is
        # partly pre-trend, not effect.
        #
        # The pre-trend coefficient gets its OWN placebo distribution. An
        # earlier version judged it against the pooled placebo sd, which is
        # the spread of full-window treatment betas - a different statistic on
        # a different sample, so the threshold meant nothing. It mattered:
        # every unit tested returned a positive D_resid pre-trend (+0.116,
        # +0.172, +0.179), which is either a biased test or a noisy one, and
        # a borrowed benchmark cannot tell those apart. Reassigning the fake
        # event to each control in turn gives the null this statistic actually
        # has, on the same 12-vs-11 month split and the same sample.
        #
        # NOTE ON POWER: with PANEL_START 2022-01 and a 12-month lag this
        # compares 12 fake-post months against 11 fake-pre months. A small
        # coefficient is consistent with no pre-trend but is NOT strong
        # evidence of none. Run --pretrend-lag 6 as a second read before
        # leaning on it in the README.
        pp = usable[usable["month"] < ev_m]
        if len(pp):
            fake = ev_m - np.timedelta64(pretrend_lag, "M")
            b, _ = twfe(pp, est, treated, event_month=fake)

            pt_placebo = []
            for c in controls:
                pb, _ = twfe(pp[pp["chokepoint"] != treated[0]], est, [c],
                             event_month=fake)
                if np.isfinite(pb):
                    pt_placebo.append(pb)
            pt_placebo = np.array(pt_placebo)

            if np.isfinite(b):
                r = {
                    "treated": treated[0], "estimator": est,
                    "spec": f"pretrend_-{pretrend_lag}mo", "beta": b,
                    "pct_change": np.exp(b) - 1,
                    "n_obs": int(len(pp)),
                    "note": "",
                }
                if len(pt_placebo) >= 3:
                    pt_sd = pt_placebo.std(ddof=1)
                    pt_rank = int((np.abs(pt_placebo) >= abs(b)).sum()) + 1
                    pt_z = (b - pt_placebo.mean()) / pt_sd
                    r.update({
                        "n_placebo": len(pt_placebo),
                        "placebo_sd": pt_sd,
                        "placebo_mean": pt_placebo.mean(),
                        "placebo_lo": np.percentile(pt_placebo, 2.5),
                        "placebo_hi": np.percentile(pt_placebo, 97.5),
                        "z": pt_z,
                        "rank": pt_rank,
                        "rank_of": len(pt_placebo) + 1,
                        # A pre-trend is only disqualifying if it is unusual
                        # for THIS test. If every control shows the same
                        # drift, the drift is a property of the estimator on
                        # a short pre-window, not of the treated unit.
                        "note": "PRE-TREND" if abs(pt_z) > 2 else "",
                    })
                rows.append(r)

                # NOT REPORTED: beta minus the pre-trend coefficient.
                #
                # An earlier version emitted a 'net_of_pretrend' row. It was
                # removed because the pre-trend null is wide enough to make
                # the subtraction meaningless: Cape's D_resid nets to +0.110
                # at a 12-month lag and -0.100 at 6 months, a sign flip driven
                # entirely by the arbitrary choice of lag, while beta itself
                # is fixed at +0.282. Netting also assumes the pre-trend would
                # have continued linearly, which nothing here establishes.
                #
                # The pre-trend belongs in the output as a coefficient with
                # its own z and rank, and its sd belongs in the limits section
                # as a resolution figure. It does not belong inside a point
                # estimate. A caveated number in a results table still gets
                # read as a result.

    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
def _fmt(res, treated, est, spec):
    m = res[(res["estimator"] == est) & (res["spec"] == spec)]
    return None if m.empty else m.iloc[0]


def main(path, treated=None, source="csv", pretrend_lag=PRETREND_LAG_MONTHS):
    panel = load_panel(path, source)
    treated = treated or TREATED
    cps, controls, excl = split_units(panel, treated)
    res = estimate(panel, treated, controls, pretrend_lag=pretrend_lag)

    print("=" * 78)
    print("DIFFERENCE-IN-DIFFERENCES  (chokepoint-month panel)")
    print("=" * 78)
    print(f"  window      {PANEL_START} to {panel['month'].max()}")
    print(f"  panel       {len(panel)} chokepoint-months, {len(cps)} chokepoints")
    print(f"  treated     {', '.join(treated)}")
    print(f"  controls    {len(controls)} (excluded: {len(excl)} shock/conflict)")
    print(f"  excluded    {', '.join(sorted(excl))}")
    print(f"  spec        log D ~ chokepoint FE + month FE + treat + log n")
    print(f"  source      {'postgres (sql views)' if source == 'db' else path}")

    for est in ESTIMATORS:
        r = _fmt(res, treated, est, "pooled")
        if r is None or not np.isfinite(r.get("beta", np.nan)):
            print(f"\n  {est}: not estimable")
            continue

        print("\n" + "-" * 78)
        print(f"  {est}")
        print("-" * 78)
        print(f"    beta (treat)      {r['beta']:+.3f}   -> {r['pct_change']:+.1%} in D")
        print(f"    delta (log n)     {r['delta_logn']:+.3f}   (mean-bias correction, within)")

        if "z" in r and pd.notna(r.get("z")):
            print(f"    placebo n         {int(r['n_placebo'])} controls")
            print(f"    placebo sd        {r['placebo_sd']:.3f}  "
                  f"(2.5-97.5%: {r['placebo_lo']:+.3f} to {r['placebo_hi']:+.3f})")
            print(f"    z vs placebo      {r['z']:+.2f}")
            print(f"    rank |beta|       {int(r['rank'])} of {int(r['rank_of'])}")
            print(f"    p (two-sided)     {r['p_two_sided']:.3f}"
                  f"   floor {r['p_floor']:.3f}")
            verdict = ("DISTINGUISHABLE from placebo" if abs(r["z"]) > 2
                       else "not distinguishable from placebo")
            print(f"    => {verdict}")

        ann = res[(res["estimator"] == est)
                  & (res["spec"].str.startswith("annual_"))]
        if len(ann):
            parts = []
            for _, a in ann.iterrows():
                yr = a["spec"].split("_")[1]
                tag = "(post)" if "partial" in str(a.get("note", "")) else ""
                parts.append(f"{yr}{tag}: {a['beta']:+.2f}")
            print(f"    by year           {'   '.join(parts)}")

        pt = res[(res["estimator"] == est)
                 & (res["spec"].str.startswith("pretrend_"))]
        if len(pt):
            p = pt.iloc[0]
            flag = "  <-- PRE-TREND" if str(p.get("note", "")) == "PRE-TREND" else ""
            print(f"    placebo -{pretrend_lag}mo     {p['beta']:+.3f}"
                  f"   (pre-event only, want ~0){flag}")
            if pd.notna(p.get("z")):
                print(f"      vs own placebo  sd {p['placebo_sd']:.3f}  "
                      f"mean {p['placebo_mean']:+.3f}  "
                      f"z {p['z']:+.2f}  rank {int(p['rank'])} of "
                      f"{int(p['rank_of'])}")
                print(f"      resolution      cannot detect a pre-trend "
                      f"below +/-{2 * p['placebo_sd']:.2f}")

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
    print()
    print(f"  The -{pretrend_lag}mo placebo is UNBIASED but WIDE. Its null is centred on")
    print("  zero, so the test is not systematically wrong, but its sd is large")
    print("  relative to the effects being estimated - and it widens further at")
    print("  shorter lags (D_resid: 0.240 at -12mo, 0.392 at -6mo). Read a")
    print("  pre-trend against its own z and rank, never as a quantity to")
    print("  subtract from beta. Parallel trends is ASSUMED here, not shown.")

    os.makedirs("outputs/tables", exist_ok=True)
    panel.to_csv("outputs/tables/did_panel.csv", index=False)
    print("\nsaved panel to outputs/tables/did_panel.csv")
    return res


if __name__ == "__main__":
    args = sys.argv[1:]
    tr, src_mode, lag = None, "csv", PRETREND_LAG_MONTHS
    if "--treated" in args:
        i = args.index("--treated")
        tr = [args[i + 1]]
        del args[i:i + 2]
    if "--pretrend-lag" in args:
        i = args.index("--pretrend-lag")
        lag = int(args[i + 1])
        del args[i:i + 2]
    if "--db" in args:
        args.remove("--db")
        src_mode = "db"
    main(args[0] if args else CSV, tr, src_mode, lag)