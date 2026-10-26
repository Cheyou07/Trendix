"""
Index universe manager (System 1 from the design doc).

NIFTY50 / NIFTYBANK stay hard-coded (small, stable, work offline).

NIFTY100 / NIFTY200 / NIFTY500 are fetched LIVE from NSE's own published
constituent CSVs instead of being hand-typed here - a 500-stock list
changes over time and typing it by hand risks going stale or containing
mistakes. The fetched list is cached to a local CSV for 24 hours so a
day of scans only hits NSE's metadata endpoint once, not on every scan.
"""
import io
import time
import logging
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger("universe")

CACHE_DIR = Path(__file__).parent / "data"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL_SECONDS = 24 * 60 * 60  # refresh once a day

NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "BHARTIARTL",
    "ITC", "SBIN", "LT", "HINDUNILVR", "KOTAKBANK", "AXISBANK",
    "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "ASIANPAINT",
    "NESTLEIND", "M&M", "NTPC", "POWERGRID", "HCLTECH",
    "ADANIENT", "TATASTEEL", "WIPRO", "JSWSTEEL", "ONGC", "COALINDIA",
    "BAJAJFINSV", "TECHM", "INDUSINDBK", "GRASIM", "HINDALCO", "CIPLA",
    "DRREDDY", "SBILIFE", "EICHERMOT", "BAJAJ-AUTO", "APOLLOHOSP",
    "DIVISLAB", "BPCL", "BRITANNIA", "HEROMOTOCO", "TATACONSUM",
    "UPL", "SHRIRAMFIN", "ADANIPORTS", "HDFCLIFE",
    # TATAMOTORS / LTIM removed - Yahoo wasn't resolving these as of the
    # last check (likely a corporate action / temporary indexing gap).
]

NIFTY_BANK = [
    "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
    "INDUSINDBK", "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "AUBANK",
    "PNB", "BANKBARODA",
]

NIFTY_500_FALLBACK = NIFTY_50 + [
    "PIDILITIND", "DABUR", "GODREJCP", "MARICO", "COLPAL", "HAVELLS",
    "SIEMENS", "ABB", "DLF", "BANKBARODA", "PNB", "CANBK", "IDFCFIRSTB",
    "FEDERALBNK", "AUBANK", "BANDHANBNK", "PAGEIND", "TRENT", "ZOMATO",
]

STATIC_INDEXES = {"NIFTY50": NIFTY_50, "NIFTYBANK": NIFTY_BANK}

NSE_CSV_URLS = {
    "NIFTY100": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "NIFTY200": "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
    "NIFTY500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
}


def _fetch_nse_constituents(index_key: str) -> list[str]:
    cache_file = CACHE_DIR / f"{index_key.lower()}.csv"

    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_TTL_SECONDS:
        try:
            df = pd.read_csv(cache_file)
            return df["Symbol"].dropna().tolist()
        except Exception:
            pass

    url = NSE_CSV_URLS[index_key]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        symbols = df["Symbol"].dropna().tolist()
        df.to_csv(cache_file, index=False)
        logger.info(f"Fetched {len(symbols)} symbols for {index_key} from NSE")
        return symbols
    except Exception as e:
        logger.warning(f"Could not fetch {index_key} from NSE ({e}); using fallback list")
        return NIFTY_500_FALLBACK if index_key != "NIFTY100" else NIFTY_50


def get_index_symbols(index_name: str) -> list[str]:
    if index_name in STATIC_INDEXES:
        return STATIC_INDEXES[index_name]
    if index_name in NSE_CSV_URLS:
        return _fetch_nse_constituents(index_name)
    raise ValueError(f"Unknown index: {index_name}")


def list_available_indexes() -> list[str]:
    return list(STATIC_INDEXES.keys()) + list(NSE_CSV_URLS.keys())
