"""
Empirical noise floor via placebo event dates.

Most chokepoints have D_resid < 1: arrivals are MORE regular than random,
because these are scheduled liner services rather than a Poisson process.
That kills the chi-square sampling bounds - (n-1)D ~ chi2 assumes Poisson.
So the resolution of the estimator has to be measured, not derived.

Design: pick random cut dates inside the PRE-period and split it exactly the
way the real test splits at the event date. Nothing happened on those dates,
so the spread of ratios they produce is the resolution limit of a single
before/after comparison at one chokepoint.

IMPORTANT - what this actually measures. The pre-period contains COVID, the
2021 container crunch, Ever Given and the Malacca receiver break. A random cut
often splits ACROSS a real structural break, so the spread is not sampling
noise: it is genuine period-to-period variation in dispersion driven by shocks
common to every chokepoint at once. That distinction matters, because common
shocks are removable by difference-in-differences and sampling noise is not.
Run with --from 2022-01-01 to exclude COVID and see how much of the floor is
attributable to it.

Placebo dates rather than resampled windows, because the 28d rolling windows
overlap by 27 days and are massively autocorrelated. Shuffling them would
understate the noise. Contiguous splits preserve autocorrelation, trend and
seasonality - every nuisance the real comparison also faces.

Reports all three D variants so the bias/noise tradeoff is visible: D_weekly
is the least mean-biased but is a DIFFERENCE of two noisy quantities, so it
may be too noisy to use. That is the question this script answers.

The bias slopes estimated here are WITHIN-chokepoint over time. Those in
validate_dispersion.py are BETWEEN chokepoints in the cross-section. They are
different relationships and they do not agree. A pre/post test is a within
comparison, so the within slopes measured here are the ones to correct with.
"""

import sys

import numpy as np
import pandas as pd

# Self-contained: duplicated from validate_dispersion.py so this runs alone.
CSV = "raw/Daily_Chokepoints_Data.csv"
EVENT = pd.Timestamp("2023-12-15")
WINDOW = 28
MIN_DAILY = 3.0
COL = "n_container"


def window_stats(a):
    """a: (28,) contiguous daily counts. Returns (D_raw, D_resid, CV)."""
    mu = a.mean()
    if mu <= 0:
        return np.nan, np.nan, np.nan
    var_raw = a.var(ddof=1)
    w = a.reshape(4, 7)
    resid = (w - w.mean(axis=0)).ravel()
    return var_raw / mu, resid.var(ddof=1) / mu, np.sqrt(var_raw) / mu


def rolling_stats(counts):
    if len(counts) < WINDOW:
        return np.empty((0, 3))
    views = np.lib.stride_tricks.sliding_window_view(counts, WINDOW)
    return np.array([window_stats(v.astype(float)) for v in views])


def ols(x, y):
    n = len(x)
    b = np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1)
    a = y.mean() - b * x.mean()
    resid = y - (a + b * x)
    ss_res = (resid ** 2).sum()
    se_b = np.sqrt(ss_res / (n - 2) / ((x - x.mean()) ** 2).sum())
    return a, b, se_b, 1 - ss_res / ((y - y.mean()) ** 2).sum()


def load(path):
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"])
    return df

PRE_START = None      # e.g. "2022-01-01" to drop COVID; None = full history
N_PLACEBO = 300
MIN_SIDE = 400        # max days each side of a cut; shrinks for short windows
ESTIMATORS = ["D_raw", "D_resid", "D_weekly"]
SEED = 0


def stats_frame(counts, dates):
    """Rolling stats aligned to the date of each window's LAST day."""
    st = rolling_stats(counts)
    if not len(st):
        return None
    out = pd.DataFrame(st, columns=["D_raw", "D_resid", "CV"])
    out["D_weekly"] = out["D_raw"] - out["D_resid"]
    out["date"] = dates[WINDOW - 1:]
    out["n"] = pd.Series(counts).rolling(WINDOW).mean().dropna().values
    return out


