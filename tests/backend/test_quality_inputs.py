from datetime import datetime, timedelta, timezone
from pathlib import Path

from quality import (
    WINDOW_HOURS,
    bucket_start,
    calculate_quality,
    daily_radiation_series,
    daily_rain_series,
    fill_gaps,
    hourly_series,
    newest_hour,
    parse_hourly,
    radiation_mean,
    rain_impact,
    rain_weight,
    rain_windows,
    series_from_records,
)

# Real hourly values of MeteoSwiss station Basel-Binningen, 6-12 Oct 2026.
# 8 Oct was a heavy rain day (28.6 mm, 16.5 mm of it in one hour), 11 Oct was dry and
# sunny at noon (429 W/m²) but dark in the rest of the day. The timestamp is the END of
# the hour (UTC).
FIXTURE = Path(__file__).parent / 'fixtures' / 'meteoswiss_bas_hourly_2026-10-06_to_12.csv'


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def load():
    text = FIXTURE.read_text(encoding='utf-8')
    return parse_hourly(text, 'rre150h0'), parse_hourly(text, 'gre000h0')


# --- parsing and hourly series ---------------------------------------------

def test_parse_hourly_keeps_the_end_of_hour_timestamp():
    rain, radiation = load()
    assert rain[utc(2026, 10, 8, 13, 0)] == 16.5  # rain between 12:00 and 13:00 UTC
    assert radiation[utc(2026, 10, 11, 10, 0)] == 429.0
    assert newest_hour(rain) == utc(2026, 10, 12, 8, 0)


def test_parse_hourly_handles_missing_values():
    rain = parse_hourly('station_abbr;reference_timestamp;rre150h0\n'
                        'BAS;12.10.2026 08:00;0.4\n'
                        'BAS;12.10.2026 09:00;\n'
                        'BAS;12.10.2026 10:00;-\n', 'rre150h0')
    assert rain == {utc(2026, 10, 12, 8): 0.4, utc(2026, 10, 12, 9): None, utc(2026, 10, 12, 10): None}
    assert newest_hour(rain) == utc(2026, 10, 12, 8)  # rows without a value are not "newest"


def test_hourly_series_is_ordered_old_to_new_and_labelled_by_hour_start():
    rain, _ = load()
    values, starts = hourly_series(rain, utc(2026, 10, 8, 13, 0), 3)
    assert values == [0.4, 1.4, 16.5]
    assert starts == ['2026-10-08T10:00:00Z', '2026-10-08T11:00:00Z', '2026-10-08T12:00:00Z']


def test_hourly_series_marks_missing_hours_as_none():
    values, _ = hourly_series({utc(2026, 10, 12, 8): 0.4}, utc(2026, 10, 12, 9), 3)
    assert values == [None, 0.4, None]


# --- rain windows and smooth weighting -------------------------------------

def test_rain_windows_do_not_overlap():
    # [R0, R1, R2] = last 24h, 24-48h ago, 48-72h ago
    rain = {utc(2026, 10, 12, 8) - timedelta(hours=h): 1.0 for h in range(0, 72)}
    rain[utc(2026, 10, 12, 8)] = 5.0                        # newest hour -> R0
    rain[utc(2026, 10, 12, 8) - timedelta(hours=24)] = 2.0  # exactly 24h earlier -> R1
    rain[utc(2026, 10, 12, 8) - timedelta(hours=48)] = 3.0  # exactly 48h earlier -> R2
    sums, missing = rain_windows(rain, utc(2026, 10, 12, 8))
    assert sums == [28.0, 25.0, 26.0]  # 23 x 1.0 + 5.0, 23 x 1.0 + 2.0, 23 x 1.0 + 3.0
    assert missing == [0, 0, 0]


def test_rain_windows_on_real_data():
    rain, _ = load()
    assert rain_windows(rain, utc(2026, 10, 12, 8, 0)) == ([0.0, 1.4, 1.0], [0, 0, 0])
    # The same rain moves one window back every 24h and is never counted twice:
    assert rain_windows(rain, utc(2026, 10, 9, 8, 0))[0] == [24.3, 7.6, 0.0]
    assert rain_windows(rain, utc(2026, 10, 10, 8, 0))[0] == [1.0, 24.3, 7.6]


def test_missing_hours_count_as_zero_and_are_reported():
    rain = {utc(2026, 10, 12, 8): 2.0, utc(2026, 10, 12, 7): None}
    sums, missing = rain_windows(rain, utc(2026, 10, 12, 8))
    assert sums[0] == 2.0
    assert missing == [23, 24, 24]  # only the newest hour is known


def test_rain_weight_decays_smoothly_to_zero():
    weights = [rain_weight(i + 0.5) for i in range(WINDOW_HOURS)]
    assert all(a > b for a, b in zip(weights, weights[1:]))                  # always decreasing
    assert max(a - b for a, b in zip(weights, weights[1:])) < 0.05           # no jumps (blocks: 0.5 / 0.25)
    assert rain_weight(WINDOW_HOURS - 0.01) < 0.01 and rain_weight(WINDOW_HOURS) == 0  # fades out, no step
    # half the weight after 24 hours (before the fade-out at the end of the window)
    assert abs(rain_weight(30.5) / rain_weight(6.5) - 0.5) < 0.01


