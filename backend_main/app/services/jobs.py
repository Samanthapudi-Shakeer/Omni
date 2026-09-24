"""
Minimal in-memory background job tracker.

Fix-with-AI and Modularization can take a while and may internally retry
(e.g. after hitting a token limit and clearing context - see
aider_runner._run_aider). Rather than block the HTTP request for all of
that, the routers kick off a background thread and immediately return a
job_id. The frontend polls GET /api/jobs/{job_id} and renders the
`progress` log in a persistent top-right tray, so a retry never blanks the
screen the way restarting the whole request would.

This is intentionally process-local (a plain dict + lock) rather than
Redis/Celery - good enough for a single-instance console tool. Swap in a
real queue if this ever needs to run behind multiple backend workers.
"""
from __future__ import annotations
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional

JobStatus = Literal["running", "done", "error"]


@dataclass
class Job:
    id: str
    kind: str
    label: str
    status: JobStatus = "running"
    progress: List[str] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


_jobs: Dict[str, Job] = {}
_lock = threading.Lock()


def create_job(kind: str, label: str) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, label=label)
    with _lock:
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)


def append_progress(job_id: str, message: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.progress.append(message)
            job.updated_at = time.time()


def _finish(job_id: str, result: Dict[str, Any]) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.status = "done"
            job.result = result
            job.updated_at = time.time()


def _fail(job_id: str, error: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.status = "error"
            job.error = error
            job.updated_at = time.time()


def run_in_background(job_id: str, fn: Callable[[Callable[[str], None]], Dict[str, Any]]) -> None:
    """Run fn(progress_cb) on a daemon thread; records the outcome on the job."""

    def _target():
        try:
            result = fn(lambda msg: append_progress(job_id, msg))
            _finish(job_id, result)
        except Exception as e:  # noqa: BLE001 - surface any failure to the job, don't crash the thread silently
            _fail(job_id, str(e))

    threading.Thread(target=_target, daemon=True).start()
