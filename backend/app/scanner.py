import logging
import time

from .errors import ScanError
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


def _evaluate_symbols(provider, symbols, configs, cache_store, progress_callback, stats):
    output = {}
    failed = []
    total = len(symbols)
    stats = stats if stats is not None else {}

    def report(phase, done):
        stats.update(total=total, evaluated=len(output), failed=len(failed), missing_symbols=failed[:])
        if progress_callback:
            progress_callback(dict(phase=phase, done=done, total=total,
                                   evaluated=len(output), failed=len(failed)))

    for start in range(0, total, CHUNK_SIZE):
        chunk = symbols[start:start + CHUNK_SIZE]
        report('fetching', start)
        try:
            batch = provider.get_historical_daily_batch(chunk)
        except Exception:
            logger.exception("Batch fetch failed")
            batch = {}
        if start == 0 and not any(s in batch and not batch[s].empty for s in chunk):
            raise ScanError("Yahoo returned no usable market data for the first batch. "
                            "The data provider may be unavailable or rate-limiting this server. "
                            "The scan was stopped; please retry later.")
        for offset, symbol in enumerate(chunk):
            daily_raw = batch.get(symbol)
            try:
                if daily_raw is None or daily_raw.empty:
                    raise ScanError("No price data")
                tf_data = build_timeframe_data(daily_raw)
                if cache_store is not None:
                    cache_store[symbol] = (tf_data, daily_raw)
                rows = []
                for cfg in configs:
                    row = evaluate_setup(symbol, cfg, tf_data)
                    row.update(data_as_of=daily_raw.index[-1].strftime("%Y-%m-%d"),
                               setup_id=cfg['id'], setup_name=cfg['name'],
                               direction=cfg.get('direction', 'bullish'))
                    rows.append(row)
                output[symbol] = rows
            except Exception as exc:
                logger.warning("Skipping %s: %s", symbol, exc)
                failed.append(symbol)
            report('evaluating', start + offset + 1)
        if start + CHUNK_SIZE < total:
            time.sleep(CHUNK_DELAY_SECONDS)
    if not output:
        raise ScanError("No stocks could be evaluated. Check the server logs for market-data or setup errors.")
    report('completed', total)
    return output


def scan_universe(provider, symbols: list[str], setup_config: dict,
                  include_near_matches: bool = True, near_match_score: float = 70.0,
                  progress_callback=None, cache_store: dict = None, stats=None) -> list[dict]:
    evaluated = _evaluate_symbols(provider, symbols, [setup_config], cache_store, progress_callback, stats)
    results = [rows[0] for rows in evaluated.values()
               if rows[0]['qualified'] or (include_near_matches and rows[0]['score'] >= near_match_score)]
    results.sort(key=lambda r: (not r["qualified"], -r["score"]))
    return results


def scan_universe_all_setups(provider, symbols: list[str], setup_configs: list[dict],
                             cache_store: dict = None, progress_callback=None, stats=None) -> list[dict]:
    """Fetch and build indicators once per stock, then evaluate every selected setup."""
    evaluated = _evaluate_symbols(provider, symbols, setup_configs, cache_store, progress_callback, stats)
    output = []
    for symbol, setup_results in evaluated.items():
        qualified_count = sum(1 for r in setup_results if r["qualified"])
        avg_score = sum(r["score"] for r in setup_results) / len(setup_results)
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
