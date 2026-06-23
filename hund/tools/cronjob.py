"""cronjob tool — hantera schemalagda tasks."""
from __future__ import annotations
import json
from ..cron.model import CronJob, load_jobs, save_jobs

def manage_cron(args: dict) -> str:
    action = args.get("action", "list")
    if action == "list":
        jobs = load_jobs()
        if not jobs:
            return "(inga cron-jobb)"
        lines = []
        for j in jobs:
            status = "aktiv" if j.enabled else "pausad"
            last = j.last_run[:16] if j.last_run else "aldrig"
            lines.append(f"[{status}] {j.name} ({j.schedule}) — senast: {last}")
        return "\n".join(lines)
    if action == "create":
        name = args.get("name", "cron-" + str(len(load_jobs()) + 1))
        schedule = args.get("schedule", "30m")
        prompt = args.get("prompt", "")
        job = CronJob(name=name, schedule=schedule, prompt=prompt)
        jobs = load_jobs()
        jobs.append(job)
        save_jobs(jobs)
        return f"skapat cron-jobb: {job.name} ({job.schedule})"
    if action == "pause":
        name = args.get("name", "")
        jobs = load_jobs()
        for j in jobs:
            if j.name == name:
                j.enabled = False
                save_jobs(jobs)
                return f"pausat: {name}"
        return f"[error] hittade inte '{name}'"
    if action == "resume":
        name = args.get("name", "")
        jobs = load_jobs()
        for j in jobs:
            if j.name == name:
                j.enabled = True
                save_jobs(jobs)
                return f"aterupptaget: {name}"
        return f"[error] hittade inte '{name}'"
    if action == "remove":
        name = args.get("name", "")
        jobs = load_jobs()
        jobs = [j for j in jobs if j.name != name]
        save_jobs(jobs)
        return f"borttaget: {name}"
    return f"[error] okand action: {action}"
