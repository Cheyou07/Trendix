"""Interactive jobs and history. Scheduled computation runs on GitHub, not here."""
import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from .history import HistoryStore, collection, snapshot_dates
from .jobs import JobQueue
from .jsonutils import sanitize
from .scan_worker import execute_scan
from .setup_engine import list_setups
from .universe import list_available_indexes

logger = logging.getLogger(__name__)


class ScanRequest(BaseModel):
    index: str = 'NIFTY50'
    mode: Literal['single', 'all'] = 'single'
    setup: str = 'setup_1'
    direction: Literal['all', 'bullish', 'bearish'] = 'all'
    near_matches: bool = True
    near_match_score: float = Field(default=70, ge=0, le=100)


class SnapshotRequest(BaseModel):
    index: str
    setup: str
    captured_at: datetime
    expected_symbols: list[str] = Field(min_length=1, max_length=1000)
    results: list[dict] = Field(min_length=1, max_length=1000)


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


def authorize_scheduler(authorization):
    token = os.getenv('CRON_SECRET', '')
    if not token or not secrets.compare_digest(authorization, f'Bearer {token}'):
        raise HTTPException(401, 'Invalid scheduler credentials.')


def install_hosting(app, queue=None):
    queue = queue if queue is not None else JobQueue(
        timeout=max(30, min(600, int(os.getenv('SCAN_TIMEOUT_SECONDS', '600')))))

    @app.post('/api/runs', status_code=202)
    def start_run(request: ScanRequest):
        validate_selection(request.index, request.setup if request.mode == 'single' else None)
        if request.mode == 'single':
            key = ('single', request.index, request.setup, request.near_matches, request.near_match_score)
        else:
            key = ('all', request.index, request.direction)
        return queue.submit(key, execute_scan, request.model_dump())

    @app.get('/api/runs/{job_id}')
    def get_run(job_id: str):
        return queue.get(job_id)

    @app.get('/api/scanner/status')
    def scanner_status():
        return queue.status()

    @app.post('/api/admin/daily-run')
    def retired_daily_run(authorization: str = Header(default='')):
        authorize_scheduler(authorization)
        raise HTTPException(410, 'Daily scans now run on GitHub Actions. Update and rerun the daily-snapshot workflow.')

    @app.get('/api/admin/daily-plan')
    def daily_plan(authorization: str = Header(default='')):
        authorize_scheduler(authorization)
        now = datetime.now(timezone.utc)
        day, _ = snapshot_dates(now)
        try:
            saved = {(r['index'], r['setup_id']) for r in collection().find(
                {'run_date': day, 'expires_at': {'$gt': now}},
                {'index': 1, 'setup_id': 1})}
        except PyMongoError:
            logger.exception('History database unavailable')
            raise HTTPException(503, 'Daily history is temporarily unavailable.')
        pending = [{'index': index, 'setup': setup['id']}
                   for index in configured_indexes() for setup in list_setups()
                   if (index, setup['id']) not in saved]
        return {'captured_at': now.isoformat(), 'run_date': day, 'pending': pending}

    @app.post('/api/admin/daily-snapshot')
    def save_snapshot(request: SnapshotRequest, authorization: str = Header(default='')):
        authorize_scheduler(authorization)
        validate_selection(request.index, request.setup)
        now = datetime.now(timezone.utc)
        captured = request.captured_at
        if (captured.tzinfo is None or captured > now + timedelta(minutes=5)
                or snapshot_dates(captured)[1] <= now):
            raise HTTPException(400, 'Snapshot date must be timezone-aware and within the retained week.')
        members = set(request.expected_symbols)
        rows = request.results
        symbols = [row.get('symbol') for row in rows]
        if (len(members) != len(request.expected_symbols)
                or any(not isinstance(s, str) or s not in members for s in symbols)
                or len(set(symbols)) != len(symbols)
                or any(r.get('setup_id') != request.setup for r in rows)):
            raise HTTPException(400, 'Snapshot rows must be unique members of the index and selected setup.')
        setup = next(s for s in list_setups() if s['id'] == request.setup)
        try:
            HistoryStore(collection()).save(request.index, setup, sanitize(rows),
                                             request.expected_symbols, captured)
        except PyMongoError:
            logger.exception('History database unavailable')
            raise HTTPException(503, 'Daily history is temporarily unavailable.')
        return {'saved': True, 'run_date': snapshot_dates(captured)[0],
                'index': request.index, 'setup': request.setup}

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
