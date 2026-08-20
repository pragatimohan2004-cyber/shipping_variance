"""
Permutation-style rank test.

Question: is Bab el-Mandeb's container CV ratio distinguishable from what any
chokepoint might show over this period?

Approach: compute the container CV ratio for all 28 chokepoints, then ask where
Bab el-Mandeb falls in that empirical distribution. Reported twice - once against
the full set, once excluding conflict-affected chokepoints, since those may reflect
AIS degradation rather than shipping behaviour.
"""

import pandas as pd

df = pd.read_csv("raw/Daily_Chokepoints_Data.csv", encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])

event = pd.Timestamp("2023-12-15")
WINDOW = 28
TARGET = "Bab el-Mandeb Strait"
MIN_DAILY = 3.0          # below this, CV is Poisson-dominated

# Conflict-affected or otherwise compromised. Excluded from the clean null.
# Bab el-Mandeb stays in as the thing being tested.
EXCLUDE = {
    "Kerch Strait",          # Crimea / war
    "Strait of Hormuz",      # Iran tension, documented GPS jamming
    "Bosporus Strait",       # Black Sea war traffic
    "Malacca Strait",        # documented 2021 receiver coverage break
}

rows = []

for name in sorted(df["portname"].unique()):
    sub = df[df["portname"] == name].sort_values("date")
    is_pre = sub["date"] < event

    roll = sub["n_container"].rolling(WINDOW)
    cv = roll.std() / roll.mean()

    pre = cv[is_pre].mean()
    post = cv[~is_pre].mean()

    rows.append({
        "chokepoint": name,
        "container_pre_n": sub.loc[is_pre, "n_container"].mean(),
        "container_post_n": sub.loc[~is_pre, "n_container"].mean(),
        "cv_pre": pre,
        "cv_post": post,
        "ratio": post / pre,
    })

res = pd.DataFrame(rows)

# Drop chokepoints too thin for CV to mean anything
thin = res[
    (res["container_pre_n"] < MIN_DAILY) | (res["container_post_n"] < MIN_DAILY)
]
res_ok = res[~res.index.isin(thin.index)].copy()

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 40)


def rank_test(frame, label):
    frame = frame.sort_values("ratio", ascending=False).reset_index(drop=True)

    if TARGET not in frame["chokepoint"].values:
        print(f"\n{label}: target not in this set")
        return

    rank = frame.index[frame["chokepoint"] == TARGET][0] + 1
    n = len(frame)
    target_ratio = frame.loc[frame["chokepoint"] == TARGET, "ratio"].iloc[0]
    n_above = (frame["ratio"] > target_ratio).sum()
    p = (n_above + 1) / (n + 1)

    print(f"\n{'='*68}")
    print(f"{label}")
    print(f"{'='*68}")
    print(frame[["chokepoint", "ratio", "container_pre_n", "container_post_n"]]
          .to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print(f"\n  {TARGET}: ratio={target_ratio:.3f}")
    print(f"  rank {rank} of {n}   ({n_above} above)")
    print(f"  one-sided empirical p = {p:.3f}")
    print(f"  null distribution: mean={frame['ratio'].mean():.3f}  "
          f"median={frame['ratio'].median():.3f}  sd={frame['ratio'].std():.3f}")

    z = (target_ratio - frame["ratio"].mean()) / frame["ratio"].std()
    print(f"  z-score vs null = {z:.2f}")


print(f"\nExcluded for thin counts (<{MIN_DAILY}/day): "
      f"{sorted(thin['chokepoint'].tolist())}")

rank_test(res_ok, "TEST 1 — all chokepoints with adequate container traffic")

clean = res_ok[~res_ok["chokepoint"].isin(EXCLUDE)]
rank_test(clean, "TEST 2 — excluding conflict-affected and known-break chokepoints")

res.to_csv("outputs/tables/container_rank_test.csv", index=False)
print("\nsaved to outputs/tables/container_rank_test.csv")