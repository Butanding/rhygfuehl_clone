# Rhine Swimming Recommendation Logic

This document defines the automated estimation logic used to determine if swimming in the Rhine at Basel is currently advisable. The recommendation is calculated by assessing two independent indices: **Water Quality** (microbiological risk) and **Swimmer Safety** (physical risk).

## Input Parameters
Data is fetched every 15 minutes from the [Basel-Stadt Open Data Portal](https://data.bs.ch/); precipitation and global radiation come from the open data of [MeteoSwiss](https://opendatadocs.meteoswiss.ch/) (hourly values).

| Parameter | Station | Unit | Metric Used |
| :--- | :--- | :--- | :--- |
| **Precipitation** | MeteoSwiss Basel-Binningen (`BAS`, parameter `rre150h0`) | mm, hourly total | Age-weighted 72h impact ($I$) and the 24h sums $R_0..R_2$ |
| **Global Radiation** | MeteoSwiss Basel-Binningen (`BAS`, parameter `gre000h0`) | W/m², hourly mean | Mean of the last 72 hours ($B$) |
| **Water Temperature** | Weil am Rhein | °C | Latest ($T_{now}$), only used for the Swimmer Safety Index |

## Calculation Models

### A. Rain Impact Score ($I$)
Rain triggers combined sewer overflows (CSO), increasing bacterial load. This impact decays over time, with a weight of roughly 100% for the last 24 hours, 50% for the 24 hours before and 25% for those before:
- $R_0$: Rain of the last 24 hours
- $R_1$: Rain of the 24 hours before that, i.e. 24-48h ago
- $R_2$: Rain 48-72h ago

The hourly totals are summed over three consecutive 24-hour windows ending at the newest available hour: $R_0$ is the last 24 hours, $R_1$ the 24 hours before that, $R_2$ the 24 hours before that. Each rain hour falls into exactly one window, so no rain is counted twice. Hours without a value count as 0 mm and a warning is logged. The same hourly values are shown as bars in the rain chart.

**Smooth decay:** The windows only name the periods and are used for the conditions on $R_0$. The impact $I$ itself weights every single hour by its age, so the rating does not jump when rain passes the 24h or 48h mark:

$I = \sum_{h} \text{rain}_h \times w(a_h)$, with $w(a) = 2^{-(a - 11.5\,\text{h}) / 24\,\text{h}}$

where $a_h$ is the age of the middle of the hour in hours. The weight halves every 24 hours and fades linearly to 0 over the last 12 hours of the 72h window. The constant 11.5 h is chosen so that steady rain counts like the former block weights: an average weight of 1.0 for 0-24h, 0.5 for 24-48h and about 0.2 for 48-72h (before: 1 / 0.5 / 0.25), so the thresholds of the decision matrix stay valid. The largest change of the weight from one hour to the next is 0.04 (before: 0.5 at once).

**Time stamps:** MeteoSwiss labels a value with the *end* of its hour (UTC): the row `08:00` is the rain between 07:00 and 08:00.

**Why Basel-Binningen and not the city's own sensors:** The "Smart Climate" sensors of the Basel-Stadt open data (dataset 100009, station St. Johann) were used before. They are raw, unvalidated readings of a single low-cost sensor. On 11 Oct 2026 it reported 9.4 mm of rain, the maximum of about 80 stations (median 0.0 mm, Binningen 0.0 mm). On 8 Oct 2026 it reported only 5.4 mm where Binningen measured 28.6 mm. Its hourly field (`meta_rain_1h_val`) adds up to only about a quarter of its own 24h sum. The other candidates are unusable too: the Rosental weather station (100294) stopped delivering in September 2026 and the Binningen air quality dataset (100051) has no precipitation values. Binningen is about 5 km from the Rhine, but it is a validated reference station, and the global radiation already comes from the same station.

> Do not derive "rain of the day" from a *rolling* 24h sum (for example the daily maximum): right after midnight the window still contains the previous day, so a dry day after a rainy one would show the rain of the day before, and the weighted sum would count it several times.

### B. Radiation Bonus ($B$)
Global radiation acts as a natural disinfectant. High radiation speeds up the inactivation of fecal indicators (e.g., *E. coli*).
- $Rad_{threshold}$: 170 W/m² (Reference for a sunny day, 24h mean including the night)
- $Rad_h$: hourly mean radiation of the **same 72 hours as the rain**, night included, so $B$ is the mean over three whole days. There is no delay: the values are as fresh as the rain. Hours without a value are left out of the mean; without any data $B = 0$ (overcast penalty applies).

**Formula:** $B = \frac{\text{Avg}(Rad_h)}{Rad_{threshold}}$

---

## Decision Matrix

The overall status is the **minimum** of the Water Quality Index and the Swimmer Safety Index.

### 1. Water Quality Index (Microbiological)
Focuses on bacterial risk from rain, overflows, and lack of natural disinfection.

| Level | Status | Condition |
| :--- | :--- | :--- |
| **3** | **Excellent** | $I < 0.5$ (Dry) OR ($R_0 < 1.0$ AND $I < 2.0$ AND $B > 1.2$) |
| **2** | **Good** | ($I < 3.5$ OR ($R_0 < 1.5$ AND $I < 5.0$ AND $B > 1.0$)) AND $B \ge 0.6$ |
| **1** | **Discouraged**| *Standard fallback* if not meeting Level 2/3. Triggered by $I \ge 5.0$, $R_0 \ge 1.5$ or $B < 0.6$ (Overcast). |

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
- **No Thermal Cap:** An earlier version capped the Water Quality Index at *Discouraged* when the 48h average water temperature exceeded 22 °C, assuming that warm water promotes bacterial growth. This was removed: the Rhine is a fast-flowing river with a high water turnover, and the Cantonal Laboratory Basel-Stadt reported very good microbiological results on hot days. In the summer of 2026 the water was above 22 °C almost continuously from late June to mid September, so the cap forced a negative recommendation on almost every day, independent of rain and sunshine (77 of 121 recorded days; without the cap about 70% of them would have been rated Good or Excellent). Temperature only enters the Swimmer Safety Index (cold shock). If a temperature-related risk is to be modelled again, it should be calibrated against laboratory data, not assumed.

## Disclaimer
This is an **automated estimate** based on environmental proxies. It is **not** a real-time biological measurement. Swimming in the Rhine is always at your own risk. Local pollution events can occur unpredictably.
