import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import sync_catalog as sync_module


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()


class SyncCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "personal"
        git(self.root, "init", "--bare", str(self.remote))
        git(self.root, "clone", str(self.remote), str(self.repo))
        git(self.repo, "config", "user.name", "Wenjin Test")
        git(self.repo, "config", "user.email", "wenjin@example.test")
        git(self.repo, "checkout", "-b", "main")
        self.catalog = self.repo / "catalog.md"
        self.catalog.write_text("# 问津目录\n", encoding="utf-8")
        (self.repo / "README.md").write_text("personal repo\n", encoding="utf-8")
        git(self.repo, "add", "catalog.md", "README.md")
        git(self.repo, "commit", "-m", "Initial catalog")
        git(self.repo, "push", "-u", "origin", "main")
        self.real_command = sync_module.command

    def tearDown(self):
        self.temp.cleanup()

    def fake_command(self, args, cwd, timeout=30):
        if args[0] == "gh":
            return "true"
        return self.real_command(args, cwd, timeout)

    def test_sync_commits_only_catalog_and_preserves_other_staged_file(self):
        self.catalog.write_text("# 问津目录\n\n## 新条目\n", encoding="utf-8")
        (self.repo / "README.md").write_text("unrelated change\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        with patch.object(sync_module, "command", side_effect=self.fake_command), patch.object(
            sync_module, "github_slug", return_value="test/private"
        ):
            result = sync_module.sync_catalog(self.catalog)
        self.assertTrue(result["ok"], result["message"])
        self.assertEqual(git(self.remote, "show", "main:catalog.md"), "# 问津目录\n\n## 新条目")
        self.assertEqual(git(self.remote, "show", "main:README.md"), "personal repo")
        self.assertIn("README.md", git(self.repo, "diff", "--cached", "--name-only"))

    def test_remote_ahead_leaves_local_catalog_uncommitted(self):
        other = self.root / "other"
        git(self.root, "clone", str(self.remote), str(other))
        git(other, "checkout", "main")
        git(other, "config", "user.name", "Other Test")
        git(other, "config", "user.email", "other@example.test")
        (other / "catalog.md").write_text("# 远端更新\n", encoding="utf-8")
        git(other, "commit", "-am", "Remote update")
        git(other, "push", "origin", "main")
        self.catalog.write_text("# 本地更新\n", encoding="utf-8")
        with patch.object(sync_module, "command", side_effect=self.fake_command), patch.object(
            sync_module, "github_slug", return_value="test/private"
        ):
            result = sync_module.sync_catalog(self.catalog)
        self.assertFalse(result["ok"])
        self.assertIn("远端已有新提交", result["message"])
        self.assertEqual(git(self.repo, "show", "HEAD:catalog.md"), "# 问津目录")
        self.assertEqual(self.catalog.read_text(encoding="utf-8"), "# 本地更新\n")

    def test_public_remote_is_not_pushed(self):
        self.catalog.write_text("# 新内容\n", encoding="utf-8")
        def public_command(args, cwd, timeout=30):
            if args[0] == "gh":
                return "false"
            return self.real_command(args, cwd, timeout)

        with patch.object(sync_module, "command", side_effect=public_command), patch.object(
            sync_module, "github_slug", return_value="test/public"
        ):
            result = sync_module.sync_catalog(self.catalog)
        self.assertFalse(result["ok"])
        self.assertIn("不是已确认的 GitHub 私有仓库", result["message"])
        self.assertEqual(git(self.repo, "show", "HEAD:catalog.md"), "# 问津目录")


if __name__ == "__main__":
    unittest.main()