def test_rain_weight_keeps_the_calibration_of_the_block_weights():
    # Steady rain must count about like the former weights 1 / 0.5 / 0.25 per 24h block,
    # so the thresholds of the decision matrix stay valid.
    def block(a, b):
        return sum(rain_weight(i + 0.5) for i in range(a, b)) / (b - a)
    assert abs(block(0, 24) - 1.0) < 0.05
    assert abs(block(24, 48) - 0.5) < 0.05
    assert 0.15 < block(48, 72) < 0.30


def test_rain_impact_does_not_jump_when_rain_gets_older():
    end = utc(2026, 10, 12, 8)
    rain = {end - timedelta(hours=30): 10.0}  # one 10 mm hour
    impacts = [rain_impact(rain, end + timedelta(hours=h)) for h in range(0, 40)]
    assert all(a >= b for a, b in zip(impacts, impacts[1:]))
    assert max(a - b for a, b in zip(impacts, impacts[1:])) < 0.5  # the block model dropped by 2.5 mm at once
    assert rain_impact(rain, end + timedelta(hours=60)) == 0.0     # out of the window


def test_rain_impact_on_real_data():
    rain, _ = load()
    # Right after the heavy rain of 8 Oct: R0 = 28.6 mm
    assert rain_impact(rain, utc(2026, 10, 8, 23, 0)) > 28
    # Four days later almost nothing is left of it
    assert rain_impact(rain, utc(2026, 10, 12, 8, 0)) < 1.0


# --- radiation --------------------------------------------------------------

def test_radiation_mean_covers_the_same_72_hours_as_the_rain():
    _, radiation = load()
    mean, missing = radiation_mean(radiation, utc(2026, 10, 12, 8))
    assert missing == 0
    assert 85 < mean < 87  # incl. the nights, 3 x 24 hours


def test_radiation_mean_ignores_missing_hours():
    mean, missing = radiation_mean({utc(2026, 10, 12, 8): 100.0, utc(2026, 10, 12, 7): 300.0}, utc(2026, 10, 12, 8))
    assert (mean, missing) == (200.0, 70)
    assert radiation_mean({}, utc(2026, 10, 12, 8)) == (None, WINDOW_HOURS)


def test_daily_radiation_is_the_mean_of_complete_local_days():
    _, radiation = load()
    values, dates = daily_radiation_series(radiation, utc(2026, 10, 12, 8), 5)
    assert dates == ['2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10', '2026-10-11']  # today is left out
    # MeteoSwiss daily means for these days: 91, 19, 103, 69, 84 W/m² (6-6 UTC, so not identical)
    assert values == [91, 19, 103, 69, 84]


def test_daily_radiation_needs_enough_hours():
    radiation = {utc(2026, 10, 10, h): 100.0 for h in range(1, 12)}  # only 11 hours of 10 Oct
    values, _ = daily_radiation_series(radiation, utc(2026, 10, 12, 8), 2)
    assert values == [None, None]


# --- daily rain --------------------------------------------------------------

def test_dry_day_is_not_reported_as_rain():
    # 11 Oct: the day the single St. Johann sensor of the city's "Smart Climate" network
    # reported 9.4 mm (maximum of ~80 stations, median 0.0). Binningen: dry.
    rain, _ = load()
    values, dates = daily_rain_series(rain, utc(2026, 10, 12, 8, 0), 7)
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


# --- recommendation ----------------------------------------------------------

def test_quality_accepts_hourly_radiation_and_a_given_rain_impact():
    sunny = [250.0] * 72
    # I is taken from the argument, the windows only feed the R0 conditions
    assert calculate_quality([0, 0, 0], sunny, 20.0, rain_impact=0.2)['quality'] == 3
    assert calculate_quality([0, 0, 0], sunny, 20.0, rain_impact=4.0)['quality'] == 2
    assert calculate_quality([0, 0, 0], sunny, 20.0, rain_impact=5.0)['quality'] == 1


def test_overcast_rule_is_unchanged_with_hourly_radiation():
    # Cantonal Laboratory: overcast skies are bad even without rain. 72h mean 85 W/m² = 0.5 x 170
    dark = [85.0] * 72
    assert calculate_quality([0, 0, 0], dark, 20.0, rain_impact=0.0)['quality'] == 1
    # the same mean made of a dark night and a bright day is just as "overcast"
    mixed = ([0.0] * 12 + [170.0] * 12) * 3
    assert calculate_quality([0, 0, 0], mixed, 20.0, rain_impact=0.0)['quality'] == 1
    # 72h mean 105 W/m² = 0.62 x 170: no penalty
    assert calculate_quality([0, 0, 0], [105.0] * 72, 20.0, rain_impact=0.0)['quality'] == 3


def test_quality_ignores_missing_radiation():
    dry = [0, 0, 0]
    # Only some (sunny) hours available: mean over what we have
    assert calculate_quality(dry, [200, None, None], 20.0)['quality'] == 3
    # No radiation data at all: conservative, same as an overcast sky
    assert calculate_quality(dry, [None, None, None], 20.0)['quality'] == 1


def test_real_data_after_the_heavy_rain_and_four_days_later():
    rain, radiation = load()
    for end, expected in ((utc(2026, 10, 8, 23, 0), 1), (utc(2026, 10, 12, 8, 0), 1)):
        windows, _ = rain_windows(rain, end)
        hours, _ = hourly_series(radiation, end, WINDOW_HOURS)
        result = calculate_quality(windows, hours, 19.0, rain_impact=rain_impact(rain, end))
        assert result['quality'] == expected  # 8 Oct: heavy rain; 12 Oct: 72h mean 86 W/m² is "overcast"


# --- helpers -----------------------------------------------------------------

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
