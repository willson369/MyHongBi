const state = {
  category: "职场吐槽",
  history: [],
};

document.addEventListener("DOMContentLoaded", () => {
  checkConfig();
  bindCategorySeg();
});

function bindCategorySeg() {
  const seg = document.getElementById("category-seg");
  if (!seg) return;
  seg.querySelectorAll(".seg-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      seg.querySelectorAll(".seg-item").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.category = btn.dataset.value;
    });
  });
}

function jumpToWorkspace() {
  const heroUrl = document.getElementById("hero-url")?.value?.trim();
  if (heroUrl) {
    document.getElementById("single-url").value = heroUrl;
  }
  document.getElementById("workspace")?.scrollIntoView({ behavior: "smooth" });
}

async function checkConfig() {
  const pill = document.getElementById("api-pill");
  try {
    const res = await fetch("/api/config/check");
    const data = await res.json();
    if (data.configured) {
      pill.textContent = "API 已配置";
      pill.className = "api-pill ok";
    } else {
      pill.textContent = "请填写 .env 中的 OpenRouter Key";
      pill.className = "api-pill bad";
    }
  } catch (e) {
    pill.textContent = "配置检查失败";
    pill.className = "api-pill bad";
  }
}

function validateUrl(url) {
  return /^https?:\/\//i.test(url) && url.length > 10;
}

function showToast(message, type = "ok") {
  const el = document.getElementById("toast");
  el.hidden = false;
  el.className = `toast ${type === "error" ? "error" : type === "info" ? "info" : ""}`;
  el.textContent = message;
  setTimeout(() => {
    el.hidden = true;
  }, 3200);
}

/** 把本地生成路径转成可直接 <img> 的 URL */
function assetUrl(path) {
  let p = String(path || "").replace(/\\/g, "/");
  const marker = "generated_notes/";
  const i = p.toLowerCase().lastIndexOf(marker);
  if (i >= 0) p = p.slice(i + marker.length);
  // 已经是 /outputs/...
  if (p.startsWith("/outputs/")) return p;
  return `/outputs/${p.replace(/^\/+/, "")}`;
}

function isImagePath(p) {
  return /\.(png|jpe?g|webp|gif)$/i.test(p || "");
}

/** 轻量 Markdown -> HTML（标题/加粗/标签/换行） */
function renderNoteHtml(md) {
  let text = String(md || "");
  // 去掉网感报告
  text = text.replace(/^# 红笔 · 网感报告[\s\S]*?---\s*/m, "");
  // 去掉本地图片 markdown，避免显示路径
  text = text.replace(/!\[[^\]]*]\([^)]+\)\s*/g, "");
  // 备选标题区块弱化
  text = text.replace(/^# 备选标题[\s\S]*?---\s*/m, (block) => {
    return block.replace(/^# 备选标题/m, "### 备选标题");
  });

  const escape = (s) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const lines = text.trim().split("\n");
  const html = [];
  for (let line of lines) {
    const raw = line.trimEnd();
    if (!raw.trim()) {
      html.push("<br>");
      continue;
    }
    let h = escape(raw);
    // 加粗 **text**
    h = h.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    if (/^###\s+/.test(raw)) {
      html.push(`<h3>${h.replace(/^###\s+/, "")}</h3>`);
    } else if (/^##\s+/.test(raw)) {
      html.push(`<h2>${h.replace(/^##\s+/, "")}</h2>`);
    } else if (/^#\s+/.test(raw)) {
      html.push(`<h1>${h.replace(/^#\s+/, "")}</h1>`);
    } else if (/^---+$/.test(raw.trim())) {
      html.push("<hr>");
    } else if (/^#\S/.test(raw.trim())) {
      html.push(`<p class="tag-line">${h}</p>`);
    } else {
      html.push(`<p>${h}</p>`);
    }
  }
  return html.join("\n");
}

function collectImages(data) {
  const fromImages = data.images || [];
  const fromFiles = (data.files || []).filter(isImagePath);
  const all = [...fromImages, ...fromFiles];
  const seen = new Set();
  return all.filter((p) => {
    const key = assetUrl(p);
    if (seen.has(key)) return false;
    seen.add(key);
    return isImagePath(p);
  });
}

async function showLatestImages() {
  try {
    const res = await fetch("/api/latest-images");
    const data = await res.json();
    if (!data.images || !data.images.length) {
      showToast(data.message || "没有配图", "error");
      return;
    }
    renderResult({
      success: true,
      message: data.message,
      images: data.images,
      files: data.images,
      title: "配图预览（验证显示）",
      body: "如果这里能直接看到封面大图，说明图片显示已修好。请关闭旧标签页，只用带「UI v3」的页面。",
      tags: ["红笔", "配图验证"],
      note: "",
    });
    showToast(data.message || "已加载配图");
  } catch (e) {
    showToast(String(e), "error");
  }
}

