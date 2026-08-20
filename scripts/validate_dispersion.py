"""
Estimator validation, pre-period only.

Before measuring what the Red Sea disruption did to dispersion, establish how the
dispersion estimators themselves behave when nothing is treated.

For count data:
  CV = sd/mean.  Under Poisson, sd = sqrt(mean), so CV = 1/sqrt(mean).
       CV is a deterministic function of the mean. A traffic collapse raises CV
       with no change in behaviour whatsoever.
       => regressing log CV on log mean should give slope ~ -0.5

  D  = var/mean (index of dispersion). Under Poisson, D = 1 for any mean.
       Under negative binomial with clustering k, D = 1 + mean/k, which grows
       with the mean.
       => slope ~ 0 means D is mean-invariant here and the confound is designed
          out; slope ~ +1 means D is contaminated too, just in the opposite
          direction, and a different estimator is needed.

Nothing here touches the post-period. Any structure found is the estimator's
behaviour, not the shock's.

Also splits D into raw and day-of-week-residualized. Container lines run weekly
service strings; a 28-day window holds four repeats of a 7-day cycle, and that
cycle lands in the variance. D_raw - D_resid is the weekly schedule structure
measured in dispersion units.
"""

import sys

import numpy as np
import pandas as pd

CSV = "raw/Daily_Chokepoints_Data.csv"
EVENT = pd.Timestamp("2023-12-15")
WINDOW = 28          # 4 complete weeks - required by the reshape(4, 7) below
MIN_DAILY = 3.0      # below this, D is dominated by discreteness not dispersion
COL = "n_container"


# ----------------------------------------------------------------------
# estimators
# ----------------------------------------------------------------------
def window_stats(a):
    """
    a : (28,) contiguous daily counts, ordered by date.

    Returns (D_raw, D_resid, CV).

    D_resid divides by the ORIGINAL window mean, not by the residual mean.
    Residualizing drives the mean to ~0 by construction, so dividing by it
    would explode. Using the original mean keeps D_resid on the same scale as
    D_raw so their difference is interpretable.
    """
    mu = a.mean()
    if mu <= 0:
        return np.nan, np.nan, np.nan

    var_raw = a.var(ddof=1)

    w = a.reshape(4, 7)                      # rows = weeks, cols = weekday slot
    resid = (w - w.mean(axis=0)).ravel()     # strip each weekday's mean
    var_res = resid.var(ddof=1)

    return var_raw / mu, var_res / mu, np.sqrt(var_raw) / mu


def rolling_stats(counts):
    """Non-overlapping-free sliding windows of length WINDOW over a 1-D array."""
    if len(counts) < WINDOW:
        return np.empty((0, 3))
    views = np.lib.stride_tricks.sliding_window_view(counts, WINDOW)
    return np.array([window_stats(v.astype(float)) for v in views])


