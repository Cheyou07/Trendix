"""Per-ticker Yahoo reads: avoid yf.download's process-global batch bookkeeping."""
import hashlib
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import yfinance as yf

from .base import MarketDataProvider
from ..errors import ScanError
from ..universe import get_index_symbols

logger = logging.getLogger(__name__)


class YFinanceProvider(MarketDataProvider):
    def __init__(self, cache_dir=None, cache_ttl=300):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else Path(__file__).parents[1] / 'data' / 'prices'
        self.cache_ttl = cache_ttl

    def get_historical_daily(self, symbol: str, years: int = 6) -> pd.DataFrame:
        ticker = symbol if symbol.endswith('.NS') else f'{symbol}.NS'
        cache_path = self.cache_dir / (hashlib.sha256(f'{ticker}:{years}'.encode()).hexdigest() + '.pkl')
        try:
            if time.time() - cache_path.stat().st_mtime < self.cache_ttl:
                return pd.read_pickle(cache_path)
        except (OSError, ValueError, EOFError):
            pass
        try:
            df = yf.Ticker(ticker).history(period=f'{years}y', interval='1d',
                                           auto_adjust=True, actions=False, timeout=15,
                                           raise_errors=True)
        except Exception as exc:
            logger.warning('Yahoo fetch failed for %s: %s', ticker, exc)
            raise ScanError(f'Market data is unavailable for {symbol}. Yahoo may be rate-limiting the server.') from exc
        if df is None or df.empty:
            raise ScanError(f'Yahoo returned no price data for {symbol}.')
        df = df.rename(columns=str.lower)[['open', 'high', 'low', 'close', 'volume']].dropna(subset=['close'])
        if df.empty:
            raise ScanError(f'Yahoo returned no usable prices for {symbol}.')
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.index.name = 'date'
        temp_path = None
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.cache_dir, delete=False) as tmp:
                temp_path = tmp.name
                df.to_pickle(tmp)
            os.replace(temp_path, cache_path)
        except OSError:
            logger.warning('Could not cache prices for %s', ticker)
        finally:
            try:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                logger.warning('Could not remove temporary price cache')
        return df

    def get_historical_daily_batch(self, symbols: list[str], years: int = 6) -> dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        result = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(self.get_historical_daily, s, years): s for s in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result[symbol] = future.result()
                except Exception as exc:
                    logger.warning('Skipping %s: %s', symbol, exc)
        return result

    def get_symbols(self, index_name: str) -> list[str]:
        return get_index_symbols(index_name)
