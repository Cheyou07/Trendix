"""Hosted API: bounded scan jobs, protected daily snapshots and public history."""
import logging
import os
import secrets
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from .history import HistoryStore, collection, snapshot_dates
from .jobs import JobQueue
from .providers.yfinance_provider import YFinanceProvider
from .scanner import scan_universe_all_setups
from .setup_engine import list_setups, load_setup
from .universe import get_index_symbols, list_available_indexes

logger = logging.getLogger(__name__)


class ScanRequest(BaseModel):
    index: str = 'NIFTY50'
    mode: Literal['single', 'all'] = 'single'
    setup: str = 'setup_1'
    direction: Literal['all', 'bullish', 'bearish'] = 'all'
    near_matches: bool = True
    near_match_score: float = Field(default=70, ge=0, le=100)


def validate_selection(index, setup=None):
    if index not in list_available_indexes():
        raise HTTPException(400, 'Unknown index')
    if setup is not None and setup not in {s['id'] for s in list_setups()}:
        raise HTTPException(400, 'Unknown setup')


def configured_indexes():
    values = os.getenv('SNAPSHOT_INDEXES', ','.join(list_available_indexes()))
    indexes = list(dict.fromkeys(i.strip() for i in values.split(',') if i.strip()))
    if not indexes:
        raise HTTPException(503, 'No daily snapshot indexes configured.')
    for index in indexes:
        validate_selection(index)
    return indexes


def run_daily(indexes, sanitize):
    store = HistoryStore(collection())  # Fail before expensive work if storage is unavailable.
    now = datetime.now(timezone.utc)
    day, _ = snapshot_dates(now)
    setups = list_setups()
    # Repeated scheduler deliveries never rerun or overwrite an already saved day.
    pending = []
    for index in indexes:
        if any(not any(r['run_date'] == day for r in store.list(index, s['id'], now))
               for s in setups):
            pending.append(index)
    if not pending:
        return {'run_date': day, 'indexes': indexes, 'already_saved': True}
    universes = {i: get_index_symbols(i) for i in pending}
    if any(not symbols for symbols in universes.values()):
        raise RuntimeError('An index constituent list is unavailable.')
    symbols = sorted({symbol for items in universes.values() for symbol in items})
    results = sanitize(scan_universe_all_setups(
        YFinanceProvider(), symbols, [load_setup(s['id']) for s in setups]))
    saved = 0
    for index, members in universes.items():
        member_set = set(members)
        rows = [r for r in results if r['symbol'] in member_set]
        if not rows:
            raise RuntimeError(f'No usable market data for {index}; no empty snapshot saved.')
        for setup in setups:
            setup_rows = [s for r in rows for s in r['setups'] if s['setup_id'] == setup['id']]
            setup_rows.sort(key=lambda r: (not r['qualified'], -r['score']))
            store.save(index, setup, setup_rows, members, now)
            saved += 1
    return {'run_date': day, 'indexes': pending, 'snapshots_processed': saved}


def install_hosting(app, scan, scan_all, sanitize):
    queue = JobQueue()

    @app.post('/api/runs', status_code=202)
    def start_run(request: ScanRequest):
        validate_selection(request.index, request.setup if request.mode == 'single' else None)
        if request.mode == 'single':
            key = ('single', request.index, request.setup, request.near_matches, request.near_match_score)
            work = lambda: scan(request.index, request.setup, request.near_matches, request.near_match_score)
        else:
            key = ('all', request.index, request.direction)
            work = lambda: scan_all(request.index, request.direction)
        return queue.submit(key, work)

    @app.get('/api/runs/{job_id}')
    def get_run(job_id: str):
        return queue.get(job_id)

    @app.post('/api/admin/daily-run', status_code=202)
    def daily_run(authorization: str = Header(default='')):
        token = os.getenv('CRON_SECRET', '')
        if not token or not secrets.compare_digest(authorization, f'Bearer {token}'):
            raise HTTPException(401, 'Invalid scheduler credentials.')
        if not os.getenv('MONGODB_URI'):
            raise HTTPException(503, 'Daily history is not configured yet.')
        indexes = configured_indexes()
        day, _ = snapshot_dates(datetime.now(timezone.utc))
        return queue.submit(('daily', day, *indexes), lambda: run_daily(indexes, sanitize), privileged=True)

    @app.get('/api/history')
    def list_history(index: str = 'NIFTY50', setup: str = 'setup_1'):
        validate_selection(index, setup)
        try:
            return HistoryStore(collection()).list(index, setup, datetime.now(timezone.utc))
        except PyMongoError:
            logger.exception('History database unavailable')
            raise HTTPException(503, 'Daily history is temporarily unavailable.')

    @app.get('/api/history/{run_date}')
    def get_history(run_date: date, index: str = 'NIFTY50', setup: str = 'setup_1'):
        validate_selection(index, setup)
        try:
            return HistoryStore(collection()).get(index, setup, run_date.isoformat(), datetime.now(timezone.utc))
        except PyMongoError:
            logger.exception('History database unavailable')
            raise HTTPException(503, 'Daily history is temporarily unavailable.')

    static_dir = Path(os.getenv('STATIC_DIR', Path(__file__).resolve().parents[2] / 'frontend' / 'dist'))
    if (static_dir / 'index.html').is_file():
        app.mount('/assets', StaticFiles(directory=static_dir / 'assets'), name='assets')

        @app.get('/', include_in_schema=False)
        def frontend():
            return FileResponse(static_dir / 'index.html')