def ols(x, y):
    """Returns (intercept, slope, se_slope, r2). Hand-rolled, matches confound_check."""
    n = len(x)
    b = np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1)
    a = y.mean() - b * x.mean()
    resid = y - (a + b * x)
    ss_res = (resid ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    se_b = np.sqrt(ss_res / (n - 2) / ((x - x.mean()) ** 2).sum())
    return a, b, se_b, 1 - ss_res / ss_tot


# ----------------------------------------------------------------------
# load + integrity
# ----------------------------------------------------------------------
def load(path):
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"])
    return df


def check_contiguity(df):
    """
    reshape(4, 7) and sliding_window_view both assume one row per day with no
    gaps. A missing date silently shifts every weekday slot after it. Fail loudly
    here rather than discovering it later as an inexplicable slope.
    """
    print("=" * 74)
    print("INTEGRITY")
    print("=" * 74)

    bad = []
    for name, sub in df.groupby("portname"):
        gaps = sub.sort_values("date")["date"].diff().dropna()
        offending = gaps[gaps != pd.Timedelta(days=1)]
        if len(offending):
            bad.append((name, len(offending), offending.max()))

    if bad:
        print(f"  !! {len(bad)} chokepoints have date gaps:")
        for name, cnt, mx in bad[:10]:
            print(f"       {name:<32} {cnt:>4} gaps, largest {mx.days}d")
        print("\n  reindex to a complete date range before trusting the weekday split.")
    else:
        print("  date grid contiguous for all chokepoints (1 row/day, no gaps)")

    zeros = df[df[COL] == 0].groupby("portname").size()
    if len(zeros):
        print(f"\n  zero-{COL} days present at {len(zeros)} chokepoints:")
        for name, cnt in zeros.sort_values(ascending=False).head(8).items():
            print(f"       {name:<32} {cnt:>5} days")
        print("  (windows with mean 0 return NaN and drop out)")
    else:
        print(f"\n  no zero-{COL} days")

    return len(bad) == 0


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def build_table(df):
    """Pre-period only. One row per chokepoint."""
    pre = df[df["date"] < EVENT]

    rows = []
    for name, sub in pre.groupby("portname"):
        sub = sub.sort_values("date")
        counts = sub[COL].to_numpy(dtype=float)

        stats = rolling_stats(counts)
        if not len(stats):
            continue

        with np.errstate(invalid="ignore"):
            d_raw, d_res, cv = np.nanmean(stats, axis=0)

        rows.append({
            "chokepoint": name,
            "mean_daily": counts.mean(),
            "D_raw": d_raw,
            "D_resid": d_res,
            "D_weekly": d_raw - d_res,
            "CV": cv,
            "n_windows": len(stats),
        })

    out = pd.DataFrame(rows)
    return out[out["mean_daily"] >= MIN_DAILY].dropna().reset_index(drop=True)


def report(tab):
    print("\n" + "=" * 74)
    print(f"PRE-PERIOD DISPERSION  ({COL}, {WINDOW}d windows, "
          f"2019-01-01 to {EVENT.date()})")
    print("=" * 74)
    print(
        tab.sort_values("mean_daily", ascending=False)[
            ["chokepoint", "mean_daily", "D_raw", "D_resid", "D_weekly", "CV"]
        ].to_string(index=False, float_format=lambda v: f"{v:.3f}")
    )

    x = np.log(tab["mean_daily"].values)
    print("\n" + "=" * 74)
    print("DOES THE ESTIMATOR MOVE WITH THE MEAN?")
    print("=" * 74)
    print(f"  {len(tab)} chokepoints, log-mean range "
          f"{x.min():.2f} to {x.max():.2f} ({x.max()-x.min():.2f} log units)\n")

    verdicts = []
    for label, col, predicted in [
        ("log D_raw    ~ log mean", "D_raw", 0.0),
        ("log D_resid  ~ log mean", "D_resid", 0.0),
        ("log D_weekly ~ log mean", "D_weekly", 0.0),
        ("log CV       ~ log mean", "CV", -0.5),
    ]:
        _, b, se, r2 = ols(x, np.log(tab[col].values))
        lo, hi = b - 1.96 * se, b + 1.96 * se
        print(f"  {label}")
        print(f"      slope  {b:+.3f}  (se {se:.3f})   95% CI [{lo:+.3f}, {hi:+.3f}]")
        print(f"      R^2    {r2:.3f}        Poisson predicts {predicted:+.1f}")
        print()
        verdicts.append((col, b, lo, hi))

    print("=" * 74)
    print("VERDICT")
    print("=" * 74)

    # Statistical significance of a slope is the wrong test. What matters is how
    # much bias each estimator carries at the actual traffic change being studied.
    # A slope of +0.15 clears zero but is practically negligible; the synthetic
    # negative-binomial case, by contrast, returned +0.71 with R^2 0.98.
    N_RATIO = 0.342          # Bab el-Mandeb container traffic, post/pre
    print(f"  Mechanical bias each estimator carries at n_ratio = {N_RATIO}:\n")
    print(f"    {'estimator':<12} {'slope':>8} {'R^2':>7} {'bias':>10}")
    best, best_bias = None, np.inf
    for col, b, lo, hi in verdicts:
        _, _, _, r2 = ols(x, np.log(tab[col].values))
        bias = N_RATIO ** b - 1
        print(f"    {col:<12} {b:>+8.3f} {r2:>7.3f} {bias:>+9.1%}")
        if col != "CV" and abs(bias) < best_bias:
            best, best_bias = col, abs(bias)
    print()
    print(f"  => Least contaminated estimator: {best} ({best_bias:.1%} bias).")
    print(f"     Correct it explicitly: D_ratio / n_ratio**slope, using the slope")
    print(f"     measured here on untreated pre-period data only.")

    _, b_cv, _, _ = verdicts[3]
    if b_cv < -0.2:
        print()
        print(f"  => CV is unusable: slope {b_cv:+.3f} means a traffic collapse alone")
        print(f"     manufactures a {N_RATIO ** b_cv - 1:+.0%} CV change with no behaviour change.")

    under = (tab["D_resid"] < 1).sum()
    print()
    print(f"  => {under}/{len(tab)} chokepoints have D_resid < 1: arrivals are MORE")
    print("     regular than random. These are scheduled liner services, not a")
    print("     Poisson process. Note this invalidates chi-square noise bounds -")
    print("     bootstrap the pre-period for an empirical noise floor instead.")

    _, b_cv, lo_cv, hi_cv = verdicts[2]
    print()
    if hi_cv < 0:
        print(f"  CV falls with the mean (slope {b_cv:+.3f}), confirming it cannot")
        print("  be used on count data whose level changes. This is the direct")
        print("  measurement of what confound_check.py inferred indirectly.")
        if lo_cv <= -0.5 <= hi_cv:
            print("  The CI covers -0.5: consistent with Poisson arithmetic.")
        else:
            print(f"  The CI excludes -0.5: overdispersion varies across chokepoints.")

    print()
    frac = (tab["D_weekly"] / tab["D_raw"]).median()
    print(f"  Weekly structure is {frac:.1%} of raw dispersion (median).")
    if frac > 0.15:
        print("  Large enough that a schedule-destroying shock should be visible")
        print("  as a change in D_raw - D_resid.")
    else:
        print("  Small - the weekly-structure test may lack power.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else CSV
    df = load(path)
    check_contiguity(df)
    report(build_table(df))