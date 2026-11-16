from datetime import datetime, timedelta, timezone

import pytest

import aggregation
from aggregation import calculate_quality

def test_safety_index_thresholds():
    # Test Safety Index transitions (assuming perfect quality Q3)
    perfect_rain = [0, 0, 0]
    perfect_rad = [200, 200, 200]
    
    # S1: < 14.0
    assert calculate_quality(perfect_rain, perfect_rad, 13.9)['safety'] == 1
    # S2: 14.0 <= T < 18.0
    assert calculate_quality(perfect_rain, perfect_rad, 14.0)['safety'] == 2
    assert calculate_quality(perfect_rain, perfect_rad, 17.9)['safety'] == 2
    # S3: >= 18.0
    assert calculate_quality(perfect_rain, perfect_rad, 18.0)['safety'] == 3

def test_quality_index_rain_impact():
    # Test Quality Index based on rain (assuming perfect safety S3)
    safe_temp = 20.0
    perfect_rad = [200, 200, 200]
    
    # Q3: I < 0.5
    assert calculate_quality([0.4, 0, 0], perfect_rad, safe_temp)['quality'] == 3
    # Q2: 0.5 <= I < 3.5 AND r0 < 1.5
    assert calculate_quality([1.4, 0, 0], perfect_rad, safe_temp)['quality'] == 2
    # Q1: I >= 3.5
    assert calculate_quality([3.5, 0, 0], perfect_rad, safe_temp)['quality'] == 1
    # Q1: r0 >= 1.5 (Immediate cap)
    assert calculate_quality([1.5, 0, 0], perfect_rad, safe_temp)['quality'] == 1

def test_quality_rescue_logic():
    # Test Quality Index "rescue" by radiation bonus
    safe_temp = 20.0
    
    # Q3 Rescue: r0 < 1.0 AND I < 2.0 AND B > 1.2
    # B = 210/170 = 1.23
    assert calculate_quality([0.9, 0, 0], [210, 210, 210], safe_temp)['quality'] == 3
    # Fail Q3 Rescue: r0 = 1.0
    assert calculate_quality([1.0, 0, 0], [210, 210, 210], safe_temp)['quality'] == 2
    
    # Q2 Rescue: r0 < 1.5 AND I < 5.0 AND B > 1.0
    # B = 180/170 = 1.05, I = 1.4 + 2.5 + 0.5 = 4.4
    assert calculate_quality([1.4, 5.0, 2.0], [180, 180, 180], safe_temp)['quality'] == 2
    # Fail Q2 Rescue: B < 1.0
    assert calculate_quality([1.4, 5.0, 2.0], [150, 150, 150], safe_temp)['quality'] == 1

def test_quality_caps():
    # Test Quality Index Caps (Radiation Penalty)
    safe_temp = 20.0
    perfect_rain = [0, 0, 0]
    
    # Overcast Penalty: B < 0.6. Without rain it only lowers "excellent" to "good"
    # B = 100/170 = 0.58
    assert calculate_quality(perfect_rain, [100, 100, 100], safe_temp)['quality'] == 2
    # Overcast after rain: discouraged (I = 1.0 would be "good" otherwise)
    assert calculate_quality([1.0, 0, 0], [100, 100, 100], safe_temp)['quality'] == 1
    # Boundary: B = 0.61 (No penalty)
    assert calculate_quality(perfect_rain, [105, 105, 105], safe_temp)['quality'] == 3
    
    # No thermal cap: hot water alone must not lower the water quality
    # (the Rhine is a flowing river, see docs/prognosis-logic.md)
    assert calculate_quality(perfect_rain, [200, 200, 200], 26.0)['quality'] == 3

def test_bottleneck_principle():
    # The overall level MUST be the minimum of Quality and Safety
    
    # Q3, S1 -> Level 1 (Cold but clean)
    res1 = calculate_quality([0, 0, 0], [200, 200, 200], 13.0)
    assert res1['level'] == 1
    assert res1['quality'] == 3
    assert res1['safety'] == 1
    
    # Q1, S3 -> Level 1 (Warm but dirty)
    res2 = calculate_quality([5.0, 0, 0], [200, 200, 200], 20.0)
    assert res2['level'] == 1
    assert res2['quality'] == 1
    assert res2['safety'] == 3
    
    # Q2, S2 -> Level 2
    res3 = calculate_quality([1.0, 0, 0], [200, 200, 200], 16.0)
    assert res3['level'] == 2


# --- fetch_quality refuses to calculate on bad inputs --------------------------

def _hourly(end, hours=24 * 40, rain_gap=None):
    """Complete dry, sunny hourly data up to `end`; `rain_gap` = hours ago without a rain value."""
    rain, radiation, sunshine = {}, {}, {}
    for i in range(hours):
        t = end - timedelta(hours=i)
        rain[t] = None if i == rain_gap else 0.0
        radiation[t] = 200.0
        sunshine[t] = 30.0
    return rain, radiation, sunshine


def _run(monkeypatch, now, hourly, water):
    monkeypatch.setattr(aggregation, 'fetch_hourly', lambda _now: hourly)
    monkeypatch.setattr(aggregation, 'updateJsonFile', lambda path, data: None)
    return aggregation.fetch_quality(water, now=now)


def test_fetch_quality_with_good_inputs(monkeypatch):
    now = datetime(2026, 7, 10, 12, 20, tzinfo=timezone.utc)
    end = now.replace(minute=0)
    water = {'actualValue': 21.0, 'lastUpdate': '2026-07-10T12:00:00+00:00'}
    result = _run(monkeypatch, now, _hourly(end), water)
    assert result['quality'] == 3 and result['inputs']['waterTempC'] == 21.0


@pytest.mark.parametrize('water', [
    {'actualValue': None, 'lastUpdate': None},                          # station delivers nothing
    {'actualValue': 21.0, 'lastUpdate': '2026-07-10T05:00:00+00:00'},   # value is 7 hours old
])
def test_fetch_quality_stops_without_a_fresh_water_temperature(monkeypatch, water):
    now = datetime(2026, 7, 10, 12, 20, tzinfo=timezone.utc)
    with pytest.raises(SystemExit) as stop:
        _run(monkeypatch, now, _hourly(now.replace(minute=0)), water)
    assert stop.value.code == aggregation.EXIT_INCOMPLETE


def test_fetch_quality_stops_on_old_weather_data(monkeypatch):
    now = datetime(2026, 7, 10, 12, 20, tzinfo=timezone.utc)
    water = {'actualValue': 21.0, 'lastUpdate': '2026-07-10T12:00:00+00:00'}
    with pytest.raises(SystemExit) as stop:
        _run(monkeypatch, now, _hourly(now.replace(hour=8, minute=0)), water)  # newest hour 4 h 20 min old
    assert stop.value.code == aggregation.EXIT_INCOMPLETE


def test_fetch_quality_stops_on_a_missing_rain_hour_in_the_last_24_hours(monkeypatch):
    now = datetime(2026, 7, 10, 12, 20, tzinfo=timezone.utc)
    end = now.replace(minute=0)
    water = {'actualValue': 21.0, 'lastUpdate': '2026-07-10T12:00:00+00:00'}
    with pytest.raises(SystemExit) as stop:
        _run(monkeypatch, now, _hourly(end, rain_gap=5), water)
    assert stop.value.code == aggregation.EXIT_INCOMPLETE
    # an older missing hour (24-72 h ago) still counts as 0 mm
    assert _run(monkeypatch, now, _hourly(end, rain_gap=30), water)['quality'] == 3
