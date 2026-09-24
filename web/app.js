const token = document.querySelector('meta[name="csrf-token"]').content;
const sourceForm = document.querySelector("#source-form");
const sourceInput = document.querySelector("#source-url");
const sourceMessage = document.querySelector("#source-message");
const inspectButton = document.querySelector("#inspect-button");
const manualButton = document.querySelector("#manual-button");
const choicePanel = document.querySelector("#choice-panel");
const choiceSelect = document.querySelector("#skill-choice");
const chooseButton = document.querySelector("#choose-button");
const draftPanel = document.querySelector("#draft-panel");
const draftForm = document.querySelector("#draft-form");
const saveButton = document.querySelector("#save-button");
const saveMessage = document.querySelector("#save-message");
const entryList = document.querySelector("#entry-list");
const entryCount = document.querySelector("#entry-count");
const categoryFilter = document.querySelector("#category-filter");
let allEntries = [];

function message(node, text, isError = false) {
  node.textContent = text;
  node.classList.toggle("error", isError);
  node.hidden = !text;
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: payload ? "POST" : "GET",
    headers: payload
      ? { "Content-Type": "application/json", "X-Wenjin-Token": token }
      : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求未完成，请重试。");
  return data;
}

function setDraft(data) {
  for (const name of ["name", "author", "source", "version", "license", "when", "not_when", "trigger", "behavior", "entry", "notes"]) {
    const field = draftForm.elements.namedItem(name);
    if (field) field.value = data[name] || "";
  }
  draftPanel.hidden = false;
  message(saveMessage, "");
  draftPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  draftForm.elements.namedItem("when").focus({ preventScroll: true });
}

async function inspect(path = null) {
  const url = sourceInput.value.trim();
  if (!url) {
    message(sourceMessage, "请先粘贴 GitHub 链接。", true);
    sourceInput.focus();
    return;
  }
  inspectButton.disabled = true;
  chooseButton.disabled = true;
  message(sourceMessage, "正在读取 GitHub 来源…");
  try {
    const data = await api("/api/inspect", { url, path });
    if (data.kind === "choose") {
      choiceSelect.replaceChildren();
      for (const skillPath of data.paths) {
        const option = document.createElement("option");
        option.value = skillPath;
        option.textContent = skillPath;
        choiceSelect.append(option);
      }
      choicePanel.hidden = false;
      draftPanel.hidden = true;
      message(sourceMessage, `找到 ${data.paths.length}${data.more ? "+" : ""} 件 Skill。请选择要收录的一件。`);
    } else {
      choicePanel.hidden = true;
      setDraft(data);
      message(sourceMessage, "已读取基本信息。请核对适用场景后保存。");
    }
  } catch (error) {
    message(sourceMessage, error.message, true);
  } finally {
    inspectButton.disabled = false;
    chooseButton.disabled = false;
  }
}

sourceForm.addEventListener("submit", (event) => {
  event.preventDefault();
  inspect();
});
chooseButton.addEventListener("click", () => inspect(choiceSelect.value));
manualButton.addEventListener("click", () => {
  choicePanel.hidden = true;
  setDraft({ source: sourceInput.value.trim() });
  message(sourceMessage, "已打开手动填写。");
});

function renderEntries() {
  entryCount.textContent = allEntries.length;
  const selected = categoryFilter.value;
  const entries = allEntries.filter((entry) => !selected || entry.category === selected);
  entryList.replaceChildren();
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = allEntries.length ? "这个分类里还没有 Skill。" : "目录还是空的。从上面的第一条链接开始。";
    entryList.append(empty);
    return;
  }
  for (const entry of entries.slice().reverse()) {
    const item = document.createElement("article");
    item.className = "entry";
    const top = document.createElement("div");
    top.className = "entry-top";
    const name = document.createElement("span");
    name.className = "entry-name";
    name.textContent = entry.name;
    const status = document.createElement("span");
    status.className = "entry-status";
    status.textContent = entry.status;
    top.append(name, status);
    const metadata = document.createElement("div");
    metadata.className = "entry-metadata";
    const category = document.createElement("span");
    category.className = "entry-category";
    category.textContent = entry.category;
    metadata.append(category);
    for (const tag of entry.tags) {
      const label = document.createElement("span");
      label.className = "entry-tag";
      label.textContent = `#${tag}`;
      metadata.append(label);
    }
    const when = document.createElement("p");
    when.textContent = entry.when;
    const link = document.createElement("a");
    link.href = entry.source;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "查看原始来源 ↗";
    item.append(top, metadata, when, link);
    entryList.append(item);
  }
}

async function refreshEntries() {
  try {
    const setup = await api("/api/setup", {});
    if (!setup.ok) message(sourceMessage, setup.message, true);
    const data = await api("/api/entries");
    allEntries = data.entries;
    const selected = categoryFilter.value;
    const categories = [...new Set(allEntries.map((entry) => entry.category))].sort((a, b) => a.localeCompare(b, "zh-CN"));
    categoryFilter.replaceChildren(new Option("全部分类", ""));
    for (const category of categories) categoryFilter.add(new Option(category, category));
    categoryFilter.value = categories.includes(selected) ? selected : "";
    renderEntries();
  } catch (error) {
    entryList.textContent = error.message;
  }
}

categoryFilter.addEventListener("change", renderEntries);

draftForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  saveButton.disabled = true;
  message(saveMessage, "正在保存到问津目录…");
  try {
    const data = Object.fromEntries(new FormData(draftForm).entries());
    const saved = await api("/api/save", data);
    const status = `已收录「${saved.name}」，状态为候选。${saved.sync.message}`;
    message(saveMessage, status, !saved.sync.ok);
    message(sourceMessage, status, !saved.sync.ok);
    await refreshEntries();
    sourceInput.value = "";
    draftPanel.hidden = true;
    choicePanel.hidden = true;
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    message(saveMessage, error.message, true);
  } finally {
    saveButton.disabled = false;
  }
});

refreshEntries();
