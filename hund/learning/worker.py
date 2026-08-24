"""Background Learning Worker — processes queued learning jobs asynchronously."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .commit_controller import CommitController
from .evaluator import evaluate_heuristic_candidates
from .ledger import claim_next_job, complete_job, fail_job, get_event

logger = logging.getLogger(__name__)


def process_pending_learning_jobs(
    home: Optional[Path] = None,
    max_jobs: int = 5,
    db_path: Path | str | None = None,
) -> int:
    """Process pending learning jobs from the durable queue deterministically.

    Extracts evidence from ledger -> runs candidate evaluation -> commits via CommitController.
    Returns the number of jobs successfully completed.
    """
    completed_count = 0
    controller = CommitController(home=home, db_path=db_path)

    for _ in range(max_jobs):
        job = claim_next_job(db_path=db_path)
        if not job:
            break

        job_id = job["job_id"]
        event_ids = job["event_ids"]

        try:
            # 1. Fetch evidence events
            events = []
            for ev_id in event_ids:
                ev = get_event(ev_id, db_path=db_path)
                if ev:
                    events.append(ev)

            if not events:
                complete_job(job_id, db_path=db_path)
                completed_count += 1
                continue

            # 2. Extract and evaluate candidate propositions
            proposals = evaluate_heuristic_candidates(events=events)

            # 3. Commit candidates via CommitController policy gate
            for prop in proposals:
                if prop.suggested_action in ("store_candidate", "store_rule"):
                    controller.commit_candidate(prop)

            complete_job(job_id, db_path=db_path)
            completed_count += 1
        except Exception as err:
            logger.warning("Error processing learning job %s: %s", job_id, err)
            fail_job(job_id, error=str(err), db_path=db_path)

    return completed_count
