"use strict";

// Static viewer: no model/backend requests, credentials, or tracking.
const state = { cases: {}, type: "article", strategies: null, matrix: [] };
const $ = (selector) => document.querySelector(selector);
const element = (tag, className, content) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
};
const loadJson = async (path) => {
  const response = await fetch(path, { credentials: "omit" });
  if (!response.ok) throw new Error("Static data unavailable");
  return response.json();
};
const safeUrl = (value) => {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value, location.href);
    if (url.protocol !== "https:" && url.origin !== location.origin) return null;
    if (!/^https?:$/.test(url.protocol)) return null;
    return url.href;
  } catch { return null; }
};

function renderImage(image) {
  const figure = element("figure", "article-image");
  const img = element("img");
  img.src = `assets/${image["图片链接"]}`;
  img.alt = image["图片说明"];
  img.loading = "lazy";
  figure.append(img);
  const caption = element("figcaption", "", `${image["图片说明"]} · 建议位置：${image["插入位置"]}。来源：`);
  const source = element("a", "", "华为官网 / ima 图片索引");
  const href = safeUrl(image["来源"]);
  if (href) source.href = href;
  source.target = "_blank";
  source.rel = "noopener";
  caption.append(source);
  figure.append(caption);
  return figure;
}

function renderArticle() {
  const draft = state.cases.article["三、图文软文"];
  const container = $("#article-content");
  container.replaceChildren();
  container.append(element("h3", "article-title", draft["标题"]));
  container.append(element("p", "article-lead", draft["导语"]));
  const body = element("div", "article-body");
  const paragraphs = draft["正文"].split(/\n\s*\n/);
  const rest = element("div", "article-rest");
  rest.id = "article-rest";
  rest.hidden = true;
  if (draft["图片方案"][0]) body.append(renderImage(draft["图片方案"][0]));
  paragraphs.forEach((paragraph, index) => {
    const destination = index < 2 ? body : rest;
    destination.append(element("p", "", paragraph));
    if (index === 2 && draft["图片方案"][1]) destination.append(renderImage(draft["图片方案"][1]));
    if (index === 3 && draft["图片方案"][2]) destination.append(renderImage(draft["图片方案"][2]));
  });
  body.append(rest);
  const expand = element("button", "article-expand", "展开完整正文与全部 3 张配图 ↓");
  expand.type = "button";
  expand.setAttribute("aria-controls", "article-rest");
  expand.setAttribute("aria-expanded", "false");
  expand.addEventListener("click", () => {
    const expanded = rest.hidden;
    rest.hidden = !expanded;
    expand.setAttribute("aria-expanded", String(expanded));
    expand.textContent = expanded ? "收起长文 ↑" : "展开完整正文与全部 3 张配图 ↓";
  });
  body.append(expand);
  container.append(body, element("p", "article-cta", draft["行动引导"]));
  const tags = element("div", "tag-list");
  draft["平台标签"].forEach((tag) => tags.append(element("span", "tag", `#${tag}`)));
  container.append(tags);
}

function renderEvidence() {
  const data = state.cases[state.type];
  const grid = $("#audit-grid");
  grid.replaceChildren();
  data["四、核验结果"].forEach((check) => {
    const card = element("div", "audit-card");
    const heading = element("div");
    heading.append(element("h3", "", check["项目"]), element("span", `badge ${check["结果"] === "通过" ? "badge-pass" : "badge-pending"}`, check["结果"]));
    card.append(heading, element("p", "", check["说明"]));
    grid.append(card);
  });
  $("#verification-subtitle").textContent = `${state.type === "article" ? "公众号文章" : "门店海报"}的真实核验快照`;
  $("#case-json").href = `assets/${state.type === "article" ? "article-json.json" : "poster.json"}`;
  $("#case-audit").href = `assets/${state.type === "article" ? "article-txt.txt" : "poster-audit.txt"}`;
  const sourceDetails = $("#source-details");
  sourceDetails.replaceChildren();
  const details = element("details");
  const facts = data["二、知识库依据"]["产品事实"];
  details.append(element("summary", "", `查看本案例引用的 ${facts.length} 条事实原文`));
  facts.forEach((fact) => {
    const row = element("p", "fact");
    row.append(element("strong", "", fact["资料标题"]), document.createTextNode(fact["事实点"]));
    details.append(row);
  });
  sourceDetails.append(details);
}

function selectCase(type) {
  state.type = type;
  for (const option of ["article", "poster"]) {
    const selected = option === type;
    $(`#tab-${option}`).setAttribute("aria-selected", String(selected));
    $(`#tab-${option}`).tabIndex = selected ? 0 : -1;
    $(`#${option}-panel`).hidden = !selected;
  }
  renderEvidence();
}

function renderStrategy() {
  const scene = state.strategies.scenarios.find((item) => item.id === $("#scenario-select").value);
  const platform = state.strategies.platforms.find((item) => item.id === $("#platform-select").value);
  const sample = state.matrix.find((item) => item.scene === scene.name && item.platform === platform.name);
  $("#strategy-title").textContent = `${scene.name} · ${platform.name}`;
  $("#strategy-focus").textContent = scene.focus;
  $("#strategy-question").textContent = scene.question;
  $("#strategy-rule").textContent = platform.instruction;
  $("#strategy-sample-title").textContent = sample ? sample.title : "本组合无快照";
  $("#strategy-image-count").textContent = sample ? sample.image_count : "—";
  $("#strategy-image-range").textContent = platform.min_images === platform.max_images ? `规则：${platform.min_images} 张主视觉` : `规则：${platform.min_images}–${platform.max_images} 张`;
  const badge = $(".strategy-top .badge");
  const passed = sample && sample.blocked.length === 0;
  badge.className = `badge ${passed ? "badge-pass" : "badge-pending"}`;
  badge.textContent = passed ? "规则检查无阻断" : "请查看规则快照";
}

function applyLinks(config) {
  const labels = { application: "打开在线工作台 ↗", github: "GitHub 源码 ↗", modelscope: "魔搭创空间 ↗", manual: "作品说明书 ↗" };
  document.querySelectorAll("[data-link]").forEach((node) => {
    const key = node.dataset.link;
    const href = safeUrl(config.links && config.links[key]);
    if (!href) return;
    node.href = href;
    node.textContent = labels[key];
    node.removeAttribute("aria-disabled");
    node.target = "_blank";
    node.rel = "noopener";
  });
}

async function init() {
  try {
    const [article, poster, strategies, matrix, config] = await Promise.all([
      loadJson("assets/article-json.json"), loadJson("assets/poster.json"),
      loadJson("assets/strategies.json"), loadJson("assets/scenario-platform-check.json"), loadJson("config.json")
    ]);
    state.cases = { article, poster };
    state.strategies = strategies;
    state.matrix = matrix;
    renderArticle();
    renderEvidence();
    applyLinks(config);
    for (const [id, entries] of [["scenario-select", strategies.scenarios], ["platform-select", strategies.platforms]]) {
      const select = $(`#${id}`);
      entries.forEach((entry) => { const option = element("option", "", entry.name); option.value = entry.id; select.append(option); });
      select.addEventListener("change", renderStrategy);
    }
    renderStrategy();
    for (const type of ["article", "poster"]) {
      $(`#tab-${type}`).addEventListener("click", () => selectCase(type));
      $(`#tab-${type}`).addEventListener("keydown", (event) => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          const next = event.key === "Home" ? "article" : event.key === "End" ? "poster" : type === "article" ? "poster" : "article";
          selectCase(next);
          $(`#tab-${next}`).focus();
        }
      });
    }
  } catch {
    $("#load-error").hidden = false;
  }
}
init();
