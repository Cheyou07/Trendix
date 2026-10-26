import io
import logging
import math
import traceback
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .providers.yfinance_provider import YFinanceProvider
from .universe import get_index_symbols, list_available_indexes
from .setup_engine import load_setup, list_setups, evaluate_setup
from .scanner import scan_universe, scan_universe_all_setups, build_timeframe_data
import time
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

app = FastAPI(title="NIFTY Multi-Timeframe Setup Scanner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

provider = YFinanceProvider()

def _sanitize(obj):
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


@lru_cache(maxsize=24)
def _fetch_single_timeframe_data(symbol: str, cache_period: int):
    daily_raw = provider.get_historical_daily(symbol)
    return build_timeframe_data(daily_raw), daily_raw


def _get_timeframe_data(symbol: str):
    return _fetch_single_timeframe_data(symbol, int(time.time() // 300))


@app.get("/api/indices")
def get_indices():
    out = []
    for idx in list_available_indexes():
        try:
            count = len(get_index_symbols(idx))
        except Exception as e:
            logger.warning(f"Could not get symbol count for {idx}: {e}")
            count = None
        out.append({"id": idx, "symbol_count": count})
    return out


@app.get("/api/setups")
def get_setups():
    return list_setups()


def scan(index: str = "NIFTY50", setup: str = "setup_1", near_matches: bool = True,
         near_match_score: float = 70.0):
    try:
        symbols = get_index_symbols(index)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if not symbols:
        raise HTTPException(
            502,
            f"Could not load the {index} constituent list right now "
            f"(NSE's site may be temporarily unreachable). Try again shortly, "
            f"or use NIFTY50/NIFTYBANK which don't depend on that fetch.",
        )

    try:
        setup_config = load_setup(setup)
    except ValueError as e:
        raise HTTPException(404, str(e))

    try:
        results = scan_universe(
            provider, symbols, setup_config,
            include_near_matches=near_matches, near_match_score=near_match_score,
        )
    except Exception as e:
        logger.error("Scan failed:\n%s", traceback.format_exc())
        raise HTTPException(
            500,
            f"Scan failed: {e}. If this persists, Yahoo Finance may be "
            f"rate-limiting requests - wait a minute and try again, or "
            f"check your internet connection.",
        )

    return _sanitize({"index": index, "setup": setup_config["name"], "count": len(results), "results": results})


def scan_all(index: str = "NIFTY50", direction: str = "all"):
    """
    Runs every registered setup (optionally filtered to bullish/bearish
    only) against every stock in the universe, fetching each stock's
    data ONCE and reusing it across all setups. Returns stocks ranked by
    how many setups they qualify for, then by average score across all
    setups evaluated - so you can see which stocks match the most
    conditions across your whole setup library, not just one setup.
    """
    try:
        symbols = get_index_symbols(index)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if not symbols:
        raise HTTPException(502, f"Could not load the {index} constituent list right now.")

    all_setups = list_setups()
    if direction in ("bullish", "bearish"):
        all_setups = [s for s in all_setups if s["direction"] == direction]
    setup_configs = [load_setup(s["id"]) for s in all_setups]

    try:
        results = scan_universe_all_setups(provider, symbols, setup_configs)
    except Exception as e:
        logger.error("Scan-all failed:\n%s", traceback.format_exc())
        raise HTTPException(
            500,
            f"Scan failed: {e}. If this persists, Yahoo Finance may be "
            f"rate-limiting requests - wait a minute and try again.",
        )

    return _sanitize({
        "index": index,
        "setups_evaluated": [s["id"] for s in all_setups],
        "count": len(results),
        "results": results,
    })


@app.get("/api/stocks/{symbol}/detail")
def stock_detail(symbol: str, setup: str = "setup_1"):
    setup_config = load_setup(setup)
    try:
        tf_data, _ = _get_timeframe_data(symbol)
    except Exception as e:
        raise HTTPException(404, f"Could not load data for {symbol}: {e}")
    return _sanitize(evaluate_setup(symbol, setup_config, tf_data))


@app.get("/api/stocks/{symbol}/history")
def stock_history(symbol: str, timeframe: str = "daily", bars: int = 180):
    try:
        tf_data, _ = _get_timeframe_data(symbol)
    except Exception as e:
        raise HTTPException(404, f"Could not load data for {symbol}: {e}")

    if timeframe not in tf_data:
        raise HTTPException(400, "timeframe must be daily, weekly, or monthly")

    df = tf_data[timeframe].tail(bars).copy()
    df = df.where(pd.notna(df), None)

    candles = [
        {
            "time": idx.strftime("%Y-%m-%d"),
            "open": round(row["open"], 2),
            "high": round(row["high"], 2),
            "low": round(row["low"], 2),
            "close": round(row["close"], 2),
        }
        for idx, row in df.iterrows()
    ]

    def ema_series(col):
        return [
            {"time": idx.strftime("%Y-%m-%d"), "value": round(row[col], 2)}
            for idx, row in df.iterrows()
            if row[col] is not None
        ]

    return _sanitize({
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": candles,
        "ema": {p: ema_series(f"ema{p}") for p in (5, 13, 26, 50, 200) if f"ema{p}" in df.columns},
    })


@app.get("/api/stocks/{symbol}/download")
def download_symbol(symbol: str, timeframe: str = "daily"):
    try:
        tf_data, _ = _get_timeframe_data(symbol)
    except Exception as e:
        raise HTTPException(404, f"Could not load data for {symbol}: {e}")

    if timeframe not in tf_data:
        raise HTTPException(400, "timeframe must be daily, weekly, or monthly")

    df = tf_data[timeframe]
    buf = io.StringIO()
    df.to_csv(buf)
    buf.seek(0)
    filename = f"{symbol}_{timeframe}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


from .hosting import install_hosting

install_hosting(app, scan, scan_all, _sanitize)
