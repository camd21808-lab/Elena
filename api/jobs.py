import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.config import settings


def _auto_index_job(job: "Job", result_path: Path | None) -> None:
    """Best-effort auto-index of a freshly produced PDF. Never raises.

    Only scan/convert outputs are indexed. Protect output lives inside
    temp_dir (protect_{id}/final.pdf) and would be wiped by TTL anyway.
    """
    try:
        from engine import library

        if job.kind not in ("convert", "scan"):
            return
        library.init_db()
        if job.kind == "convert":
            p = Path(result_path) if result_path else None
            if p and p.is_file():
                library.index_file(p, mon=job.mon)
            return
        if job.kind == "scan":
            src = Path(result_path) if result_path else None
            local_root = Path(settings.local_root).resolve()
            if src and src.is_file() and str(src.resolve()).startswith(str(local_root)):
                library.index_file(src, mon=job.mon, ten=job.ten_de)
                return
            name = src.name if src else ""
            if name:
                candidate = settings.local_subject_dir(job.mon) / name
                if candidate.is_file():
                    library.index_file(candidate, mon=job.mon, ten=job.ten_de)
    except Exception as exc:
        print(f"[library] auto-index thất bại cho job {job.id}: {exc}", flush=True)


@dataclass
class Job:
    id: str
    link: str = ""
    mon: str = ""
    ten_de: str = ""
    ky: str | None = None
    kind: str = "scan"  # scan | convert | protect
    target: str = "pdf"
    source_file: str = ""
    config_json: str = ""
    status: str = "queued"  # queued | running | done | failed
    brief_lines: list[str] = field(default_factory=list)
    ok: bool | None = None
    pdf_path: str | None = None
    result_path: str | None = None
    created_at: float = field(default_factory=time.time)
    error: str | None = None


class InProcessBackend:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = None
        self._imported_pool = None

    def _pool(self):
        if self._imported_pool is None:
            from concurrent.futures import ThreadPoolExecutor

            self._imported_pool = ThreadPoolExecutor(max_workers=settings.max_concurrent)
        return self._imported_pool

    def create_job(self, link: str, mon: str, ten_de: str, ky: str | None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], link=link, mon=mon, ten_de=ten_de, ky=ky, kind="scan")
        with self._lock:
            self._jobs[job.id] = job
        return job

    def create_convert_job(self, file_path: str, mon: str, target: str) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            mon=mon,
            kind="convert",
            target=target,
            source_file=file_path,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def create_protect_job(self, file_path: str, config_json: str) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            kind="protect",
            target="pdf",
            source_file=file_path,
            config_json=config_json,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def enqueue(self, job: Job) -> None:
        def _run():
            with self._lock:
                job.status = "running"
            try:
                result_path = None
                if job.kind == "convert":
                    from engine.convert import convert_file

                    result = convert_file(Path(job.source_file), job.mon, target=job.target)
                    result_path = result.result_path
                elif job.kind == "protect":
                    import json

                    from engine.convert.pipeline import Brief, RunResult
                    from engine.protect import protect_file

                    workdir = settings.temp_dir() / f"protect_{job.id}"
                    config = json.loads(job.config_json or "{}")
                    outcome = protect_file(Path(job.source_file), config, workdir)
                    final = outcome["final"]
                    size_kb = final.stat().st_size / 1024
                    lines = [f"File: {final}", f"Kích thước: {size_kb:.2f} KB"] + [f"• {n}" for n in outcome["notes"]]
                    result = RunResult(brief=Brief(ok=True, lines=lines), result_path=final)
                    result_path = result.result_path
                else:
                    from engine.pipeline import run_scan

                    result = run_scan(job.link, job.mon, job.ten_de, ky=job.ky)
                    result_path = result.pdf_path
                with self._lock:
                    job.status = "done" if result.brief.ok else "failed"
                    job.ok = result.brief.ok
                    job.brief_lines = result.brief.lines
                    if job.kind in ("convert", "protect"):
                        job.result_path = str(result_path) if result_path else None
                    else:
                        job.pdf_path = str(result_path) if result_path else None
                    if not result.brief.ok:
                        job.error = result.brief.failure_reason
                if result.brief.ok:
                    _auto_index_job(job, result_path)
            except Exception as exc:
                with self._lock:
                    job.status = "failed"
                    job.ok = False
                    job.error = str(exc)[:500]
                    job.brief_lines = [f"Ly do: {exc}", "Goi y: chay lai; neu van loi, gui log cho developer"]

        future = self._pool().submit(_run)
        timeout = settings.job_timeout_seconds + 60

        def _watchdog():
            try:
                future.result(timeout=timeout)
            except Exception:
                with self._lock:
                    if job.status == "running":
                        job.status = "failed"
                        job.ok = False
                        job.error = f"Job chay qua han {timeout}s - da danh dau failed"
                        job.brief_lines = [f"Ly do: Chay qua han {timeout}s (treo)", "Goi y: thu lai"]

        threading.Thread(target=_watchdog, daemon=True, name=f"wd-{job.id}").start()

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


