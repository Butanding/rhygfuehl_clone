"""Pure calculation helpers for the swim recommendation.

No network access and no file I/O in here, so everything can be unit tested
with fixed example data (see tests/backend/).
"""
import csv
import io
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo('Europe/Zurich')

RAD_THRESHOLD = 170  # W/m², reference for a sunny day (mean over 24h, night included)

# The recommendation looks at the last three days
WINDOW_HOURS = 72


def calculate_quality(rain_week, global_radiation, water_temp_latest, rain_impact=None):
    """Compute the swim recommendation.

    rain_week: [R0, R1, R2] = rain of the last 24h, 24-48h ago, 48-72h ago (mm)
    global_radiation: radiation values (W/m²) of the last three days, any
        resolution (hourly values or daily means). None entries are ignored.
    rain_impact: weighted rain impact I in mm. If omitted it is computed from the
        three windows with the weights 1 / 0.5 / 0.25 (see rain_impact()).
    """
    r0 = rain_week[0] if len(rain_week) > 0 else 0
    r1 = rain_week[1] if len(rain_week) > 1 else 0
    r2 = rain_week[2] if len(rain_week) > 2 else 0
    if rain_impact is None:
        rain_impact = (r0 * 1.0) + (r1 * 0.5) + (r2 * 0.25)

    # Mean over the values we actually have; without any radiation data the
    # bonus is 0, which is the conservative choice (overcast penalty applies).
    rad_values = [v for v in global_radiation if v is not None]
    rad_bonus = sum(rad_values) / (len(rad_values) * RAD_THRESHOLD) if rad_values else 0

    # 1. Water Quality Index (Microbiological)
    # Default is discouraged
    quality_index = 1

    # Excellent (Level 3)
    if rain_impact < 0.5 or (r0 < 1.0 and rain_impact < 2.0 and rad_bonus > 1.2):
        quality_index = 3
    # Good (Level 2)
    elif (rain_impact < 3.5 and r0 < 1.5) or (r0 < 1.5 and rain_impact < 5.0 and rad_bonus > 1.0):
        quality_index = 2

    # Hard Scientific Caps (Safety First)
    if rad_bonus < 0.6: # Overcast Penalty
        quality_index = min(quality_index, 1)
    if rain_impact >= 5.0: # Extreme Rain Impact
        quality_index = min(quality_index, 1)
    if r0 >= 2.0: # Immediate Active Runoff (even if bonus is high, surface disinfection isn't enough)
        quality_index = min(quality_index, 1)

    # 2. Swimmer Safety Index (Physical)
    safety_index = 1
    if water_temp_latest >= 18.0:
        safety_index = 3
    elif water_temp_latest >= 14.0:
        safety_index = 2

    # Final status is the bottleneck of both
    return {
        'level': min(quality_index, safety_index),
        'quality': quality_index,
        'safety': safety_index
    }


def bucket_start(range_value):
    """Start of an Opendatasoft range bucket, e.g. '[2026-10-08T12:00:00.000Z, 2026-10-09T00:00:00.000Z['."""
    if not isinstance(range_value, str) or ',' not in range_value:
        return None
    return range_value.lstrip('[(').split(',')[0].strip()


def fill_gaps(values):
    """Replace None by the previous value (0 at the start). Returns (filled, number_of_gaps)."""
    filled, last, gaps = [], 0, 0
    for v in values:
        if v is None:
            gaps += 1
            v = last
        filled.append(v)
        last = v
    return filled, gaps


def series_from_records(records, field):
    """Aggregated API records -> (values, bucket start times), gaps filled with the previous value."""
    values, times = [], []
    for e in records:
        fields = e['record']['fields']
        values.append(fields.get(field))
        times.append(bucket_start(fields.get('time')))
    filled, _ = fill_gaps(values)
    return filled, times


# --- MeteoSwiss hourly data -------------------------------------------------
# Source: MeteoSwiss open data, station Basel-Binningen, hourly values:
#   rre150h0  precipitation, hourly total (mm)
#   gre000h0  global radiation, hourly mean (W/m²)
# The timestamp of a value is the END of its hour (UTC): the row "08:00" is the
# rain that fell / the mean radiation between 07:00 and 08:00.
#
# The city's own "Smart Climate" sensors (St. Johann) were used for the rain
# before. Those are raw, unvalidated readings: on 11 Oct 2026 the station
# reported 9.4 mm (the maximum of ~80 stations, median 0.0, Binningen 0.0) and
# on 8 Oct only 5.4 mm where Binningen measured 28.6 mm.

RAIN_COLUMN = 'rre150h0'
RADIATION_COLUMN = 'gre000h0'


