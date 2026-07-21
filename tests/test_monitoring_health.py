from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


PATH = Path(__file__).resolve().parents[1] / "tools" / "check_monitoring_health.py"
SPEC = importlib.util.spec_from_file_location("check_monitoring_health", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MonitoringHealthTests(unittest.TestCase):
    def test_accepts_recent_success(self):
        now = datetime(2026, 7, 21, 8, tzinfo=timezone.utc)
        errors = MODULE.evaluate(
            {"state": "active"},
            [{"status": "completed", "conclusion": "success", "updatedAt": "2026-07-21T07:00:00Z"}],
            360, now,
        )
        self.assertEqual([], errors)

    def test_rejects_disabled_or_stale(self):
        now = datetime(2026, 7, 21, 8, tzinfo=timezone.utc)
        errors = MODULE.evaluate(
            {"state": "disabled_manually"},
            [{"status": "completed", "conclusion": "success", "updatedAt": "2026-07-20T00:00:00Z"}],
            360, now,
        )
        self.assertEqual(2, len(errors))


if __name__ == "__main__":
    unittest.main()
