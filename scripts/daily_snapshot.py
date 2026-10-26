"""Compute on GitHub Actions, then upload snapshots to Render using CRON_SECRET."""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.daily_worker import snapshots_for_plan


def request(base, path, token, deadline, payload=None):
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload, allow_nan=False).encode()
    while time.monotonic() < deadline:
        req = urllib.request.Request(base + path, data=data, headers=headers,
                                     method='POST' if payload is not None else 'GET')
        try:
            with urllib.request.urlopen(req, timeout=min(90, max(1, deadline - time.monotonic()))) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f'Snapshot request failed: HTTP {exc.code}. '
                                   'Check deployment and scheduler settings.') from None
            print(f'Waiting for service (HTTP {exc.code})...', flush=True)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            print('Waiting for service to wake up or reconnect...', flush=True)
        time.sleep(min(15, max(0, deadline - time.monotonic())))
    raise RuntimeError('Daily snapshot exceeded its 35-minute deadline.')


def main():
    base = os.environ['SCANNER_URL'].rstrip('/')
    token = os.environ['CRON_SECRET']
    if not base.startswith('https://'):
        raise SystemExit('SCANNER_URL must use HTTPS.')
    deadline = time.monotonic() + 35 * 60
    plan = request(base, '/api/admin/daily-plan', token, deadline)
    print(f"Computing {len(plan['pending'])} missing snapshots on this runner.", flush=True)

    def progress(value):
        if value['phase'] != 'evaluating' or value['done'] % 40 == 0:
            print(f"{value['phase']}: {value['done']}/{value['total']} stocks, "
                  f"{value['failed']} unavailable", flush=True)

    saved = 0
    for payload in snapshots_for_plan(plan, progress):
        request(base, '/api/admin/daily-snapshot', token, deadline, payload)
        saved += 1
        print(f"Saved {payload['index']} / {payload['setup']}", flush=True)
    print(json.dumps({'run_date': plan['run_date'], 'snapshots_processed': saved}), flush=True)


if __name__ == '__main__':
    main()
