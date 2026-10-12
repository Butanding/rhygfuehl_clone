from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from quality import (
    bucket_start,
    calculate_quality,
    daily_radiation_series,
    daily_rain_series,
    fill_gaps,
    hourly_rain_series,
    newest_hour,
    parse_hourly_rain,
    radiation_by_date,
    radiation_window,
    rain_windows,
    series_from_records,
)

# Real hourly precipitation of MeteoSwiss station Basel-Binningen, 6-12 Oct 2026.
# 8 Oct was a heavy rain day (28.6 mm, 16.5 mm of it in one hour), 11 Oct was dry.
# The timestamp is the END of the hour (UTC).
FIXTURE = Path(__file__).parent / 'fixtures' / 'meteoswiss_bas_hourly_2026-10-06_to_12.csv'


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def load_rain():
    return parse_hourly_rain(FIXTURE.read_text(encoding='utf-8'))


def test_parse_hourly_rain_keeps_the_end_of_hour_timestamp():
    rain = load_rain()
    assert rain[utc(2026, 10, 8, 13, 0)] == 16.5  # rain between 12:00 and 13:00 UTC
    assert newest_hour(rain) == utc(2026, 10, 12, 8, 0)


def test_parse_hourly_rain_handles_missing_values():
    rain = parse_hourly_rain('station_abbr;reference_timestamp;rre150h0\n'
                             'BAS;12.10.2026 08:00;0.4\n'
                             'BAS;12.10.2026 09:00;\n'
                             'BAS;12.10.2026 10:00;-\n')
    assert rain == {utc(2026, 10, 12, 8): 0.4, utc(2026, 10, 12, 9): None, utc(2026, 10, 12, 10): None}
    assert newest_hour(rain) == utc(2026, 10, 12, 8)  # rows without a value are not "newest"


def test_hourly_series_is_ordered_old_to_new_and_labelled_by_hour_start():
    values, starts = hourly_rain_series(load_rain(), utc(2026, 10, 8, 13, 0), 3)
    assert values == [0.4, 1.4, 16.5]
    assert starts == ['2026-10-08T10:00:00Z', '2026-10-08T11:00:00Z', '2026-10-08T12:00:00Z']


def test_hourly_series_marks_missing_hours_as_none():
    rain = {utc(2026, 10, 12, 8): 0.4}
    values, _ = hourly_rain_series(rain, utc(2026, 10, 12, 9), 3)
    assert values == [None, 0.4, None]


def test_rain_windows_do_not_overlap():
    # [R0, R1, R2] = last 24h, 24-48h ago, 48-72h ago
    rain = {utc(2026, 10, 12, 8) - timedelta(hours=h): 1.0 for h in range(0, 72)}
    rain[utc(2026, 10, 12, 8)] = 5.0                      # newest hour -> R0
    rain[utc(2026, 10, 12, 8) - timedelta(hours=24)] = 2.0  # exactly 24h earlier -> R1
    rain[utc(2026, 10, 12, 8) - timedelta(hours=48)] = 3.0  # exactly 48h earlier -> R2
    sums, missing = rain_windows(rain, utc(2026, 10, 12, 8))
    assert sums == [28.0, 25.0, 26.0]  # 23 x 1.0 + 5.0, 23 x 1.0 + 2.0, 23 x 1.0 + 3.0
    assert missing == [0, 0, 0]


def test_rain_windows_on_real_data():
    rain = load_rain()
    # Morning of 12 Oct: dry for 24h, a little drizzle on 10 Oct
    assert rain_windows(rain, utc(2026, 10, 12, 8, 0)) == ([0.0, 1.4, 1.0], [0, 0, 0])
    # The same rain moves one window back every 24h and is never counted twice:
    assert rain_windows(rain, utc(2026, 10, 9, 8, 0))[0] == [24.3, 7.6, 0.0]
    assert rain_windows(rain, utc(2026, 10, 10, 8, 0))[0] == [1.0, 24.3, 7.6]


def test_missing_hours_count_as_zero_and_are_reported():
    rain = {utc(2026, 10, 12, 8): 2.0, utc(2026, 10, 12, 7): None}
    sums, missing = rain_windows(rain, utc(2026, 10, 12, 8))
    assert sums[0] == 2.0
    assert missing[0] == 23  # only the newest hour is known
    assert missing[1] == 24 and missing[2] == 24


def test_dry_day_is_not_reported_as_rain():
    # 11 Oct: the day the single St. Johann sensor of the city's "Smart Climate" network
    # reported 9.4 mm (maximum of ~80 stations, median 0.0). Binningen: dry.
    values, dates = daily_rain_series(load_rain(), utc(2026, 10, 12, 8, 0), 7)
    per_day = dict(zip(dates, values))
    assert per_day['2026-10-11'] == 0.0
    assert per_day['2026-10-08'] == 28.6
    assert dates[-1] == '2026-10-12'  # today so far


def test_daily_rain_uses_swiss_days():
    # CEST is UTC+2: the hour 21:00-22:00 UTC is 23:00-24:00 local (6 Oct),
    # the hour 22:00-23:00 UTC is 00:00-01:00 local (7 Oct).
    rain = {utc(2026, 10, 6, 22): 1.0, utc(2026, 10, 6, 23): 4.0}
    values, dates = daily_rain_series(rain, utc(2026, 10, 6, 23), 2)
    assert dict(zip(dates, values)) == {'2026-10-06': 1.0, '2026-10-07': 4.0}


def test_daily_rain_ignores_days_without_data():
    values, dates = daily_rain_series({utc(2026, 10, 12, 8): 0.4}, utc(2026, 10, 12, 8), 3)
    assert dates == ['2026-10-10', '2026-10-11', '2026-10-12']
    assert values == [None, None, 0.4]


def test_dry_evening_after_rain_is_rated_by_the_last_24h_only():
    rain = load_rain()
    radiation = [173, 121, 165]
    # Evening of 11 Oct: nothing fell in the last 24h
    sums, _ = rain_windows(rain, utc(2026, 10, 11, 22, 0))
    assert sums[0] == 0.0
    assert calculate_quality(sums, radiation, 19.0)['quality'] == 2  # I = 0 + 1.2 + 0.0 -> good
    # Right after the heavy rain of 8 Oct: R0 = 28.6 -> discouraged
    sums, _ = rain_windows(rain, utc(2026, 10, 8, 23, 0))
    assert sums[0] >= 20
    assert calculate_quality(sums, radiation, 19.0)['quality'] == 1


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
    assert calculate_quality(dry, [200, None, None], safe_temp)['quality'] == 3
    # Overcast penalty still applies to a single dark day
    assert calculate_quality(dry, [100, None, None], safe_temp)['quality'] == 1
    # No radiation data at all: conservative, same as an overcast sky
    assert calculate_quality(dry, [None, None, None], safe_temp)['quality'] == 1


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
