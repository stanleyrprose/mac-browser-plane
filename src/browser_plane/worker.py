from __future__ import annotations

from .config import RuntimePaths
from .db import JobStore, RuntimeDB
from .executor import BrowserExecutor


class Worker:
    def __init__(self, paths: RuntimePaths, db: RuntimeDB):
        self.jobs = JobStore(db)
        self.executor = BrowserExecutor(paths, db)

    def once(self) -> bool:
        row = self.jobs.next_runnable()
        if row is None:
            return False
        return self.executor.run_one(row)
