"""
Confound check: is the container CV ratio just measuring the drop in sample size?

A CV estimated on ~6 observations/day is mechanically noisier than one estimated
on ~17/day. Bab el-Mandeb's container traffic fell 66%. So a traffic collapse
manufactures the exact signal we are testing for.

This script:
  1. Regresses log(CV ratio) on log(post_n / pre_n) across all chokepoints
  2. Reports R^2 - how much of the spread is explained by sample size alone
  3. Ranks the RESIDUALS - what is left after accounting for it

If Bab el-Mandeb ranks first on residuals too, the finding survives.
If it drops, the effect was largely thinness.
"""

import numpy as np
import pandas as pd

df = pd.read_csv("raw/Daily_Chokepoints_Data.csv", encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])

event = pd.Timestamp("2023-12-15")
WINDOW = 28
TARGET = "Bab el-Mandeb Strait"
MIN_DAILY = 3.0

# Not independent draws from a no-effect null:
#   Suez / Cape of Good Hope = the same shock's other half
#   Hormuz / Kerch / Bosporus = conflict, documented AIS degradation
#   Malacca = documented 2021 receiver coverage break
NOT_CLEAN = {
    "Suez Canal",
    "Cape of Good Hope",
    "Strait of Hormuz",
    "Kerch Strait",
    "Bosporus Strait",
    "Malacca Strait",
}

rows = []
for name in sorted(df["portname"].unique()):
    sub = df[df["portname"] == name].sort_values("date")
    is_pre = sub["date"] < event

    roll = sub["n_container"].rolling(WINDOW)
    cv = roll.std() / roll.mean()

    pre_n = sub.loc[is_pre, "n_container"].mean()
    post_n = sub.loc[~is_pre, "n_container"].mean()

    rows.append({
        "chokepoint": name,
        "pre_n": pre_n,
        "post_n": post_n,
        "n_ratio": post_n / pre_n,
        "cv_ratio": cv[~is_pre].mean() / cv[is_pre].mean(),
    })

res = pd.DataFrame(rows)
res = res[(res["pre_n"] >= MIN_DAILY) & (res["post_n"] >= MIN_DAILY)].copy()

# ------------------------------------------------------------------
# 1. How coupled are they?
# ------------------------------------------------------------------
res["log_n_ratio"] = np.log(res["n_ratio"])
res["log_cv_ratio"] = np.log(res["cv_ratio"])

corr = res["log_n_ratio"].corr(res["log_cv_ratio"])

# OLS by hand: log_cv = a + b * log_n
x = res["log_n_ratio"].values
y = res["log_cv_ratio"].values
b = np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1)
a = y.mean() - b * x.mean()

res["fitted"] = a + b * res["log_n_ratio"]
res["residual"] = res["log_cv_ratio"] - res["fitted"]

ss_res = (res["residual"] ** 2).sum()
ss_tot = ((y - y.mean()) ** 2).sum()
r2 = 1 - ss_res / ss_tot

print("=" * 72)
print("SAMPLE-SIZE CONFOUND")
print("=" * 72)
print(f"  n chokepoints           {len(res)}")
print(f"  corr(log n, log CV)     {corr:.3f}")
print(f"  slope                   {b:.3f}   (negative = fewer obs -> higher CV)")
print(f"  R^2                     {r2:.3f}")
print()
if r2 > 0.5:
    print("  >>> Sample size explains most of the spread. The raw ranking is")
    print("      substantially mechanical. Residual rank is the real test.")
elif r2 > 0.25:
    print("  >>> Sample size explains a meaningful share. Residual rank matters.")
else:
    print("  >>> Sample size explains little. Raw ranking largely stands.")


# ------------------------------------------------------------------
# 2. Rank on residuals
# ------------------------------------------------------------------
def report(frame, label):
    frame = frame.sort_values("residual", ascending=False).reset_index(drop=True)
    if TARGET not in frame["chokepoint"].values:
        return

    rank = frame.index[frame["chokepoint"] == TARGET][0] + 1
    n = len(frame)
    tgt = frame.loc[frame["chokepoint"] == TARGET, "residual"].iloc[0]
    n_above = (frame["residual"] > tgt).sum()
    z = (tgt - frame["residual"].mean()) / frame["residual"].std()

    print("\n" + "=" * 72)
    print(label)
    print("=" * 72)
    print(
        frame[["chokepoint", "cv_ratio", "n_ratio", "residual"]]
        .to_string(index=False, float_format=lambda v: f"{v:.3f}")
    )
    print(f"\n  {TARGET}")
    print(f"    raw CV ratio        {frame.loc[frame['chokepoint']==TARGET,'cv_ratio'].iloc[0]:.3f}")
    print(f"    residual            {tgt:+.3f}")
    print(f"    residual rank       {rank} of {n}  ({n_above} above)")
    print(f"    z vs residual null  {z:.2f}")
    print(f"    p-floor for n={n}   {1/(n+1):.3f}   <- smallest p this set can give")


report(res, "RESIDUAL RANK - all chokepoints with adequate traffic")

clean = res[~res["chokepoint"].isin(NOT_CLEAN)].copy()
# refit on the clean set only
xc = clean["log_n_ratio"].values
yc = clean["log_cv_ratio"].values
bc = np.cov(xc, yc, ddof=1)[0, 1] / np.var(xc, ddof=1)
ac = yc.mean() - bc * xc.mean()
clean["residual"] = clean["log_cv_ratio"] - (ac + bc * clean["log_n_ratio"])

report(clean, "RESIDUAL RANK - clean null (shock partners + conflict zones dropped)")

res.to_csv("outputs/tables/confound_check.csv", index=False)
print("\nsaved to outputs/tables/confound_check.csv")