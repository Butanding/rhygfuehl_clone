"""Pure calculation helpers for the swim recommendation.

No network access and no file I/O in here, so everything can be unit tested
with fixed example data (see tests/backend/).
"""
import csv
import io
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo('Europe/Zurich')

RAD_THRESHOLD = 170  # W/m², reference for a sunny day (24h mean)


def calculate_quality(rain_week, global_radiation_week, water_temp_latest):
    """Compute the swim recommendation.

    rain_week: [R0, R1, R2] = rain of the last 24h, 24-48h ago, 48-72h ago (mm)
    global_radiation_week: daily mean radiation of the last complete days, newest first
        (yesterday, 2 days ago, 3 days ago). None entries are ignored.
    """
    r0 = rain_week[0] if len(rain_week) > 0 else 0
    r1 = rain_week[1] if len(rain_week) > 1 else 0
    r2 = rain_week[2] if len(rain_week) > 2 else 0
    rain_impact = (r0 * 1.0) + (r1 * 0.5) + (r2 * 0.25)

    # Average over the days we actually have; without any radiation data the
    # bonus is 0, which is the conservative choice (overcast penalty applies).
    rad_values = [v for v in global_radiation_week[:3] if v is not None]
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


def parse_timestamp(value):
    """ISO 8601 string -> timezone-aware datetime (naive values are taken as UTC)."""
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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


# --- Rain -------------------------------------------------------------------
# Source: MeteoSwiss open data, station Basel-Binningen, hourly precipitation
# totals (`rre150h0`). The timestamp of a value is the END of its hour (UTC):
# the row "08:00" is the rain that fell between 07:00 and 08:00.
#
# The city's own "Smart Climate" sensors (St. Johann) were used before. Those
# are raw, unvalidated readings: on 11 Oct 2026 the station reported 9.4 mm
# (the maximum of ~80 stations, median 0.0, Binningen 0.0) and on 8 Oct only
# 5.4 mm where Binningen measured 28.6 mm.

HOURLY_RAIN_COLUMN = 'rre150h0'


def parse_hourly_rain(csv_text, column=HOURLY_RAIN_COLUMN):
    """MeteoSwiss OGD hourly CSV -> {end of hour (UTC datetime): mm or None}."""
    rain = {}
    for row in csv.DictReader(io.StringIO(csv_text), delimiter=';'):
        end = datetime.strptime(row['reference_timestamp'], '%d.%m.%Y %H:%M').replace(tzinfo=timezone.utc)
        raw = (row.get(column) or '').strip()
        rain[end] = float(raw) if raw not in ('', '-') else None
    return rain


def newest_hour(rain):
    """End of the newest hour that has a value, or None."""
    return max((t for t, v in rain.items() if v is not None), default=None)


def hourly_rain_series(rain, end, hours):
    """The `hours` hours up to and including the hour ending at `end`, oldest first.

    Returns (values, starts): mm per hour (None = missing) and the ISO start
    time (UTC) of each hour.
    """
    ends = [end - timedelta(hours=i) for i in range(hours - 1, -1, -1)]
    values = [rain.get(e) for e in ends]
    starts = [(e - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ') for e in ends]
    return values, starts


def rain_windows(rain, end):
    """[R0, R1, R2] with the number of missing hours of each window.

    R0 = rain of the 24 hours up to `end`, R1 = the 24 hours before that,
    R2 = the 24 hours before that. Windows do not overlap. Missing hours count
    as 0 mm. Returns (sums, missing_hours).
    """
    sums, missing = [], []
    for i in range(3):
        values, _ = hourly_rain_series(rain, end - timedelta(hours=24 * i), 24)
        sums.append(round(sum(v for v in values if v is not None), 1))
        missing.append(values.count(None))
    return sums, missing


def daily_rain_series(rain, end, days):
    """Rain per Swiss calendar day, oldest first: (values, ISO dates).

    The last day is today so far (up to the hour ending at `end`). None if no
    hour of a day has a value.
    """
    last_day = (end - timedelta(hours=1)).astimezone(LOCAL_TZ).date()
    totals = {}
    for t, v in rain.items():
        if v is None or t > end:
            continue
        day = (t - timedelta(hours=1)).astimezone(LOCAL_TZ).date()
        totals[day] = totals.get(day, 0) + v
    dates = [last_day - timedelta(days=i) for i in range(days - 1, -1, -1)]
    values = [round(totals[d], 1) if d in totals else None for d in dates]
    return values, [d.isoformat() for d in dates]


# --- Global radiation -------------------------------------------------------
# The city publishes one daily mean per day, and only after the day is over.
# The newest value is therefore always YESTERDAY's. Values are matched by date.

def radiation_by_date(rows):
    """[{'date': 'YYYY-MM-DD', 'globalRadiation': W/m²}, ...] -> {date: value}."""
    return {r['date']: r.get('globalRadiation') for r in rows if r.get('date')}


def radiation_window(by_date, today, days=3):
    """Daily radiation of yesterday, 2 days ago, ... (newest first); None where missing."""
    return [by_date.get((today - timedelta(days=i)).isoformat()) for i in range(1, days + 1)]


def daily_radiation_series(by_date, today, days):
    """Radiation of the last `days` complete days, oldest first: (values, ISO dates)."""
    dates = [(today - timedelta(days=i)).isoformat() for i in range(days, 0, -1)]
    return [by_date.get(d) for d in dates], dates

