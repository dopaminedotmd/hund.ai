"""Tester för cronjob tool och model/worker."""
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from hund.cron.model import CronJob, load_jobs, save_jobs
from hund.cron.worker import _should_run, run_due_jobs
from hund.tools.cronjob import manage_cron


def test_list_empty(tmp_path):
    """Om inga jobb finns ska list returnera (inga cron-jobb)."""
    with patch("hund.paths.hund_home", return_value=tmp_path):
        res = manage_cron({"action": "list"})
        assert "(inga cron-jobb)" in res


def test_create_and_list(tmp_path):
    """Skapa ett jobb och verifiera att det listas."""
    with patch("hund.paths.hund_home", return_value=tmp_path):
        res_create = manage_cron({
            "action": "create",
            "name": "job1",
            "schedule": "15m",
            "prompt": "do clean"
        })
        assert "skapat" in res_create
        assert "job1" in res_create
        
        res_list = manage_cron({"action": "list"})
        assert "job1" in res_list
        assert "15m" in res_list
        assert "aktiv" in res_list


def test_pause_and_resume(tmp_path):
    """Pausa och återuppta ett jobb."""
    with patch("hund.paths.hund_home", return_value=tmp_path):
        manage_cron({"action": "create", "name": "job1", "schedule": "10m"})
        
        # Pausa
        res_pause = manage_cron({"action": "pause", "name": "job1"})
        assert "pausat: job1" in res_pause
        
        res_list = manage_cron({"action": "list"})
        assert "pausad" in res_list
        
        # Återuppta
        res_resume = manage_cron({"action": "resume", "name": "job1"})
        assert "aterupptaget: job1" in res_resume
        
        res_list2 = manage_cron({"action": "list"})
        assert "aktiv" in res_list2


def test_remove(tmp_path):
    """Ta bort ett jobb."""
    with patch("hund.paths.hund_home", return_value=tmp_path):
        manage_cron({"action": "create", "name": "job1"})
        manage_cron({"action": "create", "name": "job2"})
        
        res_remove = manage_cron({"action": "remove", "name": "job1"})
        assert "borttaget: job1" in res_remove
        
        res_list = manage_cron({"action": "list"})
        assert "job2" in res_list
        assert "job1" not in res_list


def test_should_run():
    """Verifiera _should_run kontrollen för tidsintervall."""
    # Inte enabled -> ska inte köras
    job = CronJob(name="j", schedule="10m", enabled=False)
    assert not _should_run(job)
    
    # Enabled, inte körts än -> ska köras
    job2 = CronJob(name="j", schedule="10m", enabled=True, last_run=None)
    assert _should_run(job2)
    
    # Nyss körts -> ska inte köras
    from datetime import datetime, timezone
    job3 = CronJob(name="j", schedule="10m", enabled=True, last_run=datetime.now(timezone.utc).isoformat())
    assert not _should_run(job3)


def test_run_due_jobs_no_agent(tmp_path):
    """Om no_agent=True och skriptet finns, kör skriptet och uppdatera last_run."""
    with patch("hund.paths.hund_home", return_value=tmp_path):
        script_file = tmp_path / "script.py"
        script_file.write_text("print('script executed')", encoding="utf-8")
        
        job = CronJob(
            name="job-script",
            schedule="every 1h",
            no_agent=True,
            script=str(script_file),
            enabled=True
        )
        save_jobs([job], tmp_path)
        
        results = run_due_jobs(tmp_path)
        assert len(results) == 1
        assert "OK: script executed" in results[0]
        
        # Kolla att last_run har sparats
        updated_jobs = load_jobs(tmp_path)
        assert updated_jobs[0].last_run is not None
