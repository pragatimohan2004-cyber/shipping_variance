# 🚢 Chokepoint Variance — Measuring a Disruption That Mostly Wasn't There

![Data](https://img.shields.io/badge/DATA-IMF%20PortWatch-1f3864)
![Rows](https://img.shields.io/badge/ROWS-77%2C784-blue)
![Span](https://img.shields.io/badge/2019--2026-7.6%20years-green)
![Method](https://img.shields.io/badge/METHOD-Event%20Study-orange)
![Result](https://img.shields.io/badge/RESULT-Null%20after%20adjustment-red)

**When the Red Sea closed, container traffic through Bab el-Mandeb became 81% more
erratic. Most of that turned out to be an artifact of having 66% less data to
measure.**

This repo documents both the apparent effect and the check that dissolved it.

---

## 🎯 What Actually Happened

In December 2023 major carriers suspended Red Sea transits and rerouted Asia–Europe
traffic around the Cape of Good Hope. The volume shift is unambiguous:

```
Suez Canal          75 → 42 transits/day      ▼ 44%
Bab el-Mandeb       78 → 40 transits/day      ▼ 49%
Cape of Good Hope   50 → 95 transits/day      ▲ 90%
Malacca Strait     183 → 227 transits/day     ▬ flat
```

Malacca sits upstream of the Suez/Cape decision point on the same trade lane. It
didn't move. **Trade rerouted; it did not disappear.**

---

## 📉 The Apparent Finding

Measuring predictability as the coefficient of variation (rolling σ / rolling μ) of
daily transit counts, container traffic looked dramatically more erratic on the
abandoned route:

| Chokepoint | Container CV ratio | Reading |
|---|---|---|
| Bab el-Mandeb | **1.81** | far less predictable |
| Suez Canal | **1.40** | less predictable |
| Cape of Good Hope | 0.77 | *more* predictable |
| Panama Canal | 0.95 | no effect |
| Malacca Strait | 0.85 | no effect |

It survived every robustness check thrown at it. Window length made no difference
(14/28/56/91-day → 1.810/1.808/1.831/1.860). Weekly aggregation made it *stronger*
(2.76). Against all 28 chokepoints it ranked first.

The story wrote itself: container lines run fixed schedules, tankers run spot
charters, so a schedule-destroying disruption should hit containers hardest — and
the vessel-type ordering matched (container 1.81 > tanker 1.29 > dry bulk 1.18).

---

## ⚠️ The Check That Killed It

A CV estimated on ~6 observations per day is mechanically noisier than one estimated
on ~17 per day. Bab el-Mandeb's container traffic fell from 17.1/day to 5.9/day.

**So a traffic collapse manufactures the exact signal being tested for.**

Regressing log(CV ratio) on log(post_n / pre_n) across 18 chokepoints:

| | |
|---|---|
| correlation | **−0.723** |
| slope | −0.371 |
| **R²** | **0.522** |

Sample size explains more than half the cross-chokepoint variance in CV ratios.

Ranking on the residuals — what's left after accounting for observation count:

| Chokepoint | Raw CV ratio | n ratio | Residual |
|---|---|---|---|
| Taiwan Strait | 1.163 | 1.046 | **+0.172** |
| Luzon Strait | 0.992 | 1.341 | **+0.139** |
| Dover Strait | 1.038 | 1.037 | +0.054 |
| Windward Passage | 0.997 | 1.112 | +0.050 |
| **Bab el-Mandeb** | **1.808** | **0.342** | **+0.049** |
| Tsugaru Strait | 1.010 | 1.033 | +0.025 |
| Panama Canal | 0.949 | 1.070 | −0.020 |
| … | | | |

**Bab el-Mandeb falls from rank 1 to rank 5 of 13, z = 0.52.** Taiwan and Luzon
Straits — neither disrupted, neither conflict-affected — show larger unexplained
CV increases.

> **Conclusion: after adjusting for observation count, the Red Sea disruption's
> effect on container transit variance is not distinguishable from background.**

The vessel-type gradient is also unresolved. The three types lost traffic at
different rates, so differential sample-size loss is an untested rival explanation
for the ordering. It is *not* claimed as a finding here.

---

## 🧭 What This Is Worth

The null result is the deliverable. Three things it demonstrates:

**A plausible mechanism is not evidence.** The scheduling story fit the data,
survived four robustness checks, and was wrong. Window invariance and aggregation
stability test whether an estimate is *stable* — neither tests whether it's
*confounded*.

**The confound was visible in the output all along.** Sort the results by CV ratio
and by sample-size change and you get nearly the same ordering. It took explicitly
regressing one on the other to see it.

**Small-n inference has a hard floor.** With 28 chokepoints and ~13 usable as a
clean null, the smallest empirical p obtainable is 1/(n+1) = 0.071. A permutation
test here can never reach 0.05 regardless of effect size, which is why the residual
rank and z-score carry the inferential weight rather than the p-value.

---

## 🔍 Open Leads

| Lead | Why it's interesting |
|---|---|
| **Cape of Good Hope**, residual +0.167, rank 2 | It *gained* traffic and still shows excess variance. Opposite direction — not explicable by thin data. Possibly the real finding. |
| **Strait of Hormuz**, residual +0.489, largest | Consistent with AIS degradation (documented GPS jamming) rather than shipping behaviour. Would help characterise measurement error directly. |
| **Subsample-matched test** | Thin each pre-period to its own post-period n, 500 draws, rank on median. More convincing than regression adjustment. Not yet run. |
| **Ever Given, March 2021** | Visible in the series. A disruption with a known answer — method validation. |
| **Port-level data** (2,065 ports) | Untouched. Did arrival clustering propagate into port congestion? |

---

## 📦 Data

**Source:** [IMF PortWatch](https://portwatch.imf.org) — Daily Chokepoint Transit
Calls and Trade Volume Estimates. Satellite AIS on ~90,000 vessels.

| | |
|---|---|
| Chokepoints | 28 |
| Rows | 77,784 |
| Range | 2019-01-01 → 2026-08-09 |
| Grain | one row per chokepoint per day |
| Vessel types | container, dry bulk, general cargo, ro-ro, tanker |
| Retrieved | 2026-08-18 (vintage 2026-08-11) |

Raw data is gitignored — download from the link into `raw/`.

**Reproducibility caveat:** PortWatch restates history when methodology changes.
Vessel classification expanded from 2 to 5 categories in 2024 (backfilled),
boundaries have been refined, AIS spoofing checks added in 2026. Reproducing these
numbers requires the same vintage.

---

## ⚠️ Other Limitations

**Conflict-zone data quality.** PortWatch documents GPS jamming, AIS spoofing, and
dark vessels in the Red Sea and around Hormuz. Degraded reporting inflates measured
variance independently of shipping behaviour. This is a second confound, separate
from sample size, and it is not addressed here.

**Malacca has a known break.** Receiver coverage expanded in 2021, causing a
documented step change. Used as qualitative confirmation that trade rerouted, not
as a quantitative control.

**Suez and Cape are not independent comparators.** They are the same shock's other
half and are excluded from the clean null.

**Event date.** 2023-12-15, when carriers announced suspension. First vessel seizure
was 2023-11-19. Results are not sensitive to the choice.

---

## 🚀 Running It

```bash
python -m venv .venv
.venv\Scripts\activate
pip install pandas numpy matplotlib

python scripts/explore.py           # schema, date range, integrity check
python scripts/plot_chokepoints.py  # transit volumes
python scripts/plot_cv.py           # rolling CV
python scripts/cv_all.py            # vessel-type CV ratios
python scripts/cv_robust.py         # window + weekly aggregation checks
python scripts/rank_test.py         # permutation rank (superseded — p is floored)
python scripts/confound_check.py    # ← the one that matters
```

Outputs land in `outputs/figures/` and `outputs/tables/`.