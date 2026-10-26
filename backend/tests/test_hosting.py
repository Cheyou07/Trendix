import time
import unittest
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import patch

import mongomock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.history import HistoryStore, snapshot_dates
from app.hosting import install_hosting
from app.daily_worker import snapshots_for_plan
from app.errors import ScanError
from app.jobs import JobQueue

NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
SETUP = {'id': 'setup_1', 'name': 'Test setup'}
ROWS = [{'symbol': 'AAA', 'score': 80, 'qualified': False, 'setup_id': 'setup_1'}]


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.coll = mongomock.MongoClient(tz_aware=True).db.daily_runs
        self.coll.create_index([('run_date', 1), ('index', 1), ('setup_id', 1)], unique=True)
        self.store = HistoryStore(self.coll)

    def test_first_run_is_preserved_on_retries(self):
        self.store.save('NIFTY50', SETUP, ROWS, ['AAA', 'BBB'], NOW)
        self.store.save('NIFTY50', SETUP, [], ['AAA'], NOW + timedelta(hours=1))
        result = self.store.get('NIFTY50', 'setup_1', '2026-10-26', NOW)
        self.assertEqual(self.coll.count_documents({}), 1)
        self.assertEqual(result['results'], ROWS)
        self.assertEqual(result['captured_at'], NOW)
        self.assertEqual(result['missing_symbols'], ['BBB'])
        self.assertFalse(result['complete'])

    def test_ist_midnight_and_retention(self):
        before = datetime(2026, 10, 26, 18, 29, tzinfo=timezone.utc)
        after = before + timedelta(minutes=1)
        self.assertEqual(snapshot_dates(before)[0], '2026-10-26')
        self.assertEqual(snapshot_dates(after)[0], '2026-10-27')
        self.store.save('NIFTY50', SETUP, ROWS, ['AAA'], NOW)
        expiry = snapshot_dates(NOW)[1]
        self.assertEqual(len(self.store.list('NIFTY50', 'setup_1', expiry - timedelta(seconds=1))), 1)
        # Reads exclude expired records even before Mongo's asynchronous TTL deletion.
        self.assertEqual(self.store.list('NIFTY50', 'setup_1', expiry), [])
        with self.assertRaises(HTTPException) as ctx:
            self.store.get('NIFTY50', 'setup_1', '2026-10-26', expiry)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_indexes_and_setups_have_separate_snapshots(self):
        for index in ('NIFTY50', 'NIFTYBANK'):
            for setup_id in ('setup_1', 'setup_2'):
                self.store.save(index, dict(SETUP, id=setup_id), ROWS, ['AAA'], NOW)
        self.assertEqual(self.coll.count_documents({}), 4)

    def test_daily_worker_fetches_union_once_and_produces_only_missing_snapshots(self):
        rows = [dict(symbol='AAA', setups=ROWS),
                dict(symbol='BBB', setups=[dict(ROWS[0], symbol='BBB')])]
        plan = {'captured_at': NOW.isoformat(), 'pending': [
            {'index': 'NIFTY50', 'setup': 'setup_1'},
            {'index': 'NIFTYBANK', 'setup': 'setup_1'}]}
        with patch('app.daily_worker.get_index_symbols', side_effect=lambda i: ['AAA'] if i == 'NIFTY50' else ['AAA', 'BBB']), \
             patch('app.daily_worker.load_setup', return_value=SETUP), \
             patch('app.daily_worker.scan_universe_all_setups', return_value=rows) as scanner:
            snapshots = list(snapshots_for_plan(plan))
            self.assertEqual(list(snapshots_for_plan(dict(plan, pending=[]))), [])
        self.assertEqual(scanner.call_count, 1)
        self.assertEqual(scanner.call_args.args[1], ['AAA', 'BBB'])
        self.assertEqual([len(s['results']) for s in snapshots], [1, 2])

    def test_failed_index_does_not_save_an_empty_success(self):
        plan = {'captured_at': NOW.isoformat(), 'pending': [{'index': 'NIFTY50', 'setup': 'setup_1'}]}
        with patch('app.daily_worker.get_index_symbols', return_value=['AAA']), \
             patch('app.daily_worker.load_setup', return_value=SETUP), \
             patch('app.daily_worker.scan_universe_all_setups', return_value=[]):
            with self.assertRaises(ScanError):
                list(snapshots_for_plan(plan))