class RQBackend:
    def __init__(self) -> None:
        import redis
        from rq import Queue

        self._redis = redis.Redis.from_url(settings.redis_url)
        self._queue = Queue("scan", connection=self._redis, default_timeout=settings.job_timeout_seconds)

    def create_job(self, link: str, mon: str, ten_de: str, ky: str | None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], link=link, mon=mon, ten_de=ten_de, ky=ky, kind="scan")
        key = f"scanjob:{job.id}"
        self._redis.hset(key, mapping={"status": job.status, "kind": "scan", "link": link, "mon": mon, "ten_de": ten_de})
        self._redis.expire(key, settings.job_timeout_seconds * 2)
        return job

    def create_convert_job(self, file_path: str, mon: str, target: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], mon=mon, kind="convert", target=target, source_file=file_path)
        key = f"scanjob:{job.id}"
        self._redis.hset(
            key,
            mapping={
                "status": job.status,
                "kind": "convert",
                "mon": mon,
                "target": target,
                "source_file": file_path,
            },
        )
        self._redis.expire(key, settings.job_timeout_seconds * 2)
        return job

    def create_protect_job(self, file_path: str, config_json: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind="protect", target="pdf", source_file=file_path, config_json=config_json)
        key = f"scanjob:{job.id}"
        self._redis.hset(
            key,
            mapping={
                "status": job.status,
                "kind": "protect",
                "target": "pdf",
                "source_file": file_path,
                "config_json": config_json,
            },
        )
        self._redis.expire(key, settings.job_timeout_seconds * 2)
        return job

    def enqueue(self, job: Job) -> None:
        from rq import Retry

        if job.kind == "convert":
            self._queue.enqueue(
                "api.worker.run_convert_job",
                job.id,
                job.source_file,
                job.mon,
                job.target,
                retry=Retry(max=settings.retry_transient),
            )
        elif job.kind == "protect":
            self._queue.enqueue(
                "api.worker.run_protect_job",
                job.id,
                job.source_file,
                job.config_json,
                retry=Retry(max=settings.retry_transient),
            )
        else:
            self._queue.enqueue(
                "api.worker.run_job",
                job.id,
                job.link,
                job.mon,
                job.ten_de,
                job.ky,
                retry=Retry(max=settings.retry_transient),
            )

    def get_job(self, job_id: str) -> Job | None:
        import redis as redis_lib

        key = f"scanjob:{job_id}"
        raw = self._redis.hgetall(key)
        if not raw:
            return None
        job = Job(
            id=job_id,
            kind=raw.get(b"kind", b"scan").decode(),
            target=raw.get(b"target", b"pdf").decode(),
            link=raw.get(b"link", b"").decode(),
            mon=raw.get(b"mon", b"").decode(),
            ten_de=raw.get(b"ten_de", b"").decode(),
            ky=raw.get(b"ky", b"").decode() or None,
            source_file=raw.get(b"source_file", b"").decode(),
            config_json=raw.get(b"config_json", b"").decode(),
            status=raw.get(b"status", b"queued").decode(),
            brief_lines=[],
        )
        if raw.get(b"brief_lines"):
            import json

            job.brief_lines = json.loads(raw[b"brief_lines"])
        job.ok = raw.get(b"ok", b"") in (b"1", b"true")
        if raw.get(b"pdf_path"):
            job.pdf_path = raw[b"pdf_path"].decode()
        if raw.get(b"result_path"):
            job.result_path = raw[b"result_path"].decode()
        job.error = (raw.get(b"error") or b"").decode() or None
        return job


def make_backend():
    import os

    if os.getenv("SCANDE_QUEUE", "inprocess").lower() == "redis":
        return RQBackend()
    return InProcessBackend()


backend = make_backend()
