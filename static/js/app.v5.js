const state = {
  category: "职场吐槽",
  templates: [],
  history: [],
};

const COVER_CLASS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9", "c10"];

document.addEventListener("DOMContentLoaded", async () => {
  checkConfig();
  await loadTemplates();
  // 不自动塞配图占满预览，留空状态引导；用户可点「先看上次配图」
});

function jumpToWorkspace() {
  const heroUrl = document.getElementById("hero-url")?.value?.trim();
  if (heroUrl) document.getElementById("single-url").value = heroUrl;
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

async function loadTemplates() {
  try {
    const res = await fetch("/api/templates");
    const data = await res.json();
    state.templates = data.categories || [];
  } catch (e) {
    state.templates = fallbackTemplates();
  }
  renderCategorySeg();
  renderTemplateGrid();
  selectCategory(state.category, { scroll: false });
}

function fallbackTemplates() {
  return [
    {
      name: "职场吐槽",
      tone: "真实、克制吐槽",
      structure: ["今天发生了什么", "真实感受", "清醒判断", "互动共鸣"],
      structure_detail: ["现场切片开场", "写出最耗人的点", "落一句清醒判断", "邀请树洞"],
      few_shot_title: "上班第302天🙂我又破防了",
      few_shot_body: "今天真的笑不出来……",
      viral_examples: [],
    },
  ];
}

function renderCategorySeg() {
  const seg = document.getElementById("category-seg");
  if (!seg) return;
  seg.innerHTML = "";
  state.templates.forEach((tpl) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "seg-item" + (tpl.name === state.category ? " active" : "");
    btn.dataset.value = tpl.name;
    btn.textContent = tpl.name;
    btn.addEventListener("click", () => selectCategory(tpl.name, { scroll: false }));
    seg.appendChild(btn);
  });
}

function renderTemplateGrid() {
  const grid = document.getElementById("template-grid");
  if (!grid) return;
  grid.innerHTML = "";
  state.templates.forEach((tpl, idx) => {
    const cover = COVER_CLASS[idx % COVER_CLASS.length];
    const steps = (tpl.structure || []).join(" → ");
    const example = (tpl.viral_examples && tpl.viral_examples[0]) || {
      title: tpl.few_shot_title,
      body: tpl.few_shot_body,
    };
    const imgSrc = tpl.cover_thumb || tpl.cover_image || "";
    const card = document.createElement("article");
    card.className = "tpl-card" + (tpl.name === state.category ? " active" : "");
    card.innerHTML = `
      <div class="tpl-cover ${cover}">
        ${imgSrc ? `<img src="${imgSrc}?v=1" alt="${escapeHtml(tpl.name)}" loading="lazy">` : ""}
      </div>
      <div class="tpl-body">
        <h3>${escapeHtml(tpl.name)}</h3>
        <p class="tpl-tone">${escapeHtml(tpl.tone || "")}</p>
        <div class="tpl-steps">${escapeHtml(steps)}</div>
        <div class="tpl-sample">
          <div class="tpl-sample-title">${escapeHtml(example.title || "")}</div>
          <div class="tpl-sample-body">${escapeHtml(shorten(example.body || "", 72))}</div>
        </div>
        <button type="button" class="tpl-use">使用此模板</button>
      </div>
    `;
    card.querySelector(".tpl-use").addEventListener("click", () => {
      selectCategory(tpl.name, { scroll: true });
    });
    card.addEventListener("click", (e) => {
      if (e.target.closest(".tpl-use")) return;
      selectCategory(tpl.name, { scroll: false });
    });
    grid.appendChild(card);
  });
}

function selectCategory(name, opts = {}) {
  state.category = name;
  document.querySelectorAll("#category-seg .seg-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.value === name);
  });
  document.querySelectorAll(".tpl-card").forEach((c) => {
    const h = c.querySelector("h3");
    c.classList.toggle("active", h && h.textContent === name);
  });
  renderBlueprint(name);
  if (opts.scroll) {
    document.getElementById("workspace")?.scrollIntoView({ behavior: "smooth" });
    showToast(`已选用「${name}」模板`, "ok");
  }
}

