from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    state_dir: Path
    evidence_dir: Path
    profiles_dir: Path
    auth_state_dir: Path
    logs_dir: Path
    run_dir: Path
    db_path: Path

    @classmethod
    def discover(cls) -> "RuntimePaths":
        root = Path(os.environ.get("BROWSER_PLANE_HOME", "~/agent-browser-runtime")).expanduser()
        state_dir = root / "state"
        return cls(
            root=root,
            state_dir=state_dir,
            evidence_dir=root / "evidence",
            profiles_dir=root / "profiles",
            auth_state_dir=root / "auth-state",
            logs_dir=root / "logs",
            run_dir=root / "run",
            db_path=state_dir / "runtime.db",
        )

    def ensure(self) -> None:
        for path in (
            self.root,
            self.state_dir,
            self.evidence_dir,
            self.profiles_dir,
            self.auth_state_dir,
            self.logs_dir,
            self.run_dir,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for profile in ("public-research", "authenticated-work", "development"):
            (self.profiles_dir / profile).mkdir(parents=True, exist_ok=True, mode=0o700)
