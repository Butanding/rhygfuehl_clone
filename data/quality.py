"""Pure calculation helpers for the swim recommendation.

No network access and no file I/O in here, so everything can be unit tested
with fixed example data (see tests/backend/).
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo('Europe/Zurich')

# The rain station reports roughly hourly. A reading older than this is treated as missing.
RAIN_MAX_GAP = timedelta(hours=3)

RAD_THRESHOLD = 170  # W/m², reference for a sunny day (24h mean)


def calculate_quality(rain_week, global_radiation_week, water_temp_latest, water_temp_48h_avg):
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
    if water_temp_48h_avg > 22.0: # Thermal Risk
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
# The station reports `meta_rain24h_sum`, a ROLLING sum: rain of the 24 hours
# before the reading. Taking the daily maximum of it (as done before) attributes
# yesterday's rain to today, because the window still contains it after midnight.
# Reading the rolling sum at fixed points in time gives non-overlapping windows.

def prepare_rain_records(rows):
    """[{'dates_max_date': iso, 'meta_rain24h_sum': mm}, ...] -> sorted [(datetime, mm)], skipping nulls."""
    rain = [(parse_timestamp(r['dates_max_date']), r['meta_rain24h_sum'])
            for r in rows
            if r.get('dates_max_date') and r.get('meta_rain24h_sum') is not None]
    rain.sort(key=lambda item: item[0])
    return rain


def latest_rain_timestamp(rain):
    """ISO timestamp (UTC) of the newest rain reading, or None without data."""
    return rain[-1][0].astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if rain else None


def rain_24h_at(rain, when):
    """Rolling 24h rain sum at `when`: latest reading not after it, or None if missing/too old."""
    for t, value in reversed(rain):
        if t <= when:
            return value if when - t <= RAIN_MAX_GAP else None
    return None


def rain_windows(rain, now):
    """[R0, R1, R2]: rain of the last 24h, 24-48h ago, 48-72h ago. None where data is missing."""
    return [rain_24h_at(rain, now - timedelta(hours=24 * i)) for i in range(3)]


def daily_rain_series(rain, now, days):
    """Rain per Swiss calendar day, oldest first: (values, ISO dates).

    A finished day is the 24h window ending at its local midnight; today is the
    last 24h up to `now`. Windows of consecutive days do not overlap.
    """
    today = now.astimezone(LOCAL_TZ).date()
    values, dates = [], []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        if offset == 0:
            when = now
        else:
            midnight = datetime.combine(day + timedelta(days=1), time.min, tzinfo=LOCAL_TZ)
            when = midnight.astimezone(timezone.utc) - timedelta(seconds=1)
        values.append(rain_24h_at(rain, when))
        dates.append(day.isoformat())
    return values, dates


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


# --- Temperature ------------------------------------------------------------

def water_temp_48h_avg(week_chart, latest):
    """Mean of the newest four 12h buckets (= last 48h). The chart is ordered oldest -> newest."""
    recent = week_chart[-4:]
    return sum(recent) / len(recent) if recent else latest
