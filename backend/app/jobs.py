"""Small, bounded, single-process queue for a single-instance beta deployment."""
import logging
import math
import time
from threading import Lock, Thread
from uuid import uuid4

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class JobQueue:
    def __init__(self, ttl=300, cooldown=60):
        self.lock = Lock()
        self.jobs = {}
        self.ttl = ttl
        self.cooldown = cooldown
        self.last_public_start = float('-inf')

    def submit(self, key, work, privileged=False):
        now = time.monotonic()
        with self.lock:
            self.jobs = {k: j for k, j in self.jobs.items()
                         if j['status'] == 'running' or now - j['finished'] < self.ttl}
            for job in self.jobs.values():
                if job['key'] == key and job['status'] != 'failed':
                    return {'job_id': job['job_id'], 'status': job['status']}
            if any(j['status'] == 'running' for j in self.jobs.values()):
                raise HTTPException(429, 'Another scan is running. Please retry shortly.',
                                    headers={'Retry-After': '30'})
            if not privileged and now - self.last_public_start < self.cooldown:
                remaining = max(1, math.ceil(self.cooldown - (now - self.last_public_start)))
                raise HTTPException(429, f'The shared scanner is cooling down. Retry in {remaining} seconds.',
                                    headers={'Retry-After': str(remaining)})
            # Bound retained result memory even when admin requests bypass cooldown.
            while len(self.jobs) >= 6:
                del self.jobs[next(iter(self.jobs))]
            job_id = uuid4().hex
            self.jobs[job_id] = {'job_id': job_id, 'key': key, 'status': 'running'}
            if not privileged:
                self.last_public_start = now
            Thread(target=self._run, args=(job_id, work), daemon=True).start()
            return {'job_id': job_id, 'status': 'running'}

    def _run(self, job_id, work):
        try:
            result = work()
            update = {'status': 'completed', 'result': result}
        except Exception:
            logger.exception('Scan job failed')
            update = {'status': 'failed', 'error':
                      'Scan failed. Market data or storage may be unavailable. Please retry later.'}
        with self.lock:
            self.jobs[job_id].update(update, finished=time.monotonic())

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or (job['status'] != 'running' and
                           time.monotonic() - job['finished'] >= self.ttl):
                raise HTTPException(404, 'Run expired or server restarted. Please run the scan again.')
            return {k: v for k, v in job.items() if k not in ('key', 'finished')}
