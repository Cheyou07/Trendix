"""Shared, disposable evaluations in Atlas; never a substitute for fresh market data."""
import gzip
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

from pymongo import MongoClient, ReplaceOne, timeout
from pymongo.errors import PyMongoError

from .jsonutils import sanitize

logger = logging.getLogger(__name__)
MAX_AGE_SECONDS = 15 * 60


@lru_cache(maxsize=1)
def engine_signature():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for filename in ('scanner.py', 'indicators.py', 'setup_engine.py',
                     'providers/yfinance_provider.py', 'result_cache.py'):
        # Normalize Git line endings so local and Linux deployments agree.
        digest.update((root / filename).read_text(encoding='utf-8').encode())
    for dependency in ('pandas', 'numpy', 'yfinance'):
        digest.update(f'{dependency}:{version(dependency)}'.encode())
    return digest.hexdigest()


def fingerprint(configs):
    serialized = json.dumps(sorted(configs, key=lambda c: c['id']), sort_keys=True,
                            separators=(',', ':'), allow_nan=False)
    return hashlib.sha256((engine_signature() + serialized).encode()).hexdigest()


class ResultCache:
    def __init__(self, coll=None):
        self.coll = coll
        self.client = None
        self.available = coll is not None or bool(os.getenv('MONGODB_URI'))

    def _collection(self):
        if self.coll is None:
            self.client = MongoClient(os.environ['MONGODB_URI'], tz_aware=True,
                                      serverSelectionTimeoutMS=1500, connectTimeoutMS=1500,
                                      socketTimeoutMS=2000)
            self.coll = self.client[os.getenv('MONGODB_DATABASE', 'nifty_scanner')]['scan_cache']
            self.coll.create_index('expires_at', expireAfterSeconds=0)
        return self.coll

    def _disable(self):
        # Fail open once per scan, without leaking a connection string to the UI.
        logger.warning('Shared result cache unavailable; continuing with fresh calculations.')
        self.available = False

    def read(self, symbols, signature, now):
        if not self.available:
            return {}
        try:
            with timeout(3):
                docs = list(self._collection().find({
                    '_id': {'$in': [f'{signature}:{s}' for s in symbols]},
                    'expires_at': {'$gt': now},
                    'fetched_at': {'$gte': now - timedelta(seconds=MAX_AGE_SECONDS), '$lte': now},
                }))
            results = {}
            for doc in docs:
                try:
                    doc['rows'] = json.loads(gzip.decompress(doc.pop('results_gzip')))
                    if not isinstance(doc['rows'], list) or not all(isinstance(r, dict) for r in doc['rows']):
                        continue
                    if not all(isinstance(r.get('qualified'), bool)
                               and isinstance(r.get('score'), (int, float))
                               and isinstance(r.get('setup_id'), str)
                               and isinstance(r.get('symbol'), str) for r in doc['rows']):
                        continue
                    results[doc['symbol']] = doc
                except (ValueError, KeyError, OSError, EOFError):
                    logger.warning('Ignoring an unreadable shared cache entry.')
            return results
        except PyMongoError:
            self._disable()
            return {}

    def write(self, rows_by_symbol, signature, fetched_at):
        if not self.available or not rows_by_symbol:
            return
        expires = fetched_at + timedelta(seconds=MAX_AGE_SECONDS)
        if expires <= datetime.now(timezone.utc):
            return
        operations = []
        for symbol, rows in rows_by_symbol.items():
            key = f'{signature}:{symbol}'
            document = dict(_id=key, symbol=symbol, fingerprint=signature,
                            fetched_at=fetched_at, expires_at=expires,
                            results_gzip=gzip.compress(json.dumps(sanitize(rows), allow_nan=False).encode()))
            operations.append(ReplaceOne({'_id': key}, document, upsert=True))
        try:
            with timeout(3):
                self._collection().bulk_write(operations, ordered=False)
        except PyMongoError:
            self._disable()

    def close(self):
        if self.client is not None:
            self.client.close()
