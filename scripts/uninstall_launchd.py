from __future__ import annotations

import os
import subprocess
from pathlib import Path


LABEL = "com.stanley.mac-browser-plane"


def main() -> int:
    target = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target)], check=False)
    if target.exists():
        target.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
