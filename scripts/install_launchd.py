from __future__ import annotations

import os
import subprocess
from pathlib import Path


LABEL = "com.stanley.mac-browser-plane"


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    home = Path.home()
    runtime_home = Path(os.environ.get("BROWSER_PLANE_HOME", "~/agent-browser-runtime")).expanduser()
    runtime_browserctl = runtime_home / "app" / "venv" / "bin" / "browserctl"
    if not runtime_browserctl.exists():
        raise SystemExit(
            f"runtime is not installed: {runtime_browserctl}; run scripts/install_runtime.py first"
        )

    template = (repo / "launchd" / f"{LABEL}.plist.in").read_text(encoding="utf-8")
    rendered = (
        template.replace("__HOME__", str(home))
        .replace("__RUNTIME_HOME__", str(runtime_home))
        .replace("__RUNTIME_BROWSERCTL__", str(runtime_browserctl))
    )
    target = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")

    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target)], check=False, capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{LABEL}"], check=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=True)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
