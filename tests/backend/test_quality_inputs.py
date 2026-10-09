import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from quality import (
    bucket_start,
    calculate_quality,
    daily_radiation_series,
    daily_rain_series,
    fill_gaps,
    prepare_rain_records,
    radiation_by_date,
    radiation_window,
    rain_24h_at,
    rain_windows,
    series_from_records,
    water_temp_48h_avg,
)

# Real hourly readings of the rain station (rolling 24h sum) from data.bs.ch,
# 3-9 Oct 2026. 5 Oct had rain, 6 Oct was dry, it rained again on 8 Oct.
FIXTURE = Path(__file__).parent / 'fixtures' / 'rain_station_2026-10-03_to_09.json'


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def load_rain():
    return prepare_rain_records(json.loads(FIXTURE.read_text()))


def test_dry_day_after_rain_is_not_reported_as_rain():
    # The old logic took the maximum of the rolling sum per UTC day. On 6 Oct the
    # sum starts at 2.2 mm (rain of 5 Oct still in the window) and falls to 0.
    rain = load_rain()
    by_day = defaultdict(list)
    for t, mm in rain:
        by_day[t.date().isoformat()].append(mm)
    assert max(by_day['2026-10-06']) == 2.2  # what the old logic reported for a dry day

    values, dates = daily_rain_series(rain, utc(2026, 10, 9, 15, 0), 7)
    per_day = dict(zip(dates, values))
    assert per_day['2026-10-05'] == 2.2  # the rainy day
    assert per_day['2026-10-06'] == 0.0  # the dry day
    assert per_day['2026-10-07'] == 0.0


def test_daily_rain_series_is_ordered_old_to_new_with_dates():
    values, dates = daily_rain_series(load_rain(), utc(2026, 10, 9, 15, 0), 7)
    assert dates == ['2026-10-03', '2026-10-04', '2026-10-05', '2026-10-06',
                     '2026-10-07', '2026-10-08', '2026-10-09']
    # today is the rolling sum of the last 24h
    assert values == [1.6, 1.2, 2.2, 0.0, 0.0, 5.4, 7.2]


def test_rain_windows_do_not_overlap():
    # [R0, R1, R2] = last 24h, 24-48h ago, 48-72h ago
    assert rain_windows(load_rain(), utc(2026, 10, 9, 14, 10)) == [7.2, 3.0, 0.0]
    # Evening of the dry day: nothing in the last 24h, the rain of 5 and 4 Oct is further back.
    assert rain_windows(load_rain(), utc(2026, 10, 6, 21, 0)) == [0.0, 2.2, 1.2]


def test_dry_evening_after_rain_is_rated_better_than_with_old_logic():
    rain = load_rain()
    now = utc(2026, 10, 6, 21, 0)
    radiation = [173, 121, 165]  # 5, 4 and 3 Oct

    # Old logic: maxima of the rolling sum per day [6 Oct, 5 Oct, 4 Oct] = [2.2, 3.0, 1.8]
    old = calculate_quality([2.2, 3.0, 1.8], radiation, 19.0, 19.0)
    new = calculate_quality(rain_windows(rain, now), radiation, 19.0, 19.0)
    assert old['quality'] == 1
    assert new['quality'] == 2


def test_missing_rain_data_is_none_not_zero():
    rain = load_rain()
    assert rain_24h_at(rain, utc(2026, 10, 2, 12, 0)) is None  # before the first reading
    assert rain_24h_at(rain, utc(2026, 10, 9, 20, 0)) is None  # last reading is older than 3h
    assert rain_24h_at(rain, utc(2026, 10, 9, 14, 10)) == 7.2


def test_rain_day_boundaries_use_swiss_time():
    # Basel is on CEST (UTC+2) in October: the local day 6 Oct ends at 6 Oct 22:00 UTC.
    # The reading of 21:09 UTC is still on the 6th, the one of 22:09 UTC is already on the 7th.
    rain = [(utc(2026, 10, 6, 21, 9), 1.0), (utc(2026, 10, 6, 22, 9), 4.0)]
    values, dates = daily_rain_series(rain, utc(2026, 10, 8, 12, 0), 3)
    per_day = dict(zip(dates, values))
    assert per_day['2026-10-06'] == 1.0  # 22:09 UTC is already 7 Oct locally


def test_radiation_is_matched_by_date():
    today = date(2026, 10, 9)
    by_date = radiation_by_date([
        {'date': '2026-10-08', 'globalRadiation': 19},
        {'date': '2026-10-07', 'globalRadiation': 91},
        {'date': '2026-10-05', 'globalRadiation': 173},  # 6 Oct is missing
    ])
    # newest first: yesterday, 2 days ago, 3 days ago
    assert radiation_window(by_date, today) == [19, 91, None]

    values, dates = daily_radiation_series(by_date, today, 4)
    assert dates == ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08']
    assert values == [173, None, 91, 19]


def test_radiation_today_is_never_used():
    # The daily mean of today is published tomorrow; a stray entry for today must not shift anything.
    today = date(2026, 10, 9)
    by_date = radiation_by_date([
        {'date': '2026-10-09', 'globalRadiation': 300},
        {'date': '2026-10-08', 'globalRadiation': 19},
    ])
    assert radiation_window(by_date, today, days=1) == [19]


def test_quality_ignores_missing_radiation_days():
    safe_temp = 20.0
    dry = [0, 0, 0]
    # Only one (sunny) day available: average over what we have, B = 200/170
    assert calculate_quality(dry, [200, None, None], safe_temp, safe_temp)['quality'] == 3
    # Overcast penalty still applies to a single dark day
    assert calculate_quality(dry, [100, None, None], safe_temp, safe_temp)['quality'] == 1
    # No radiation data at all: conservative, same as an overcast sky
    assert calculate_quality(dry, [None, None, None], safe_temp, safe_temp)['quality'] == 1


def test_48h_average_uses_the_newest_buckets():
    # Chart is ordered oldest -> newest with 12h buckets: the last four are the last 48h.
    week = [24.0] * 11 + [20.0] * 4
    assert water_temp_48h_avg(week, 20.0) == 20.0  # the hot days a week ago must not count
    assert water_temp_48h_avg([], 19.5) == 19.5


def test_bucket_start_and_series():
    assert bucket_start('[2026-10-08T12:00:00.000Z, 2026-10-09T00:00:00.000Z[') == '2026-10-08T12:00:00.000Z'
    assert bucket_start(None) is None

    records = [
        {'record': {'fields': {'time': '[2026-10-08T00:00:00.000Z, 2026-10-08T12:00:00.000Z[', 'temp': 20.0}}},
        {'record': {'fields': {'time': '[2026-10-08T12:00:00.000Z, 2026-10-09T00:00:00.000Z[', 'temp': None}}},
        {'record': {'fields': {'time': '[2026-10-09T00:00:00.000Z, 2026-10-09T12:00:00.000Z[', 'temp': 21.0}}},
    ]
    values, times = series_from_records(records, 'temp')
    assert values == [20.0, 20.0, 21.0]  # gap filled with the previous value
    assert times[2] == '2026-10-09T00:00:00.000Z'


def test_fill_gaps_reports_number_of_gaps():
    assert fill_gaps([None, 1.0, None, None, 2.0]) == ([0, 1.0, 1.0, 1.0, 2.0], 3)
