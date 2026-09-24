import base64
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = Path(self.temp.name) / "catalog.md"
        self.catalog.write_text(
            "# 问津目录\n\n当前尚无条目。\n\n<!--\n## 示例\n- 来源：https://example.com/template\n-->\n",
            encoding="utf-8",
        )
        self.original = app.CATALOG
        app.CATALOG = self.catalog

    def tearDown(self):
        app.CATALOG = self.original
        self.temp.cleanup()

    def test_save_candidate_and_reject_duplicate(self):
        payload = {
            "name": "测试 Skill",
            "source": "https://github.com/example/skills/blob/abc/SKILL.md",
            "when": "需要核查公开说法",
        }
        result = app.save_entry(payload)
        self.assertEqual(result["status"], "候选")
        entries = app.entries_from_catalog()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "测试 Skill")
        self.assertEqual(entries[0]["category"], "未分类")
        self.assertEqual(entries[0]["tags"], [])
        self.assertNotIn("当前尚无条目", self.catalog.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(app.AppError, "已收录"):
            app.save_entry(payload)
        self.assertEqual(len(app.entries_from_catalog()), 1)

    def test_save_initializes_missing_personal_catalog(self):
        self.catalog.unlink()
        app.save_entry({
            "name": "个人条目",
            "source": "https://github.com/example/skills/blob/abc/SKILL.md",
            "when": "需要记录方法",
        })
        self.assertTrue(self.catalog.exists())
        self.assertEqual([entry["name"] for entry in app.entries_from_catalog()], ["个人条目"])
        self.assertIn("- 分类：未分类", self.catalog.read_text(encoding="utf-8"))

    def test_agent_category_edit_appears_in_catalog_api(self):
        app.save_entry({
            "name": "解释概念",
            "source": "https://github.com/example/skills/blob/abc/SKILL.md",
            "when": "理解一个新概念",
        })
        text = self.catalog.read_text(encoding="utf-8")
        text = text.replace("- 分类：未分类", "- 分类：学习理解")
        text = text.replace("- 标签：\n", "- 标签：概念解释、入门学习\n")
        self.catalog.write_text(text, encoding="utf-8")
        entry = app.entries_from_catalog()[0]
        self.assertEqual(entry["category"], "学习理解")
        self.assertEqual(entry["tags"], ["概念解释", "入门学习"])

    def test_local_http_form_saves_to_catalog(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            with urlopen(url + "/") as response:
                self.assertIn(b"wenjin", response.read().lower())
            payload = {
                "name": "浏览器候选",
                "source": "https://github.com/example/browser/blob/abc/SKILL.md",
                "when": "通过网页收录",
            }
            request = Request(
                url + "/api/save",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-Wenjin-Token": app.TOKEN,
                },
            )
            with patch.object(app, "sync_catalog", return_value={"ok": True, "message": "已同步。"}) as sync:
                with urlopen(request) as response:
                    saved = json.load(response)
            self.assertEqual(saved["status"], "候选")
            self.assertEqual(saved["sync"], {"ok": True, "message": "已同步。"})
            sync.assert_called_once_with(self.catalog)
            self.assertEqual(len(app.entries_from_catalog()), 1)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_invalid_source_does_not_write(self):
        with self.assertRaisesRegex(app.AppError, "https"):
            app.save_entry({"name": "坏链接", "source": "javascript:alert(1)", "when": "测试"})
        self.assertEqual(app.entries_from_catalog(), [])


class GithubInspectTests(unittest.TestCase):
    def test_repository_lists_primary_skills_and_pins_selection(self):
        sha = "a" * 40
        skill = b"---\nname: sample-skill\ndescription: Helps compare two decisions.\n---\n"
        data = {
            "repo": {"default_branch": "main", "license": {"spdx_id": "MIT"}},
            "commit": {"sha": sha},
            "tree": {
                "tree": [
                    {"type": "blob", "path": "skills/one/SKILL.md"},
                    {"type": "blob", "path": "skills/two/SKILL.md"},
                    {"type": "blob", "path": "vendor/one/SKILL.md"},
                ],
                "truncated": False,
            },
            "file": {"encoding": "base64", "content": base64.b64encode(skill).decode()},
        }

        def fake_github_json(url):
            if "/contents/" in url:
                return data["file"]
            if "/git/trees/" in url:
                return data["tree"]
            if "/commits/" in url:
                return data["commit"]
            return data["repo"]

        with patch.object(app, "github_json", side_effect=fake_github_json):
            choices = app.inspect_github("https://github.com/example/repo")
            self.assertEqual(choices["paths"], ["skills/one/SKILL.md", "skills/two/SKILL.md"])
            selected = app.inspect_github("https://github.com/example/repo", "skills/one/SKILL.md")
        self.assertEqual(selected["name"], "sample-skill")
        self.assertIn(sha, selected["source"])
        self.assertEqual(selected["when"], "Helps compare two decisions.")

    def test_only_github_is_fetched(self):
        with self.assertRaisesRegex(app.AppError, "github.com"):
            app.parse_github_url("http://127.0.0.1/private")


if __name__ == "__main__":
    unittest.main()
