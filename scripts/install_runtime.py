from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


DEFAULT_PYTHON = "/usr/local/bin/python3"


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    runtime_home = Path(os.environ.get("BROWSER_PLANE_HOME", "~/agent-browser-runtime")).expanduser()
    app_dir = runtime_home / "app"
    venv_dir = app_dir / "venv"
    python = Path(os.environ.get("BROWSER_PLANE_RUNTIME_PYTHON", DEFAULT_PYTHON))

    if not python.exists():
        raise SystemExit(f"runtime Python not found: {python}")

    app_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if venv_dir.exists():
        shutil.rmtree(venv_dir)

    run([str(python), "-m", "venv", str(venv_dir)])
    venv_python = venv_dir / "bin" / "python"
    run([str(venv_python), "-m", "pip", "install", f"{repo}[browser,agent]"])

    marker = app_dir / "INSTALLATION.txt"
    marker.write_text(
        "\n".join(
            [
                "Mac Browser Plane runtime installation",
                f"source_repo={repo}",
                f"runtime_python={python}",
                f"runtime_browserctl={venv_dir / 'bin' / 'browserctl'}",
                f"runtime_mcp={venv_dir / 'bin' / 'mac-browser-mcp'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(marker, 0o600)
    print(venv_dir / "bin" / "browserctl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