def placebo_ratios(sf, rng):
    """Ratios from random cut dates. Returns dict est -> array of log ratios."""
    d = sf["date"].values
    total = (d[-1] - d[0]).astype("timedelta64[D]").astype(int)
    # Each side of a cut needs enough windows to estimate D. Cap at MIN_SIDE but
    # shrink for short histories, otherwise a restricted window drops everything.
    side = min(MIN_SIDE, int(total * 0.30))
    if side < 3 * WINDOW:
        return None
    lo, hi = d[0] + np.timedelta64(side, "D"), d[-1] - np.timedelta64(side, "D")
    if lo >= hi:
        return None

    span = (hi - lo).astype("timedelta64[D]").astype(int)
    cuts = lo + rng.integers(0, span, N_PLACEBO).astype("timedelta64[D]")

    out = {e: [] for e in ESTIMATORS}
    out["n_ratio"] = []
    for c in cuts:
        a, b = sf[sf["date"] < c], sf[sf["date"] >= c]
        if len(a) < WINDOW or len(b) < WINDOW:
            continue
        for e in ESTIMATORS:
            va, vb = a[e].mean(), b[e].mean()
            out[e].append(np.log(vb / va) if va > 0 and vb > 0 else np.nan)
        out["n_ratio"].append(np.log(b["n"].mean() / a["n"].mean()))
    return {k: np.array(v) for k, v in out.items()}


def main(path):
    rng = np.random.default_rng(SEED)
    df = load(path)
    pre = df[df["date"] < EVENT]
    if PRE_START is not None:
        pre = pre[pre["date"] >= pd.Timestamp(PRE_START)]

    per_cp, keep = {}, []
    for name, sub in pre.groupby("portname"):
        sub = sub.sort_values("date")
        counts = sub[COL].to_numpy(dtype=float)
        if counts.mean() < MIN_DAILY:
            continue
        sf = stats_frame(counts, sub["date"].values)
        if sf is None:
            continue
        r = placebo_ratios(sf, rng)
        if r is None or not len(r["D_raw"]):
            continue
        per_cp[name] = r
        keep.append(name)

    print("=" * 78)
    print(f"PLACEBO NOISE FLOOR  ({N_PLACEBO} cut dates/chokepoint, "
          f"{len(keep)} chokepoints)")
    print(f"  window: {pd.Timestamp(PRE_START).date() if PRE_START else '2019-01-01'}"
          f" to {EVENT.date()}   (<={MIN_SIDE}d each side of a cut, adaptive)")
    print("=" * 78)
    print("  A real effect must exceed this to mean anything.\n")

    print(f"  {'estimator':<10} {'sd(log r)':>10} {'2.5%':>9} {'97.5%':>9} "
          f"{'band width':>12}")
    floors = {}
    for e in ESTIMATORS:
        allr = np.concatenate([np.asarray(per_cp[c][e], dtype=float) for c in keep])
        allr = allr[np.isfinite(allr)]
        sd = allr.std(ddof=1)
        lo, hi = np.percentile(allr, [2.5, 97.5])
        floors[e] = sd
        print(f"  {e:<10} {sd:>10.3f} {np.exp(lo):>9.3f} {np.exp(hi):>9.3f} "
              f"{np.exp(hi)/np.exp(lo):>11.2f}x")

    print("\n  (ratios, not logs, in the percentile columns)")

    # Does the placebo cut also shift traffic? If so the mean-bias correction
    # matters even here, and the floor should be measured on corrected ratios.
    print("\n" + "=" * 78)
    print("BIAS CORRECTION UNDER PLACEBO")
    print("=" * 78)
    for e in ESTIMATORS:
        x, y = [], []
        for c in keep:
            x.append(np.asarray(per_cp[c]["n_ratio"], dtype=float))
            y.append(np.asarray(per_cp[c][e], dtype=float))
        x, y = np.concatenate(x), np.concatenate(y)
        m = np.isfinite(x) & np.isfinite(y)
        _, b, se, r2 = ols(x[m], y[m])
        print(f"  {e:<10} slope {b:+.3f} (se {se:.3f})  R^2 {r2:.3f}"
              f"   -> corrected sd {(y[m] - b * x[m]).std(ddof=1):.3f}")

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    best = min(floors, key=floors.get)
    print(f"  Tightest floor: {best} (sd {floors[best]:.3f})")
    for e in ESTIMATORS:
        pct = np.exp(1.96 * floors[e]) - 1
        print(f"    {e:<10} needs a move larger than ~{pct:+.0%} to clear noise")
    print("\n  Compare against the mean-bias table from validate_dispersion.py.")
    print("  The usable estimator is the one that is both unbiased AND tight.")
    print("  An unbiased estimator with a 2x noise band cannot detect anything.")

    pd.DataFrame(
        {e: [floors[e], np.exp(1.96 * floors[e]) - 1] for e in ESTIMATORS},
        index=["sd_log_ratio", "min_detectable_move"],
    ).to_csv("outputs/tables/noise_floor.csv")
    print("\nsaved to outputs/tables/noise_floor.csv")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--from" in args:
        i = args.index("--from")
        globals()["PRE_START"] = args[i + 1]
        del args[i:i + 2]
    path = args[0] if args else CSV
    main(path)