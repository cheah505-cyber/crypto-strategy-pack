from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MonitoringPolicyTests(unittest.TestCase):
    def test_policy_limits_automation_identity_and_paths(self):
        policy = json.loads((ROOT / ".handoff-monitoring.json").read_text(encoding="utf-8"))
        self.assertEqual(1, policy["version"])
        self.assertEqual(
            ["github-actions[bot]@users.noreply.github.com"],
            policy["allowed_author_emails"],
        )
        self.assertEqual(
            {
                "data/eth_usdt_4h.csv",
                "paper_trade/equity.csv",
                "paper_trade/state.json",
                "paper_trade/trades.csv",
            },
            set(policy["allowed_paths"]),
        )
        for check in policy["checks"]:
            self.assertTrue((ROOT / check["script"]).is_file())

    def test_current_monitoring_files_are_consistent(self):
        result = subprocess.run(
            [sys.executable, "tools/check_monitoring_state.py", "--ref", "HEAD"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
