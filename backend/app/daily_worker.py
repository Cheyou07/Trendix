"""Compute daily snapshots on the scheduler's machine, independently of web scans."""
from .errors import ScanError
from .jsonutils import sanitize
from .providers.yfinance_provider import YFinanceProvider
from .scanner import scan_universe_all_setups
from .setup_engine import load_setup
from .universe import get_index_symbols


def snapshots_for_plan(plan, progress_callback=None):
    pending = plan['pending']
    if not pending:
        return
    indexes = list(dict.fromkeys(p['index'] for p in pending))
    universes = {index: get_index_symbols(index) for index in indexes}
    if any(not members for members in universes.values()):
        raise ScanError('An index constituent list is unavailable.')
    symbols = sorted({s for members in universes.values() for s in members})
    setups = list(dict.fromkeys(p['setup'] for p in pending))
    results = sanitize(scan_universe_all_setups(
        YFinanceProvider(), symbols, [load_setup(s) for s in setups],
        progress_callback=progress_callback))
    for item in pending:
        members = universes[item['index']]
        member_set = set(members)
        rows = [s for r in results if r['symbol'] in member_set
                for s in r['setups'] if s['setup_id'] == item['setup']]
        if not rows:
            raise ScanError(f"No usable data for {item['index']}; no empty snapshot saved.")
        rows.sort(key=lambda r: (not r['qualified'], -r['score']))
        yield dict(item, captured_at=plan['captured_at'], expected_symbols=members, results=rows)
