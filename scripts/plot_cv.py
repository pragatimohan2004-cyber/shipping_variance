import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("raw/Daily_Chokepoints_Data.csv", encoding="utf-8-sig")
df["date"] = pd.to_datetime(df["date"])

targets = [
    "Suez Canal",
    "Bab el-Mandeb Strait",
    "Cape of Good Hope",
    "Malacca Strait",
]

event = pd.Timestamp("2023-12-15")
WINDOW = 28

fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)

for name, ax in zip(targets, axes):
    sub = df[df["portname"] == name].sort_values("date")

    roll = sub["n_total"].rolling(WINDOW)
    cv = roll.std() / roll.mean()

    ax.plot(sub["date"], cv, linewidth=1)
    ax.axvline(event, color="red", linestyle="--", alpha=0.7)
    ax.set_title(name)
    ax.set_ylabel("CV")
    ax.grid(alpha=0.3)

    # pre/post means, printed for the record
    pre = cv[sub["date"] < event].mean()
    post = cv[sub["date"] >= event].mean()
    print(f"{name:24} pre={pre:.4f}  post={post:.4f}  ratio={post/pre:.2f}")

axes[-1].set_xlabel("date")
fig.suptitle(f"Coefficient of variation, {WINDOW}-day rolling window", y=1.00)

plt.tight_layout()
plt.savefig("outputs/figures/chokepoint_cv.png", dpi=150, bbox_inches="tight")
print("\nsaved to outputs/figures/chokepoint_cv.png")