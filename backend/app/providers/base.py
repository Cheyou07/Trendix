"""
Abstract base class for market data providers.

The rest of the system (indicators, conditions, setup engine, scanner)
never talks to yfinance / NSE / a broker API directly. It only talks to
this interface. Swapping the free yfinance provider for a paid broker
feed later means writing ONE new class - nothing else changes.
"""
from abc import ABC, abstractmethod
import pandas as pd


class MarketDataProvider(ABC):
    @abstractmethod
    def get_historical_daily(self, symbol: str, years: int = 6) -> pd.DataFrame:
        """
        Return a DataFrame indexed by date with columns:
        open, high, low, close, volume
        Must return enough history to compute a 200-period daily EMA
        and a 3-month-lookback monthly EMA trend (so several years).
        """
        raise NotImplementedError

    def get_historical_daily_batch(self, symbols: list[str], years: int = 6) -> dict:
        """
        Optional: fetch many symbols in one call for large universes.
        Default implementation just loops the single-symbol method -
        providers that support real batch requests (like yfinance)
        should override this for real efficiency gains.
        """
        result = {}
        for s in symbols:
            try:
                result[s] = self.get_historical_daily(s, years)
            except Exception:
                continue
        return result

    @abstractmethod
    def get_symbols(self, index_name: str) -> list[str]:
        """Return the list of ticker symbols belonging to an index universe."""
        raise NotImplementedError
