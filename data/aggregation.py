import requests
import json
import os
from datetime import datetime, timedelta, timezone

from quality import (  # noqa: F401  (calculate_quality is re-exported for the tests)
    LOCAL_TZ,
    RADIATION_COLUMN,
    RAIN_COLUMN,
    SUNSHINE_COLUMN,
    MAX_MISSING_HOURS,
    WINDOW_HOURS,
    calculate_quality,
    daily_radiation_series,
    daily_sunshine_series,
    daily_rain_series,
    fill_gaps,
    hourly_series,
    missing_hours,
    newest_hour,
    parse_hourly,
    radiation_mean,
    rain_impact,
    rain_windows,
    series_from_records,
    sunshine_fraction,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
API = 'https://data.bs.ch/api/v2/catalog/datasets'

AIR_STATION_ID = '034003A7'  # Rheinpromenade 2

# MeteoSwiss open data, station Basel-Binningen (BAS): hourly precipitation and global radiation.
# "recent" = 1 Jan of this year until yesterday, "now" = today.
METEOSWISS = 'https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/bas/ogd-smn_bas_h_'
RAIN_STALE_AFTER = timedelta(hours=3)

# Exit code: the weather data has a hole right now. The site keeps its current version (see the workflow).
EXIT_INCOMPLETE = 3


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


def get_text(url):
    try:
        resp = requests.get(url=url, timeout=60)
        resp.raise_for_status()
        return resp.content.decode('utf-8-sig')
    except requests.exceptions.RequestException as e:
        raise SystemExit(e)


def fetch_hourly(now):
    """Hourly rain, radiation and sunshine duration of Basel-Binningen for the last ~32 days.

    Returns three dicts {end of hour (UTC): value}.
    """
    kinds = ['recent', 'now']
    if (now - timedelta(days=33)).year < now.year:
        # early January: the window reaches into the previous year
        decade = now.year // 10 * 10
        kinds.insert(0, f'historical_{decade}-{decade + 9}')
    rain, radiation, sunshine = {}, {}, {}
    for kind in kinds:
        text = get_text(f'{METEOSWISS}{kind}.csv')
        rain.update(parse_hourly(text, RAIN_COLUMN))
        radiation.update(parse_hourly(text, RADIATION_COLUMN))
        sunshine.update(parse_hourly(text, SUNSHINE_COLUMN))
    return rain, radiation, sunshine


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

    # Rain, global radiation and sunshine duration: hourly values of Basel-Binningen, labelled with the END of the hour
    rain, radiation, sunshine = fetch_hourly(now)
    end = newest_hour(rain)
    if end is None:
        raise SystemExit('no rain data available')
    if now - end > RAIN_STALE_AFTER:
        print(f'warning: newest rain value is from {end:%Y-%m-%d %H:%M} UTC, the feed seems to be late')
    # A hole in the data (e.g. a whole day, right after midnight UTC) makes every result wrong: stop here.
    holes = missing_hours([rain, radiation, sunshine], end)
    if max(holes) > MAX_MISSING_HOURS:
        print(f'weather data incomplete: missing hours in the 72 h window (rain, radiation, sunshine): {holes}. '
              'The source files are updated with a delay; nothing is published now.')
        raise SystemExit(EXIT_INCOMPLETE)
    # The recommendation is as fresh as the newest hour.
    last_update = end.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Recommendation inputs: the same 72 hours for rain and radiation
    rain_inputs, rain_missing = rain_windows(rain, end)  # [R0, R1, R2]
    impact = rain_impact(rain, end)
    rad_hours, _ = hourly_series(radiation, end, WINDOW_HOURS)
    rad_mean, rad_missing = radiation_mean(radiation, end)
    sun_share, sun_missing = sunshine_fraction(sunshine, end)
    if any(rain_missing):
        print(f'rain: missing hours per 24h window {rain_missing}, counting as 0 mm')
    if rad_missing:
        print(f'radiation: {rad_missing} of {WINDOW_HOURS} hours missing, ignoring them')
    if sun_share is None:
        print('sunshine duration not available, overcast is judged by the mean radiation')
    elif sun_missing:
        print(f'sunshine: {sun_missing} of {WINDOW_HOURS} hours missing, ignoring them')

    waterTempLatest = waterData.get('actualValue', 0)
    prognosis = calculate_quality(rain_inputs, rad_hours, waterTempLatest, rain_impact=impact, sunshine_fraction=sun_share)

    windows = {'last24h': rain_inputs[0], 'from24to48h': rain_inputs[1], 'from48to72h': rain_inputs[2]}
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
            'rainMm': windows,
            'rainImpactMm': impact,
            'radiationMeanWm2': None if rad_mean is None else round(rad_mean),
            'radiationHoursMissing': rad_missing,
            'sunshineFraction': None if sun_share is None else round(sun_share, 3),
            'overcast': prognosis['overcast'],
        },
        'data': [],
    }

    source = 'MeteoSwiss, station Basel-Binningen'
    radiation_data = {
        'measure': 'globalRadiation',
        'source': source,
        'meanLast72hWm2': None if rad_mean is None else round(rad_mean),
        'sunshineLast72hPercent': None if sun_share is None else round(100 * sun_share),
        'chart': {},
    }
    rain_data = {'measure': 'rain', 'source': source, 'windowsMm': windows, 'chart': {}}

    # Charts, oldest -> newest, with the date of every value.
    # Hourly bars of the last 72 hours; 'hourlyStarts' = start of each hour (UTC)
    for data, hourly in ((rain_data, rain), (radiation_data, radiation)):
        values, starts = hourly_series(hourly, end, WINDOW_HOURS)
        data['chart']['hourly'] = [0 if v is None else v for v in values]
        data['chart']['hourlyStarts'] = starts

    # Daily values for week and month. Rain per Swiss day (today = so far); radiation as
    # mean over complete days (today is left out, a partial day is not comparable).
    for name, days in (('week', 7), ('month', 30)):
        values, dates = daily_rain_series(rain, end, days)
        rain_data['chart'][name], gaps = fill_gaps(values)
        rain_data['chart'][name + 'Dates'] = dates
        if gaps:
            print(f'rain {name}: {gaps} day(s) without data, filled with previous value')

        values, dates = daily_radiation_series(radiation, end, days)
        radiation_data['chart'][name], gaps = fill_gaps(values)
        radiation_data['chart'][name + 'Dates'] = dates
        if gaps:
            print(f'radiation {name}: {gaps} day(s) without data, filled with previous value')

    # Sunshine duration: minutes per hour for the 3-day view, share of the possible duration per day for week and month
    sunshine_data = {
        'measure': 'sunshine',
        'source': source,
        'sharePercent72h': None if sun_share is None else round(100 * sun_share),
        'chart': {},
    }
    values, starts = hourly_series(sunshine, end, WINDOW_HOURS)
    sunshine_data['chart']['hourly'] = [0 if v is None else v for v in values]
    sunshine_data['chart']['hourlyStarts'] = starts
    for name, days in (('week', 7), ('month', 30)):
        values, dates = daily_sunshine_series(sunshine, end, days)
        sunshine_data['chart'][name], gaps = fill_gaps(values)
        sunshine_data['chart'][name + 'Dates'] = dates
        if gaps:
            print(f'sunshine {name}: {gaps} day(s) without data, filled with previous value')

    qualityData['data'] = [radiation_data, rain_data, sunshine_data]
    updateJsonFile('qualityData.json', qualityData)
    return qualityData


def main():
    waterData = fetch_water()
    fetch_air()
    fetch_level()
    fetch_quality(waterData)


if __name__ == '__main__':
    main()
