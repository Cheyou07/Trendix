import logging
import time
from .indicators import compute_all_indicators, resample_ohlcv
from .setup_engine import evaluate_setup

logger = logging.getLogger("scanner")

CHUNK_SIZE = 40
CHUNK_DELAY_SECONDS = 1.5


def build_timeframe_data(daily_raw):
    daily = compute_all_indicators(daily_raw)
    weekly = compute_all_indicators(resample_ohlcv(daily_raw, "W"))
    monthly = compute_all_indicators(resample_ohlcv(daily_raw, "ME"))
    return {"daily": daily, "weekly": weekly, "monthly": monthly}


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def scan_universe(provider, symbols: list[str], setup_config: dict,
                   include_near_matches: bool = True, near_match_score: float = 70.0,
                   progress_callback=None, cache_store: dict = None) -> list[dict]:
    results = []
    failures = []
    chunk_list = list(_chunks(symbols, CHUNK_SIZE))

    for ci, chunk in enumerate(chunk_list):
        try:
            batch = provider.get_historical_daily_batch(chunk)
        except Exception as e:
            logger.warning(f"Batch fetch failed for chunk starting at {chunk[0]}: {e}")
            failures.extend(chunk)
            batch = {}

        for symbol in chunk:
            daily_raw = batch.get(symbol)
            if daily_raw is None or daily_raw.empty:
                failures.append(symbol)
                continue
            try:
                tf_data = build_timeframe_data(daily_raw)
                if cache_store is not None:
                    cache_store[symbol] = (tf_data, daily_raw)
                result = evaluate_setup(symbol, setup_config, tf_data)
                result["data_as_of"] = daily_raw.index[-1].strftime("%Y-%m-%d")
                if result["qualified"] or (include_near_matches and result["score"] >= near_match_score):
                    results.append(result)
            except Exception as e:
                logger.warning(f"Skipping {symbol}: {e}")
                failures.append(symbol)

        if progress_callback:
            progress_callback(min((ci + 1) * CHUNK_SIZE, len(symbols)), len(symbols))

        if ci < len(chunk_list) - 1:
            time.sleep(CHUNK_DELAY_SECONDS)

    if failures:
        logger.info(f"{len(failures)}/{len(symbols)} symbols failed to fetch: {failures[:20]}"
                     f"{'...' if len(failures) > 20 else ''}")

    if len(failures) == len(symbols) and len(symbols) > 0:
        raise RuntimeError(
            f"Could not fetch data for any of {len(symbols)} symbols "
            f"(e.g. {symbols[0]} failed). Check your internet connection "
            f"or wait a minute in case Yahoo Finance is rate-limiting."
        )

    results.sort(key=lambda r: (not r["qualified"], -r["score"]))
    return results


def scan_universe_all_setups(provider, symbols: list[str], setup_configs: list[dict],
                              cache_store: dict = None) -> list[dict]:
    """
    Fetches each symbol's data ONCE per scan (not once per setup) and
    evaluates it against every provided setup config. Returns one entry
    per symbol: {symbol, best, setups: [...]} where 'best' is the setup
    that symbol matched best (ranked by: qualified setups count, then
    average score across all setups it was evaluated against).
    """
    per_symbol_results = {}
    failures = []
    chunk_list = list(_chunks(symbols, CHUNK_SIZE))

    for ci, chunk in enumerate(chunk_list):
        try:
            batch = provider.get_historical_daily_batch(chunk)
        except Exception as e:
            logger.warning(f"Batch fetch failed for chunk starting at {chunk[0]}: {e}")
            failures.extend(chunk)
            batch = {}

        for symbol in chunk:
            daily_raw = batch.get(symbol)
            if daily_raw is None or daily_raw.empty:
                failures.append(symbol)
                continue
            try:
                tf_data = build_timeframe_data(daily_raw)
                if cache_store is not None:
                    cache_store[symbol] = (tf_data, daily_raw)
                setup_results = []
                for cfg in setup_configs:
                    r = evaluate_setup(symbol, cfg, tf_data)
                    r["data_as_of"] = daily_raw.index[-1].strftime("%Y-%m-%d")
                    r["setup_id"] = cfg["id"]
                    r["setup_name"] = cfg["name"]
                    r["direction"] = cfg.get("direction", "bullish")
                    setup_results.append(r)
                per_symbol_results[symbol] = setup_results
            except Exception as e:
                logger.warning(f"Skipping {symbol}: {e}")
                failures.append(symbol)

        if ci < len(chunk_list) - 1:
            time.sleep(CHUNK_DELAY_SECONDS)

    if failures:
        logger.info(f"{len(failures)}/{len(symbols)} symbols failed to fetch")
    if len(failures) == len(symbols) and len(symbols) > 0:
        raise RuntimeError(
            f"Could not fetch data for any of {len(symbols)} symbols. "
            f"Check your internet connection or wait a minute in case "
            f"Yahoo Finance is rate-limiting."
        )

    output = []
    for symbol, setup_results in per_symbol_results.items():
        qualified_count = sum(1 for r in setup_results if r["qualified"])
        avg_score = sum(r["score"] for r in setup_results) / len(setup_results) if setup_results else 0
        best = max(setup_results, key=lambda r: (r["qualified"], r["score"]))
        output.append({
            "symbol": symbol,
            "qualified_setup_count": qualified_count,
            "avg_score": round(avg_score, 1),
            "best_setup_id": best["setup_id"],
            "best_setup_name": best["setup_name"],
            "best_direction": best["direction"],
            "best_score": best["score"],
            "setups": setup_results,
        })

    output.sort(key=lambda r: (-r["qualified_setup_count"], -r["avg_score"]))
    return output
