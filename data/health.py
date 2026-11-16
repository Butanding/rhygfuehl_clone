"""Log of data source problems: which source was late, had a gap or failed, and for how long.

The log is a CSV file with one row per *change* of a source's status (not one per run), so a
two-day outage is two rows: its start and its end. Counting rows answers "how often", the column
`previous_minutes` answers "how long".

Nothing in here depends on where the script runs. The file is at `data/health-log.csv` or wherever
the environment variable HEALTH_LOG points to; keeping that file between runs (committing it,
caching it) is the job of the CI.
"""
import csv
import os
from datetime import datetime, timezone

FIELDS = ['time_utc', 'source', 'status', 'previous_status', 'previous_minutes',
          'data_time_utc', 'age_minutes', 'detail']

OK = 'ok'
DELAYED = 'delayed'            # newer data is overdue, the recommendation is still calculated
OUTAGE = 'outage'              # so old that no recommendation is calculated
NO_VALUE = 'no_value'          # the source answers, but without a usable value
GAP = 'gap'                    # hours are missing inside the 72 h window
DOWNLOAD_FAILED = 'download_failed'
ERROR = 'error'                # unexpected answer of the source

TIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def default_path():
    return os.environ.get('HEALTH_LOG') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'health-log.csv')


def status_by_age(age, delayed_after, outage_after):
    """ok / delayed / outage from the age (timedelta) of the newest value; no_value without one."""
    if age is None:
        return NO_VALUE
    if age > outage_after:
        return OUTAGE
    if age > delayed_after:
        return DELAYED
    return OK


def read_log(path):
    """Rows of the log (list of dicts), [] if there is no log yet."""
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def last_statuses(rows):
    """{source: (status, time of that row)} from the newest row of every source."""
    last = {}
    for row in rows:
        try:
            when = datetime.strptime(row['time_utc'], TIME_FORMAT).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        last[row.get('source')] = (row.get('status'), when)
    return last


def new_rows(now, current, previous):
    """Rows to append: one for every source whose status differs from its last logged status.

    current: {source: {'status': ..., 'data_time': datetime or None, 'detail': text}}
    previous: result of last_statuses(). A source that was never logged counts as ok,
    so a healthy source produces no row at all.
    """
    rows = []
    for source in sorted(current):
        state = current[source]
        before, since = previous.get(source, (OK, None))
        if state['status'] == before:
            continue
        data_time = state.get('data_time')
        rows.append({
            'time_utc': now.strftime(TIME_FORMAT),
            'source': source,
            'status': state['status'],
            'previous_status': before,
            'previous_minutes': '' if since is None else round((now - since).total_seconds() / 60),
            'data_time_utc': '' if data_time is None else data_time.astimezone(timezone.utc).strftime(TIME_FORMAT),
            'age_minutes': '' if data_time is None else round((now - data_time).total_seconds() / 60),
            'detail': ' '.join(str(state.get('detail') or '').split())[:200],
        })
    return rows


def append_rows(path, rows):
    if not rows:
        return
    is_new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def record(now, current, path=None):
    """Compare with the log and append the changes. Returns the appended rows."""
    path = path or default_path()
    rows = new_rows(now, current, last_statuses(read_log(path)))
    append_rows(path, rows)
    return rows
