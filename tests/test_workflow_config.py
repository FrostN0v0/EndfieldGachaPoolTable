import unittest
from pathlib import Path


class SyncWorkflowConfigTests(unittest.TestCase):
    def setUp(self):
        self.workflow_path = Path(".github/workflows/sync-tablecfg.yml")

    def test_sync_workflow_exists(self):
        self.assertTrue(self.workflow_path.exists())

    def test_sync_workflow_has_required_triggers_and_permissions(self):
        text = self.workflow_path.read_text(encoding="utf-8")
        self.assertIn("schedule:", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("contents: write", text)
        self.assertIn("actions: write", text)

    def test_sync_workflow_runs_sync_script_and_commits_state(self):
        text = self.workflow_path.read_text(encoding="utf-8")
        self.assertIn("uv run --locked sync_tablecfg.py", text)
        self.assertIn("git add TableCfg/ .github/tablecfg-sync-state.json", text)
        self.assertIn("git commit -m", text)

    def test_sync_workflow_dispatches_generation_when_tablecfg_changed(self):
        text = self.workflow_path.read_text(encoding="utf-8")
        self.assertIn("tablecfg_changed", text)
        self.assertIn("gh workflow run update-gacha.yml", text)
        self.assertIn("GH_TOKEN: ${{ github.token }}", text)

    def test_sync_workflow_uses_status_to_detect_untracked_changes(self):
        text = self.workflow_path.read_text(encoding="utf-8")
        self.assertIn("git status --porcelain -- TableCfg", text)
        self.assertIn("git status --porcelain -- TableCfg .github/tablecfg-sync-state.json", text)
        self.assertNotIn("git diff --quiet -- TableCfg", text)


if __name__ == "__main__":
    unittest.main()
