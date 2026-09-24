#!/usr/bin/env python3
"""Commit and push only the personal Wenjin catalog to its private GitHub repo."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path


class SyncError(Exception):
    pass


def command(args: list[str], cwd: Path, timeout: int = 30) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        result = subprocess.run(
            args, cwd=cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise SyncError(f"缺少命令：{args[0]}。") from exc
    except subprocess.TimeoutExpired as exc:
        raise SyncError(f"{args[0]} 操作超时。") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise SyncError(f"{args[0]} 失败：{detail[-1] if detail else '未知错误'}")
    return result.stdout.strip()


def github_slug(remote: str) -> str:
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?",
        remote,
    )
    if not match:
        raise SyncError("origin 必须指向 GitHub 私有仓库。")
    return f"{match.group(1)}/{match.group(2)}"


def sync_catalog(catalog: Path | None = None) -> dict[str, str | bool]:
    catalog = (catalog or Path.home() / ".wenjin" / "catalog.md").resolve()
    repo = catalog.parent
    try:
        if not catalog.is_file():
            raise SyncError("个人目录 catalog.md 不存在。")
        root = Path(command(["git", "rev-parse", "--show-toplevel"], repo)).resolve()
        if root != repo or catalog.name != "catalog.md":
            raise SyncError("catalog.md 必须位于个人 Git 仓库根目录。")
        remote = command(["git", "remote", "get-url", "origin"], repo)
        slug = github_slug(remote)
        private = command(["gh", "repo", "view", slug, "--json", "isPrivate", "--jq", ".isPrivate"], repo)
        if private != "true":
            raise SyncError("origin 不是已确认的 GitHub 私有仓库，已停止同步。")
        branch = command(["git", "branch", "--show-current"], repo)
        upstream = command(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], repo)
        if not branch or upstream != f"origin/{branch}":
            raise SyncError("当前分支需要跟踪同名 origin 分支。")
        command(["git", "fetch", "origin", branch], repo)
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", upstream, "HEAD"],
            cwd=repo, capture_output=True, check=False,
        )
        if ancestor.returncode:
            raise SyncError("远端已有新提交或分支已分叉，请先处理冲突。")
        ahead = command(["git", "log", "--format=%H", f"{upstream}..HEAD"], repo).splitlines()
        for commit in ahead:
            if len(command(["git", "show", "-s", "--format=%P", commit], repo).split()) != 1:
                raise SyncError("本地有合并提交，已停止自动同步。")
            changed = command(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit], repo).splitlines()
            if any(path != "catalog.md" for path in changed):
                raise SyncError("本地有涉及其他文件的未推送提交，已停止自动同步。")
        dirty = bool(command(["git", "status", "--porcelain", "--", "catalog.md"], repo))
        if dirty:
            command(["git", "add", "--", "catalog.md"], repo)
            command(["git", "commit", "--only", "-m", "Update Wenjin catalog", "--", "catalog.md"], repo)
        if dirty or ahead:
            command(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], repo, timeout=60)
            return {"ok": True, "message": f"已同步到私有仓库 {slug} 的 {branch} 分支。"}
        return {"ok": True, "message": "个人目录已与 GitHub 同步，无需新提交。"}
    except SyncError as exc:
        return {"ok": False, "message": f"已保存在本地，未同步到 GitHub：{exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="同步问津个人目录到已配置的 GitHub 私有仓库")
    parser.add_argument("--catalog", type=Path, help="个人目录路径；默认 ~/.wenjin/catalog.md")
    args = parser.parse_args()
    result = sync_catalog(args.catalog)
    print(result["message"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
