from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

LABEL = "com.stanley.mac-browser-provider"
DEFAULT_HOST = "signalforge-provider@43.133.101.242"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-source", type=Path, required=True)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--identity-file", type=Path, default=Path.home() / ".ssh" / "signalforge-provider-bkk")
    return parser


def main() -> int:
    args = _parser().parse_args()
    repo = Path(__file__).resolve().parents[1]
    home = Path.home()
    runtime_home = Path(os.environ.get("BROWSER_PLANE_HOME", "~/agent-browser-runtime")).expanduser()
    provider_agent = runtime_home / "app" / "venv" / "bin" / "mac-browser-provider-agent"
    if not provider_agent.exists():
        raise SystemExit(f"runtime provider agent is not installed: {provider_agent}")
    identity = args.identity_file.expanduser().resolve()
    if not identity.is_file():
        raise SystemExit(f"provider identity is missing: {identity}")
    contract_source = args.contract_source.expanduser().resolve()
    try:
        contract = json.loads(contract_source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid provider contract source: {exc}") from exc
    if contract.get("enabled") is not True or contract.get("provider_id") != "mac-mm-01" or contract.get("transport") != "pull_ssh_v1":
        raise SystemExit("provider production contract is not enabled pull_ssh_v1 for mac-mm-01")

    config_dir = runtime_home / "config"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_dir.chmod(0o700)
    runtime_contract = config_dir / "provider-contract-v1.json"
    shutil.copyfile(contract_source, runtime_contract)
    runtime_contract.chmod(0o600)

    template = (repo / "launchd" / f"{LABEL}.plist.in").read_text(encoding="utf-8")
    rendered = (
        template.replace("__HOME__", str(home))
        .replace("__RUNTIME_HOME__", str(runtime_home))
        .replace("__RUNTIME_PROVIDER_AGENT__", str(provider_agent))
        .replace("__PROVIDER_HOST__", str(args.host))
        .replace("__IDENTITY_FILE__", str(identity))
        .replace("__RUNTIME_CONTRACT__", str(runtime_contract))
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
