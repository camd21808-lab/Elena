import json
import redis as redis_lib

from engine.config import settings


def _index_after_job(kind: str, mon: str, ten: str, result_path=None, pdf_path=None) -> None:
    """Best-effort auto-index parity for RQ workers. Never raises."""
    try:
        from pathlib import Path

        from engine import library

        library.init_db()
        if kind == "convert":
            p = Path(result_path) if result_path else None
            if p and p.is_file():
                library.index_file(p, mon=mon)
            return
        src = Path(pdf_path) if pdf_path else None
        local_root = Path(settings.local_root).resolve()
        if src and src.is_file() and str(src.resolve()).startswith(str(local_root)):
            library.index_file(src, mon=mon, ten=ten)
            return
        name = src.name if src else ""
        if name:
            candidate = settings.local_subject_dir(mon) / name
            if candidate.is_file():
                library.index_file(candidate, mon=mon, ten=ten)
    except Exception as exc:
        print(f"[library] auto-index thất bại: {exc}", flush=True)


def _store(key: str, mapping: dict) -> None:
    r = redis_lib.Redis.from_url(settings.redis_url)
    r.hset(key, mapping=mapping)


def run_job(job_id: str, link: str, mon: str, ten_de: str, ky: str | None) -> dict:
    from engine.pipeline import run_scan

    key = f"scanjob:{job_id}"
    _store(key, {"status": "running"})

    result = run_scan(link, mon, ten_de, ky=ky)

    mapping = {
        "status": "done" if result.brief.ok else "failed",
        "ok": "1" if result.brief.ok else "0",
        "brief_lines": json.dumps(result.brief.lines, ensure_ascii=False),
    }
    if result.pdf_path:
        mapping["pdf_path"] = str(result.pdf_path)
    if result.brief.failure_reason:
        mapping["error"] = result.brief.failure_reason
    _store(key, mapping=mapping)
    if result.brief.ok:
        _index_after_job("scan", mon, ten_de, pdf_path=result.pdf_path)
    return mapping


def run_protect_job(job_id: str, file_path: str, config_json: str) -> dict:
    import json
    from pathlib import Path

    from engine.config import settings
    from engine.convert.pipeline import Brief, RunResult
    from engine.protect import protect_file

    key = f"scanjob:{job_id}"
    _store(key, {"status": "running"})

    workdir = settings.temp_dir() / f"protect_{job_id}"
    config = json.loads(config_json or "{}")
    outcome = protect_file(Path(file_path), config, workdir)
    final = outcome["final"]
    size_kb = final.stat().st_size / 1024
    lines = [f"File: {final}", f"Kích thước: {size_kb:.2f} KB"] + [f"• {n}" for n in outcome["notes"]]
    result = RunResult(brief=Brief(ok=True, lines=lines), result_path=final)

    mapping = {
        "status": "done" if result.brief.ok else "failed",
        "ok": "1" if result.brief.ok else "0",
        "brief_lines": json.dumps(result.brief.lines, ensure_ascii=False),
    }
    if result.result_path:
        mapping["result_path"] = str(result.result_path)
    if result.brief.failure_reason:
        mapping["error"] = result.brief.failure_reason
    _store(key, mapping=mapping)
    return mapping


def run_convert_job(job_id: str, file_path: str, mon: str, target: str) -> dict:
    from pathlib import Path

    from engine.convert import convert_file

    key = f"scanjob:{job_id}"
    _store(key, {"status": "running"})

    result = convert_file(Path(file_path), mon, target=target)

    mapping = {
        "status": "done" if result.brief.ok else "failed",
        "ok": "1" if result.brief.ok else "0",
        "brief_lines": json.dumps(result.brief.lines, ensure_ascii=False),
    }
    if result.result_path:
        mapping["result_path"] = str(result.result_path)
    if result.brief.failure_reason:
        mapping["error"] = result.brief.failure_reason
    _store(key, mapping=mapping)
    if result.brief.ok:
        _index_after_job("convert", mon, "", result_path=result.result_path)
    return mapping
