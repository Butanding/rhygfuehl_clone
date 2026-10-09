import requests
import json
import os
from datetime import datetime, timezone

from quality import (  # noqa: F401  (calculate_quality is re-exported for the tests)
    LOCAL_TZ,
    calculate_quality,
    daily_radiation_series,
    daily_rain_series,
    fill_gaps,
    latest_rain_timestamp,
    prepare_rain_records,
    radiation_by_date,
    radiation_window,
    rain_windows,
    series_from_records,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
API = 'https://data.bs.ch/api/v2/catalog/datasets'

AIR_STATION_ID = '034003A7'  # Rheinpromenade 2
RAIN_STATION_ID = '034001AF'  # St. Johann


def updateJsonFile( path, data ):
    with open(os.path.join(DATA_DIR, path), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def get_json(url, **kwargs):
    try:
        resp = requests.get(url=url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise SystemExit(e)


def add_chart(target, name, url, field):
    """Fetch an aggregated series into target['chart'][name] and target['chart'][name + 'Times']."""
    values, times = series_from_records(get_json(url)['records'], field)
    target['chart'][name] = values
    target['chart'][name + 'Times'] = times


def fetch_water():
    # Actual temperature
    waterData = {}
    d = get_json(f'{API}/100046/records?order_by=endezeitpunkt%20DESC&limit=2&pretty=false&timezone=UTC')

    if d['records'][0]['record']['fields']['rus_w_o_s3_te'] is not None:
        waterData['actualValue'] = d['records'][0]['record']['fields']['rus_w_o_s3_te']
        waterData['lastUpdate'] = d['records'][0]['record']['fields']['endezeitpunkt']
    else:
        print('newest temp is null we take next older one')
        if d['records'][1]['record']['fields']['rus_w_o_s3_te'] is not None:
            waterData['actualValue'] = d['records'][1]['record']['fields']['rus_w_o_s3_te']
            waterData['lastUpdate'] = d['records'][1]['record']['fields']['endezeitpunkt']
        else:
            print('no valid temp')
            waterData['actualValue'] = 0
            waterData['lastUpdate'] = None

    waterData['chart'] = {}
    # Weekly data (12h buckets, oldest first)
    add_chart(waterData, 'week', f'{API}/100046/records?select=avg(rus_w_o_s3_te)%20as%20temp&where=endezeitpunkt%3E%3Dnow(days%3D-7)&group_by=range(endezeitpunkt%2C%2012%20hour)%20as%20time&limit=900&pretty=false&timezone=UTC', 'temp')
    # Monthly data (2 day buckets, oldest first)
    add_chart(waterData, 'month', f'{API}/100046/records?select=avg(rus_w_o_s3_te)%20as%20temp&where=endezeitpunkt%3E%3Dnow(days%3D-30)&group_by=range(endezeitpunkt,2days)%20as%20time&limit=900&pretty=false&timezone=UTC', 'temp')

    updateJsonFile('waterData.json', waterData)
    return waterData


def fetch_air():
    # Air temperature
    airData = {}
    d = get_json(f'{API}/100009/records?select=dates_max_date%20as%20date%2C%20meta_airtemp%20as%20temp&where=name_original="{AIR_STATION_ID}"&limit=1&pretty=false&timezone=UTC&order_by=dates_max_date%20DESC')

    try:
        d['records'][0]['record']['fields']['temp']
    except (KeyError, IndexError):
        print('air temp not defined')
        try:
            airData['actualValue'] = d['records'][1]['record']['fields']['temp']
            airData['lastUpdate'] = d['records'][1]['record']['fields']['date']
        except (KeyError, IndexError):
            print('last air temp not defined')
            airData['actualValue'] = 0
            airData['lastUpdate'] = None
    else:
        airData['actualValue'] = d['records'][0]['record']['fields']['temp']
        airData['lastUpdate'] = d['records'][0]['record']['fields']['date']

    airData['chart'] = {}
    add_chart(airData, 'week', f'{API}/100009/records?select=avg(meta_airtemp)%20as%20temp&where=name_original="{AIR_STATION_ID}"%20and%20dates_max_date%3E%3Dnow(days%3D-7)&group_by=range(dates_max_date%2C%206%20hour)%20as%20time&limit=900&pretty=false&timezone=UTC', 'temp')
    add_chart(airData, 'month', f'{API}/100009/records?select=avg(meta_airtemp)%20as%20temp&where=name_original="{AIR_STATION_ID}"%20and%20dates_max_date%3E%3Dnow(days%3D-30)&group_by=range(dates_max_date,2days)%20as%20time&limit=900&pretty=false&timezone=UTC', 'temp')

    updateJsonFile('airData.json', airData)
    return airData


def fetch_level():
    # Water level
    levelData = {}
    d = get_json('https://data.bs.ch/api/records/1.0/analyze?dataset=100089&y.pegel.func=AVG&y.pegel.expr=pegel&precision=year&x=timestamp&sort=-x&exclude.pegel=0')
    lastAvg = d[1]['pegel']

    d = get_json(f'{API}/100089/records?select=pegel&limit=1&pretty=false&timezone=UTC&order_by=timestamp%20DESC')
    try:
        levelData['actualValue'] = d['records'][0]['record']['fields']['pegel'] - lastAvg
        levelData['lastUpdate'] = d['records'][0]['record']['timestamp']
    except (KeyError, IndexError):
        print('level not defined')
        levelData['actualValue'] = 0
        levelData['lastUpdate'] = None

    levelData['chart'] = {}
    add_chart(levelData, 'week', f'{API}/100089/records?select=avg(pegel)%20as%20pegel&where=timestamp%3E%3Dnow(days%3D-7)&group_by=range(timestamp%2C%206%20hour)%20as%20time&limit=900&pretty=false&timezone=UTC', 'pegel')
    add_chart(levelData, 'month', f'{API}/100089/records?select=avg(pegel)%20as%20pegel&where=timestamp%3E%3Dnow(days%3D-30)&group_by=range(timestamp,2days)%20as%20time&limit=900&pretty=false&timezone=UTC', 'pegel')

    updateJsonFile('levelData.json', levelData)
    return levelData


def fetch_quality(waterData, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(LOCAL_TZ).date()

    # Global radiation: daily mean, the city publishes it the day after.
    d = get_json(f'{API}/100254/records?select=date%2C%20gre000d0%20as%20globalRadiation&limit=40&pretty=false&timezone=UTC&order_by=date%20DESC')
    radiation = radiation_by_date([r['record']['fields'] for r in d['records']])

    # Rain: hourly readings of the rolling 24h sum. 32 days cover the month chart.
    rows = get_json(
        f'{API}/100009/exports/json',
        params={
            'select': 'dates_max_date,meta_rain24h_sum',
            'where': f'name_original="{RAIN_STATION_ID}" and dates_max_date>=now(days=-32)',
            'order_by': 'dates_max_date',
            'timezone': 'UTC',
        },
    )
    rain = prepare_rain_records(rows)
    # The recommendation is as fresh as the latest rain reading (radiation only changes daily).
    last_update = latest_rain_timestamp(rain) or now.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Recommendation inputs
    rain_inputs = rain_windows(rain, now)  # [R0, R1, R2]
    rad_inputs = radiation_window(radiation, today)  # [yesterday, 2 days ago, 3 days ago]
    if None in rain_inputs:
        print(f'rain data missing for {rain_inputs.count(None)} of 3 windows, counting as 0 mm')
    if None in rad_inputs:
        print(f'radiation data missing for {rad_inputs.count(None)} of 3 days, ignoring them')
    rain_inputs = [0 if v is None else v for v in rain_inputs]

    waterTempLatest = waterData.get('actualValue', 0)

    prognosis = calculate_quality(rain_inputs, rad_inputs, waterTempLatest)

    # Charts, oldest -> newest, with the date of every value
    qualityData = {
        'quality': prognosis['level'],
        'lastUpdate': last_update,
        'indices': {
            'quality': prognosis['quality'],
            'safety': prognosis['safety'],
        },
        # What the recommendation was calculated from, for transparency and debugging
        'inputs': {
            'asOf': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'rainMm': {'last24h': rain_inputs[0], 'from24to48h': rain_inputs[1], 'from48to72h': rain_inputs[2]},
            'radiationWm2': {'yesterday': rad_inputs[0], 'twoDaysAgo': rad_inputs[1], 'threeDaysAgo': rad_inputs[2]},
        },
        'data': [],
    }

    radiation_data = {'measure': 'globalRadiation', 'chart': {}}
    rain_data = {'measure': 'rain', 'chart': {}}
    for name, days in (('week', 7), ('month', 30)):
        values, dates = daily_radiation_series(radiation, today, days)
        radiation_data['chart'][name], gaps = fill_gaps(values)
        radiation_data['chart'][name + 'Dates'] = dates
        if gaps:
            print(f'radiation {name}: {gaps} day(s) without data, filled with previous value')

        values, dates = daily_rain_series(rain, now, days)
        rain_data['chart'][name], gaps = fill_gaps(values)
        rain_data['chart'][name + 'Dates'] = dates
        if gaps:
            print(f'rain {name}: {gaps} day(s) without data, filled with previous value')

    qualityData['data'] = [radiation_data, rain_data]
    updateJsonFile('qualityData.json', qualityData)
    return qualityData


def main():
    waterData = fetch_water()
    fetch_air()
    fetch_level()
    fetch_quality(waterData)


if __name__ == '__main__':
    main()
