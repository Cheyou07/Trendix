import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from app.errors import ScanError
from app.jsonutils import sanitize
from app.providers.yfinance_provider import YFinanceProvider
from app.scanner import scan_universe, scan_universe_all_setups
from app.setup_engine import list_setups, load_setup


def prices():
    values = np.linspace(100, 250, 1500) + np.sin(np.arange(1500) / 10) * 10
    return pd.DataFrame(dict(open=values, high=values + 2, low=values - 2,
                             close=values + 1, volume=np.full(1500, 10000)),
                        index=pd.date_range('2020-01-01', periods=1500, freq='B'))


class ProviderTests(unittest.TestCase):
    def test_overlapping_chart_and_batch_use_independent_histories_and_cache(self):
        barrier = Barrier(3)
        raw = prices().rename(columns=str.title)
        def ticker_history(**kwargs):
            self.assertEqual(kwargs['timeout'], 15)
            barrier.wait(timeout=5)
            return raw.copy()
        with tempfile.TemporaryDirectory() as directory, \
             patch('app.providers.yfinance_provider.yf.download', side_effect=AssertionError('Global batch downloader used')), \
             patch('app.providers.yfinance_provider.yf.Ticker') as ticker:
            ticker.return_value.history.side_effect = ticker_history
            provider = YFinanceProvider(cache_dir=directory)
            with ThreadPoolExecutor(max_workers=2) as pool:
                scan = pool.submit(provider.get_historical_daily_batch, ['AAA', 'BBB'])
                chart = pool.submit(provider.get_historical_daily, 'CCC')
                self.assertEqual(set(scan.result(timeout=10)), {'AAA', 'BBB'})
                self.assertEqual(len(chart.result(timeout=10)), 1500)
            self.assertEqual(ticker.return_value.history.call_count, 3)
            self.assertEqual(len(provider.get_historical_daily('AAA')), 1500)
            self.assertEqual(ticker.return_value.history.call_count, 3)
            provider.cache_ttl = -1
            ticker.return_value.history.side_effect = None
            ticker.return_value.history.return_value = raw
            provider.get_historical_daily('AAA')
            self.assertEqual(ticker.return_value.history.call_count, 4)


class ScannerTests(unittest.TestCase):
    def test_all_failed_batch_stops_early_instead_of_empty_success(self):
        for batch in (Mock(return_value={}), Mock(side_effect=RuntimeError('Rate limited'))):
            provider = Mock(get_historical_daily_batch=batch)
            for scanner, config in ((scan_universe, load_setup('setup_1')),
                                    (scan_universe_all_setups, [load_setup('setup_1')])):
                batch.reset_mock()
                with self.assertRaisesRegex(ScanError, 'no usable market data'):
                    scanner(provider, [str(i) for i in range(100)], config)
                self.assertEqual(batch.call_count, 1)

    def test_real_nine_setup_engine_completes_and_reports_partial_coverage(self):
        provider = Mock()
        provider.get_historical_daily_batch.return_value = {'AAA': prices()}
        configs = [load_setup(s['id']) for s in list_setups()]
        progress = []
        stats = {}
        result = scan_universe_all_setups(provider, ['AAA', 'MISSING'], configs,
                                          progress_callback=progress.append, stats=stats)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['setups']), 9)
        self.assertEqual(stats, dict(total=2, evaluated=1, failed=1, missing_symbols=['MISSING']))
        self.assertEqual(progress[-1]['done'], 2)
        self.assertEqual(progress[-1]['phase'], 'completed')
        json.dumps(sanitize(result), allow_nan=False)

    def test_single_setup_zero_matches_is_valid_when_stocks_were_evaluated(self):
        provider = Mock()
        provider.get_historical_daily_batch.return_value = {'AAA': prices()}
        stats = {}
        with patch('app.scanner.evaluate_setup', return_value={'qualified': False, 'score': 0}):
            results = scan_universe(provider, ['AAA'], load_setup('setup_1'), stats=stats)
        self.assertEqual(results, [])
        self.assertEqual(stats['evaluated'], 1)
        self.assertEqual(stats['failed'], 0)
