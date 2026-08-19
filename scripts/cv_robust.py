import pandas as pd

df = pd.read_csv("raw/Daily_Chokepoints_Data.csv", encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])

event = pd.Timestamp("2023-12-15")

targets = [
    "Bab el-Mandeb Strait",
    "Suez Canal",
    "Cape of Good Hope",
    "Panama Canal",
    "Malacca Strait",
]
metrics = ["n_container", "n_tanker", "n_dry_bulk"]


def cv_ratio(series, dates, window):
    roll = series.rolling(window)
    cv = roll.std() / roll.mean()
    is_pre = dates < event
    return cv[is_pre].mean() / 1 and cv[~is_pre].mean() / cv[is_pre].mean()


# --- daily grain, three window lengths ---
print("=== DAILY grain, container CV ratio by window ===")
for window in [14, 28, 56, 91]:
    line = {"window": window}
    for name in targets:
        sub = df[df["portname"] == name].sort_values("date")
        line[name.split()[0]] = cv_ratio(sub["n_container"], sub["date"], window)
    print({k: (f"{v:.3f}" if isinstance(v, float) else v) for k, v in line.items()})


# --- weekly grain ---
print("\n=== WEEKLY aggregation, 13-week window ===")
rows = []
for name in targets:
    sub = df[df["portname"] == name].sort_values("date").set_index("date")
    wk = sub[metrics].resample("W").sum().reset_index()

    row = {"chokepoint": name}
    for m in metrics:
        roll = wk[m].rolling(13)
        cv = roll.std() / roll.mean()
        is_pre = wk["date"] < event
        row[m] = cv[~is_pre].mean() / cv[is_pre].mean()
    row["container_wk_pre_n"] = wk.loc[wk["date"] < event, "n_container"].mean()
    row["container_wk_post_n"] = wk.loc[wk["date"] >= event, "n_container"].mean()
    rows.append(row)

res = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(res.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

res.to_csv("outputs/tables/cv_robust.csv", index=False)
print("\nsaved to outputs/tables/cv_robust.csv")