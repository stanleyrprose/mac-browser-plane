from __future__ import annotations

from .config import RuntimePaths
from .db import JobStore, RuntimeDB
from .executor import BrowserExecutor
from .leases import LeaseManager
from .models import JobState
from .processes import BrowserProcessRegistry


class Worker:
    RECOVERY_STATES = {
        JobState.RUNNING,
        JobState.PAUSED_FOR_INSPECTION,
        JobState.WAITING_HUMAN,
        JobState.CANCEL_REQUESTED,
    }

    def __init__(self, paths: RuntimePaths, db: RuntimeDB):
        self.jobs = JobStore(db)
        self.executor = BrowserExecutor(paths, db)
        self.leases = LeaseManager(db)
        self.processes = BrowserProcessRegistry(db)

    def recover_startup(self) -> dict[str, object]:
        recovered: list[str] = []
        ambiguous: list[str] = []
        for row in self.jobs.recovery_candidates():
            job_id = str(row["job_id"])
            process_report = self.processes.reconcile_for_job(job_id)
            safe = bool(process_report["safe"])
            result = {
                "reason": "worker_startup_recovery",
                "process_recovery": process_report,
            }
            transitioned = self.jobs.transition(
                job_id,
                self.RECOVERY_STATES,
                JobState.RECOVERY_REQUIRED,
                failure_class="STATE_RECOVERY_REQUIRED",
                result=result,
            )
            if not transitioned:
                continue
            if safe:
                self.leases.release_for_job(job_id)
                recovered.append(job_id)
            else:
                ambiguous.append(job_id)
        return {"recovered": recovered, "ambiguous": ambiguous}

    def once(self) -> bool:
        row = self.jobs.next_runnable()
        if row is None:
            return False
        return self.executor.run_one(row)