async function processSingle() {
  const urlInput = document.getElementById("single-url");
  const url = urlInput.value.trim();
  if (!url) {
    showToast("请输入视频链接", "error");
    return;
  }
  if (!validateUrl(url)) {
    showToast("链接需以 http:// 或 https:// 开头", "error");
    return;
  }

  const genXiaohongshu = document.getElementById("gen-xiaohongshu").checked;
  const genBlog = document.getElementById("gen-blog")?.checked || false;
  const styleReference = document.getElementById("style-ref").value.trim();

  const progress = document.getElementById("single-progress");
  const bar = document.getElementById("single-progress-bar");
  const status = document.getElementById("single-status");
  const result = document.getElementById("single-result");
  const tipsBox = document.getElementById("tips-box");
  const scoreBadge = document.getElementById("score-badge");

  progress.hidden = false;
  bar.style.width = "18%";
  status.textContent = "正在生成（下载完整视频 → 转写 → 真实截帧 → 网感文案）…";
  result.className = "preview-body";
  result.textContent = "生成中，请稍候…";
  if (tipsBox) tipsBox.hidden = true;
  if (scoreBadge) scoreBadge.hidden = true;

  const tick = setInterval(() => {
    const cur = parseFloat(bar.style.width);
    if (cur < 88) bar.style.width = `${cur + 2}%`;
  }, 1200);

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1800000);

    const res = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        generate_xiaohongshu: genXiaohongshu,
        generate_blog: genBlog,
        category: state.category,
        style_reference: styleReference,
      }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    clearInterval(tick);

    const data = await res.json();
    bar.style.width = "100%";

    if (!res.ok || !data.success) {
      status.textContent = "处理失败";
      result.textContent = data.error || data.message || data.detail || "未知错误";
      showToast(data.error || data.message || "处理失败", "error");
      return;
    }

    status.textContent = data.message || "完成";
    renderResult(data);
    showToast("小红书图文已生成", "ok");
  } catch (err) {
    clearInterval(tick);
    status.textContent = "请求中断或超时";
    result.textContent = String(err);
    showToast("请求失败", "error");
  }
}

function renderResult(data) {
  const result = document.getElementById("single-result");
  const tipsBox = document.getElementById("tips-box");
  const scoreBadge = document.getElementById("score-badge");

  result.className = "preview-body";
  result.innerHTML = "";
  if (tipsBox) tipsBox.hidden = true;
  if (scoreBadge) scoreBadge.hidden = true;

  const images = collectImages(data);
  if (images.length) {
    const coverPath = images[0];
    const rest = images.slice(1);

    const coverWrap = document.createElement("div");
    coverWrap.className = "cover-wrap";
    coverWrap.innerHTML = `<div class="cover-label">视频真实截帧 · 封面候选</div>`;
    const coverImg = document.createElement("img");
    coverImg.className = "cover-img";
    coverImg.src = assetUrl(coverPath) + `?t=${Date.now()}`;
    coverImg.alt = "封面图";
    coverImg.loading = "eager";
    coverImg.onerror = () => {
      coverWrap.insertAdjacentHTML(
        "beforeend",
        `<p style="color:#b91c1c;font-size:13px;margin-top:8px">图片加载失败：${assetUrl(coverPath)}<br>请确认服务在 8001 端口运行</p>`
      );
    };
    coverWrap.appendChild(coverImg);
    const coverActions = document.createElement("div");
    coverActions.className = "note-actions";
    coverActions.innerHTML = `<a class="mini-btn primary" href="${assetUrl(coverPath)}" download>下载截图</a>`;
    coverWrap.appendChild(coverActions);
    result.appendChild(coverWrap);

    if (rest.length) {
      const grid = document.createElement("div");
      grid.className = "image-grid";
      rest.forEach((imgPath, idx) => {
        const a = document.createElement("a");
        a.href = assetUrl(imgPath);
        a.target = "_blank";
        a.download = imgPath.split(/[/\\]/).pop();
        const img = document.createElement("img");
        img.src = assetUrl(imgPath);
        img.alt = `截帧${idx + 2}`;
        img.loading = "lazy";
        a.appendChild(img);
        grid.appendChild(a);
      });
      result.appendChild(grid);
    }
  } else {
    const tip = document.createElement("div");
    tip.className = "file-card";
    tip.textContent = "本次未截到视频画面（可能下载失败），请重试。";
    result.appendChild(tip);
  }

  const title = data.title || "";
  const body = data.body || "";
  const tags = Array.isArray(data.tags) ? data.tags : [];
  const note = data.note || "";

  // 优先结构化展示：标题 + 正文 + 标签
  if (title || body) {
    const actions = document.createElement("div");
    actions.className = "note-actions";
    actions.innerHTML = `
      <button class="mini-btn primary" id="btn-copy-note">复制小红书正文</button>
      <span style="color:#64748b;font-size:12px;">标题、正文、标签可直接发小红书；配图为视频原画面截帧</span>
    `;
    result.appendChild(actions);

    const box = document.createElement("div");
    box.className = "note-box note-html";
    const tagLine = tags.map((t) => `#${String(t).replace(/^#/, "")}`).join(" ");
    box.innerHTML = `
      <h2>${escapeHtml(title)}</h2>
      <div class="note-body">${escapeHtml(body).replace(/\n/g, "<br>")}</div>
      ${tagLine ? `<p class="note-tags">${escapeHtml(tagLine)}</p>` : ""}
    `;
    result.appendChild(box);

    const cleanForCopy = [title, body, tagLine].filter(Boolean).join("\n\n");
    document.getElementById("btn-copy-note")?.addEventListener("click", async () => {
      await navigator.clipboard.writeText(cleanForCopy);
      showToast("已复制小红书正文");
    });
  } else if (note) {
    const actions = document.createElement("div");
    actions.className = "note-actions";
    actions.innerHTML = `<button class="mini-btn primary" id="btn-copy-note">复制小红书正文</button>`;
    result.appendChild(actions);
    const box = document.createElement("div");
    box.className = "note-box note-html";
    box.innerHTML = renderNoteHtml(note);
    result.appendChild(box);
    document.getElementById("btn-copy-note")?.addEventListener("click", async () => {
      await navigator.clipboard.writeText(note);
      showToast("已复制小红书正文");
    });
  }
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
