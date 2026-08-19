import pandas as pd
import matplotlib.pyplot as plt

# Load
df = pd.read_csv("raw/Daily_Chokepoints_Data.csv", encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])

# The four series that tell the rerouting story
targets = [
    "Suez Canal",
    "Bab el-Mandeb Strait",
    "Cape of Good Hope",
    "Malacca Strait",
]

# Major carriers announced Red Sea suspension mid-December 2023
event = pd.Timestamp("2023-12-15")

fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)

for name, ax in zip(targets, axes):
    sub = df[df["portname"] == name].sort_values("date")
    smooth = sub["n_total"].rolling(7).mean()

    ax.plot(sub["date"], smooth, linewidth=1)
    ax.axvline(event, color="red", linestyle="--", alpha=0.7)
    ax.set_title(name)
    ax.set_ylabel("transits/day")
    ax.grid(alpha=0.3)

axes[-1].set_xlabel("date")
fig.suptitle("Daily transits, 7-day rolling mean", y=1.00)

plt.tight_layout()
plt.savefig("outputs/figures/chokepoint_series.png", dpi=150, bbox_inches="tight")
print("saved to outputs/figures/chokepoint_series.png")