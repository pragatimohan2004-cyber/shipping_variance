import pandas as pd

df = pd.read_csv("raw/Daily_Chokepoints_Data.csv", encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])

print(df.shape)
print(df["date"].min(), df["date"].max())
for name in sorted(df["portname"].unique()):
    print(name)
types = ["n_container", "n_dry_bulk", "n_general_cargo", "n_roro", "n_tanker"]
print((df[types].sum(axis=1) != df["n_total"]).sum(), "rows where types dont sum to total")
