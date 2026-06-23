"""Cron worker — pollar jobs.json, kor forfallna jobs."""
from __future__ import annotations
import json, time, subprocess, re
from datetime import datetime, timezone
from pathlib import Path
from .model import CronJob, load_jobs, save_jobs

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _should_run(job: CronJob) -> bool:
    """Enkel kontroll: har jobbet korts sen sist?"""
    if not job.enabled:
        return False
    if job.last_run is None:
        return True
    sched = job.schedule.strip()
    # "30m" eller "every 2h"
    m = re.match(r"(\d+)\s*m", sched)
    if m:
        minutes = int(m.group(1))
        try:
            last = datetime.fromisoformat(job.last_run)
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            return elapsed >= minutes * 60
        except Exception:
            return True
    m = re.match(r"every\s+(\d+)\s*h", sched)
    if m:
        hours = int(m.group(1))
        try:
            last = datetime.fromisoformat(job.last_run)
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            return elapsed >= hours * 3600
        except Exception:
            return True
    return False  # cron-uttryck stods inte annu


def run_due_jobs(home: Path | None = None) -> list[str]:
    """Kor alla forfallna jobs. Returnerar loggrader."""
    jobs = load_jobs(home)
    results: list[str] = []
    for job in jobs:
        if not _should_run(job):
            continue
        if job.no_agent and job.script:
            script_path = Path(job.script)
            if script_path.exists():
                try:
                    output = subprocess.check_output(
                        ["python", str(script_path)],
                        text=True, timeout=60, stderr=subprocess.STDOUT,
                    )
                    results.append(f"[{job.name}] OK: {output[:200]}")
                except Exception as e:
                    results.append(f"[{job.name}] FAIL: {e}")
            else:
                results.append(f"[{job.name}] FAIL: script '{job.script}' hittades inte")
        else:
            results.append(f"[{job.name}] SKIPPAD: LLM-agent mode ej implementerat (krav HUND_API_KEY)")
        job.last_run = _now()
    save_jobs(jobs, home)
    return results
