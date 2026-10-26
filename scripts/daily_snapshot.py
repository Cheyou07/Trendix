"""Invoke the deployed scheduler endpoint; keep polling until success or failure.

Uses only Python's standard library. Secrets come from environment variables.
"""
import json
import os
import time
import urllib.error
import urllib.request


def request(base, path, token=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(base + path, headers=headers,
                                 method='POST' if token else 'GET')
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def main():
    base = os.environ['SCANNER_URL'].rstrip('/')
    token = os.environ['CRON_SECRET']
    if not base.startswith('https://'):
        raise SystemExit('SCANNER_URL must use HTTPS.')
    deadline = time.monotonic() + 35 * 60
    job_id = None
    while time.monotonic() < deadline:
        try:
            if job_id is None:
                job_id = request(base, '/api/admin/daily-run', token)['job_id']
            job = request(base, f'/api/runs/{job_id}')
            if job['status'] == 'completed':
                print(json.dumps(job['result']))
                return
            if job['status'] == 'failed':
                raise SystemExit(job['error'])
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and job_id:
                job_id = None  # Server restarted; daily writes are idempotent.
            elif exc.code not in (429, 500, 502, 503, 504):
                raise SystemExit(f'Scheduler request failed: HTTP {exc.code}') from None
            print(f'Waiting for service (HTTP {exc.code})…')
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            print('Waiting for service to wake up or reconnect…')
        time.sleep(15)
    raise SystemExit('Daily snapshot did not complete within 35 minutes.')


if __name__ == '__main__':
    main()
