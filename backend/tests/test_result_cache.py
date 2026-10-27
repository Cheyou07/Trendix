import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import mongomock
from pymongo.errors import ServerSelectionTimeoutError

from app.result_cache import MAX_AGE_SECONDS, ResultCache, fingerprint
from app.scanner import scan_universe, scan_universe_all_setups
from test_scanner import prices


CONFIGS = [dict(id='setup_1', name='First', direction='bullish'),
           dict(id='setup_2', name='Second', direction='bearish')]


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.coll = mongomock.MongoClient(tz_aware=True).db.scan_cache
        self.cache = ResultCache(self.coll)
        self.now = datetime.now(timezone.utc)
        # mongomock lacks PyMongo's optional sort argument. Production uses
        # PyMongo directly; adapt only the test double, asserting no sort used.
        original = mongomock.collection.BulkOperationBuilder.add_replace
        def add_replace(builder, selector, doc, upsert, collation=None, hint=None, sort=None):
            assert sort is None
            return original(builder, selector, doc, upsert, collation, hint)
        self.compat = patch.object(mongomock.collection.BulkOperationBuilder, 'add_replace', add_replace)
        self.compat.start()
        self.addCleanup(self.compat.stop)
        self.provider = Mock()
        self.provider.get_historical_daily_batch.side_effect = lambda symbols: {s: prices() for s in symbols}

    @staticmethod
    def evaluate(symbol, config, data):
        return dict(symbol=symbol, qualified=False, score=60 if config['id'] == 'setup_1' else 80)

    def scan(self, symbols, setup=0, threshold=70, use_cache=True, stats=None, configs=None):
        configs = configs or CONFIGS
        with patch('app.scanner.build_timeframe_data', return_value={}), \
             patch('app.scanner.evaluate_setup', side_effect=self.evaluate):
            return scan_universe(self.provider, symbols, configs[setup], near_match_score=threshold,
                                 result_cache=self.cache, cache_configs=configs,
                                 use_cache=use_cache, stats=stats)

    def test_reuses_nonmatches_for_lower_threshold_other_setup_and_overlapping_index(self):
        self.assertEqual(self.scan(['AAA', 'BBB']), [])  # Scores below 70 still cached.
        self.provider.get_historical_daily_batch.reset_mock()
        stats = {}
        lower = self.scan(['AAA', 'BBB'], threshold=50, stats=stats)
        self.assertEqual(len(lower), 2)
        self.assertEqual(stats['cache']['reused_stocks'], 2)
        self.provider.get_historical_daily_batch.assert_not_called()
        other = self.scan(['BBB', 'CCC'], setup=1)
        self.assertEqual({r['symbol'] for r in other}, {'BBB', 'CCC'})
        self.provider.get_historical_daily_batch.assert_called_once_with(['CCC'])
        self.assertEqual(self.coll.count_documents({}), 3)

    def test_all_setups_can_reuse_single_setup_warmup_without_fetch_or_evaluation(self):
        self.scan(['AAA'])
        stats = {}
        with patch('app.scanner.build_timeframe_data', side_effect=AssertionError('Should reuse')), \
             patch('app.scanner.evaluate_setup', side_effect=AssertionError('Should reuse')):
            result = scan_universe_all_setups(self.provider, ['AAA'], CONFIGS, result_cache=self.cache, stats=stats)
        self.assertEqual(len(result[0]['setups']), 2)
        self.assertEqual(stats['cache']['reused_stocks'], 1)

    def test_expired_records_are_not_used_even_before_ttl_deletes_them(self):
        self.scan(['AAA'])
        self.coll.update_many({}, {'$set': {'expires_at': self.now - timedelta(seconds=1)}})
        self.assertEqual(self.coll.count_documents({}), 1)
        self.provider.get_historical_daily_batch.reset_mock()
        stats = {}
        self.scan(['AAA'], stats=stats)
        self.provider.get_historical_daily_batch.assert_called_once_with(['AAA'])
        self.assertEqual(stats['cache']['reused_stocks'], 0)

    def test_reuse_does_not_extend_source_age_or_expiry(self):
        self.scan(['AAA'])
        before = self.coll.find_one()
        self.scan(['AAA'])
        after = self.coll.find_one()
        self.assertEqual(before['fetched_at'], after['fetched_at'])
        self.assertEqual(before['expires_at'], after['expires_at'])
        self.assertEqual(after['expires_at'] - after['fetched_at'], timedelta(seconds=MAX_AGE_SECONDS))

    def test_rule_and_engine_changes_invalidate_results(self):
        self.scan(['AAA'])
        self.provider.get_historical_daily_batch.reset_mock()
        changed = copy.deepcopy(CONFIGS)
        changed[0]['conditions'] = ['changed rule']
        self.scan(['AAA'], configs=changed)
        self.provider.get_historical_daily_batch.assert_called_once_with(['AAA'])
        self.provider.get_historical_daily_batch.reset_mock()
        with patch('app.result_cache.engine_signature', return_value='new-engine'):
            self.scan(['AAA'])
        self.provider.get_historical_daily_batch.assert_called_once_with(['AAA'])
        self.assertNotEqual(fingerprint(CONFIGS), fingerprint(changed))

    def test_fresh_scan_bypasses_shared_entries_and_recomputes(self):
        self.scan(['AAA'])
        self.provider.get_historical_daily_batch.reset_mock()
        stats = {}
        self.scan(['AAA'], use_cache=False, stats=stats)
        self.provider.get_historical_daily_batch.assert_called_once_with(['AAA'])
        self.assertEqual(stats['cache']['reused_stocks'], 0)
        self.assertTrue(stats['cache']['bypassed'])

    def test_database_failure_falls_back_once_and_still_returns_results(self):
        unavailable = Mock()
        unavailable.find.side_effect = ServerSelectionTimeoutError('unavailable')
        self.cache = ResultCache(unavailable)
        stats = {}
        result = self.scan(['AAA'], threshold=50, stats=stats)
        self.assertEqual(len(result), 1)
        self.assertFalse(stats['cache']['available'])
        self.assertEqual(stats['cache']['status'], 'timeout')
        unavailable.find.assert_called_once()
        unavailable.bulk_write.assert_not_called()

    def test_corrupt_cache_entry_is_recomputed(self):
        self.scan(['AAA'])
        self.coll.update_many({}, {'$set': {'results_gzip': b'invalid'}})
        self.provider.get_historical_daily_batch.reset_mock()
        self.scan(['AAA'])
        self.provider.get_historical_daily_batch.assert_called_once_with(['AAA'])

    def test_missing_data_is_not_cached_as_a_nonmatch(self):
        self.provider.get_historical_daily_batch.side_effect = lambda symbols: {'AAA': prices()}
        self.scan(['AAA', 'MISSING'])
        self.assertEqual(self.coll.count_documents({}), 1)
        self.assertEqual(self.coll.find_one()['symbol'], 'AAA')

    def test_unavailable_first_stock_does_not_hide_later_cached_results(self):
        self.scan(['BBB'])
        self.provider.get_historical_daily_batch.side_effect = lambda symbols: {}
        stats = {}
        with patch('app.scanner.CHUNK_SIZE', 1), patch('app.scanner.CHUNK_DELAY_SECONDS', 0):
            result = self.scan(['MISSING', 'BBB'], threshold=50, stats=stats)
        self.assertEqual([r['symbol'] for r in result], ['BBB'])
        self.assertEqual(stats['missing_symbols'], ['MISSING'])
        self.assertEqual(stats['cache']['reused_stocks'], 1)

    def test_fresh_api_scan_constructs_price_provider_with_local_reuse_disabled(self):
        from app.main import scan
        with patch('app.main.ResultCache', return_value=self.cache), \
             patch('app.main.YFinanceProvider', return_value=self.provider) as provider_type, \
             patch('app.main.get_index_symbols', return_value=['AAA']), \
             patch('app.main.scan_universe', return_value=[]):
            scan(use_cache=False)
        provider_type.assert_called_once_with(cache_ttl=0)
