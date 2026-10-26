import time
import unittest
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import patch

import mongomock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.history import HistoryStore, snapshot_dates
from app.hosting import install_hosting, run_daily
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

    def test_daily_run_fetches_union_once_and_is_idempotent(self):
        rows = [dict(symbol='AAA', setups=ROWS),
                dict(symbol='BBB', setups=[dict(ROWS[0], symbol='BBB')])]
        with patch('app.hosting.collection', return_value=self.coll), \
             patch('app.hosting.list_setups', return_value=[SETUP]), \
             patch('app.hosting.get_index_symbols', side_effect=lambda i: ['AAA'] if i == 'NIFTY50' else ['AAA', 'BBB']), \
             patch('app.hosting.load_setup', return_value=SETUP), \
             patch('app.hosting.scan_universe_all_setups', return_value=rows) as scanner:
            run_daily(['NIFTY50', 'NIFTYBANK'], lambda x: x)
            repeat = run_daily(['NIFTY50', 'NIFTYBANK'], lambda x: x)
        self.assertTrue(repeat['already_saved'])
        self.assertEqual(scanner.call_count, 1)
        self.assertEqual(scanner.call_args.args[1], ['AAA', 'BBB'])
        self.assertEqual(self.coll.count_documents({}), 2)

    def test_failed_index_does_not_save_an_empty_success(self):
        with patch('app.hosting.collection', return_value=self.coll), \
             patch('app.hosting.list_setups', return_value=[SETUP]), \
             patch('app.hosting.get_index_symbols', return_value=['AAA']), \
             patch('app.hosting.load_setup', return_value=SETUP), \
             patch('app.hosting.scan_universe_all_setups', return_value=[]):
            with self.assertRaises(RuntimeError):
                run_daily(['NIFTY50'], lambda x: x)
        self.assertEqual(self.coll.count_documents({}), 0)


class QueueTests(unittest.TestCase):
    def test_duplicate_shares_work_and_busy_scan_is_rejected(self):
        release = Event()
        queue = JobQueue()
        try:
            first = queue.submit(('one',), lambda: release.wait(5))
            self.assertEqual(first['job_id'], queue.submit(('one',), lambda: None)['job_id'])
            with self.assertRaises(HTTPException) as ctx:
                queue.submit(('two',), lambda: None)
            self.assertEqual(ctx.exception.status_code, 429)
        finally:
            release.set()

    def test_completed_jobs_reuse_result_then_expire(self):
        queue = JobQueue(ttl=300)
        first = queue.submit(('one',), lambda: {'count': 2})
        deadline = time.monotonic() + 2
        while queue.get(first['job_id'])['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(queue.get(first['job_id'])['result'], {'count': 2})
        self.assertEqual(queue.submit(('one',), lambda: None)['job_id'], first['job_id'])
        queue.ttl = -1
        with self.assertRaises(HTTPException):
            queue.get(first['job_id'])


class ApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        install_hosting(app, lambda *a: {'results': []}, lambda *a: {'results': []}, lambda x: x)
        self.client = TestClient(app)

    def test_scheduler_requires_secret(self):
        with patch.dict('os.environ', {'CRON_SECRET': 'test-secret'}):
            self.assertEqual(self.client.post('/api/admin/daily-run').status_code, 401)
            self.assertEqual(self.client.post('/api/admin/daily-run', headers={'Authorization': 'Bearer wrong'}).status_code, 401)

    def test_validation_rejects_unknown_index_and_setup(self):
        for body in ({'index': 'unknown'}, {'setup': '../main'}, {'near_match_score': 101}, {'mode': 'bad'}):
            self.assertIn(self.client.post('/api/runs', json=body).status_code, (400, 422))

    def test_post_starts_pollable_scan(self):
        response = self.client.post('/api/runs', json={'index': 'NIFTY50'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.client.get('/api/runs/' + response.json()['job_id']).status_code, 200)

    def test_history_without_database_is_explicit(self):
        with patch.dict('os.environ', {'MONGODB_URI': ''}):
            response = self.client.get('/api/history')
        self.assertEqual(response.status_code, 503)


if __name__ == '__main__':
    unittest.main()
