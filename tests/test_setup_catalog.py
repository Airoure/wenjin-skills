import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import setup_catalog as setup_module
from sync_catalog import SyncError


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()


class SetupCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "personal"
        self.catalog = self.repo / "catalog.md"
        self.remote = self.root / "remote.git"
        self.real_command = setup_module.command

    def tearDown(self):
        self.temp.cleanup()

    def fake_command(self, args, cwd, timeout=30):
        if args[:3] == ["gh", "api", "user"]:
            return json.dumps({"login": "sample", "id": 123})
        if args[:3] == ["gh", "api", "repos/sample/wenjin-catalog"]:
            if not self.remote.exists():
                raise SyncError("gh 失败：HTTP 404")
            return json.dumps({"private": True})
        if args[:3] == ["gh", "repo", "view"]:
            return "false" if (self.remote / "refs" / "heads" / "main").exists() else "true"
        if args[:3] == ["gh", "repo", "create"]:
            git(self.root, "init", "--bare", str(self.remote))
            return ""
        if args[:3] == ["gh", "auth", "setup-git"]:
            return ""
        return self.real_command(args, cwd, timeout)

    def fake_which(self, name):
        return name

    def test_first_use_creates_private_catalog_and_pushes_template(self):
        with patch.object(setup_module.shutil, "which", side_effect=self.fake_which), patch.object(
            setup_module, "command", side_effect=self.fake_command
        ), patch.object(setup_module, "remote_url", return_value=str(self.remote)):
            result = setup_module.setup_catalog(self.catalog)
        self.assertTrue(result["ok"], result["message"])
        self.assertTrue(self.catalog.is_file())
        self.assertIn("问津", git(self.remote, "show", "main:catalog.md"))
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "@{upstream}"), "origin/main")

    def test_new_device_clones_existing_catalog(self):
        git(self.root, "init", "--bare", str(self.remote))
        seed = self.root / "seed"
        git(self.root, "clone", str(self.remote), str(seed))
        git(seed, "checkout", "-b", "main")
        git(seed, "config", "user.name", "Seed")
        git(seed, "config", "user.email", "seed@example.test")
        (seed / "catalog.md").write_text("# 远端已有收藏\n", encoding="utf-8")
        git(seed, "add", "catalog.md")
        git(seed, "commit", "-m", "Seed catalog")
        git(seed, "push", "-u", "origin", "main")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        with patch.object(setup_module.shutil, "which", side_effect=self.fake_which), patch.object(
            setup_module, "command", side_effect=self.fake_command
        ), patch.object(setup_module, "remote_url", return_value=str(self.remote)):
            result = setup_module.setup_catalog(self.catalog)
        self.assertTrue(result["ok"], result["message"])
        self.assertEqual(self.catalog.read_text(encoding="utf-8"), "# 远端已有收藏\n")

    def test_missing_gh_gives_setup_guidance_without_creating_catalog(self):
        with patch.object(setup_module.shutil, "which", side_effect=lambda name: None if name == "gh" else name):
            result = setup_module.setup_catalog(self.catalog)
        self.assertFalse(result["ok"])
        self.assertIn("gh auth login", result["message"])
        self.assertFalse(self.catalog.exists())

    def test_existing_local_files_are_not_overwritten(self):
        git(self.root, "init", "--bare", str(self.remote))
        git(self.root, "clone", str(self.remote), str(self.root / "seed"))
        seed = self.root / "seed"
        git(seed, "checkout", "-b", "main")
        git(seed, "config", "user.name", "Seed")
        git(seed, "config", "user.email", "seed@example.test")
        (seed / "catalog.md").write_text("# 远端\n", encoding="utf-8")
        git(seed, "add", "catalog.md")
        git(seed, "commit", "-m", "Seed catalog")
        git(seed, "push", "origin", "main")
        self.repo.mkdir()
        self.catalog.write_text("# 本地\n", encoding="utf-8")
        with patch.object(setup_module.shutil, "which", side_effect=self.fake_which), patch.object(
            setup_module, "command", side_effect=self.fake_command
        ), patch.object(setup_module, "remote_url", return_value=str(self.remote)):
            result = setup_module.setup_catalog(self.catalog)
        self.assertFalse(result["ok"])
        self.assertIn("避免覆盖", result["message"])
        self.assertEqual(self.catalog.read_text(encoding="utf-8"), "# 本地\n")


if __name__ == "__main__":
    unittest.main()