function renderBlueprint(name) {
  const tpl = state.templates.find((t) => t.name === name) || state.templates[0];
  if (!tpl) return;
  document.getElementById("tpl-bp-name").textContent = tpl.name;
  document.getElementById("tpl-bp-tone").textContent = tpl.tone || "";
  const coverEl = document.getElementById("tpl-bp-cover");
  if (coverEl) {
    const src = tpl.cover_image || tpl.cover_thumb || "";
    if (src) {
      coverEl.hidden = false;
      coverEl.src = src + "?v=1";
      coverEl.alt = tpl.name;
    } else {
      coverEl.hidden = true;
    }
  }
  const steps = document.getElementById("tpl-bp-steps");
  steps.innerHTML = "";
  const details = tpl.structure_detail?.length ? tpl.structure_detail : tpl.structure || [];
  details.forEach((s) => {
    const li = document.createElement("li");
    li.textContent = s;
    steps.appendChild(li);
  });
  const example = (tpl.viral_examples && tpl.viral_examples[0]) || {
    title: tpl.few_shot_title,
    body: tpl.few_shot_body,
  };
  document.getElementById("tpl-bp-title").textContent = example.title || "";
  document.getElementById("tpl-bp-body").textContent = shorten(example.body || "", 160);
}

function shorten(s, n) {
  const t = String(s || "").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n) + "…" : t;
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

function assetUrl(path) {
  let p = String(path || "").replace(/\\/g, "/");
  if (!p) return "";
  if (p.startsWith("/outputs/")) return p;
  if (p.startsWith("http://") || p.startsWith("https://")) return p;
  const marker = "generated_notes/";
  const i = p.toLowerCase().lastIndexOf(marker);
  if (i >= 0) p = p.slice(i + marker.length);
  const imgIdx = p.toLowerCase().lastIndexOf("/images/");
  if (imgIdx >= 0) p = p.slice(imgIdx + 1);
  if (p.toLowerCase().startsWith("images/")) return `/outputs/${p}`;
  return `/outputs/${p.replace(/^\/+/, "")}`;
}

function isImagePath(p) {
  return /\.(png|jpe?g|webp|gif)$/i.test(p || "");
}

function stripMarkdown(text) {
  return String(text || "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s*[-*•]\s+/gm, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
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
    return isImagePath(p) || String(p).startsWith("/outputs/");
  });
}

function validateUrl(url) {
  return /^https?:\/\//i.test(url) && url.length > 10;
}

