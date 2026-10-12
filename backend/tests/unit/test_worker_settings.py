from __future__ import annotations

from app.core.queue.arq import GENERAL_QUEUE_NAME, HEAVY_QUEUE_NAME
from app.core.queue.general_worker import WorkerSettings as GeneralWorkerSettings
from app.core.queue.heavy_worker import WorkerSettings as HeavyWorkerSettings


def _function_names(worker_settings) -> set[str]:
    return {function.__name__ for function in worker_settings.functions}


def test_general_worker_registration_imports_cleanly() -> None:
    assert GeneralWorkerSettings.queue_name == GENERAL_QUEUE_NAME
    assert _function_names(GeneralWorkerSettings) == {
        "process_email_outbox_batch",
        "process_attendance_retention_job",
        "process_subscription_lifecycle_job",
        "process_pending_payment_reconciliation_job",
    }
    assert GeneralWorkerSettings.cron_jobs
    assert GeneralWorkerSettings.max_jobs == 3
    assert GeneralWorkerSettings.health_check_key


def test_heavy_worker_registration_imports_cleanly() -> None:
    assert HeavyWorkerSettings.queue_name == HEAVY_QUEUE_NAME
    assert _function_names(HeavyWorkerSettings) == {
        "process_bulk_import_job",
        "process_session_progression_job",
    }
    assert HeavyWorkerSettings.max_jobs == 1
    assert HeavyWorkerSettings.job_timeout == 3600
    assert HeavyWorkerSettings.health_check_key