def parse_hourly(csv_text, column):
    """MeteoSwiss OGD hourly CSV -> {end of hour (UTC datetime): value or None}."""
    values = {}
    for row in csv.DictReader(io.StringIO(csv_text), delimiter=';'):
        end = datetime.strptime(row['reference_timestamp'], '%d.%m.%Y %H:%M').replace(tzinfo=timezone.utc)
        raw = (row.get(column) or '').strip()
        values[end] = float(raw) if raw not in ('', '-') else None
    return values


def newest_hour(hourly):
    """End of the newest hour that has a value, or None."""
    return max((t for t, v in hourly.items() if v is not None), default=None)


def hourly_series(hourly, end, hours):
    """The `hours` hours up to and including the hour ending at `end`, oldest first.

    Returns (values, starts): the value per hour (None = missing) and the ISO
    start time (UTC) of each hour.
    """
    ends = [end - timedelta(hours=i) for i in range(hours - 1, -1, -1)]
    values = [hourly.get(e) for e in ends]
    starts = [(e - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ') for e in ends]
    return values, starts


def local_day(hour_end):
    """Swiss calendar day an hour (given by its end) belongs to."""
    return (hour_end - timedelta(hours=1)).astimezone(LOCAL_TZ).date()


# --- Rain -------------------------------------------------------------------

def rain_windows(rain, end):
    """[R0, R1, R2] with the number of missing hours of each window.

    R0 = rain of the 24 hours up to `end`, R1 = the 24 hours before that,
    R2 = the 24 hours before that. Windows do not overlap. Missing hours count
    as 0 mm. Returns (sums, missing_hours).
    """
    sums, missing = [], []
    for i in range(3):
        values, _ = hourly_series(rain, end - timedelta(hours=24 * i), 24)
        sums.append(round(sum(v for v in values if v is not None), 1))
        missing.append(values.count(None))
    return sums, missing


# Rain loses its influence smoothly: the weight halves every 24 hours (washout
# and die-off are roughly exponential) and fades to 0 over the last 12 hours of
# the three-day window, so nothing jumps when an hour leaves the window. The
# constant 11.5 h makes steady rain count like the former block weights
# 1 / 0.5 / 0.25 for 0-24h / 24-48h / 48-72h, so the thresholds stay valid.
RAIN_HALF_LIFE_H = 24
RAIN_TAPER_H = 12
_RAIN_SCALE_SHIFT_H = 11.5


def rain_weight(age_hours):
    """Weight of rain that fell `age_hours` ago (measured to the middle of its hour)."""
    if age_hours >= WINDOW_HOURS:
        return 0.0
    weight = 2 ** (-(age_hours - _RAIN_SCALE_SHIFT_H) / RAIN_HALF_LIFE_H)
    if age_hours > WINDOW_HOURS - RAIN_TAPER_H:
        weight *= (WINDOW_HOURS - age_hours) / RAIN_TAPER_H
    return weight


def rain_impact(rain, end):
    """Rain impact I in mm: every hour of the last 72 hours weighted by its age."""
    total = 0.0
    for i in range(WINDOW_HOURS):
        value = rain.get(end - timedelta(hours=i))
        if value:
            total += value * rain_weight(i + 0.5)
    return round(total, 2)


def daily_rain_series(rain, end, days):
    """Rain per Swiss calendar day, oldest first: (values, ISO dates).

    The last day is today so far (up to the hour ending at `end`). None if no
    hour of a day has a value.
    """
    last_day = local_day(end)
    totals = {}
    for t, v in rain.items():
        if v is None or t > end:
            continue
        totals[local_day(t)] = totals.get(local_day(t), 0) + v
    dates = [last_day - timedelta(days=i) for i in range(days - 1, -1, -1)]
    values = [round(totals[d], 1) if d in totals else None for d in dates]
    return values, [d.isoformat() for d in dates]


# --- Global radiation -------------------------------------------------------

def radiation_mean(radiation, end, hours=WINDOW_HOURS):
    """Mean radiation (W/m²) of the last `hours` hours, night included, and the number of missing hours.

    Windows end at the same hour as the rain windows. None if there is no value at all.
    """
    values, _ = hourly_series(radiation, end, hours)
    present = [v for v in values if v is not None]
    mean = sum(present) / len(present) if present else None
    return mean, values.count(None)


def daily_radiation_series(radiation, end, days, min_hours=18):
    """Mean radiation per complete Swiss calendar day, oldest first: (values, ISO dates).

    Today is left out: a mean over the daylight hours so far is not comparable with
    the mean over 24 hours. None if fewer than `min_hours` hours of a day are known.
    """
    today = local_day(end)
    per_day = {}
    for t, v in radiation.items():
        if v is None or t > end:
            continue
        per_day.setdefault(local_day(t), []).append(v)
    dates = [today - timedelta(days=i) for i in range(days, 0, -1)]
    values = [round(sum(per_day[d]) / len(per_day[d])) if len(per_day.get(d, [])) >= min_hours else None
              for d in dates]
    return values, [d.isoformat() for d in dates]
