"""Bounded FIFO for interactive scans, with disposable processes and hard deadlines."""
import logging
import multiprocessing
import time
from collections import deque
from threading import Lock, Thread
from uuid import uuid4

from fastapi import HTTPException

from .errors import ScanError

logger = logging.getLogger(__name__)
ACTIVE = {'queued', 'running'}


def _process_entry(connection, work, payload):
    try:
        result = work(payload, lambda progress: connection.send(('progress', progress)))
        connection.send(('result', result))
    except (ScanError, HTTPException) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        logger.exception('Scan worker failed')
        connection.send(('error', message))
    except BaseException:
        logger.exception('Unexpected scan worker failure')
        connection.send(('error', 'The scan worker failed. See the server logs for details.'))
    finally:
        connection.close()


def run_isolated(work, payload, progress, timeout):
    """A timeout must stop the actual work, not abandon a stuck thread."""
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_process_entry, args=(sender, work, payload), daemon=True)
    try:
        process.start()
        sender.close()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if receiver.poll(min(.2, max(0, deadline - time.monotonic()))):
                try:
                    kind, data = receiver.recv()
                except EOFError:
                    break
                if kind == 'result':
                    return data
                if kind == 'error':
                    raise ScanError(data)
                progress(data)
            elif not process.is_alive():
                break
        else:
            raise ScanError(f'The scan exceeded its {timeout:g}-second server limit and was stopped. '
                            'Try a smaller index, or retry when market data is available.')
        raise ScanError('The scan worker stopped unexpectedly. The server may have run out of memory.')
    finally:
        # Reap before releasing the slot: a hung download cannot block later scans.
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join(2)
            process.close()
        sender.close()
        receiver.close()


class JobQueue:
    def __init__(self, ttl=300, timeout=600, max_pending=2, runner=run_isolated):
        self.lock = Lock()
        self.jobs = {}
        self.pending = deque()
        self.running_id = None
        self.ttl = ttl
        self.timeout = timeout
        self.max_pending = max_pending
        self.runner = runner

    def submit(self, key, work, payload, reuse_completed=True, deduplicate=True):
        with self.lock:
            now = time.monotonic()
            self.jobs = {k: j for k, j in self.jobs.items()
                         if j['status'] in ACTIVE or now - j['finished'] < self.ttl}
            for job in self.jobs.values():
                if (deduplicate and job['key'] == key and
                        (job['status'] in ACTIVE or (reuse_completed and job['status'] == 'completed'))):
                    return self._public(job)
            if self.running_id is not None and len(self.pending) >= self.max_pending:
                raise HTTPException(429, 'The scan queue is full. Please retry shortly.',
                                    headers={'Retry-After': '10'})
            completed = [k for k, j in self.jobs.items() if j['status'] not in ACTIVE]
            for old_id in completed[:-5]:
                del self.jobs[old_id]
            job_id = uuid4().hex
            self.jobs[job_id] = {'job_id': job_id, 'key': key, 'status': 'queued',
                                 'created': now, 'progress': {'phase': 'queued'}}
            self.pending.append((job_id, work, payload))
            self._start_next()
            return self._public(self.jobs[job_id])

    def _start_next(self):
        # Called with lock held. One child process runs at a time.
        if self.running_id is not None or not self.pending:
            return
        job_id, work, payload = self.pending.popleft()
        self.running_id = job_id
        self.jobs[job_id].update(status='running', started=time.monotonic(),
                                 progress={'phase': 'starting'})
        Thread(target=self._run, args=(job_id, work, payload), daemon=True).start()

    def _run(self, job_id, work, payload):
        def progress(value):
            with self.lock:
                self.jobs[job_id]['progress'] = value
        try:
            result = self.runner(work, payload, progress, self.timeout)
            update = {'status': 'completed', 'result': result}
        except ScanError as exc:
            logger.warning('Scan %s failed: %s', job_id, exc)
            update = {'status': 'failed', 'error': str(exc)}
        except Exception:
            logger.exception('Unable to run scan worker')
            update = {'status': 'failed', 'error': 'Unable to start the scan worker. Please check server logs.'}
        with self.lock:
            self.jobs[job_id].update(update, finished=time.monotonic())
            self.running_id = None
            self._start_next()

    def _public(self, job):
        output = {k: v for k, v in job.items() if k not in ('key', 'created', 'started', 'finished')}
        if job['status'] == 'queued':
            output['queue_position'] = next(i + 1 for i, (jid, _, _) in enumerate(self.pending)
                                             if jid == job['job_id'])
        if job['status'] == 'running':
            output['elapsed_seconds'] = int(time.monotonic() - job['started'])
            output['timeout_seconds'] = self.timeout
        return output

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or (job['status'] not in ACTIVE and
                           time.monotonic() - job['finished'] >= self.ttl):
                raise HTTPException(404, 'Run expired or server restarted. Please run the scan again.')
            return self._public(job)

    def status(self):
        with self.lock:
            running = self.jobs.get(self.running_id)
            return {'running': bool(running), 'queued': len(self.pending),
                    'elapsed_seconds': int(time.monotonic() - running['started']) if running else 0,
                    'progress': running['progress'] if running else None,
                    'timeout_seconds': self.timeout}
