#!/usr/bin/env python3
"""问津：只在本机运行的 Skill 收录表单。"""

from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "skills" / "wenjin" / "scripts"))
from sync_catalog import sync_catalog
from setup_catalog import setup_catalog

WEB = ROOT / "web"
CATALOG = Path.home() / ".wenjin" / "catalog.md"
CATALOG_TEMPLATE = ROOT / "skills" / "wenjin" / "references" / "catalog.example.md"
MAX_BODY = 32_768
MAX_GITHUB_RESPONSE = 4_000_000
WRITE_LOCK = threading.Lock()
SAVE_SYNC_LOCK = threading.Lock()
SETUP_CACHE = None
TOKEN = secrets.token_urlsafe(32)
REPO_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


class AppError(Exception):
    pass


def prepare_catalog() -> dict:
    global SETUP_CACHE
    now = time.monotonic()
    if SETUP_CACHE and SETUP_CACHE[0] == CATALOG and now - SETUP_CACHE[1] < 60:
        return SETUP_CACHE[2]
    result = setup_catalog(CATALOG)
    SETUP_CACHE = (CATALOG, now, result) if result["ok"] else None
    return result


def github_json(url: str) -> dict:
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "wenjin-skills-local-form",
        },
    )
    try:
        with urlopen(req, timeout=12) as response:
            raw = response.read(MAX_GITHUB_RESPONSE + 1)
    except HTTPError as exc:
        if exc.code == 403:
            raise AppError("GitHub 暂时拒绝了请求，可能是访问次数达到限制。可以稍后再试，或手动填写。") from exc
        if exc.code == 404:
            raise AppError("没有找到这个公开仓库或文件。请检查链接，也可以手动填写。") from exc
        raise AppError(f"GitHub 返回 HTTP {exc.code}。可以稍后再试或手动填写。") from exc
    except (URLError, TimeoutError) as exc:
        raise AppError("暂时无法连接 GitHub。请检查网络，或手动填写。") from exc
    if len(raw) > MAX_GITHUB_RESPONSE:
        raise AppError("仓库信息过大，请使用具体的 SKILL.md 链接。")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("GitHub 返回的数据无法读取。") from exc


def parse_github_url(value: str) -> tuple[str, str, str | None, str | None]:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise AppError("自动读取目前支持 github.com 链接；其他来源可用“手动填写”。")
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) < 2:
        raise AppError("请粘贴 GitHub 仓库或具体 SKILL.md 的链接。")
    owner, repo = segments[0], segments[1].removesuffix(".git")
    if not REPO_PART.fullmatch(owner) or not REPO_PART.fullmatch(repo):
        raise AppError("GitHub 仓库地址格式不正确。")
    if len(segments) == 2:
        return owner, repo, None, None
    if len(segments) < 4 or segments[2] not in {"blob", "tree"}:
        raise AppError("请使用仓库首页或 GitHub 上的 SKILL.md / 文件夹链接。")
    ref = segments[3]
    path = "/".join(segments[4:]) or None
    return owner, repo, ref, path


def frontmatter(text: str) -> dict[str, str]:
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return {}
    end = normalized.find("\n---", 4)
    if end < 0:
        return {}
    rows = normalized[4:end].splitlines()
    result: dict[str, str] = {}
    current = None
    for row in rows:
        match = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", row)
        if match:
            current = match.group(1)
            value = match.group(2).strip()
            if value in {">", ">-", "|", "|-"}:
                result[current] = ""
            else:
                result[current] = value.strip("'\"")
        elif current and row.startswith((" ", "\t")):
            result[current] = (result[current] + " " + row.strip()).strip()
        else:
            current = None
    return result


def clean(value: object, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].strip()


