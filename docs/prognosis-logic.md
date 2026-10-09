# Rhine Swimming Recommendation Logic

This document defines the automated estimation logic used to determine if swimming in the Rhine at Basel is currently advisable. The recommendation is calculated by assessing two independent indices: **Water Quality** (microbiological risk) and **Swimmer Safety** (physical risk).

## Input Parameters
Data is fetched every 15 minutes (radiation: one value per day) from the [Basel-Stadt Open Data Portal](https://data.bs.ch/).

| Parameter | Station | Unit | Metric Used |
| :--- | :--- | :--- | :--- |
| **Precipitation** | St. Johann (`034001AF`) | mm (rolling 24h sum, hourly readings) | Weighted 72h impact ($I$) |
| **Global Radiation** | MeteoSchweiz Basel-Binningen (dataset 100254, daily mean) | W/m² | Average of the last 3 complete days ($B$) |
| **Water Temperature** | Weil am Rhein | °C | Latest ($T_{now}$) & 48h Average ($T_{avg}$, mean of the newest four 12h buckets) |

## Calculation Models

### A. Rain Impact Score ($I$)
Rain triggers combined sewer overflows (CSO), increasing bacterial load. This impact decays over time:
- $R_0$: Rain of the last 24 hours (100% weight)
- $R_1$: Rain of the 24 hours before that, i.e. 24-48h ago (50% weight)
- $R_2$: Rain 48-72h ago (25% weight)

The station reports a *rolling* 24h sum with every reading. $R_0$ is the latest reading, $R_1$ the reading 24h earlier and $R_2$ the reading 48h earlier. Each window therefore covers a different 24 hours, so no rain is counted twice. A reading is only used if it is at most 3 hours older than the requested time; otherwise the window counts as 0 mm and a warning is logged.

**Formula:** $I = (R_0 \times 1.0) + (R_1 \times 0.5) + (R_2 \times 0.25)$

> Do not use the *daily maximum* of the rolling sum as "rain of the day": right after midnight the window still contains the previous day, so a dry day after a rainy one would show the rain of the day before (and the weighted sum above would count it several times).

### B. Radiation Bonus ($B$)
Global radiation acts as a natural disinfectant. High radiation speeds up the inactivation of fecal indicators (e.g., *E. coli*).
- $Rad_{threshold}$: 170 W/m² (Reference for a sunny day, 24h mean including the night)
- $Rad_{0..2}$: daily mean of **yesterday, 2 days ago and 3 days ago**. The city publishes a day's mean only after the day is over, so today is never available. Values are matched by date. Missing days are left out of the average; without any data $B = 0$ (overcast penalty applies).

**Formula:** $B = \frac{\text{Avg}(Rad_{0..2})}{Rad_{threshold}}$

---

## Decision Matrix

The overall status is the **minimum** of the Water Quality Index and the Swimmer Safety Index.

### 1. Water Quality Index (Microbiological)
Focuses on bacterial risk from rain, overflows, and lack of natural disinfection.

| Level | Status | Condition |
| :--- | :--- | :--- |
| **3** | **Excellent** | $I < 0.5$ (Dry) OR ($R_0 < 1.0$ AND $I < 2.0$ AND $B > 1.2$) |
| **2** | **Good** | ($I < 3.5$ OR ($R_0 < 1.5$ AND $I < 5.0$ AND $B > 1.0$)) AND $B \ge 0.6$ |
| **1** | **Discouraged**| *Standard fallback* if not meeting Level 2/3. Triggered by $I \ge 5.0$, $R_0 \ge 1.5$, $B < 0.6$ (Overcast), or $T_{avg} > 22^\circ\text{C}$ (Thermal). |

### 2. Swimmer Safety Index (Physical)
Focuses on immediate physical dangers, primarily cold shock.

| Level | Status | Condition |
| :--- | :--- | :--- |
| **3** | **Safe** | $T_{now} \ge 18^\circ\text{C}$ |
| **2** | **Caution** | $14^\circ\text{C} \le T_{now} < 18^\circ\text{C}$ (Cold water risk) |
| **1** | **Discouraged**| $T_{now} < 14^\circ\text{C}$ (High cold-shock risk) |

---

## Scientific Rationale

- **Decoupling Indices:** Microbiological quality (bacteria) and physical safety (temperature) are independent variables. A river can be bacterially clean but dangerously cold. Separating these ensures transparency.
- **The 3.5mm Threshold:** In Basel, sewer overflows typically begin after 3-5mm of rain. Our threshold of 3.5 reflects this tipping point.
- **Radiation Bonus (Global vs. UV):** Global radiation (W/m²) is used as a proxy for total solar energy. Total insolation is a proven predictor of bacterial decline in turbid waters.
- **Overcast Penalty ($B < 0.6$):** Data from the Kantonslabor BS (2025) shows that on overcast days without rain, 54% of samples are unsafe due to lack of natural disinfection.
- **The 14°C Rule:** Water below 14°C significantly increases the risk of "Cold Shock Response" (involuntary gasping/hyperventilation), which is a leading cause of drowning.
- **Thermal Risk ($22^\circ\text{C}$ Average):** Sustained high temperatures promote rapid microbial growth.

## Disclaimer
This is an **automated estimate** based on environmental proxies. It is **not** a real-time biological measurement. Swimming in the Rhine is always at your own risk. Local pollution events can occur unpredictably.
