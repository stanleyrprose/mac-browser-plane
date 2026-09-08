from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProviderLaunchdTests(unittest.TestCase):
    def test_provider_launchagent_is_pull_only_and_uses_dedicated_contract(self) -> None:
        template = (ROOT / "launchd" / "com.stanley.mac-browser-provider.plist.in").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install_provider_launchd.py").read_text(encoding="utf-8")
        self.assertIn("__RUNTIME_PROVIDER_AGENT__", template)
        self.assertIn("mac-browser-provider-agent", installer)
        self.assertIn("--identity-file", template)
        self.assertIn("--contract", template)
        self.assertIn("--interval-sec", template)
        self.assertNotIn("0.0.0.0", template)
        self.assertNotIn("--once", template)
        self.assertIn("provider-contract-v1.json", installer)
        self.assertIn("pull_ssh_v1", installer)
        self.assertIn("mac-mm-01", installer)


if __name__ == "__main__":
    unittest.main()