def immediate_runner(work, payload, progress, timeout):
    return work(payload, progress)


def wait_done(queue, job_id, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job = queue.get(job_id)
        if job['status'] not in ('queued', 'running'):
            return job
        time.sleep(.02)
    raise AssertionError('Job did not finish')


# Module-level workers are picklable under Windows and Linux spawn.
def hung_worker(payload, progress):
    progress({'phase': 'fetching'})
    while True:
        time.sleep(.1)


def successful_worker(payload, progress):
    progress({'phase': 'completed', 'done': 1, 'total': 1})
    return {'value': payload}


class QueueTests(unittest.TestCase):
    def test_hung_process_is_killed_and_next_scan_finishes(self):
        import multiprocessing
        before = {p.pid for p in multiprocessing.active_children()}
        queue = JobQueue(timeout=5)
        first = queue.submit(('stuck',), hung_worker, {})
        second = queue.submit(('next',), successful_worker, 42)
        self.assertEqual(second['status'], 'queued')
        self.assertEqual(second['queue_position'], 1)
        failed = wait_done(queue, first['job_id'])
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('was stopped', failed['error'])
        completed = wait_done(queue, second['job_id'])
        self.assertEqual(completed['status'], 'completed', completed)
        self.assertEqual(completed['result'], {'value': 42})
        self.assertFalse(queue.status()['running'])
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)

    def test_fifo_dedup_and_capacity_without_cooldown(self):
        release = Event()
        started = Event()
        order = []
        def worker(value, progress):
            order.append(value)
            started.set()
            if value == 1:
                release.wait(5)
            return value
        queue = JobQueue(runner=immediate_runner, max_pending=1)
        try:
            first = queue.submit(('one',), worker, 1)
            self.assertTrue(started.wait(2))
            self.assertEqual(queue.submit(('one',), worker, 1)['job_id'], first['job_id'])
            second = queue.submit(('two',), worker, 2)
            self.assertEqual(queue.submit(('two',), worker, 2)['job_id'], second['job_id'])
            with self.assertRaises(HTTPException) as ctx:
                queue.submit(('three',), worker, 3)
            self.assertEqual(ctx.exception.status_code, 429)
        finally:
            release.set()
        self.assertEqual(wait_done(queue, second['job_id'])['result'], 2)
        third = queue.submit(('three',), worker, 3)
        self.assertEqual(wait_done(queue, third['job_id'])['result'], 3)
        self.assertEqual(order, [1, 2, 3])

    def test_failure_allows_immediate_retry(self):
        def fail(value, progress):
            raise ScanError('Provider unavailable')
        queue = JobQueue(runner=immediate_runner)
        first = queue.submit(('one',), fail, {})
        self.assertEqual(wait_done(queue, first['job_id'])['error'], 'Provider unavailable')
        retry = queue.submit(('one',), successful_worker, {})
        self.assertNotEqual(first['job_id'], retry['job_id'])
        self.assertEqual(wait_done(queue, retry['job_id'])['status'], 'completed')

    def test_completed_results_expire(self):
        queue = JobQueue(runner=immediate_runner)
        first = queue.submit(('one',), successful_worker, 2)
        self.assertEqual(wait_done(queue, first['job_id'])['result'], {'value': 2})
        self.assertEqual(queue.submit(('one',), successful_worker, None)['job_id'], first['job_id'])
        queue.ttl = -1
        with self.assertRaises(HTTPException):
            queue.get(first['job_id'])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.queue = JobQueue(runner=lambda *args: {'results': []})
        app = FastAPI()
        install_hosting(app, queue=self.queue)
        self.client = TestClient(app)
        self.coll = mongomock.MongoClient(tz_aware=True).db.daily_runs
        self.headers = {'Authorization': 'Bearer test-secret'}

    def test_scheduler_requires_secret(self):
        with patch.dict('os.environ', {'CRON_SECRET': 'test-secret'}):
            for path, method in [('/api/admin/daily-run', self.client.post),
                                 ('/api/admin/daily-plan', self.client.get)]:
                self.assertEqual(method(path).status_code, 401)
                self.assertEqual(method(path, headers={'Authorization': 'Bearer wrong'}).status_code, 401)
            body = dict(index='NIFTY50', setup='setup_1', results=ROWS,
                        expected_symbols=['AAA'], captured_at=datetime.now(timezone.utc).isoformat())
            self.assertEqual(self.client.post('/api/admin/daily-snapshot', json=body).status_code, 401)

    def test_old_cron_endpoint_cannot_take_scan_slot(self):
        with patch.dict('os.environ', {'CRON_SECRET': 'test-secret'}):
            response = self.client.post('/api/admin/daily-run', headers=self.headers)
        self.assertEqual(response.status_code, 410)
        self.assertFalse(self.queue.status()['running'])

    def test_snapshot_upload_is_independent_of_active_scan_and_idempotent(self):
        release = Event()
        self.queue.runner = immediate_runner
        active = self.queue.submit(('busy',), lambda p, cb: release.wait(5), {})
        body = dict(index='NIFTY50', setup='setup_1', results=ROWS,
                    expected_symbols=['AAA', 'BBB'], captured_at=datetime.now(timezone.utc).isoformat())
        try:
            with patch.dict('os.environ', {'CRON_SECRET': 'test-secret', 'SNAPSHOT_INDEXES': 'NIFTY50'}), \
                 patch('app.hosting.collection', return_value=self.coll):
                for _ in range(2):
                    response = self.client.post('/api/admin/daily-snapshot', headers=self.headers, json=body)
                    self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(self.coll.count_documents({}), 1)
                plan = self.client.get('/api/admin/daily-plan', headers=self.headers).json()
                self.assertEqual(len(plan['pending']), 8)
                self.assertNotIn({'index': 'NIFTY50', 'setup': 'setup_1'}, plan['pending'])
                saved = self.client.get('/api/history/' + response.json()['run_date']).json()
                self.assertEqual(saved['results'], ROWS)
                self.assertEqual(saved['missing_symbols'], ['BBB'])
                self.assertEqual(self.queue.get(active['job_id'])['status'], 'running')
        finally:
            release.set()
            wait_done(self.queue, active['job_id'])

    def test_invalid_snapshot_is_rejected(self):
        body = dict(index='NIFTY50', setup='setup_1', results=ROWS,
                    expected_symbols=['AAA'], captured_at=datetime.now(timezone.utc).isoformat())
        variants = [
            dict(body, results=[]), dict(body, results=ROWS * 2),
            dict(body, expected_symbols=['BBB']), dict(body, setup='setup_2'),
            dict(body, captured_at='2026-01-01T00:00:00Z'),
            dict(body, captured_at='2099-01-01T00:00:00Z'),
            dict(body, captured_at='2026-10-26T12:00:00')]
        with patch.dict('os.environ', {'CRON_SECRET': 'test-secret'}):
            for invalid in variants:
                response = self.client.post('/api/admin/daily-snapshot', headers=self.headers, json=invalid)
                self.assertIn(response.status_code, (400, 422), response.text)

    def test_validation_rejects_unknown_index_and_setup(self):
        for body in ({'index': 'unknown'}, {'setup': '../main'}, {'near_match_score': 101}, {'mode': 'bad'}):
            self.assertIn(self.client.post('/api/runs', json=body).status_code, (400, 422))

    def test_post_starts_pollable_scan(self):
        response = self.client.post('/api/runs', json={'index': 'NIFTY50'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.client.get('/api/runs/' + response.json()['job_id']).status_code, 200)
        wait_done(self.queue, response.json()['job_id'])
        self.assertEqual(self.client.get('/api/scanner/status').json()['queued'], 0)

    def test_history_without_database_is_explicit(self):
        with patch.dict('os.environ', {'MONGODB_URI': ''}):
            response = self.client.get('/api/history')
        self.assertEqual(response.status_code, 503)


if __name__ == '__main__':
    unittest.main()