def inspect_github(url: str, selected_path: str | None = None) -> dict:
    owner, repo, ref, hinted_path = parse_github_url(url)
    base = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
    info = github_json(base)
    ref = ref or info.get("default_branch")
    if not ref:
        raise AppError("无法确定仓库版本，请使用具体的提交链接。")
    commit = github_json(base + "/commits/" + quote(ref, safe=""))
    sha = commit.get("sha")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise AppError("无法确定 GitHub 提交版本。")
    tree = github_json(base + "/git/trees/" + sha + "?recursive=1")
    if tree.get("truncated"):
        raise AppError("仓库文件列表过大，请使用具体的 SKILL.md 链接。")
    paths = sorted(
        item.get("path", "")
        for item in tree.get("tree", [])
        if item.get("type") == "blob"
        and (item.get("path", "").endswith("/SKILL.md") or item.get("path") == "SKILL.md")
    )
    if not hinted_path and not selected_path:
        primary = [p for p in paths if not p.startswith("vendor/")]
        if primary:
            paths = primary
    if hinted_path:
        if hinted_path.endswith("/SKILL.md") or hinted_path == "SKILL.md":
            paths = [p for p in paths if p == hinted_path]
        else:
            prefix = hinted_path.rstrip("/") + "/"
            paths = [p for p in paths if p.startswith(prefix)]
    if selected_path:
        paths = [p for p in paths if p == selected_path]
    if not paths:
        raise AppError("这个位置没有找到 SKILL.md。请检查链接或手动填写。")
    if len(paths) > 1:
        return {
            "kind": "choose",
            "paths": paths[:120],
            "more": len(paths) > 120,
        }
    path = paths[0]
    encoded_path = quote(path, safe="/")
    file_data = github_json(base + "/contents/" + encoded_path + "?ref=" + sha)
    if file_data.get("encoding") != "base64" or not file_data.get("content"):
        raise AppError("无法读取 SKILL.md 内容，请手动填写。")
    try:
        raw = base64.b64decode(file_data["content"], validate=False)
        skill_text = raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("SKILL.md 不是可读取的 UTF-8 文本。") from exc
    if len(raw) > 300_000:
        raise AppError("SKILL.md 过大，请手动填写。")
    meta = frontmatter(skill_text)
    folder = path.rsplit("/", 2)[-2] if "/" in path else repo
    license_info = info.get("license") or {}
    spdx = license_info.get("spdx_id")
    license_label = f"仓库标注 {spdx}；具体 Skill 待核实" if spdx and spdx != "NOASSERTION" else "未核实"
    skill_root = path.rsplit("/", 1)[0] if "/" in path else ""
    has_scripts = any(
        item.get("path", "").startswith(skill_root + "/scripts/")
        for item in tree.get("tree", [])
    ) if skill_root else False
    source = f"https://github.com/{owner}/{repo}/blob/{sha}/{encoded_path}"
    return {
        "kind": "skill",
        "name": clean(meta.get("name") or folder, 100),
        "author": "",
        "source": source,
        "version": sha,
        "license": license_label,
        "when": clean(meta.get("description"), 500),
        "not_when": "",
        "trigger": "",
        "behavior": "未核实（含脚本，请检查）" if has_scripts else "未核实",
        "entry": clean(meta.get("name") or folder, 100),
        "notes": "",
        "raw_description": clean(meta.get("description"), 500),
        "has_scripts": has_scripts,
        "repo": f"{owner}/{repo}",
        "path": path,
    }


def entries_from_catalog() -> list[dict]:
    text = CATALOG.read_text(encoding="utf-8") if CATALOG.exists() else ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    entries = []
    for block in re.split(r"(?=^## )", text, flags=re.M):
        match = re.match(r"^## (.+)", block)
        if not match:
            continue
        fields = dict(re.findall(r"^- ([^：]+)：(.*)$", block, flags=re.M))
        entries.append(
            {
                "name": match.group(1).strip(),
                "source": fields.get("来源", "").strip(),
                "status": fields.get("状态", "").strip(),
                "when": fields.get("适用", "").strip(),
                "category": fields.get("分类", "").strip() or "未分类",
                "tags": [tag.strip() for tag in re.split(r"[、,，]", fields.get("标签", "")) if tag.strip()],
            }
        )
    return entries


FIELDS = {
    "author": "作者",
    "source": "来源",
    "version": "版本",
    "license": "许可",
    "when": "适用",
    "not_when": "不适用",
    "trigger": "我会这样提问",
    "behavior": "所需工具与行为",
    "entry": "使用入口",
    "category": "分类",
    "tags": "标签",
    "status": "状态",
    "notes": "试用笔记",
}


