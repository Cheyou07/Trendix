import logging
import time
from datetime import datetime, timezone

from .result_cache import MAX_AGE_SECONDS, fingerprint

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


def _evaluate_symbols(provider, symbols, configs, cache_store, progress_callback, stats,
                      result_cache=None, cache_configs=None, use_cache=True):
    output = {}
    failed = []
    total = len(symbols)
    stats = stats if stats is not None else {}
    all_configs = cache_configs or configs
    wanted = {cfg['id'] for cfg in configs}
    signature = fingerprint(all_configs) if result_cache is not None else None
    cache_hits = 0
    fetched_times = []
    cached = {}
    if result_cache is not None and use_cache:
        if progress_callback:
            progress_callback(dict(phase='cache', done=0, total=total))
        cached = result_cache.read(symbols, signature, datetime.now(timezone.utc))

    def report(phase, done):
        stats.update(total=total, evaluated=len(output), failed=len(failed), missing_symbols=failed[:])
        if result_cache is not None:
            stats['cache'] = dict(reused_stocks=cache_hits, recalculated_stocks=len(output) - cache_hits,
                                  max_age_seconds=MAX_AGE_SECONDS, bypassed=not use_cache,
                                  available=result_cache.available,
                                  oldest_price_fetch=min(fetched_times).isoformat() if fetched_times else None,
                                  newest_price_fetch=max(fetched_times).isoformat() if fetched_times else None)
        if progress_callback:
            progress_callback(dict(phase=phase, done=done, total=total,
                                   evaluated=len(output), failed=len(failed), reused=cache_hits))

    for start in range(0, total, CHUNK_SIZE):
        chunk = symbols[start:start + CHUNK_SIZE]
        hits = {}
        now = datetime.now(timezone.utc)
        for symbol in chunk:
            entry = cached.get(symbol)
            if entry is not None and entry['expires_at'] > now:
                rows = entry['rows']
                if (len(rows) == len(all_configs)
                        and {r.get('setup_id') for r in rows} == {c['id'] for c in all_configs}
                        and all(r.get('symbol') == symbol for r in rows)):
                    hits[symbol] = entry
        missing = [s for s in chunk if s not in hits]
        fetched_at = datetime.now(timezone.utc)
        batch = {}
        if missing:
            report('fetching', start)
            try:
                batch = provider.get_historical_daily_batch(missing)
            except Exception:
                logger.exception("Batch fetch failed")
            if start == 0 and not cached and not any(
                    s in batch and batch[s] is not None and not batch[s].empty for s in missing):
                raise ScanError("Yahoo returned no usable market data for the first batch. "
                                "The data provider may be unavailable or rate-limiting this server. "
                                "The scan was stopped; please retry later.")
        computed = {}
        for offset, symbol in enumerate(chunk):
            if symbol in hits:
                entry = hits[symbol]
                output[symbol] = [r for r in entry['rows'] if r['setup_id'] in wanted]
                cache_hits += 1
                fetched_times.append(entry['fetched_at'])
                report('cached', start + offset + 1)
                continue
            daily_raw = batch.get(symbol)
            try:
                if daily_raw is None or daily_raw.empty:
                    raise ScanError("No price data")
                tf_data = build_timeframe_data(daily_raw)
                if cache_store is not None:
                    cache_store[symbol] = (tf_data, daily_raw)
                rows = []
                for cfg in all_configs:
                    row = evaluate_setup(symbol, cfg, tf_data)
                    row.update(data_as_of=daily_raw.index[-1].strftime("%Y-%m-%d"),
                               price_fetched_at=fetched_at.isoformat(),
                               setup_id=cfg['id'], setup_name=cfg['name'],
                               direction=cfg.get('direction', 'bullish'))
                    rows.append(row)
                computed[symbol] = rows
                output[symbol] = [r for r in rows if r['setup_id'] in wanted]
                fetched_times.append(fetched_at)
            except Exception as exc:
                logger.warning("Skipping %s: %s", symbol, exc)
                failed.append(symbol)
            report('evaluating', start + offset + 1)
        if result_cache is not None:
            result_cache.write(computed, signature, fetched_at)
        if missing and start + CHUNK_SIZE < total:
            time.sleep(CHUNK_DELAY_SECONDS)
    if not output:
        raise ScanError("No stocks could be evaluated. Check the server logs for market-data or setup errors.")
    report('completed', total)
    return output


def scan_universe(provider, symbols: list[str], setup_config: dict,
                  include_near_matches: bool = True, near_match_score: float = 70.0,
                  progress_callback=None, cache_store: dict = None, stats=None,
                  result_cache=None, cache_configs=None, use_cache=True) -> list[dict]:
    evaluated = _evaluate_symbols(provider, symbols, [setup_config], cache_store, progress_callback, stats,
                                  result_cache, cache_configs, use_cache)
    results = [rows[0] for rows in evaluated.values()
               if rows[0]['qualified'] or (include_near_matches and rows[0]['score'] >= near_match_score)]
    results.sort(key=lambda r: (not r["qualified"], -r["score"]))
    return results


def scan_universe_all_setups(provider, symbols: list[str], setup_configs: list[dict],
                             cache_store: dict = None, progress_callback=None, stats=None,
                             result_cache=None, cache_configs=None, use_cache=True) -> list[dict]:
    """Fetch and build indicators once per stock, then evaluate every selected setup."""
    evaluated = _evaluate_symbols(provider, symbols, setup_configs, cache_store, progress_callback, stats,
                                  result_cache, cache_configs, use_cache)
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
