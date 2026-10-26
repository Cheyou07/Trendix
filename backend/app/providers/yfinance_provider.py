"""
Free market data provider backed by yfinance (Yahoo Finance).

No API key required. Includes a BATCH download method for scanning
large universes (NIFTY200/500) efficiently - yfinance can fetch many
tickers in one call with internal threading, which is far faster and
gentler on Yahoo's servers than looping single-symbol downloads with
per-request delays.
"""
import pandas as pd
import yfinance as yf
from .base import MarketDataProvider
from ..universe import get_index_symbols


class YFinanceProvider(MarketDataProvider):
    def get_historical_daily(self, symbol: str, years: int = 6) -> pd.DataFrame:
        ticker = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
        df = yf.download(
            ticker,
            period=f"{years}y",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            raise ValueError(f"No data returned for {ticker}")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df.index.name = "date"
        return df

    def get_historical_daily_batch(self, symbols: list[str], years: int = 6) -> dict[str, pd.DataFrame]:
        """
        Fetch many symbols in ONE yfinance call (internally threaded).
        Returns {symbol: DataFrame}; symbols with no usable data are
        simply omitted from the result rather than raising.
        """
        if not symbols:
            return {}

        tickers = [s if s.endswith(".NS") else f"{s}.NS" for s in symbols]
        raw = yf.download(
            tickers,
            period=f"{years}y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )

        result = {}
        for symbol, ticker in zip(symbols, tickers):
            try:
                if len(tickers) == 1:
                    df = raw
                    if isinstance(df.columns, pd.MultiIndex):
                        df = df.copy()
                        df.columns = df.columns.get_level_values(0)
                else:
                    if ticker not in raw.columns.get_level_values(0):
                        continue
                    df = raw[ticker]

                df = df.dropna(how="all")
                if df.empty:
                    continue

                df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
                df = df.dropna(subset=["close"])
                if df.empty:
                    continue
                df.index.name = "date"
                result[symbol] = df
            except Exception:
                continue  # skip this symbol, the scanner logs it as a failure

        return result

    def get_symbols(self, index_name: str) -> list[str]:
        return get_index_symbols(index_name)
