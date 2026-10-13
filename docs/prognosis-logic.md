# Rhine Swimming Recommendation Logic

This document describes how the automated swimming recommendation for the Rhine at Basel is calculated: where the data comes from, how it is processed, every formula and threshold, what the website shows, and why things are the way they are. It is the reference for the code in `data/quality.py` (calculation) and `data/aggregation.py` (data download and output files).

> **Status: BETA.** The thresholds are engineering estimates, **not** calibrated against laboratory measurements (see [Open questions](#9-known-limitations-and-open-questions)). The recommendation is an automated estimate from weather data, not a measurement of the water.

## Contents
1. [Overview](#1-overview)
2. [Data sources](#2-data-sources)
3. [Time windows and missing data](#3-time-windows-and-missing-data)
4. [Calculation](#4-calculation)
5. [Output data (`qualityData.json`)](#5-output-data)
6. [What the website shows](#6-what-the-website-shows)
7. [Worked examples](#7-worked-examples)
8. [Decision history](#8-decision-history)
9. [Known limitations and open questions](#9-known-limitations-and-open-questions)
10. [Tests, validation and how to run it](#10-tests-validation-and-how-to-run-it)
11. [Constants at a glance](#11-constants-at-a-glance)

---

## 1. Overview

The recommendation is the **minimum** of two independent indices, each with three levels:

```
 rain (hourly, 72 h) ──► rain impact I ───────────┐
 radiation (hourly, 72 h) ──► bonus B ────────────┼──► Water Quality Index (bacteria) ──┐
 sunshine duration (hourly, 72 h) ──► share S ────┘                                     ├─► min() ─► Recommendation
 water temperature (latest) ─────────────────────────► Swimmer Safety Index (cold shock) ┘
```

| Level | Label | Colour |
| :--- | :--- | :--- |
| 3 | Excellent | green |
| 2 | Good | yellow |
| 1 | Discouraged | red |

Decoupling the two indices keeps the result transparent: a river can be bacterially clean but dangerously cold, or warm but polluted after a storm.

All three weather inputs come from the **same MeteoSwiss station and the same 72 hours**, so they are equally fresh and cover the same period.

---

## 2. Data sources

| Input | Source | Parameter | Resolution | Used for |
| :--- | :--- | :--- | :--- | :--- |
| Precipitation | MeteoSwiss, station Basel-Binningen (`BAS`) | `rre150h0`, precipitation, hourly total (mm) | hourly | rain impact $I$, windows $R_0..R_2$, rain chart |
| Global radiation | MeteoSwiss, `BAS` | `gre000h0`, global radiation, hourly mean (W/m²) | hourly | radiation bonus $B$, radiation chart |
| Sunshine duration | MeteoSwiss, `BAS` | `sre000h0`, sunshine duration, hourly total (minutes) | hourly | overcast rule (share $S$) |
| Water temperature | Basel-Stadt open data, dataset `100046`: Rhine monitoring station (RUES) **Weil am Rhein**, Rhine km 171.37 (47.601 N, 7.595 E), about 3.3 km downstream (north) of the Rheinpromenade | `rus_w_o_s3_te` | 15 min | Swimmer Safety Index |
| Air temperature, water level | Basel-Stadt open data: air temperature dataset `100009`, measuring station **Rheinpromenade 2** (`034003A7`, 47.572 N, 7.584 E); water level dataset `100089`, measuring station **Kleinbasel** at the Birs confluence (FOEN station 2289) | | | display only, **not** part of the recommendation |

MeteoSwiss files (open data, free to use with source attribution "MeteoSwiss"):

```
https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/bas/ogd-smn_bas_h_recent.csv   1 January of this year until yesterday
https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/bas/ogd-smn_bas_h_now.csv      today
https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/bas/ogd-smn_bas_h_historical_2020-2029.csv   only used in early January
```

`recent` and `now` join without a gap. Early in January the 33 days that the month charts need reach into the previous year, so the `historical` file of the decade is loaded as well.

**Time stamps.** MeteoSwiss labels every value with the **end of its hour (UTC)**: the row `08:00` is the rain, the mean radiation and the sunshine between 07:00 and 08:00. The code keeps this convention internally and converts to the **start** of the hour (`hourlyStarts`) for the charts.

**Freshness.** The newest hour is typically available about 10 minutes after it ends. The `recent` file is only completed with yesterday at about 02:48 UTC; until then the data has a hole of one day (see section 3). The recommendation is anchored at the newest hour that has a rain value; if that hour is older than 3 hours a warning is logged (feed late).

**Why not the city's own rain sensors?** The "Smart Climate" network of the Basel-Stadt open data (dataset `100009`, rain station St. Johann `034001AF`) was used before. Those are raw, unvalidated readings of single low-cost sensors:

- On 11 Oct 2026 the St. Johann sensor reported 9.4 mm rain. That was the **maximum of about 80 stations** (median 0.0 mm, Binningen 0.0 mm).
- On 8 Oct 2026 it reported 5.4 mm where Binningen measured 28.6 mm (official daily value 27.1 mm for 6-6 UTC).
- Its hourly field (`meta_rain_1h_val`) adds up to only about a quarter of its own 24-hour sum.
- Rolling 24h sums made it hard to attribute rain to a day (see [Decision history](#8-decision-history)).

Other candidates are unusable: the Rosental weather station (dataset `100294`) stopped delivering in September 2026, and the Binningen air-quality dataset (`100051`) has no precipitation values. Binningen lies about 5 km from the Rhine, but it is a validated reference station. Local showers can still differ between Binningen and the river.

---

## 3. Time windows and missing data

Everything looks at the **72 hours up to and including the newest hour** (`WINDOW_HOURS = 72`). For the rain this is split into three consecutive 24-hour windows:

| Window | Hours before the newest hour | Meaning |
| :--- | :--- | :--- |
| $R_0$ | 0-23 | rain of the last 24 hours |
| $R_1$ | 24-47 | the 24 hours before that |
| $R_2$ | 48-71 | the 24 hours before that |

Every hour belongs to exactly one window, so no rain is counted twice.

**Missing data**

| Situation | Behaviour |
| :--- | :--- |
| a rain hour has no value | counts as 0 mm, a warning with the number of missing hours per window is logged |
| a radiation hour has no value | left out of the mean; no value at all: $B = 0$ (conservative) |
| a sunshine hour has no value | left out of **both** sides of the share $S$; no hour with possible sunshine: no share, the earlier radiation rule is used for the overcast decision |
| hourly bars (3-day view) | a missing hour is drawn as 0 |
| daily bars (week, month) | a day without data repeats the previous value; a warning is logged |
| more than `MAX_MISSING_HOURS` (3) hours are missing in the 72 h window of rain, radiation or sunshine | **nothing is calculated or published** (`aggregation.py` ends with exit code 3, the deploy workflow skips build and deployment, the site keeps its current version). Cause: MeteoSwiss updates the `recent` file only at about 02:48 UTC, so between 00:00 UTC and then the whole previous day is missing. A calculation on what is left would be wrong (see the decision history, 13 Oct 2026) |
| the download fails | the script aborts and the run fails; the site keeps its current version |

---

## 4. Calculation

### 4.1 Rain Impact Score $I$

Rain triggers combined sewer overflows (CSO) and surface runoff, which raise the bacterial load. The influence of rain fades over about three days: washout and die-off are roughly exponential. The impact $I$ (mm) weights every hour of rain by its age:

$$I = \sum_{h} \text{rain}_h \cdot w(a_h), \qquad w(a) = 2^{-(a - 11.5\,\text{h}) / 24\,\text{h}} \cdot \text{taper}(a)$$

- $a_h$ is the age of the **middle** of the hour, in hours (the newest hour has $a = 0.5$).
- The weight **halves every 24 hours** (half-life `RAIN_HALF_LIFE_H = 24`).
- `taper(a)` fades the weight linearly to 0 over the last 12 hours of the window ($a$ from 60 to 72 h), so nothing drops out of the window abruptly. Beyond 72 hours the weight is 0.
- The constant 11.5 h calibrates the curve: steady rain counts like the **former block weights** 1 / 0.5 / 0.25 for the windows 0-24 h / 24-48 h / 48-72 h. Average weights of the smooth curve: **1.005 / 0.503 / 0.202**. All thresholds below were set for the block weights and stay valid.

| Age | 0.5 h | 12.5 h | 24.5 h | 48.5 h | 66.5 h | 72 h |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Weight | 1.37 | 0.97 | 0.69 | 0.34 | 0.09 | 0 |

Why smooth: with three blocks a heavy shower lost half of its weight at exactly 24 hours and the rating could flip from one hour to the next. The largest weight change between two neighbouring hours is now 0.04 (before: 0.5 at once).

The window sums $R_0, R_1, R_2$ are still calculated. They are shown under the rain chart and $R_0$ is used in the decision rules below ("immediate runoff").

> **Do not** derive "rain of the day" from a *rolling* 24h sum (for example the daily maximum). Right after midnight the window still contains the previous day: a dry day after a rainy one then shows the rain of the day before, and a weighted sum counts it several times. This was a bug of the original implementation.

### 4.2 Radiation Bonus $B$

Sunlight is a natural disinfectant: it speeds up the inactivation of faecal indicator bacteria (e.g. *E. coli*), so strong sun after light rain helps the river to recover.

$$B = \frac{\overline{G}_{72\,\text{h}}}{170\ \text{W/m}^2}$$

- $\overline{G}_{72\,\text{h}}$ is the mean of the hourly global radiation over the same 72 hours, **night included**. It is therefore the mean over three whole days.
- 170 W/m² is the reference for a sunny day as a 24h mean. For orientation, the 24h mean of a cloudless day in Basel is about 335 W/m² in midsummer and about 170 W/m² in early October.
- $B$ only **rescues** the rating after light rain (levels 3 and 2, see 4.4). It does **not** decide whether the sky is overcast any more.

### 4.3 Overcast rule: sunshine share $S$ (interim)

The Cantonal Laboratory reports that overcast days are bad for the water quality **even without rain**, because less sunlight means less natural disinfection. "Overcast" is judged by the **share of the possible sunshine duration** during the last 72 hours:

$$S = \frac{\sum_h \text{sunshine}_h}{\sum_h \text{possible}_h}$$

Overcast if **$S < 20\ \%$** (`OVERCAST_SUNSHINE = 0.20`). Then the water quality is capped at level 1 (see 4.4).

**Possible sunshine** is calculated astronomically for Basel-Binningen (47.5408° N, 7.5835° E): for every minute of every hour the elevation of the sun is calculated (NOAA approximation of declination and equation of time). A minute counts as possible if the sun stands **higher than 5°**. A low sun does not deliver the direct beam of 120 W/m² that defines "sunshine" (WMO), and MeteoSwiss itself relates its relative sunshine duration to such a maximum. The value 5° reproduces the "possible" minutes behind MeteoSwiss' daily relative sunshine duration (`sremaxdv`) within about 4 %, in midwinter about 8 %.

**Validation.** Calculated from the hourly values, the daily share differs from the official daily value (`sremaxdv`) by 1.1 percentage points on average (284 days of 2026, 90 % of the days within -2 to +3 points). For 6-11 Oct 2026: 91.9 / 23.1 / 0.0 / 18.9 / 3.0 / 8.8 % against 93 / 23 / 0 / 19 / 3 / 9 % official.

**Why sunshine instead of the radiation in W/m².** The earlier rule was "mean radiation below 0.6 x 170 = 102 W/m²". Both numbers were set by hand (see [Decision history](#8-decision-history)). A fixed threshold in W/m² mixes the sky condition with the season: even a cloudless day stays below 102 W/m² from about November to February, so the rule was always active then. The sunshine share is relative to what is possible and therefore independent of the season. The threshold of 20 % was chosen so that the rule is about as strict in summer as the old one (June-August: flagged on 2 % of the 72h windows of 2026; the old rule on 1-3 % over 1981-2026), and fairer in winter.

| Share of the days flagged as overcast, 2026 | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct (1-11) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| radiation rule (72 h mean < 102 W/m²) | 100 % | 86 % | 11 % | 11 % | 0 % | 0 % | 0 % | 0 % | 0 % | 36 % |
| sunshine rule (S < 20 %) | 28 % | 50 % | 14 % | 14 % | 11 % | 7 % | 0 % | 0 % | 0 % | 27 % |

Effect on the water quality class in 2026 (281 days, temperature excluded): 24 days better (January 17, February 7), 6 days worse (March 2, April 2, May 1, June 1), no difference from July to October.

**Fallback.** If there is no sunshine value, "overcast" is decided by the earlier radiation rule ($B < 0.6$).

> This rule is an **interim solution**. Sunshine duration is a better indicator of the sky than radiation, but neither is calibrated against laboratory data. See [Open questions](#9-known-limitations-and-open-questions).

### 4.4 Water Quality Index (bacteria)

Start with level 1 (discouraged), then:

| Level | Status | Condition |
| :--- | :--- | :--- |
| **3** | Excellent | $I < 0.5$ (dry) **or** ($R_0 < 1.0$ and $I < 2.0$ and $B > 1.2$) |
| **2** | Good | ($I < 3.5$ and $R_0 < 1.5$) **or** ($R_0 < 1.5$ and $I < 5.0$ and $B > 1.0$) |
| **1** | Discouraged | otherwise |

Then three **caps** are applied. Each lowers the level to at most 1, whatever the rows above said:

| Cap | Condition | Reason |
| :--- | :--- | :--- |
| Overcast | $S < 20\ \%$ (fallback: $B < 0.6$) | little sun, little natural disinfection, also without rain |
| Extreme rain impact | $I \ge 5.0$ | large overflow volume |
| Immediate runoff | $R_0 \ge 2.0$ | rain within the last 24 hours; even strong sun does not disinfect the surface runoff quickly enough |

The third row of the table therefore holds when no rule above applies or a cap is active.

Rationale of the rain thresholds:
- **3.5 mm.** In Basel sewer overflows typically start after 3-5 mm of rain; 3.5 is the tipping point. The first value was chosen in the original design, not measured by us.
- **$I < 0.5$ mm** counts as dry. Binningen measures in steps of 0.1 mm, so dew and drizzle no longer lift a dry period above that (the old St. Johann sensor reported 0.2-0.4 mm of dew).

### 4.5 Swimmer Safety Index (physical)

Only the **latest** water temperature $T_{now}$ counts. Cold water is the main physical danger (cold shock: gasping and hyperventilation on entering, a leading cause of drowning).

| Level | Status | Condition |
| :--- | :--- | :--- |
| **3** | Safe | $T_{now} \ge 18\,^\circ\text{C}$ |
| **2** | Caution | $14\,^\circ\text{C} \le T_{now} < 18\,^\circ\text{C}$ |
| **1** | Discouraged | $T_{now} < 14\,^\circ\text{C}$ |

There is **no upper temperature limit**: an earlier cap at 22 °C was removed (see [Decision history](#8-decision-history)).

### 4.6 Recommendation

$$\text{level} = \min(\text{Water Quality}, \text{Swimmer Safety})$$

---

## 5. Output data

`data/aggregation.py` writes `data/data/qualityData.json` (and `waterData.json`, `airData.json`, `levelData.json`, `metadata.json`). `qualityData.json`:

```jsonc
{
  "quality": 1,                         // recommendation, 1..3
  "lastUpdate": "2026-10-12T09:00:00Z", // end of the newest hour
  "indices": { "quality": 1, "safety": 3 },
  "inputs": {                           // what the calculation used, for transparency and debugging
    "asOf": "2026-10-12T09:45:01Z",
    "rainMm": { "last24h": 0.0, "from24to48h": 0.8, "from48to72h": 1.6 },
    "rainImpactMm": 0.81,
    "radiationMeanWm2": 87,
    "radiationHoursMissing": 0,
    "sunshineFraction": 0.133,          // null if there is no sunshine data
    "overcast": true
  },
  "data": [
    { "measure": "globalRadiation",
      "source": "MeteoSwiss, station Basel-Binningen",
      "meanLast72hWm2": 87, "sunshineLast72hPercent": 13,
      "chart": { "hourly": [/* 72 W/m² */], "hourlyStarts": [/* 72 ISO times, UTC */],
                 "week": [/* 7 */], "weekDates": [/* local dates */], "month": [/* 30 */], "monthDates": [/* */] } },
    { "measure": "rain",
      "source": "MeteoSwiss, station Basel-Binningen",
      "windowsMm": { "last24h": 0.0, "from24to48h": 0.8, "from48to72h": 1.6 },
      "chart": { "hourly": [/* 72 mm */], "hourlyStarts": [/* */], "week": [], "weekDates": [], "month": [], "monthDates": [] } },
    { "measure": "sunshine",
      "source": "MeteoSwiss, station Basel-Binningen",
      "sharePercent72h": 13,
      "chart": { "hourly": [/* 72 values, minutes of sun per hour, 0-60 */], "hourlyStarts": [/* */],
                 "week": [/* 7, % of the possible duration */], "weekDates": [], "month": [/* 30 */], "monthDates": [] } }
  ]
}
```

- `hourly`: the 72 hourly values, oldest first; `hourlyStarts` is the start of each hour in UTC.
- `week` / `month`: **daily** values per Swiss calendar day (Europe/Zurich), oldest first, with their `...Dates`. Rain: total per day, today = so far. Radiation: 24-hour mean (night included) of **complete** days; today is left out because a mean over the daylight hours so far is not comparable. Sunshine: share of the possible sunshine duration per complete day, in percent. These arrays are also what the WebMCP tool `get_history` returns.
- `waterData.json`, `airData.json`, `levelData.json` carry the bucket start times as `weekTimes` / `monthTimes` next to `week` / `month`.
- Older data files without `hourly` still work: the tile then shows the previous line charts.

---

## 6. What the website shows

**Experiment mode.** The recommendation is a BETA feature. The tile is **hidden by default** and only shown when the *experiment mode* is on. The switch sits at the top right, left of the language switch (`Off | Beta`). The choice is kept in the browser (`localStorage`, key `experiment`) and applies to both languages. A link can set it, too: `?experiment=on` or `?experiment=off`. The state is set on the `<html>` element (`data-experiment`) before the first paint, so the tile does not flash. The data is calculated and loaded in any case; only the display is switched. The structured data (FAQ), `llms.txt` and the WebMCP interface still mention the recommendation.

The tile "Swimming Recommendation" (`SwimPrognosis.astro`, the last tile of the page) shows:

- the overall level, the two indices, a short description and a disclaimer;
- a **rain chart** and a **radiation chart** (`BarChart.astro`). The radiation chart has a switch **Radiation | Sunshine** below the chart (hourly: minutes of sun per hour; week and month: share of the possible duration per day in %). Both charts have three views:
  - **3 days**: 72 hourly bars. Weekday names and a line at every midnight (Basel time); "Now" at the right end;
  - **Week**: 7 daily bars with weekday names;
  - **Month**: 30 daily bars, labelled on Mondays;
- under the rain chart the sums of the last 24 h / 24-48 h / 48-72 h ($R_0, R_1, R_2$), under the radiation chart the 72 h mean in W/m² and the sunshine share with the overcast limit;
- the source (MeteoSwiss) and an explanation of the views.

Colours: rain blue, radiation orange, sunshine yellow, adapted to the light/dark setting of the browser (`prefers-color-scheme`, see `src/utils/chartTheme.ts`).

---

## 7. Worked examples

All numbers come from the real test data (`tests/backend/fixtures/`).

**Example 1: Monday 12 Oct 2026, 08:00 UTC. Dry, but grey.**
- Rain: $R_0 = 0.0$, $R_1 = 1.4$, $R_2 = 1.0$ mm, weighted $I = 0.84$ mm.
- Radiation: 72 h mean 86 W/m², $B = 0.51$. Sunshine: $S = 13\ \%$ (the three days had 19 %, 3 % and 9 %).
- Water Quality: $I \ge 0.5$ so not level 3; $I < 3.5$ and $R_0 < 1.5$ gives level 2. **Cap:** $S < 20\ \%$ (overcast), so level 1.
- Safety: 18.1 °C gives level 3. Recommendation: **1, discouraged.**

**Example 2: Friday 9 Oct 2026, 08:00 UTC. The day after the heavy rain of 8 Oct (28.6 mm).**
- Rain: $R_0 = 24.3$, $R_1 = 7.6$, $R_2 = 0.0$ mm, $I = 23.6$ mm.
- $S = 36\ \%$, not overcast. But $I \ge 5.0$ and $R_0 \ge 2.0$ are caps. Water Quality **1**, recommendation 1.

**Example 3: a sunny summer day with a little rain (constructed).**
- $R_0 = 0.8$ mm, $I = 0.8$ mm, 72 h mean radiation 250 W/m² ($B = 1.47$), $S = 70\ \%$, 22 °C.
- $I \ge 0.5$, but $R_0 < 1.0$, $I < 2.0$ and $B > 1.2$ give level 3 (**rescue by the sun**). Not overcast, no cap. Safety 3. Recommendation: **3, excellent.**

---

## 8. Decision history

| Date | Change | Why |
| :--- | :--- | :--- |
| 2026-04-12 | First version: weighted rain impact 1 / 0.5 / 0.25, UV bonus with 170 W/m², thermal cap at 22 °C | original design |
| 2026-05-22 | Indices decoupled; **overcast penalty** $B < 0.6$ added | documented with "data of the Kantonslabor BS (2025): on overcast days without rain 54 % of the samples are unsafe". No source, no definition of "overcast" in W/m² and none of "unsafe" in the repository. 102 W/m² is simply 0.6 x 170. |
| 2026-07-10 | Issue #1 (original repo): rain shown on dry days, radiation looks too low | analysis below |
| 2026-07-18 | Recommendation hidden in the original; issue #3 | the Cantonal Laboratory reported false warnings on hot days with very good analyses |
| 2026-10-09 | **Rain per day fixed** | the daily maximum of the rolling 24h sum attributes the rain of the day before to the current day (6 Oct 2026 was dry but showed 2.2 mm) and made the three windows overlap |
| 2026-10-09 | **Radiation matched by date** | the daily mean is published a day late, but was paired by list position with the live rain |
| 2026-10-09 | **Temperature average fixed** | the "48 h average" took the *oldest* four buckets of the week |
| 2026-10-09 | **22 °C cap removed** | active on 77 of 121 recorded days in summer 2026 and always "discouraged", independent of rain and sun. The Rhine is a fast-flowing river with a high water turnover and the Cantonal Laboratory reports very good results on hot days. Without the cap about 70 % of those days would have been good or excellent. If a temperature risk is modelled again it should be calibrated against laboratory data |
| 2026-10-12 | **Rain source: MeteoSwiss Binningen, hourly** | the city's single St. Johann sensor is unreliable (see section 2) |
| 2026-10-12 | **Smooth decay** instead of three blocks | no jumps in the rating; calibration preserved. In 2026, 12 of about 290 days changed their water quality class (11 better, 1 worse) |
| 2026-10-12 | **Radiation hourly** instead of daily | no delay of one day, same 72 hours as the rain |
| 2026-10-12 | **Overcast rule on sunshine share** instead of radiation | see 4.3. Interim until the Cantonal Laboratory's data allows a calibration |
| 2026-10-13 | **Data holes are no longer calculated** | the deploy at 01:43 UTC saw a day without data (12 Oct) because the MeteoSwiss `recent` file is only updated at about 02:48 UTC. The missing sunny day was ignored, three grey days remained: sunshine 6 %, "overcast", "Discouraged". The site showed that result until the next run, hours later. Now an incomplete window stops the calculation and the site keeps its last good version. The fallback to the data files of the original repository was removed: it used the old, faulty model |

The 22 °C cap and the overcast rule were both justified with laboratory statements. The first was refuted by the laboratory itself, the second could not be verified by us.

---

## 9. Known limitations and open questions

1. **Thresholds are not calibrated.** 0.5 / 1.0 / 1.5 / 2.0 / 3.5 / 5.0 mm, the weights, 1.0 / 1.2 for $B$, the 20 % sunshine limit and the safety limits are estimates. The only reliable way to validate them is to compare the model with **laboratory measurements** (E. coli, enterococci) on dated samples.
2. **What does the laboratory mean by "overcast" and by "unsafe"?** Radiation, sunshine duration or cloud cover? Which limit values? Open questions to the Cantonal Laboratory, together with a request for the data of the 2025 evaluation (date, location, measured values). If the samples come from the bathing season, they do not prove anything for October-March.
3. **Other explanations are possible, hypothesis not checked:** "overcast without rain in Basel" can also mean rain further up the Rhine or a high, turbid river. The Basel rain gauge does not see that. Water level and discharge are available (`levelData.json`) but not part of the model.
4. **The radiation bonus $B$ is still an absolute threshold** (1.0 / 1.2 x 170 W/m²). It can only be reached from about April to September. That is deliberate (sun helps after light rain only when it is strong), but it was not examined against data.
5. **Binningen is about 5 km from the Rhine.** Showers can differ locally.
6. **No cloud cover.** MeteoSwiss does not publish a cloud cover for Basel-Binningen in these files. Sunshine duration is the closest measurement.
7. **Possible sunshine is calculated**, not measured: about 4 % uncertainty, about 8 % in midwinter (low sun, horizon).
8. **The water temperature is not measured at the bathing spots** but at the Rhine monitoring station Weil am Rhein, about 3.3 km downstream (north) of the Rheinpromenade. It can differ slightly from the temperature in the city centre; the limits of 14 and 18 °C are coarse enough for that.
9. **Swimmer safety ignores flow and water level.** Strong current is a real danger for swimmers; no thresholds are known to us.
10. **The site is only as fresh as the last scheduled run.** The original builds and deploys every 15 minutes with a reliable CI cron job on Codeberg. On GitHub the scheduler is best effort: it delays and skips many runs (with an interval of 30 minutes there were gaps of 3-7 hours here). The workflow is therefore asked every 5 minutes (the shortest interval GitHub allows) and ends right away if the published site already has the newest data (a fingerprint of the newest time stamps is published as `fingerprint.txt`). How many runs GitHub really starts is up to GitHub; an external trigger (e.g. cron-job.org calling the GitHub API) would make it exact. The "Update" time in the tile shows how old the data is.
11. **Missing data counts as 0 mm of rain** (the less cautious choice) but as "no information" for radiation and sunshine. A long feed outage therefore lowers the rain impact. The feed delay warning (3 hours) is only logged.

---

## 10. Tests, validation and how to run it

- **Code:** `data/quality.py` is pure (no network, no file access). `data/aggregation.py` downloads the data and writes the JSON files, it only runs when executed directly.
- **Tests:** `PYTHONPATH=./data pytest tests/backend/`
  - `test_aggregation.py`: decision matrix and indices;
  - `test_quality_inputs.py`: parsing, windows, smooth weights, daily series, radiation, sunshine, overcast rule, using **real hourly data of 6-12 Oct 2026** (`tests/backend/fixtures/meteoswiss_bas_hourly_2026-10-06_to_12.csv`). Among them: weights without jumps and with preserved calibration, the astronomical possible sunshine against the official MeteoSwiss values, the sunshine share against the official daily values, and the fixed rain cases (dry day after rain, the heavy rain of 8 Oct).
- **Frontend:** `npm run test:unit`, `npm run test:e2e` (Playwright).
- **Run the data update:** `pip install -r data/requirements.txt && python data/aggregation.py` (from the repository root), then `npm run build`.
- **How the figures in this document were obtained:** the monthly tables are back-tests over 2026 with the hourly MeteoSwiss data (rain, radiation, sunshine) and the historical daily radiation of Basel-Binningen (dataset `100254`, 1981-2026): for every day the model was evaluated at the end of the day, with the temperature fixed. These scripts are not part of the repository.

---

## 11. Constants at a glance

| Constant | Value | Where |
| :--- | :--- | :--- |
| `WINDOW_HOURS` | 72 | `quality.py` |
| `RAIN_HALF_LIFE_H` / `RAIN_TAPER_H` / `_RAIN_SCALE_SHIFT_H` | 24 h / 12 h / 11.5 h | `quality.py` |
| `RAD_THRESHOLD` | 170 W/m² | `quality.py` |
| `OVERCAST_SUNSHINE` | 0.20 | `quality.py` |
| `SUN_MIN_ELEVATION_DEG` | 5° | `quality.py` |
| `STATION_LAT` / `STATION_LON` | 47.5408 / 7.5835 | `quality.py` |
| Rain rules | 0.5, 1.0, 1.5, 2.0, 3.5, 5.0 mm | `calculate_quality` |
| Bonus $B$ | > 1.0 and > 1.2; fallback overcast < 0.6 | `calculate_quality` |
| Safety | 14 °C and 18 °C | `calculate_quality` |
| `RAIN_STALE_AFTER` | 3 h | `aggregation.py` |
| `MAX_MISSING_HOURS` | 3 h per series and 72 h window | `quality.py` |
| `EXIT_INCOMPLETE` | exit code 3 | `aggregation.py` |

## Disclaimer
This is an **automated estimate** based on environmental proxies. It is **not** a real-time biological measurement and **not** an official laboratory result. Swimming in the Rhine is always at your own risk. Local pollution events can occur unpredictably.
