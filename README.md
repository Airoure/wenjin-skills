# 问津 · wenjin

> 遇事寻法，不必记名。

问津是一个个人提示词与 Agent Skill 导航目录。你描述当前处境，它从已收录的条目中找出适合的一项；看到值得留下的 Skill，可以直接在 Codex 收录，也可以使用本地网页表单。

## 直接在 Codex 收录

在输入框键入 `/`，搜索并选择 `Wenjin:shoulu`，然后贴上要收录的链接；也可以直接说“用问津收录这个链接：……”或输入 `$wenjin-shoulu`。Agent 会按问津的规则检查来源，并把条目写入 `~/.wenjin/catalog.md`。这条路径无需启动本地网页，也不会自动安装外部 Skill。写入后会自动尝试同步到已配置的 GitHub 私有仓库，并报告结果。

## 打开收录表单

需要 Python 3.10 或更新版本，不需要安装第三方 Python 包。在本仓库目录运行：

```powershell
python app.py
```

然后打开 **http://127.0.0.1:8765/**。如端口被占用，可运行 `python app.py --port 8877`。

1. 粘贴公开 GitHub 仓库、文件夹或具体 `SKILL.md` 的链接。
2. 仓库内有多件 Skill 时，选出要收录的一件。表单会读取名称、描述、固定提交链接和仓库许可提示。
3. 用自己的话补充适用场景与不适用场景，点击 **存入问津**。

其他网站的链接可以点 **手动填写**。保存后，条目会以“候选”状态写入个人目录 `~/.wenjin/catalog.md`；首次保存时会按[空白模板](skills/wenjin/references/catalog.example.md)创建该文件。表单会自动尝试同步到 GitHub 私有仓库，并在页面显示成功或失败；失败时本地条目仍保留。表单只监听本机地址；收录不会安装或运行外部 Skill。GitHub 自动读取使用公开 API，遇到访问限制时仍可手动填写。

## 让 Agent 整理分类

网页收录的新条目先放在“未分类”，标签留空。收录若干件后，在已能读取 `skills/wenjin` 和个人目录 `~/.wenjin/catalog.md` 的 Agent 中说：

> 用问津整理分类。

Agent 会按用途给未分类条目选一个主分类、补一至三个标签，并写回目录；依据不足的条目继续留在“未分类”。网页刷新后可看到分类、标签，并按分类筛选。已有分类和标签默认不重做；需要全部重新判断时说“用问津重新整理所有分类”。分类不会改变“候选 / 已试用”等试用状态。

## 在 Agent 中使用

- 找方法：「用问津看看，我现在有两个都不错的方案，不知道怎么选。」
- 用一件已收录的 Skill：「用问津里的 XXX 帮我完成这件事。」
- 校正推荐：「这条不适合，因为……」

导航与收录规则在 [skills/wenjin/SKILL.md](skills/wenjin/SKILL.md)。整个 `skills/wenjin` 文件夹是一件 Skill。将它放入目标 Agent 的个人 Skill 目录即可使用：Codex 为 `~/.agents/skills/`，Claude Code 为 `~/.claude/skills/`，Cursor 为 `~/.cursor/skills/`（Cursor 也读取 `~/.agents/skills/`）。不同 Agent 的自动选择和调用其他 Skill 的能力可能不同；问津始终可以给出推荐理由和来源链接。

在 Codex 中想用快捷入口，可将 [分类](skills/wenjin-fenlei/SKILL.md) 和 [收录](skills/wenjin-shoulu/SKILL.md) 两件 Skill 也放入与 `wenjin` 相同的目录。在输入框键入 `/` 后分别搜索 `Wenjin:fenlei` 或 `Wenjin:shoulu`；分类也可输入 `$wenjin-fenlei`。分类入口会按问津的规则整理当前未分类条目。

通过问津实际试用一件尚未安装的 Skill 后，Agent 会询问你是否将它加入当前项目或个人的 Skill 目录，也可以选择暂不添加。仅收录或推荐不会触发安装；临时使用所需的文件或工具无法取得时，Agent 会先说明原因。

本仓库只维护问津的程序、Skill 规则和空白模板；个人收录目录放在 `~/.wenjin/catalog.md`。自动同步要求 `~/.wenjin` 是 Git 仓库、当前分支跟踪同名的 `origin` 分支、`origin` 指向 GitHub 私有仓库，并且本机 `gh` 已登录。同步脚本只提交 `catalog.md`，不会强推；远端有新提交或本地有其他未推送提交时会停止并提示处理。同步失败后可在问津代码仓库运行 `python skills/wenjin/scripts/sync_catalog.py` 重试。若在多处复制安装 `wenjin`，每处的规则文件会独立变化；想保持一份规则，请把个人 Skill 目录中的 `wenjin` 链接到本仓库的 `skills/wenjin`，或每次更新后重新同步。目录中记录的是外部 Skill 的来源与自己的摘要，不是外部 Skill 的完整安装包。

## 收录原则

先记录来源、适用场景和自己的使用笔记；试用后再标记为已试用。外部 Skill 的 `SKILL.md`、脚本和附带文件属于外部内容，收录链接时不自动安装或执行。公开分发他人的原文前，先核对对应许可与署名要求。

目录状态：`候选` 表示尚未真实试用；`已试用` 表示至少用一个真实任务检验；`常用` 表示反复使用且边界清楚；`归档` 表示不再推荐但保留记录。

## 开发检查

```powershell
python -X utf8 -m unittest discover -s tests -v
```
