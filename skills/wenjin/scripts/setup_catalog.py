#!/usr/bin/env python3
"""Prepare ~/.wenjin from the signed-in user's private GitHub repository."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from sync_catalog import SyncError, command, github_slug


TEMPLATE = Path(__file__).resolve().parent.parent / "references" / "catalog.example.md"
REPO_NAME = "wenjin-catalog"
GH_INSTALL = "https://cli.github.com/"


def remote_url(slug: str) -> str:
    return f"https://github.com/{slug}.git"


def gh_user(cwd: Path) -> tuple[str, int]:
    try:
        data = json.loads(command(["gh", "api", "user", "--jq", "{login:.login,id:.id}"], cwd))
    except (SyncError, ValueError) as exc:
        raise SyncError("gh 尚未登录或登录已失效。请运行 `gh auth login` 后重试。") from exc
    login, user_id = data.get("login"), data.get("id")
    if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]+", login) or not isinstance(user_id, int):
        raise SyncError("无法识别当前 GitHub 账号。请检查 `gh auth status`。")
    return login, user_id


def remote_state(slug: str, cwd: Path) -> str:
    try:
        data = json.loads(command(
            ["gh", "api", f"repos/{slug}", "--jq", "{private:.private}"], cwd,
        ))
    except SyncError as exc:
        if "HTTP 404" in str(exc):
            return "missing"
        raise
    except ValueError as exc:
        raise SyncError("GitHub 仓库信息无法读取。") from exc
    if data.get("private") is not True:
        raise SyncError(f"{slug} 已存在但不是私有仓库，已停止配置。")
    empty = command(["gh", "repo", "view", slug, "--json", "isEmpty", "--jq", ".isEmpty"], cwd)
    return "empty" if empty == "true" else "existing"


def ensure_git_identity(repo: Path, login: str, user_id: int) -> None:
    for key, value in (
        ("user.name", login),
        ("user.email", f"{user_id}+{login}@users.noreply.github.com"),
    ):
        try:
            current = command(["git", "config", "--get", key], repo)
        except SyncError:
            current = ""
        if not current:
            command(["git", "config", "--local", key, value], repo)


def prepare_existing_repo(repo: Path, catalog: Path) -> str:
    root = Path(command(["git", "rev-parse", "--show-toplevel"], repo)).resolve()
    if root != repo:
        raise SyncError("个人目录必须是独立 Git 仓库，不能位于其他仓库内部。")
    remote = command(["git", "remote", "get-url", "origin"], repo)
    slug = github_slug(remote)
    info = json.loads(command(["gh", "api", f"repos/{slug}", "--jq", "{private:.private}"], repo))
    if info.get("private") is not True:
        raise SyncError("origin 不是 GitHub 私有仓库，已停止配置。")
    branch = command(["git", "branch", "--show-current"], repo)
    upstream = command(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], repo)
    if not branch or upstream != f"origin/{branch}":
        raise SyncError("当前分支需要跟踪同名 origin 分支。")
    command(["git", "fetch", "origin", branch], repo)
    dirty = bool(command(["git", "status", "--porcelain"], repo))
    if not dirty:
        command(["git", "merge", "--ff-only", upstream], repo)
    if not catalog.is_file():
        raise SyncError("远端目录中没有 catalog.md，请确认仓库用途。")
    return f"已连接私有仓库 {slug}" + ("；本地有未提交改动，暂未拉取远端更新。" if dirty else "，目录已更新。")


def create_local_repo(repo: Path, catalog: Path, slug: str, login: str, user_id: int) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    if not catalog.exists():
        shutil.copyfile(TEMPLATE, catalog)
    command(["git", "init", "-b", "main"], repo)
    command(["git", "remote", "add", "origin", remote_url(slug)], repo)
    ensure_git_identity(repo, login, user_id)
    command(["git", "add", "--", "catalog.md"], repo)
    command(["git", "commit", "-m", "Initialize Wenjin catalog", "--", "catalog.md"], repo)
    command(["git", "push", "-u", "origin", "main"], repo, timeout=60)
    return f"已创建并连接私有仓库 {slug}。"


def setup_catalog(catalog: Path | None = None) -> dict[str, str | bool]:
    catalog = (catalog or Path.home() / ".wenjin" / "catalog.md").resolve()
    repo = catalog.parent
    try:
        if catalog.name != "catalog.md":
            raise SyncError("目录文件名必须是 catalog.md。")
        if not shutil.which("git"):
            raise SyncError("未找到 Git。请先安装 Git，再重试。")
        if not shutil.which("gh"):
            raise SyncError(f"未找到 GitHub CLI。请先安装 gh（{GH_INSTALL}），运行 `gh auth login` 后重试。")
        login, user_id = gh_user(Path(__file__).resolve().parent)
        if (repo / ".git").exists():
            message = prepare_existing_repo(repo, catalog)
            return {"ok": True, "message": message}
        slug = f"{login}/{REPO_NAME}"
        state = remote_state(slug, Path(__file__).resolve().parent)
        if state == "missing":
            command(["gh", "repo", "create", slug, "--private", "--description", "Personal Wenjin catalog"], Path(__file__).resolve().parent)
            state = "empty"
        if state == "existing":
            if repo.exists() and any(repo.iterdir()):
                raise SyncError(f"本地 {repo} 已有文件，远端 {slug} 也有目录；为避免覆盖，请先手动合并。")
            repo.parent.mkdir(parents=True, exist_ok=True)
            command(["gh", "auth", "setup-git", "--hostname", "github.com"], Path(__file__).resolve().parent)
            command(["git", "clone", remote_url(slug), str(repo)], repo.parent, timeout=60)
            if not catalog.is_file():
                raise SyncError(f"远端 {slug} 没有 catalog.md，请确认仓库用途。")
            return {"ok": True, "message": f"已从私有仓库 {slug} 取回个人目录。"}
        command(["gh", "auth", "setup-git", "--hostname", "github.com"], Path(__file__).resolve().parent)
        message = create_local_repo(repo, catalog, slug, login, user_id)
        return {"ok": True, "message": message}
    except (SyncError, OSError, ValueError) as exc:
        return {"ok": False, "message": f"问津目录尚未完成 GitHub 配置：{exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="首次使用时配置或取回问津个人目录")
    parser.add_argument("--catalog", type=Path, help="个人目录路径；默认 ~/.wenjin/catalog.md")
    args = parser.parse_args()
    result = setup_catalog(args.catalog)
    print(result["message"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