async function showLatestImages(opts = {}) {
  const silent = !!opts.silent;
  try {
    const res = await fetch("/api/latest-images");
    const data = await res.json();
    if (!data.images || !data.images.length) {
      if (!silent) showToast(data.message || "没有配图", "error");
      return;
    }
    renderResult({
      success: true,
      message: data.message,
      images: data.images,
      title: "配图预览",
      body: "这是上次生成的视频真实截帧。正式生成后，这里会显示完整小红书笔记卡。",
      tags: ["红笔", "配图验证"],
      score: null,
    });
    if (!silent) showToast(data.message || "已加载配图");
  } catch (e) {
    if (!silent) showToast(String(e), "error");
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
  status.textContent = "提炼主旨 → 学爆款模板写笔记 → 真实截帧…";
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

  // 网感分
  const score = data.score || {};
  if (scoreBadge) {
    if (typeof score.score === "number") {
      scoreBadge.hidden = false;
      document.getElementById("score-num").textContent = score.score;
      document.getElementById("score-grade").textContent = score.grade || "网感分";
    } else {
      scoreBadge.hidden = true;
    }
  }

  // 主旨条
  const thesis = data.thesis || score.thesis;
  if (thesis && thesis.gist) {
    const th = document.createElement("div");
    th.className = "thesis-bar";
    th.innerHTML = `<strong>视频主旨</strong><span>${escapeHtml(thesis.gist)}</span>`;
    result.appendChild(th);
  }

  // 配图
  const images = collectImages(data);
  if (images.length) {
    const coverPath = images[0];
    const rest = images.slice(1);
    const coverWrap = document.createElement("div");
    coverWrap.className = "cover-wrap";
    coverWrap.innerHTML = `<div class="cover-label">视频真实截帧</div>`;
    const coverImg = document.createElement("img");
    coverImg.className = "cover-img";
    coverImg.src = assetUrl(coverPath) + `?t=${Date.now()}`;
    coverImg.alt = "封面图";
    coverImg.onerror = () => {
      coverWrap.insertAdjacentHTML(
        "beforeend",
        `<p class="img-fail">图片加载失败：${assetUrl(coverPath)}</p>`
      );
    };
    coverWrap.appendChild(coverImg);
    result.appendChild(coverWrap);

    if (rest.length) {
      const grid = document.createElement("div");
      grid.className = "image-grid";
      rest.forEach((imgPath, idx) => {
        const a = document.createElement("a");
        a.href = assetUrl(imgPath);
        a.target = "_blank";
        const img = document.createElement("img");
        img.src = assetUrl(imgPath);
        img.alt = `截帧${idx + 2}`;
        a.appendChild(img);
        grid.appendChild(a);
      });
      result.appendChild(grid);
    }
  }

  let title = stripMarkdown(data.title || "");
  let body = stripMarkdown(data.body || "");
  let tags = Array.isArray(data.tags) ? data.tags : [];

  // 若只有 note，从纯文本里拆
  if ((!title || !body) && data.note) {
    const plain = stripMarkdown(data.note);
    const lines = plain.split("\n").filter((l) => l.trim());
    if (!title && lines[0]) title = lines[0];
    if (!body) {
      body = lines.slice(1).join("\n").replace(/(?:#[^\s#]+\s*)+$/g, "").trim();
    }
    if (!tags.length) {
      tags = Array.from(plain.matchAll(/#([^\s#]+)/g)).map((m) => m[1]);
    }
  }

  if (title || body) {
    const actions = document.createElement("div");
    actions.className = "note-actions";
    actions.innerHTML = `
      <button class="mini-btn primary" id="btn-copy-note">复制小红书正文</button>
      <span class="note-hint">纯文本，可直接粘贴发小红书</span>
    `;
    result.appendChild(actions);

    const phone = document.createElement("div");
    phone.className = "xhs-phone";
    const tagLine = tags.map((t) => `#${String(t).replace(/^#/, "")}`).join(" ");
    const bodyHtml = escapeHtml(body)
      .split(/\n{2,}/)
      .map((para) => `<p>${para.replace(/\n/g, "<br>")}</p>`)
      .join("");
    phone.innerHTML = `
      <div class="xhs-phone-top">小红书笔记预览</div>
      <div class="xhs-note">
        <h2 class="xhs-title">${escapeHtml(title)}</h2>
        <div class="xhs-body">${bodyHtml}</div>
        ${tagLine ? `<p class="xhs-tags">${escapeHtml(tagLine)}</p>` : ""}
      </div>
    `;
    result.appendChild(phone);

    // 备选标题
    const alts = (score.titles || []).filter((t) => stripMarkdown(t) !== title);
    if (alts.length) {
      const altBox = document.createElement("div");
      altBox.className = "alt-titles";
      altBox.innerHTML = `<div class="alt-label">备选标题</div>` +
        alts
          .slice(0, 4)
          .map((t) => `<button type="button" class="alt-item">${escapeHtml(stripMarkdown(t))}</button>`)
          .join("");
      result.appendChild(altBox);
      altBox.querySelectorAll(".alt-item").forEach((btn) => {
        btn.addEventListener("click", () => {
          const h = phone.querySelector(".xhs-title");
          if (h) h.textContent = btn.textContent;
          title = btn.textContent;
          showToast("已切换标题");
        });
      });
    }

    const cleanForCopy = [title, body, tagLine].filter(Boolean).join("\n\n");
    document.getElementById("btn-copy-note")?.addEventListener("click", async () => {
      await navigator.clipboard.writeText(cleanForCopy);
      showToast("已复制小红书正文");
    });
  }

  if (tipsBox) {
    const tips = score.tips || [];
    if (tips.length) {
      tipsBox.hidden = false;
      tipsBox.innerHTML = `<strong>网感建议</strong><ul>${tips
        .map((t) => `<li>${escapeHtml(t)}</li>`)
        .join("")}</ul>`;
    } else {
      tipsBox.hidden = true;
    }
  }
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
