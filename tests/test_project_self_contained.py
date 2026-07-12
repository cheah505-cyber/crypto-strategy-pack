import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectSelfContainedTest(unittest.TestCase):
    def test_required_handoff_files_exist(self):
        for name in ("AGENTS.md", "INDEX.md", "CHANGELOG.md", "DECISIONS.md", "requirements.txt"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_authoritative_docs_do_not_require_obsidian(self):
        for name in ("AGENTS.md", "INDEX.md", "README.md", "ARCHITECTURE.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("Obsidian", text, name)
            self.assertNotIn("Obsidian-Vault", text, name)

    def test_workflow_updates_state_before_signal_and_prevents_overlap(self):
        text = (ROOT / ".github/workflows/signal_check.yml").read_text(encoding="utf-8")
        self.assertIn("concurrency:", text)
        self.assertLess(text.index("python tools/paper_trade.py"), text.index("python tools/manual_signal.py"))

    def test_index_declares_projects_as_source_of_truth(self):
        text = (ROOT / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("唯一事实源", text)
        self.assertIn("AGENTS.md", text)
        self.assertIn("DECISIONS.md", text)
        self.assertIn("CHANGELOG.md", text)

    def test_operational_files_do_not_reference_obsidian(self):
        excluded = {
            Path("tests/test_project_self_contained.py"),
            Path("docs/superpowers/plans/2026-07-12-remove-obsidian-dependency.md"),
        }
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            relative = path.relative_to(ROOT)
            if relative in excluded or path.suffix not in {".md", ".py", ".yml", ".yaml", ".json", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("Obsidian", text, str(relative))
            self.assertNotIn("Obsidian-Vault", text, str(relative))


if __name__ == "__main__":
    unittest.main()