def save_entry(payload: dict) -> dict:
    name = clean(payload.get("name"), 100)
    source = clean(payload.get("source"), 1_000)
    when = clean(payload.get("when"), 500)
    if not name or not source or not when:
        raise AppError("请填写名称、来源链接和适用场景。")
    parsed = urlparse(source)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AppError("来源需要是完整的 https:// 链接。")
    if len(name) > 100 or any(x in name for x in "\r\n#"):
        raise AppError("名称格式不正确。")
    values = {key: clean(payload.get(key), 1_000 if key == "source" else 500) for key in FIELDS}
    values["source"] = source
    values["when"] = when
    values["category"] = "未分类"
    values["tags"] = ""
    values["status"] = "候选"
    lines = [f"## {name}", ""]
    for key, label in FIELDS.items():
        default = "" if key == "tags" else "未核实"
        lines.append(f"- {label}：{values[key] or default}")
    entry_text = "\n".join(lines) + "\n"
    with WRITE_LOCK:
        existing = (
            CATALOG.read_text(encoding="utf-8")
            if CATALOG.exists()
            else CATALOG_TEMPLATE.read_text(encoding="utf-8")
        )
        if any(item["source"].casefold() == source.casefold() for item in entries_from_catalog()):
            raise AppError("这个来源链接已收录，请在目录中更新原条目。")
        existing = existing.replace("当前尚无条目。\n", "")
        CATALOG.parent.mkdir(parents=True, exist_ok=True)
        with CATALOG.open("w", encoding="utf-8", newline="\n") as file:
            file.write(existing.rstrip() + "\n\n" + entry_text)
    return {"name": name, "source": source, "status": "候选"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Wenjin/0.1"

    def _headers(self, code: int, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        self.end_headers()

    def _json(self, code: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self._headers(code, "application/json; charset=utf-8")
        self.wfile.write(data)

    def _same_origin(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        allowed = f"127.0.0.1:{self.server.server_port}"
        return host == allowed and (origin is None or origin == f"http://{allowed}")

    def do_GET(self):
        if not self._same_origin():
            self._json(403, {"error": "仅允许从本机页面访问。"})
            return
        if self.path == "/api/entries":
            with SAVE_SYNC_LOCK:
                self._json(200, {"entries": entries_from_catalog()})
            return
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "application/javascript; charset=utf-8"),
        }
        if self.path not in files:
            self._json(404, {"error": "页面不存在。"})
            return
        filename, content_type = files[self.path]
        data = (WEB / filename).read_bytes()
        if filename == "index.html":
            data = data.replace(b"__WENJIN_TOKEN__", TOKEN.encode("ascii"))
        self._headers(200, content_type)
        self.wfile.write(data)

    def do_POST(self):
        if not self._same_origin() or self.headers.get("X-Wenjin-Token") != TOKEN:
            self._json(403, {"error": "页面验证失败，请刷新后重试。"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_BODY:
                raise AppError("提交内容过大或为空。")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise AppError("表单数据格式不正确。")
            if self.path == "/api/setup":
                with SAVE_SYNC_LOCK:
                    result = prepare_catalog()
            elif self.path == "/api/inspect":
                result = inspect_github(str(data.get("url", "")), data.get("path"))
            elif self.path == "/api/save":
                with SAVE_SYNC_LOCK:
                    setup = prepare_catalog()
                    if not setup["ok"] and not CATALOG.is_file():
                        raise AppError(str(setup["message"]))
                    result = save_entry(data)
                    result["sync"] = sync_catalog(CATALOG) if setup["ok"] else {
                        "ok": False,
                        "message": f"已保存在本地，未同步到 GitHub：{setup['message']}",
                    }
            else:
                self._json(404, {"error": "接口不存在。"})
                return
            self._json(200, result)
        except (AppError, ValueError, UnicodeDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, format: str, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


def main():
    parser = argparse.ArgumentParser(description="在本机打开问津收录表单")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"问津收录表单：http://127.0.0.1:{server.server_port}/")
    print("按 Ctrl+C 停止。表单只在本机开放。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
