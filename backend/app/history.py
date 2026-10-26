"""One immutable snapshot per IST date, index and setup; rolling seven calendar days."""
import gzip
import json
import os
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache

from fastapi import HTTPException
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

IST = timezone(timedelta(hours=5, minutes=30))


def snapshot_dates(now):
    day = now.astimezone(IST).date()
    # Today plus six previous IST dates, rather than seven trading sessions.
    expires = datetime.combine(day + timedelta(days=7), time.min, IST)
    return day.isoformat(), expires.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def collection():
    uri = os.getenv('MONGODB_URI')
    if not uri:
        raise HTTPException(503, 'Daily history is not configured yet.')
    client = MongoClient(uri, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000,
                         socketTimeoutMS=10000, tz_aware=True)
    coll = client[os.getenv('MONGODB_DATABASE', 'nifty_scanner')]['daily_runs']
    coll.create_index([('run_date', 1), ('index', 1), ('setup_id', 1)], unique=True)
    coll.create_index('expires_at', expireAfterSeconds=0)
    return coll


class HistoryStore:
    def __init__(self, coll):
        self.coll = coll

    def save(self, index, setup, results, expected_symbols, now):
        day, expires = snapshot_dates(now)
        key = {'run_date': day, 'index': index, 'setup_id': setup['id']}
        missing = sorted(set(expected_symbols) - {r['symbol'] for r in results})
        document = dict(key, setup_name=setup['name'], captured_at=now,
                        expires_at=expires, count=len(results),
                        expected_count=len(expected_symbols), missing_symbols=missing,
                        complete=not missing, results_gzip=gzip.compress(
                            json.dumps(results, allow_nan=False).encode('utf-8')))
        try:
            self.coll.update_one(key, {'$setOnInsert': document}, upsert=True)
        except DuplicateKeyError:
            # Another process won the unique-key race; preserve its first run.
            pass

    def list(self, index, setup_id, now):
        return list(self.coll.find(
            {'index': index, 'setup_id': setup_id, 'expires_at': {'$gt': now}},
            {'_id': 0, 'results_gzip': 0}).sort('run_date', -1).limit(7))

    def get(self, index, setup_id, run_date, now):
        doc = self.coll.find_one({'index': index, 'setup_id': setup_id,
                                 'run_date': run_date, 'expires_at': {'$gt': now}},
                                {'_id': 0})
        if doc is None:
            raise HTTPException(404, 'No saved run for this date, or it has expired.')
        doc['results'] = json.loads(gzip.decompress(doc.pop('results_gzip')))
        return doc
