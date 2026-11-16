import requests
import json
import os
import time
from datetime import datetime, timedelta, timezone

import health
from quality import (  # noqa: F401  (calculate_quality is re-exported for the tests)
    LOCAL_TZ,
    RADIATION_COLUMN,
    RAIN_COLUMN,
    SUNSHINE_COLUMN,
    MAX_MISSING_HOURS,
    WINDOW_HOURS,
    age,
    calculate_quality,
    daily_radiation_series,
    daily_sunshine_series,
    data_fingerprint,
    daily_rain_series,
    fill_gaps,
    hourly_series,
    missing_hours,
    newest_hour,
    newest_valid,
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
# Older inputs than this are not used for a recommendation (nothing is published, the site keeps
# its current version and the page itself warns once that version is too old).
RAIN_STALE_AFTER = timedelta(hours=3)
WATER_STALE_AFTER = timedelta(hours=6)

# Exit code: the weather data has a hole right now. The site keeps its current version (see the workflow).
EXIT_INCOMPLETE = 3


class Incomplete(SystemExit):
    """The inputs do not allow a recommendation right now (ends the script with EXIT_INCOMPLETE)."""

    def __init__(self, source, status, detail):
        super().__init__(EXIT_INCOMPLETE)
        self.source, self.status, self.detail = source, status, detail


# Health log (see health.py): a source counts as "delayed" when its newest value is older than this.
# Usual ages: water, air and level under an hour, the weather hour up to about two hours.
DELAYED_AFTER = {'water': timedelta(hours=2), 'air': timedelta(hours=2), 'level': timedelta(hours=2),
                 'weather': timedelta(hours=2, minutes=30)}
# ... and as "outage" after this (water and weather: no recommendation is calculated then)
OUTAGE_AFTER = {'water': WATER_STALE_AFTER, 'air': timedelta(hours=6), 'level': timedelta(hours=6),
                'weather': RAIN_STALE_AFTER}
# Every night until about 02:50 UTC yesterday is missing in the MeteoSwiss files. That gap is
# expected and not logged; a gap at or after this hour (UTC) is.
NIGHTLY_GAP_UNTIL_HOUR_UTC = 4

RETRIES = 4


def updateJsonFile( path, data ):
    with open(os.path.join(DATA_DIR, path), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def _get(url, timeout, **kwargs):
    """GET with a few retries: the data portals reset a connection now and then."""
    for attempt in range(RETRIES):
        try:
            resp = requests.get(url=url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            if attempt == RETRIES - 1:
                raise SystemExit(e)
            print(f'request failed ({e.__class__.__name__}), retrying')
            time.sleep(2 * (attempt + 1))


def get_json(url, **kwargs):
    return _get(url, 30, **kwargs).json()


def get_text(url):
    return _get(url, 60).content.decode('utf-8-sig')


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
    d = get_json(f'{API}/100046/records?order_by=endezeitpunkt%20DESC&limit=50&pretty=false&timezone=UTC')

    # Newest value that is not empty. None if the station delivered nothing usable:
    # fetch_quality() then refuses to calculate (a made-up 0 °C would read "discouraged").
    waterData['actualValue'], waterData['lastUpdate'] = newest_valid(d['records'], 'rus_w_o_s3_te', 'endezeitpunkt')
    if waterData['actualValue'] is None:
        print('no valid water temperature in the newest 50 records')

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


def fetch_quality(waterData, now=None, report=None):
    """Calculate the recommendation. `report` (a dict) receives 'weather_end', the end of the newest hour."""
    now = now or datetime.now(timezone.utc)

    # Rain, global radiation and sunshine duration: hourly values of Basel-Binningen, labelled with the END of the hour
    rain, radiation, sunshine = fetch_hourly(now)
    end = newest_hour(rain)
    if end is None:
        raise Incomplete('weather', health.NO_VALUE, 'no rain value in the files')
    if report is not None:
        report['weather_end'] = end
    if now - end > RAIN_STALE_AFTER:
        print(f'weather data too old: newest rain value is from {end:%Y-%m-%d %H:%M} UTC. Nothing is published now.')
        raise Incomplete('weather', health.OUTAGE, 'newest rain value too old')
    # A hole in the data (e.g. a whole day, right after midnight UTC) makes every result wrong: stop here.
    holes = missing_hours([rain, radiation, sunshine], end)
    if max(holes) > MAX_MISSING_HOURS:
        print(f'weather data incomplete: missing hours in the 72 h window (rain, radiation, sunshine): {holes}. '
              'The source files are updated with a delay; nothing is published now.')
        raise Incomplete('weather', health.GAP, f'missing hours in 72 h (rain/radiation/sunshine): {"/".join(map(str, holes))}')
    # A missing hour counts as 0 mm. In the last 24 hours that could hide the very rain that matters.
    rain_inputs, rain_missing = rain_windows(rain, end)  # [R0, R1, R2]
    if rain_missing[0]:
        print(f'rain: {rain_missing[0]} hour(s) of the last 24 hours missing. Nothing is published now.')
        raise Incomplete('weather', health.GAP, f'{rain_missing[0]} rain hour(s) of the last 24 h missing')
    # The water temperature decides the safety index: no value or an old one -> no recommendation.
    water_age = age(waterData.get('lastUpdate'), now)
    if waterData.get('actualValue') is None or water_age is None or water_age > WATER_STALE_AFTER:
        print(f"water temperature missing or too old (last value: {waterData.get('lastUpdate')}). Nothing is published now.")
        raise Incomplete('water', health.NO_VALUE if water_age is None else health.OUTAGE, 'water temperature missing or too old')
    # The recommendation is as fresh as the newest hour.
    last_update = end.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Recommendation inputs: the same 72 hours for rain and radiation
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

    waterTempLatest = waterData['actualValue']
    prognosis = calculate_quality(rain_inputs, rad_hours, waterTempLatest, rain_impact=impact, sunshine_fraction=sun_share)

    windows = {'last24h': rain_inputs[0], 'from24to48h': rain_inputs[1], 'from48to72h': rain_inputs[2]}
    qualityData = {
        'quality': prognosis['level'],
        'lastUpdate': last_update,
        'indices': {
            'quality': prognosis['quality'],
            'safety': prognosis['safety'],
        },
        # Why the water quality is what it is: codes, the website turns them into sentences
        'reasons': prognosis['reasons'],
        # What the recommendation was calculated from, for transparency and debugging
        'inputs': {
            'asOf': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'rainMm': windows,
            'rainImpactMm': impact,
            'radiationMeanWm2': None if rad_mean is None else round(rad_mean),
            'radiationHoursMissing': rad_missing,
            'sunshineFraction': None if sun_share is None else round(sun_share, 3),
            'overcast': prognosis['overcast'],
            'waterTempC': waterTempLatest,
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


def _parse_time(timestamp):
    if not timestamp:
        return None
    return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))


def main(now=None):
    now = now or datetime.now(timezone.utc)
    results, states, failure = {}, {}, None

    # Every source is fetched even if another one fails, so the health log sees all of them.
    for source, fetch in (('water', fetch_water), ('air', fetch_air), ('level', fetch_level)):
        try:
            results[source] = fetch()
        except SystemExit as e:  # download failed after all retries
            states[source] = {'status': health.DOWNLOAD_FAILED, 'detail': e}
            failure = failure or e
        except Exception as e:  # unexpected answer
            states[source] = {'status': health.ERROR, 'detail': f'{e.__class__.__name__}: {e}'}
            failure = failure or e
        else:
            updated = _parse_time(results[source].get('lastUpdate'))
            states[source] = {
                'status': health.status_by_age(age(updated, now), DELAYED_AFTER[source], OUTAGE_AFTER[source]),
                'data_time': updated,
            }

    qualityData, report, nightly_gap = None, {}, False
    if 'water' in results:
        try:
            qualityData = fetch_quality(results['water'], now=now, report=report)
        except Incomplete as e:
            failure = failure or e
            if e.source == 'weather':
                nightly_gap = e.status == health.GAP and now.hour < NIGHTLY_GAP_UNTIL_HOUR_UTC
                if not nightly_gap:
                    states['weather'] = {'status': e.status, 'detail': e.detail, 'data_time': report.get('weather_end')}
        except SystemExit as e:
            states['weather'] = {'status': health.DOWNLOAD_FAILED, 'detail': e}
            failure = failure or e
        except Exception as e:
            states['weather'] = {'status': health.ERROR, 'detail': f'{e.__class__.__name__}: {e}'}
            failure = failure or e
        # The weather checks passed (or only the water temperature stopped the calculation): judge by age
        if 'weather' not in states and not nightly_gap and 'weather_end' in report:
            end = report['weather_end']
            states['weather'] = {
                'status': health.status_by_age(now - end, DELAYED_AFTER['weather'], OUTAGE_AFTER['weather']),
                'data_time': end,
            }

    # The log must never break the data update.
    try:
        for row in health.record(now, states):
            print(f"health log: {row['source']} {row['previous_status']} -> {row['status']} {row['detail']}".rstrip())
    except Exception as e:
        print(f'health log could not be written: {e}')

    if failure is not None:
        raise failure

    waterData, airData, levelData = results['water'], results['air'], results['level']
    # Changes whenever any of the data got a newer time stamp. The Pages workflow publishes it next
    # to the site and skips a scheduled run if the published site already has the same fingerprint.
    fingerprint = data_fingerprint(qualityData['lastUpdate'], waterData['lastUpdate'],
                                   airData['lastUpdate'], levelData['lastUpdate'])
    with open(os.path.join(DATA_DIR, 'fingerprint.txt'), 'w', encoding='utf-8') as f:
        f.write(fingerprint)


if __name__ == '__main__':
    main()
