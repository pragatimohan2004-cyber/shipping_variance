import pandas as pd

df = pd.read_csv("raw/Daily_Chokepoints_Data.csv", encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])

event = pd.Timestamp("2023-12-15")
WINDOW = 28

targets = [
    "Bab el-Mandeb Strait",
    "Suez Canal",
    "Cape of Good Hope",
    "Panama Canal",
    "Malacca Strait",
]

metrics = ["n_total", "n_container", "n_tanker", "n_dry_bulk"]

rows = []

for name in targets:
    sub = df[df["portname"] == name].sort_values("date")
    is_pre = sub["date"] < event

    row = {"chokepoint": name}

    for m in metrics:
        roll = sub[m].rolling(WINDOW)
        cv = roll.std() / roll.mean()

        pre = cv[is_pre].mean()
        post = cv[~is_pre].mean()

        row[f"{m}_ratio"] = post / pre
        # mean daily counts, to flag small-sample fragility
        row[f"{m}_pre_n"] = sub.loc[is_pre, m].mean()
        row[f"{m}_post_n"] = sub.loc[~is_pre, m].mean()

    rows.append(row)

res = pd.DataFrame(rows)

pd.set_option("display.width", 200)

print("\n=== CV RATIO (post / pre) ===")
print(
    res[["chokepoint"] + [f"{m}_ratio" for m in metrics]]
    .to_string(index=False, float_format=lambda x: f"{x:.3f}")
)

print("\n=== MEAN DAILY COUNTS (watch for small samples) ===")
count_cols = [c for m in metrics for c in (f"{m}_pre_n", f"{m}_post_n")]
print(
    res[["chokepoint"] + count_cols]
    .to_string(index=False, float_format=lambda x: f"{x:.1f}")
)

res.to_csv("outputs/tables/cv_by_type.csv", index=False)
print("\nsaved to outputs/tables/cv_by_type.csv")