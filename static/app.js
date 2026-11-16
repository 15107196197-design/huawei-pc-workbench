"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { status: null, task: null, tasks: [], platform: "wechat", evidenceTab: "sources", busy: false, editRevision: null, assetRevision: null, redirectingToLogin: false };
const defaultPlatforms = [{id:"wechat",name:"公众号",min_images:2,max_images:4},{id:"xiaohongshu",name:"小红书",min_images:3,max_images:6},{id:"moments",name:"门店朋友圈",min_images:1,max_images:3},{id:"poster",name:"门店海报",min_images:1,max_images:1}];
const defaultScenarios = [{id:"school",name:"开学季"},{id:"office",name:"职场办公"},{id:"creator",name:"内容创作"},{id:"family",name:"家庭换新"},{id:"business",name:"企业采购"},{id:"store",name:"门店到访"},{id:"launch",name:"新品首发"},{id:"holiday",name:"节日营销"}];
const defaultChannels = ["华为商城","淘宝","闲鱼","小红书","微信小程序","京东华为自营","线下门店"];
const connectionLabels = {ima:"ima 知识库",dify:"Dify",deepseek:"DeepSeek",vision:"Qwen 视觉",image:"Qwen-Image",search:"联网检索"};
const iconPaths = {
  logout:'<path d="M10 4H4v16h6M14 8l4 4-4 4M8 12h10"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',history:'<path d="M3 11a9 9 0 1 1 2.5 7M3 4v7h7"/><path d="M12 7v5l3 2"/>',settings:'<path d="m9 3-1 3-3 1-2 3 2 3v4l3 1 2 3h4l2-3 3-1v-4l2-3-2-3-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',user:'<circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/>',edit:'<path d="m16 3 5 5-12 12-6 1 1-6Z"/><path d="m13 6 5 5"/>',down:'<path d="m5 10 7 7 7-7M12 3v14"/>',arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',spark:'<path d="m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7ZM20 2v4m-2-2h4"/>',image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',copy:'<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/>',alert:'<path d="m12 3 10 18H2Z"/><path d="M12 9v5m0 3v1"/>',check:'<path d="m4 12 5 5L20 6"/>',book:'<path d="M3 4h7a2 2 0 0 1 2 2v15a3 3 0 0 0-3-2H3Zm18 0h-7a2 2 0 0 0-2 2v15a3 3 0 0 1 3-2h6Z"/>',search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',upload:'<path d="M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5"/>',refresh:'<path d="M21 9a9 9 0 0 0-15-5L3 7m0-5v5h5M3 15a9 9 0 0 0 15 5l3-3m0 5v-5h-5"/>',wechat:'<path d="M21 11c0 4-4 7-9 7H8l-4 3 1-5a7 7 0 0 1-2-5c0-4 4-7 9-7s9 3 9 7Z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>',xiaohongshu:'<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 7h8M8 11h8m-8 4h4"/>',moments:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="m8 4 4 5m8 3h-5m-2 8 1-5M4 14l5-1"/>',poster:'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h5m-5 4h8m-8 3h5"/>',file:'<path d="M14 2H5v20h14V7Zm0 0v6h5M8 12h8m-8 4h8"/>',coins:'<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 4 16 4 16 0V6M4 12v6c0 4 16 4 16 0v-6"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${iconPaths[name] || iconPaths.file}</svg>`;
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const array = value => Array.isArray(value) ? value : [];
const textValue = value => typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "");
const platforms = () => array(state.status?.platforms).length ? state.status.platforms : defaultPlatforms;
const scenarios = () => array(state.status?.scenarios).length ? state.status.scenarios : defaultScenarios;
const channels = () => array(state.status?.channels).length ? state.status.channels : defaultChannels;
const platformName = id => platforms().find(p => p.id === id)?.name || id || "待确认";
const scenarioName = id => scenarios().find(s => s.id === id)?.name || id || "待确认";
const money = value => value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? "待核实" : Number(value).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2});
const dateText = value => { if (!value) return "时间未记录"; const d = new Date(value); return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}); };
function safeURL(value, local = false) { try { const url = new URL(String(value || ""), location.origin); return ["http:","https:"].includes(url.protocol) && (local || url.origin !== location.origin || String(value).startsWith("http")) ? url.href : ""; } catch { return ""; } }
function sourceLink(url, label = "查看来源") { const safe = safeURL(url, true); return safe ? `<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>` : '<span>未提供可打开的来源</span>'; }
function renderIcons(root = document) { $$('[data-icon]',root).forEach(el => { el.innerHTML = icon(el.dataset.icon); }); }
function showDialog(id) { const d = document.getElementById(id); if (!d.open) { setDialogFeedback(d); d.showModal(); } }
function closeDialog(id) { const d = document.getElementById(id); d.close(); if (id === "settings-dialog") $$('input[type="password"]', d).forEach(el => { el.value = ""; }); }
function setDialogFeedback(dialog, message = "", error = false) {
  if (!dialog) return;
  let feedback = $("[data-dialog-feedback]",dialog);
  if (!feedback) {
    const footer = $(".dialog-footer",dialog);
    if (!footer) return;
    feedback = document.createElement("p");
    feedback.className = "dialog-feedback";
    feedback.setAttribute("data-dialog-feedback","");
    feedback.setAttribute("aria-live","polite");
    footer.prepend(feedback);
  }
  feedback.textContent = message;
  feedback.hidden = !message;
  feedback.classList.toggle("error",error);
  feedback.setAttribute("role",error ? "alert" : "status");
}
let toastTimer;
function toast(message, error = false) { clearTimeout(toastTimer); const el = $("#toast"); el.textContent = message; el.classList.toggle("error",error); el.hidden = false; toastTimer = setTimeout(() => { el.hidden = true; },error ? 6500 : 3500); }
function showError(message) { $("#global-error-message").textContent = message; $("#global-error").hidden = false; toast(message,true); }
function setBusy(value, message = "正在处理") { state.busy = value; $("#busy-overlay").hidden = !value; $("#busy-message").textContent = message; document.body.setAttribute("aria-busy",String(value)); ["#chat-send-btn","#new-task-btn","#generate-btn"].forEach(s => { $(s).disabled = value; }); }
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout || 240000);
  try {
    const response = await fetch(path,{...options,credentials:"same-origin",headers:{"Content-Type":"application/json",...(options.headers || {})},body:options.body === undefined ? undefined : JSON.stringify(options.body),signal:controller.signal});
    requireSession(response);
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("json") ? await response.json() : await response.text();
    if (!response.ok) { const detail = data?.detail || data?.message || `请求失败（${response.status}）`; throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail)); }
    return data;
  } catch (error) { if (error.name === "AbortError") throw new Error("请求超时，请检查连接后重新尝试。已保存的任务可以从历史记录重新打开。"); if (error instanceof TypeError) throw new Error("无法连接工作台服务，请检查网络后重试。"); throw error; }
  finally { clearTimeout(timer); }
}
function requireSession(response) {
  if (response.status !== 401) return;
  if (location.pathname !== "/login" && !state.redirectingToLogin) { state.redirectingToLogin = true; location.replace("/login"); }
  throw new Error("登录已失效，正在前往登录页面。");
}
async function run(message, fn) {
  if (state.busy) return;
  const dialog = $$("dialog[open]").at(-1);
  const dialogButtons = dialog ? $$('button[type="submit"], input[type="submit"], [data-close]',dialog).map(button => [button,button.disabled]) : [];
  dialogButtons.forEach(([button]) => { button.disabled = true; });
  if (dialog) dialog.setAttribute("aria-busy","true");
  setDialogFeedback(dialog,message);
  setBusy(true,message);
  try { await fn(); $("#global-error").hidden = true; setDialogFeedback(dialog); }
  catch (error) { const detail = error.message || "操作未完成，请重试。"; setDialogFeedback(dialog,detail,true); showError(detail); }
  finally {
    dialogButtons.forEach(([button,disabled]) => { button.disabled = disabled; });
    if (dialog) dialog.removeAttribute("aria-busy");
    setBusy(false); renderControls();
    if (dialog?.id === "settings-dialog") renderSettingsAccess();
  }
}
function useTask(data) { const task = data?.task || data; if (!task || !task.id) throw new Error("服务未返回有效任务，内容未更新。"); state.task = task; state.platform = task.brief?.platform || state.platform; try { localStorage.setItem("huawei-pc-active-task",task.id); } catch {} renderAll(); }
async function ensureTask() { if (!state.task) { const chosenPlatform = state.platform; useTask(await api("/api/tasks",{method:"POST",body:{}})); if (state.task.brief?.platform !== chosenPlatform) useTask(await api(`/api/tasks/${encodeURIComponent(state.task.id)}/brief`,{method:"POST",body:{brief:{...(state.task.brief || {}),platform:chosenPlatform}}})); } return state.task; }
const taskPath = suffix => `/api/tasks/${encodeURIComponent(state.task.id)}${suffix}`;
async function refreshTaskList() { const result = await api("/api/tasks"); state.tasks = array(result.tasks || result); }
async function refreshStatus() { state.status = await api("/api/status",{timeout:30000}); $("#global-error").hidden = true; renderStatus(); renderPlatforms(); renderMode(); renderSettingsAccess(); if ($("#settings-dialog").open) renderSettingsConnections(); }
function isRuleMode() { const mode = state.task?.mode || state.status?.mode || ""; return /rule|fallback|offline|规则|local/i.test(mode) && !/llm|deepseek|dify/i.test(mode); }
function renderMode() { const el = $("#mode-label"); el.classList.toggle("warning",isRuleMode()); el.textContent = isRuleMode() ? "规则草稿模式" : state.status ? (state.task?.mode === "dify" || state.status.mode === "dify" ? "Dify 云端流程" : "模型连接已配置") : "等待连接"; }
function renderStatus() {
  const c = state.status?.connections || {};
  const ids = ["ima","dify","deepseek","vision","image","search"];
  $("#connection-items").innerHTML = ids.map(id => { const item = c[id] || {}; const live = item.connected === true; const configured = item.configured === true; const label = live ? "已连接" : configured ? (/失败|HTTP|超时/.test(item.message || "") ? "连接失败" : "已配置 · 未测试") : "待配置"; return `<button class="connection-item" data-open-connection="${id}" title="${esc(item.message || label)}"><i class="status-dot ${live ? 'connected' : configured ? 'pending' : ''}"></i>${esc(connectionLabels[id])}<span class="status-suffix">${label}</span></button>`; }).join("");
  const user = state.status?.user; const authentication = state.status?.authentication;
  const context = state.status?.managed_config ? "共享工作台" : authentication?.enabled ? "已登录" : "本机";
  $("#account-status").title = [user?.source || "身份来源待核验",authentication?.enabled ? "授权操作者共享任务与素材；使用后请退出登录。" : ""].filter(Boolean).join(" · ");
  $("#account-status").innerHTML = `${icon("user")}<span>${context} · ${esc(user?.name || "工作台")}${user?.verified ? "" : " · 待核验"}</span>`;
  $("#logout-btn").hidden = authentication?.enabled !== true;
}
function renderPlatforms() { $("#platform-tabs").innerHTML = platforms().map(p => `<button class="platform-tab ${p.id === state.platform ? 'active' : ''}" data-platform="${esc(p.id)}" role="tab" aria-selected="${p.id === state.platform}">${icon(p.id)}${esc(p.name)}</button>`).join(""); }
function renderBrief() {
  const b = state.task?.brief || {};
  const fields = [["目标人群",b.audience],["使用场景",b.scenario ? scenarioName(b.scenario) : ""],["发布平台",b.platform ? platformName(b.platform) : ""],["产品选择",b.product],["内容目标",b.goal],["地区 / 预算",[b.region,b.budget].filter(Boolean).join(" · ")]];
  $("#brief-summary").innerHTML = fields.map(([key,value]) => `<dt>${esc(key)}</dt><dd class="${value ? '' : 'unset'}">${esc(value || '待补充')}</dd>`).join("");
  const summary = state.task?.understanding_summary;
  if (summary) {
    const candidates = array(state.task?.candidates).slice(0,3);
    const reasons = candidates.map(c => `${c.model}：${c.status === 'conditional' ? '条件候选 · ' : c.status === 'excluded' ? '存在冲突 · ' : ''}${c.ranking_reason || ''}`).join('；');
    const gaps = array(state.task?.evidence_gaps).map(g => typeof g === 'string' ? g : g.message).filter(Boolean).slice(0,3).join('；');
    $("#brief-summary").innerHTML += `<dt>理解摘要</dt><dd>${esc(summary)}</dd>${reasons ? `<dt>推荐依据</dt><dd>${esc(reasons)}</dd>` : ''}${gaps ? `<dt>关键待核实</dt><dd>${esc(gaps)}</dd>` : ''}`;
  }
  const canContinue = Boolean(array(state.task?.task_context?.conditions).length || b.audience || b.product || b.goal);
  $("#brief-progress").classList.toggle("complete",canContinue);
  $("#brief-progress").innerHTML = `${icon(canContinue ? "check" : "edit")}<span>${!state.task ? "在对话中描述需求，即可开始" : canContinue ? "可先查询与创作，关键差异按需确认" : "先描述内容或使用任务，型号、预算和软件均可暂不确定"}</span>`;
  const statusLabels = {needs_evidence:"依据待补充",new:"需求待补充",draft:"草稿",ready:"可生成",generated:"已生成",completed:"已完成",blocked:"待确认",needs_input:"待补充",needs_review:"待复核",awaiting_input:"待补充",verified:"已核验"};
  $("#task-state").textContent = state.task ? (statusLabels[state.task.status] || state.task.status || "进行中") : "尚未开始";
  $("#task-title").textContent = state.task?.title || "开始一次有依据的创作";
}
function renderChat() {
  const messages = array(state.task?.messages);
  $("#chat-messages").innerHTML = messages.length ? messages.map(m => `<div class="chat-message ${m.role === 'user' ? 'user' : 'assistant'}">${m.role === 'user' ? '' : `<div class="assistant-avatar">${icon('spark')}</div>`}<div class="message-content">${esc(m.content)}</div></div>`).join("") : `<div class="chat-welcome"><div class="assistant-avatar">${icon("spark")}</div><div class="welcome-text"><strong>先说说，这次想写给谁？</strong>告诉我产品、人群、使用场景和发布平台。尚未选定产品也可以先说需求，我会逐步补齐关键信息。</div></div>`;
  const el = $("#chat-messages"); el.scrollTop = el.scrollHeight;
}
function renderProcess() {
  const steps = [{id:"brief",label:"理解需求"},{id:"retrieve",label:"资料检索"},{id:"quote",label:"推荐报价"},{id:"generate",label:"图文生成"},{id:"verify",label:"交付核验"}];
  const aliases = {new:0,parsing:0,needs_input:0,awaiting_input:0,retrieval:1,retrieving:1,knowledge:1,facts:1,pricing:2,quotes:2,planning:2,generating:3,generation:3,compliance:4,checking:4,completed:4,complete:4,ready:4,review:4};
  const stage = state.task?.stage || "brief"; let idx = steps.findIndex(s => s.id === stage); if (idx < 0) idx = aliases[stage] ?? (state.task?.draft ? 4 : 0);
  $("#process-track").innerHTML = steps.map((s,i) => `${i ? '<span class="process-divider"></span>' : ''}<span class="process-step ${state.task && i === idx ? 'current' : state.task && i < idx ? 'done' : ''}"><i>${state.task && i < idx ? '✓' : i+1}</i>${s.label}</span>`).join("");
}
function resolvedImages() {
  const assets = array(state.task?.assets);
  return array(state.task?.draft?.images).map(image => { if (typeof image === "string") return assets.find(a => a.id === image) || {id:image}; return {...(assets.find(a => a.id === image.id || a.id === image.asset_id) || {}),...image}; });
}
function imageHTML(image) {
  const url = safeURL(image.url || image.image_url,true);
  return `<figure class="preview-figure">${url ? `<img src="${esc(url)}" alt="${esc(image.caption || image.name || '产品配图')}" loading="lazy">` : '<div class="image-load-error">图片链接暂不可用，请在配图管理中核实来源。</div>'}<figcaption>${esc(image.caption || image.name || '')}${image.source_title ? `<span class="image-source-line">来源：${esc(image.source_title)}</span>` : ''}</figcaption></figure>`;
}
function bodyHTML(body) { return esc(body).split(/\n\n+/).map(block => { if (/^#{1,3} /.test(block)) return `<h3>${block.replace(/^#{1,3} /,"")}</h3>`; return `<p>${block}</p>`; }).join(""); }
function bodyWithImages(body, images) {
  const blocks = String(body || "").split(/\n\n+/);
  const slots = new Map();
  images.forEach(image => { const match = String(image.position || "").match(/第\s*(\d+)\s*段/); const idx = Math.min(blocks.length - 1,Math.max(0,match ? Number(match[1])-1 : Math.floor(blocks.length/2))); slots.set(idx,[...(slots.get(idx) || []),image]); });
  return blocks.map((block,i) => bodyHTML(block) + (slots.get(i) || []).map(imageHTML).join("")).join("");
}
function renderDraft() {
  const draft = state.task?.draft;
  if (!draft) {
    $("#draft-area").innerHTML = `<div class="draft-empty"><div class="empty-art" aria-hidden="true"><div class="art-page"></div><div class="art-picture">${icon("image")}</div><div class="art-spark">${icon("spark")}</div></div><h3>从一个真实场景开始</h3><p>明确人群与需求，找到可靠的产品依据，<br>再把合适的卖点，写成适合平台的内容。</p><button class="suggestion" id="use-example-btn"><small>${icon("spark")} 试试这样描述</small><p>面向杭州大学新生，在小红书介绍适合日常学习和多设备协同的华为电脑，预算 6000 元左右。</p></button><p class="empty-note">示例只填入对话框，发送后才开始处理。</p></div>`;
    return;
  }
  const images = resolvedImages();
  const ruleNotice = isRuleMode() ? `<div class="rule-notice">${icon("alert")}<span>当前为规则草稿：未调用已验证的文本模型，内容仅作结构整理。连接模型并重新生成后再用于发布。</span></div>` : "";
  if (state.platform === "poster") {
    const renderedURL = safeURL(draft.poster_url,true);
    $("#draft-area").innerHTML = ruleNotice + (renderedURL ? `<img class="poster-rendered" src="${esc(renderedURL)}" alt="已生成门店海报">` : `<div class="poster-preview"><div class="poster-layout-label">海报版式预览 · 尚未生成成品图</div><h1>${esc(draft.title)}</h1><p class="lead">${esc(draft.lead)}</p>${images[0] && safeURL(images[0].url,true) ? `<img class="product-image" src="${esc(safeURL(images[0].url,true))}" alt="${esc(images[0].caption || images[0].name)}">` : '<div class="empty-section"><p>产品主体图片尚未确认</p></div>'}<div class="poster-points">${esc(draft.body)}</div><div class="poster-cta">${esc(draft.cta)}</div></div>`);
    return;
  }
  const introImages = images.filter(im => /开|标题|首|顶部|导语|main|hero|start/.test(im.position || ""));
  const endImages = images.filter(im => /结尾|底部|end|footer/.test(im.position || ""));
  const bodyImages = images.filter(im => !introImages.includes(im) && !endImages.includes(im));
  const tags = array(draft.tags).map(t => `<span>${esc(String(t).startsWith("#") ? t : `#${t}`)}</span>`).join("");
  $("#draft-area").innerHTML = `${ruleNotice}<article class="article-preview platform-${esc(state.platform)}"><div class="preview-platform-label"><span>${esc(platformName(state.platform))} · 成品预览</span><span>${images.length} 张配图</span></div><h1>${esc(draft.title)}</h1>${draft.lead ? `<p class="lead">${esc(draft.lead)}</p>` : ''}${introImages.map(imageHTML).join("")}<div class="article-body">${bodyWithImages(draft.body || "",bodyImages)}</div>${draft.cta ? `<div class="article-cta">${esc(draft.cta)}</div>` : ''}${endImages.map(imageHTML).join("")}${tags ? `<div class="article-tags">${tags}</div>` : ''}</article>`;
}
function renderControls() {
  const draft = !!state.task?.draft; const busy = state.busy;
  const blocked = state.task?.status === "blocked" || array(state.task?.checks).some(check => check.status === "blocked");
  const exportSelect = $("#export-format");
  if (![...exportSelect.options].some(option => option.value === "report")) exportSelect.add(new Option("审核报告 TXT","report"));
  $("#poster-tools").hidden = state.platform !== "poster" || !draft;
  $("#background-btn").disabled = busy || !state.status?.connections?.image?.configured;
  $("#background-btn").title = state.status?.connections?.image?.configured ? "调用Qwen-Image生成背景，保留产品原图" : "请先在连接与设置中配置图片模型";
  $("#vision-btn").disabled = busy || !state.status?.connections?.vision?.configured || !state.task?.draft?.poster_url;
  $("#vision-btn").title = !state.status?.connections?.vision?.configured ? "请先配置视觉模型" : !state.task?.draft?.poster_url ? "请先合成海报" : "检查成品与产品原图";
  $("#edit-draft-btn").disabled = !draft || busy;
  $("#copy-btn").disabled = !draft || busy || blocked;
  $("#copy-btn").title = blocked ? "先修正核验问题" : "重新核验报价后，复制含必要标识的成品文字";
  $("#assets-btn").disabled = !state.task || busy;
  $("#versions-btn").disabled = !array(state.task?.versions).length || busy;
  $("#versions-label").textContent = array(state.task?.versions).length ? `版本 ${state.task.versions.length}` : "版本";
  $("#save-status").textContent = draft ? `已保存 · r${state.task.revision ?? 1}` : "尚无成品";
  $("#revision-form").hidden = !draft;
  $("#generate-btn").disabled = busy;
  $("#chat-send-btn").disabled = busy;
  $("#new-task-btn").disabled = busy;
  $$('#export-format option').forEach(el => { el.disabled = (["png","pdf"].includes(el.value) && state.platform !== "poster") || (blocked && !["json","report"].includes(el.value)); });
  if (state.platform !== "poster" && ["png","pdf"].includes($("#export-format").value)) $("#export-format").value = "html";
  const auditExport = ["json","report"].includes(exportSelect.value);
  $("#export-btn").disabled = busy || !state.task || (!draft && !auditExport) || (blocked && !auditExport);
  $("#export-btn").title = blocked && !auditExport ? "先修正核验问题；可选择核验数据 JSON 或审核报告导出" : auditExport ? "导出核验依据与审核结果" : "导出前服务端会重新核价与检查";
}
function emptySection(iconName,title,description) { return `<div class="empty-section"><span data-icon="${iconName}"></span><h3>${esc(title)}</h3><p>${esc(description)}</p></div>`; }
function renderSources() {
  const facts = array(state.task?.facts); const assets = array(state.task?.assets);
  const recommendations = array(state.task?.recommendations);
  const recommended = recommendations.length ? `<div class="source-headline"><h3>产品推荐方向</h3><span class="subtle-note">依据当前需求</span></div>${recommendations.map(r => `<div class="recommendation-card"><strong>${esc(r.model)}</strong><p>${esc(r.reason)}</p>${r.limitations ? `<p class="limitation">${esc(Array.isArray(r.limitations) ? r.limitations.join("；") : r.limitations)}</p>` : ''}<p>${array(r.fact_ids).length} 条关联事实</p></div>`).join("")}<div style="height:10px"></div>` : '';
  return `${recommended}<div class="source-headline"><h3>产品事实 <span class="subtle-note">${facts.length}</span></h3><button class="text-button" id="retrieve-btn">${icon("refresh")}刷新依据</button></div><form class="source-search" id="source-search-form"><label class="sr-only" for="source-query">检索产品资料</label><input id="source-query" placeholder="输入具体型号或事实点" maxlength="500"><button type="submit" class="button small">检索</button></form>${facts.length ? facts.map(f => `<details class="source-card"><summary><div><div class="source-product">${esc(f.model || f.product_id || '型号待确认')} <span class="verified-tag ${f.verified ? 'yes' : 'no'}">${f.verified ? '已核验' : '待核验'}</span></div><div class="claim">${esc(String(f.claim || "").length > 150 ? String(f.claim).slice(0,150) + "…" : f.claim)}</div></div></summary><div class="source-meta"><strong>${esc(f.source_title || '资料标题待确认')}</strong>${f.excerpt ? `<blockquote>${esc(f.excerpt)}</blockquote>` : ''}${sourceLink(f.source_url)}</div></details>`).join("") : emptySection("book","还没有产品依据","发送需求或检索具体型号后，在这里查看事实原文与来源。")}
    <div class="source-headline" style="margin-top:20px"><h3>知识库图片 <span class="subtle-note">${assets.length}</span></h3><button class="text-button" id="manage-source-assets-btn">选择配图 ↗</button></div>${assets.length ? `<div class="image-source-grid">${assets.slice(0,8).map(a => `<div class="image-source-tile">${safeURL(a.url,true) ? `<img src="${esc(safeURL(a.url,true))}" alt="${esc(a.name)}" loading="lazy">` : '<div class="image-load-error">图片链接待核实</div>'}<div><strong>${esc(a.name)}</strong>${esc(a.model || '型号待确认')}<br><span class="verified-tag ${a.verified ? 'yes' : 'no'}">${a.verified ? '型号已核验' : '型号待核验'}</span></div></div>`).join("")}</div>${assets.length > 8 ? '<p class="subtle-note">完整图片列表见配图管理。</p>' : ''}` : emptySection("image","尚无可用配图","只使用知识库中的产品主体原图，并保留型号和来源。")}`;
}
function quoteCard(q,best) {
  const statusLabel = {verified:"已核实",conditional:"附条件",excluded:"已排除"}[q.status] || q.status || "待核实";
  const price = q.checkout_amount;
  const steps = array(q.steps).map(s => typeof s === "string" ? `<div class="row"><span>${esc(s)}</span></div>` : `<div class="row"><span>${esc(s.label || s.name || s.rule_id || s.type || '优惠步骤')}</span><span>${esc(s.amount !== undefined ? `¥${money(s.amount)}` : s.after !== undefined ? `¥${money(s.after)}` : s.description || '')}</span></div>`).join("");
  return `<div class="quote-card ${best ? 'best' : ''}"><div class="quote-model">${esc(q.product_name || q.model || q.sku_key || q.offer_id || '报价方案')}</div><div class="quote-top"><div><div class="quote-channel">${esc(q.channel || '渠道待确认')} · ${esc(q.seller || '商家待确认')}</div><span class="verified-tag ${q.status === 'verified' ? 'yes' : 'no'}">${best ? '同条件推荐 · ' : ''}${esc(statusLabel)}</span></div><div class="quote-price"><small>¥</small>${money(price)}</div></div><div class="quote-breakdown">${q.sku_key ? `<div class="row"><span>SKU</span><span>${esc(q.sku_key)}</span></div>` : ""}${q.condition ? `<div class="row"><span>商品状态</span><span>${esc(({new_unactivated:"全新未激活",activated:"已激活",used:"二手",refurbished:"翻新",unknown:"状态未知"})[q.condition] || q.condition)}</span></div>` : ''}${q.service_key ? `<div class="row"><span>服务条件</span><span>${esc(q.service_key)}</span></div>` : ""}${steps}${Number(q.trade_in_credit) > 0 ? `<div class="row"><span>旧机回收款（另列）</span><span>¥${money(q.trade_in_credit)}</span></div>` : ''}${q.estimated_cash_outlay !== undefined && q.estimated_cash_outlay !== price ? `<div class="row"><span>估算现金支出</span><span>¥${money(q.estimated_cash_outlay)}</span></div>` : ''}${q.conditional_checkout_amount !== null && q.conditional_checkout_amount !== undefined ? `<div class="row"><span>条件满足时金额</span><span>¥${money(q.conditional_checkout_amount)}</span></div>` : ''}</div>${array(q.assumptions).concat(array(q.issues)).filter(Boolean).map(w => `<p class="quote-warning">${esc(textValue(w))}</p>`).join("")}<div class="quote-foot">采集：${esc(dateText(q.observed_at))}${q.expires_at ? `<br>有效至：${esc(dateText(q.expires_at))}` : ""}${q.scope ? `<br>${esc(q.scope)}` : ""}<br>${sourceLink(q.source_url)}</div></div>`;
}
function renderQuotes() {
  const q = state.task?.quotes || {}; const all = array(q.quotes); const best = array(q.best).map(b => ({...(all.find(item => item.offer_id === b.offer_id) || {}),...b})); const ids = new Set(best.map(b => b.offer_id)); const warnings = array(q.warnings).concat(array(state.task?.price_search_warnings));
  const discovery = array(state.task?.price_evidence).length ? `<div class="source-headline" style="margin-top:18px"><h3>联网发现的价格资料</h3><span class="verified-tag no">尚未核实为可下单报价</span></div>${state.task.price_evidence.map(e => `<div class="price-evidence-card"><strong>${esc(e.title)}</strong><p>${esc(e.excerpt)}</p>${sourceLink(e.source_url)}</div>`).join("")}` : '';
  return `<div class="source-headline"><h3>杭州 · 渠道比价</h3><button class="button small" id="import-quotes-btn">${icon("upload")}录入报价</button></div><p class="quote-intro">按同型号、配置、商品与服务条件比较。最低方案仅覆盖已核实报价；旧机回收款单独展示。</p>${state.status?.connections?.search?.configured ? '<button class="text-button" id="search-prices-btn">联网刷新价格依据 ↗</button>' : '<p class="quote-warning">联网价格检索待配置，可先录入带来源与时间的实际报价。</p>'}${warnings.map(w => `<p class="quote-warning">${esc(textValue(w))}</p>`).join("")}${discovery}${best.map(item => quoteCard(item,true)).join("")}${all.filter(item => !ids.has(item.offer_id)).map(item => quoteCard(item,false)).join("")}${!all.length && !best.length ? emptySection("coins","暂无已计算的报价","填写商家实际报价与购买条件，由规则引擎计算可用优惠。") : ''}<p class="subtle-note">报价具有时效性，最终以实际结算与资格核验结果为准。</p>`;
}
function renderChecks() {
  const checks = array(state.task?.checks); const blocked = checks.filter(c => c.status === "blocked").length; const warnings = checks.filter(c => c.status === "warning").length;
  const actions = `<div class="verification-actions"><span>来源、图文与营销表达</span><button class="button small" id="verify-btn" ${state.task ? "" : "disabled"}>${icon("refresh")}重新核验</button></div>`;
  if (!checks.length) return actions + emptySection("shield","核验尚未开始","完成资料检索与内容生成后，逐项检查事实、图片、价格及营销表达。");
  const status = blocked ? "blocked" : warnings ? "warning" : "pass";
  const title = blocked ? `${blocked} 项问题阻止成品交付` : warnings ? `${warnings} 项内容仍需复核` : "本轮自动核验通过";
  const description = blocked ? "先处理来源冲突、缺失依据或型号问题，再继续交付。" : warnings ? "查看下方说明，确认条件与证据后再发布。" : "自动核验已完成；发布前仍需复核实际场景与平台要求。";
  return `${actions}<div class="check-summary ${status}"><strong>${icon(status === 'pass' ? 'check' : 'alert')}${esc(title)}</strong><p>${esc(description)}</p></div>${checks.map(c => `<div class="check-item ${['pass','warning','blocked'].includes(c.status) ? c.status : 'warning'}"><div class="check-symbol">${c.status === 'pass' ? '✓' : c.status === 'blocked' ? '×' : '!'}</div><div><strong>${esc(c.category || '核验项')}</strong><p>${esc(c.message)}</p></div></div>`).join("")}`;
}
function renderEvidence() {
  $$("[data-evidence-tab]").forEach(el => { el.classList.toggle("active",el.dataset.evidenceTab === state.evidenceTab); el.setAttribute("aria-selected",String(el.dataset.evidenceTab === state.evidenceTab)); });
  $("#evidence-count").textContent = `${array(state.task?.facts).length} 条依据`;
  const open = array(state.task?.checks).filter(c => c.status !== "pass").length;
  $("#check-count").textContent = open ? String(open) : "";
  $("#evidence-content").innerHTML = state.evidenceTab === "sources" ? renderSources() : state.evidenceTab === "quotes" ? renderQuotes() : renderChecks();
  renderIcons($("#evidence-content"));
}
function renderAll() { renderPlatforms(); renderMode(); renderBrief(); renderChat(); renderProcess(); renderDraft(); renderEvidence(); renderControls(); }
function setSelectValue(select,value) { if (value && ![...select.options].some(o => o.value === value)) select.add(new Option(value,value)); select.value = value || ""; }
function openBrief() {
  const form = $("#brief-form"); form.reset(); const b = state.task?.brief || {region:"杭州",platform:state.platform};
  $("#brief-scenario").innerHTML = '<option value="">待确认</option>' + scenarios().map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("");
  $("#brief-platform").innerHTML = platforms().map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
  Object.entries(b).forEach(([key,value]) => { const el = form.elements.namedItem(key); if (el && key !== "channels") { if (el.tagName === "SELECT") setSelectValue(el,String(value || "")); else el.value = textValue(value); } });
  $("#brief-channels").innerHTML = channels().map(channel => `<label><input type="checkbox" name="channel" value="${esc(channel)}" ${array(b.channels).includes(channel) ? 'checked' : ''}>${esc(channel)}</label>`).join("");
  showDialog("brief-dialog");
}
function openEdit() { if (!state.task?.draft) return; const form = $("#edit-form"); const draft = state.task.draft; ["title","lead","body","cta"].forEach(key => { form.elements.namedItem(key).value = draft[key] || ""; }); form.elements.namedItem("tags").value = array(draft.tags).join(" "); state.editRevision = state.task.revision; showDialog("edit-dialog"); }
function openAssets() {
  if (!state.task) { toast("请先创建任务并检索产品图片。"); return; }
  const p = platforms().find(p => p.id === state.platform) || defaultPlatforms[0];
  $("#asset-guidance").textContent = `${p.name}建议 ${p.min_images}–${p.max_images} 张图片。只有型号已核验的知识库素材可以选入成品；背景生成不改变产品主体。`;
  const images = resolvedImages(); const selected = new Map(images.map(im => [im.id || im.asset_id,im]));
  state.assetRevision = state.task.revision;
  $("#asset-picker").innerHTML = array(state.task.assets).length ? state.task.assets.map((a,i) => { const current = selected.get(a.id) || a; const isSelected = selected.has(a.id) && a.verified; return `<div class="asset-pick-item ${isSelected ? 'selected' : ''}" data-asset-index="${i}"><input type="checkbox" name="asset" value="${esc(a.id)}" aria-label="选择 ${esc(a.name)}" ${isSelected ? 'checked' : ''} ${a.verified ? '' : 'disabled'}>${safeURL(a.url,true) ? `<img src="${esc(safeURL(a.url,true))}" alt="${esc(a.name)}">` : '<div class="image-load-error">图片暂不可用</div>'}<div class="asset-item-info"><strong>${esc(a.name)}</strong><div class="source">${esc(a.model || '型号待确认')} · ${esc(a.source_title || '来源待确认')}<br>${sourceLink(a.source_url)}</div>${a.verified ? '' : '<div class="unverified-reason">型号未核验，不可选入成品。</div>'}<div class="asset-item-fields"><label>图片说明<input name="caption" value="${esc(current.caption || a.name || '')}" maxlength="300"></label><label>插入位置<select name="position"><option value="开篇">开篇</option><option value="正文中">正文中</option><option value="结尾">结尾</option><option value="主视觉">主视觉</option></select></label></div></div></div>`; }).join("") : emptySection("image","暂时没有图片","先在资料与图片中按具体型号检索。来源或型号无法确认的图片不会用于成品。");
  $$("[data-asset-index]",$("#asset-picker")).forEach(row => { const a = state.task.assets[Number(row.dataset.assetIndex)]; const current = selected.get(a.id) || a; setSelectValue($('select[name="position"]',row),current.position || (state.platform === "poster" ? "主视觉" : "正文中")); });
  renderIcons($("#asset-picker")); updateAssetCount(); showDialog("assets-dialog");
}
function updateAssetCount() { const rows = $$("[data-asset-index]",$("#asset-picker")); let count = 0; rows.forEach(row => { const checked = $('input[name="asset"]',row).checked; row.classList.toggle("selected",checked); if (checked) count++; }); $("#asset-selection-count").textContent = `已选择 ${count} 张`; }
let quoteSequence = 0;
const quoteOriginals = new Map();
const triValue = value => value === true ? "true" : value === false ? "false" : "unknown";
const triBool = value => value === "true" ? true : value === "false" ? false : null;
function beijingInput(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(date).replace(" ","T");
}
function inputISO(value) { if (!value) return null; const date = new Date(`${value}+08:00`); if (Number.isNaN(date.getTime())) throw new Error("请填写有效的北京时间。"); return date.toISOString(); }
const field = (root,name) => $(`[data-field="${name}"]`,root);
function quoteFormError(message) { $("#quotes-error").textContent = message; $("#quotes-error").hidden = false; $("#quotes-error").scrollIntoView({block:"nearest"}); }
function addDiscountRow(card, discount = {}) {
  const list = $(".discount-list",card); if ($$(".discount-row",list).length >= 12) { toast("每条报价最多录入 12 条优惠。",true); return; }
  const row = document.createElement("div"); row.className = "discount-row"; row.dataset.discountId = discount.id || `discount-${++quoteSequence}`;
  row.innerHTML = `<div class="discount-row-top"><span class="discount-order"></span><button type="button" class="text-button" data-discount-up>上移</button><button type="button" class="text-button danger-text" data-remove-discount>移除</button></div><div class="quote-fields"><label>优惠名称<input data-field="discount-label" value="${esc(discount.label || '')}" placeholder="按商家活动名称填写" maxlength="100"></label><label>固定减免金额（元）<input data-field="discount-value" type="number" min="0.01" step="0.01" value="${esc(discount.value ?? '')}" placeholder="实际减免金额"></label><label>满减门槛（元）<input data-field="discount-threshold" type="number" min="0" step="0.01" value="${esc(discount.threshold ?? '')}" placeholder="无门槛可留空"></label><label>互斥组（可选）<input data-field="discount-group" value="${esc(discount.exclusive_group || '')}" placeholder="不能同用的优惠填同一组名" maxlength="100"></label><label class="span-two">活动来源（可选）<input data-field="discount-source" type="url" value="${esc(discount.source_url || '')}" placeholder="留空沿用此条商家报价的来源 URL"></label></div><div class="quote-inline-checks"><label class="quote-check-label"><input data-field="discount-verified" type="checkbox" ${discount.verified === true ? 'checked' : ''}>已核对活动与叠加规则</label><label class="quote-check-label"><input data-field="discount-student" type="checkbox" ${array(discount.requires).includes('student') ? 'checked' : ''}>需学生资格</label></div>`;
  list.append(row); updateDiscountOrder(card);
}
function updateDiscountOrder(card) { $$(".discount-row",card).forEach((row,i) => { $(".discount-order",row).textContent = `优惠 ${i+1}`; $("[data-discount-up]",row).disabled = i === 0; }); }
function addOfferRow(offer = {}) {
  const key = `quote-row-${++quoteSequence}`; quoteOriginals.set(key,offer);
  const card = document.createElement("article"); card.className = "quote-entry-card"; card.dataset.quoteKey = key; card.dataset.offerId = offer.id || `offer-${crypto.randomUUID()}`;
  card.innerHTML = `<div class="quote-entry-heading"><h4></h4><button type="button" class="text-button danger-text" data-remove-offer>移除这条</button></div><div class="quote-fields"><label>购买渠道<select data-field="channel"><option value="">请选择实际渠道</option>${channels().map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('')}</select></label><label>具体商家<input data-field="seller" value="${esc(offer.seller || '')}" placeholder="店铺或门店全称" maxlength="150"></label><label class="span-two">完整型号与配置 SKU<input data-field="sku_key" value="${esc(offer.sku_key || '')}" placeholder="完整型号、处理器、内存、存储、系统等；同配置才可比价" maxlength="300"></label><label>产品名称<input data-field="product_name" value="${esc(offer.product_name || '')}" placeholder="实际销售的产品名称" maxlength="200"></label><label>商品状态<select data-field="condition"><option value="unknown">未确认</option><option value="new_unactivated">全新未激活</option><option value="activated">已激活</option><option value="used">二手</option><option value="refurbished">翻新</option></select></label><label class="span-two">发票与保修条件<input data-field="service_key" value="${esc(offer.service_key && offer.service_key !== 'unspecified' ? offer.service_key : '')}" placeholder="例如：发票类型、保修主体及期限；未知请留空" maxlength="300"></label><label>商品原始报价（元）<input data-field="base_price" type="number" min="0.01" step="0.01" value="${esc(offer.base_price ?? '')}" placeholder="填商家实际商品价，不填定金或月供" required></label><label>库存<select data-field="in_stock"><option value="unknown">未确认</option><option value="true">确认有库存</option><option value="false">已无库存</option></select></label><label>运费（元）<input data-field="shipping" type="number" min="0" step="0.01" value="${esc(offer.shipping ?? '')}" placeholder="已确认包邮可填 0"></label><label>其他必付费用（元）<input data-field="mandatory_fee" type="number" min="0" step="0.01" value="${esc(offer.mandatory_fee ?? '')}" placeholder="没有其他必付费可填 0"></label><label class="span-two">报价来源 URL<input data-field="source_url" type="url" value="${esc(offer.source_url || '')}" placeholder="商品页、商家活动页或可核查的门店报价记录"></label><label>采集时间（北京时间）<input data-field="observed_at" type="datetime-local" value="${esc(beijingInput(offer.observed_at))}"></label><label>有效期（可选，北京时间）<input data-field="expires_at" type="datetime-local" value="${esc(offer.expires_at ? beijingInput(offer.expires_at) : '')}"></label></div><label class="quote-check-label source-verified-check"><input data-field="verified" type="checkbox" ${offer.verified === true ? 'checked' : ''}>我已核对商家来源、完整配置与全部必付费用</label><details class="quote-rule-section" ${array(offer.discounts).length ? 'open' : ''}><summary>固定减免与叠加规则 <span class="subtle-note">可选</span></summary><p>按列表顺序计算，每步以当前商品价判断门槛。同一互斥组最多用一条；不要重复录入已包含在商品报价中的优惠。</p><div class="discount-list"></div><button type="button" class="button small" data-add-discount>${icon('plus')}添加固定减免</button></details><details class="quote-rule-section" ${offer.subsidy ? 'open' : ''}><summary>此商品的国补规则 <span class="subtle-note">默认不启用</span></summary><label class="quote-check-label subsidy-toggle"><input data-field="subsidy-enabled" type="checkbox" ${offer.subsidy ? 'checked' : ''}>按已核实政策录入国补</label><fieldset class="subsidy-fields" ${offer.subsidy ? '' : 'disabled'}><div class="quote-fields"><label>减免比例（%）<input data-field="subsidy-rate" type="number" min="0.01" max="100" step="0.01" value="${esc(offer.subsidy?.rate !== undefined ? Number((Number(offer.subsidy.rate)*100).toFixed(6)) : '')}" placeholder="填写政策明确比例"></label><label>单件减免上限（元）<input data-field="subsidy-cap" type="number" min="0.01" step="0.01" value="${esc(offer.subsidy?.cap ?? '')}" placeholder="填写政策明确上限"></label><label>该 SKU 符合政策<select data-field="subsidy-eligible"><option value="unknown">未确认</option><option value="true">已确认符合</option><option value="false">不符合</option></select></label><label>政策来源 URL<input data-field="subsidy-source" type="url" value="${esc(offer.subsidy?.source_url || '')}" placeholder="适用本地区和本商品的政策依据"></label></div><label class="quote-check-label"><input data-field="subsidy-verified" type="checkbox" ${offer.subsidy?.verified === true ? 'checked' : ''}>已核对当前政策、商户范围与适用顺序</label><p class="quote-rule-hint">个人资格仍需在上方确认；企业采购不计入个人国补。不支持的政策计算顺序请使用高级规则或先人工复核。</p></fieldset></details>`;
  $("#quote-offer-list").append(card);
  setSelectValue(field(card,"channel"),offer.channel || ""); setSelectValue(field(card,"condition"),offer.condition || "unknown"); setSelectValue(field(card,"in_stock"),triValue(offer.in_stock)); setSelectValue(field(card,"subsidy-eligible"),triValue(offer.subsidy?.eligible));
  array(offer.discounts).filter(d => d.kind === "fixed").forEach(d => addDiscountRow(card,d)); updateOfferLabels();
  return card;
}
function updateOfferLabels() { $$(".quote-entry-card",$("#quote-offer-list")).forEach((card,i) => { $("h4",card).textContent = `商家报价 ${i+1}`; }); }
function toggleQuoteMode() { const advanced = $("#use-json-quotes").checked; $("#quote-human-fields").disabled = advanced; $("#quote-human-fields").classList.toggle("disabled",advanced); $("#quote-entry-mode").textContent = advanced ? "本次使用高级 JSON 数据" : "人工报价录入"; $("#offers-json").required = advanced; $("#buyer-json").required = advanced; }
function hasAdvancedRules(offers,buyer) { return offers.some(o => o.trade_in || o.is_deposit || o.price_type && o.price_type !== "full" || o.subsidy && (o.subsidy.observed_at || o.subsidy.expires_at) || array(o.discounts).some(d => d.kind !== "fixed" || d.base && d.base !== "current" || d.observed_at || d.expires_at || array(d.requires).some(r => r !== "student"))) || Object.keys(buyer).some(k => !["kind","student","subsidy_eligible","region"].includes(k)); }
function openQuotes() {
  if (!state.task) { toast("请先创建本次任务。"); return; }
  $("#quotes-error").hidden = true; $("#quote-offer-list").innerHTML = ""; quoteOriginals.clear();
  const existing = array(state.task.offers); const buyer = state.task.buyer || {kind:"personal",student:null,subsidy_eligible:null};
  setSelectValue($("#buyer-kind"),buyer.kind || "personal"); setSelectValue($("#buyer-student"),triValue(buyer.student)); setSelectValue($("#buyer-subsidy"),triValue(buyer.subsidy_eligible));
  (existing.length ? existing : [{}]).forEach(addOfferRow);
  $("#offers-json").value = JSON.stringify(existing,null,2); $("#buyer-json").value = JSON.stringify(buyer,null,2); $("#quote-file").value = ""; $("#quote-file-name").textContent = "报价数组，或包含 offers、buyer 的对象";
  const advanced = hasAdvancedRules(existing,buyer); $("#use-json-quotes").checked = advanced; $("#advanced-quote-import").open = advanced; toggleQuoteMode(); showDialog("quotes-dialog");
}
function humanQuotes() {
  const cards = $$(".quote-entry-card",$("#quote-offer-list")); if (!cards.length) throw new Error("请至少添加一条商家报价。");
  const offers = cards.map((card,index) => {
    const value = name => field(card,name).value.trim(); const checked = name => field(card,name).checked;
    const original = quoteOriginals.get(card.dataset.quoteKey) || {};
    const offer = {...original,id:card.dataset.offerId,channel:value("channel"),seller:value("seller"),sku_key:value("sku_key"),product_name:value("product_name"),condition:value("condition"),service_key:value("service_key"),base_price:value("base_price"),shipping:value("shipping") || "0",mandatory_fee:value("mandatory_fee") || "0",source_url:value("source_url"),observed_at:inputISO(value("observed_at")),in_stock:triBool(value("in_stock")),verified:checked("verified"),currency:"CNY"};
    if (!Number.isFinite(Number(offer.base_price)) || Number(offer.base_price) <= 0) throw new Error(`商家报价 ${index+1}：请填写大于零的实际商品报价。`);
    const expires = inputISO(value("expires_at")); if (expires) offer.expires_at = expires; else delete offer.expires_at;
    offer.discounts = $$(".discount-row",card).map((row,i) => { const amount = field(row,"discount-value").value.trim(); const label = field(row,"discount-label").value.trim(); if (!label || !amount || Number(amount) <= 0) throw new Error(`商家报价 ${index+1} 的优惠 ${i+1}：请填写优惠名称与实际减免金额，或移除空行。`); return {id:row.dataset.discountId,label,kind:"fixed",value:amount,threshold:field(row,"discount-threshold").value.trim() || "0",exclusive_group:field(row,"discount-group").value.trim(),order:i+1,base:"current",source_url:field(row,"discount-source").value.trim() || offer.source_url,verified:field(row,"discount-verified").checked,requires:field(row,"discount-student").checked ? ["student"] : []}; });
    if (checked("subsidy-enabled")) { const rate = value("subsidy-rate"),cap = value("subsidy-cap"),source = value("subsidy-source"); if (!rate || !cap || !source) throw new Error(`商家报价 ${index+1}：启用国补后，请填写已核实的比例、上限与政策来源，或关闭国补。`); offer.subsidy = {rate:Number(rate)/100,cap,source_url:source,eligible:triBool(value("subsidy-eligible")),verified:checked("subsidy-verified")}; } else delete offer.subsidy;
    return offer;
  });
  return {offers,buyer:{kind:$("#buyer-kind").value,student:triBool($("#buyer-student").value),subsidy_eligible:triBool($("#buyer-subsidy").value)}};
}
function renderSettingsConnections() {
  const connections = state.status?.connections || {};
  $("#settings-connections").innerHTML = Object.entries(connectionLabels).map(([id,label]) => { const c = connections[id] || {}; const status = c.connected ? "已连接" : c.configured ? "已配置，等待测试" : "待配置"; return `<div class="setting-connection"><i class="status-dot ${c.connected ? 'connected' : c.configured ? 'pending' : ''}"></i><span class="connection-name">${esc(label)}</span><span class="connection-message">${esc(c.name ? `${c.name} · ` : '')}${esc(c.message || status)}${c.identity_note ? `<br>${esc(c.identity_note)}` : ""}</span><button type="button" class="button small" data-test-connection="${id}" ${c.configured ? '' : 'disabled'}>测试连接</button></div>`; }).join("");
}
function renderSettingsAccess() {
  const managed = state.status?.managed_config === true;
  const pending = !state.status;
  $$("input,select,textarea",$("#settings-form")).forEach(field => { field.disabled = managed || pending; });
  $("#settings-submit").hidden = managed;
  $("#settings-submit").disabled = managed || pending;
  $("#settings-managed-notice").hidden = !managed;
  $("#settings-intro").textContent = managed ? "密钥保存在服务端安全配置中，不向浏览器回显。" : pending ? "正在确认配置权限，请稍候。" : "密钥只提交到服务端，不在页面回显或保存在浏览器。留空表示保留当前配置。";
}
function openSettings() {
  const form = $("#settings-form"); form.reset(); const settings = state.status?.settings || {};
  ["dify_base_url","dashscope_base_url","text_model","vision_model","image_model","public_api_base"].forEach(key => { const value = settings[key] ?? settings.models?.[key.replace("_model","")]; if (typeof value === "string") form.elements.namedItem(key).value = value; });
  renderSettingsAccess(); renderSettingsConnections(); $("#settings-save-status").textContent = ""; showDialog("settings-dialog");
}
function renderHistory() {
  const query = $("#history-search").value.trim().toLowerCase();
  const filtered = state.tasks.filter(t => `${t.title} ${platformName(t.platform || t.brief?.platform)}`.toLowerCase().includes(query));
  $("#history-list").innerHTML = filtered.length ? filtered.map(t => `<button class="history-item" data-open-task="${esc(t.id)}"><span><strong>${esc(t.title || '未命名任务')}</strong><small>${esc(platformName(t.platform || t.brief?.platform))} · ${esc(dateText(t.updated_at))}${state.task?.id === t.id ? ' · 当前任务' : ''}</small></span><span class="mini-tag">打开 ↗</span></button>`).join("") : `<p class="history-empty">${query ? '未找到匹配任务。' : '暂无历史任务，完成的任务会保存在这里。'}</p>`;
}
function openVersions() { $("#version-list").innerHTML = array(state.task?.versions).map((v,i) => `<div class="history-item"><span><strong>${esc(v.label || `版本 ${i+1}`)}</strong><small>${esc(dateText(v.created_at))}</small></span><button class="button small" data-restore-version="${esc(v.id)}">恢复此版</button></div>`).reverse().join("") || '<p class="history-empty">尚无成品版本。</p>'; showDialog("versions-dialog"); }
async function generate(instruction = "",platform) { await ensureTask(); useTask(await api(taskPath("/generate"),{method:"POST",body:{platform:platform || state.platform,...(instruction ? {instruction} : {})}})); toast(state.task.draft ? "内容已保存，请查看核验结果。" : "任务已更新，请补齐助手提示的信息。"); }
async function exportFile() {
  if (!state.task) return; const format = $("#export-format").value;
  const response = await fetch(`${taskPath("/export")}?format=${encodeURIComponent(format)}`,{credentials:"same-origin"});
  requireSession(response);
  if (!response.ok) { let detail; try { detail = await response.json(); } catch {} throw new Error(detail?.detail || `导出失败（${response.status}）`); }
  const blob = await response.blob(); if (!blob.size) throw new Error("导出文件为空，未保存文件。");
  const disposition = response.headers.get("content-disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i); const plain = disposition.match(/filename="?([^";]+)"?/i);
  let filename = `${(state.task.title || "华为PC内容").replace(/[\\/:*?"<>|]/g,"_")}.${format}`;
  try { if (encoded) filename = decodeURIComponent(encoded[1]); else if (plain) filename = plain[1]; } catch {}
  const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),1000); toast("导出文件已准备完成。");
}

document.addEventListener("click",event => {
  const close = event.target.closest("[data-close]"); if (close && !state.busy) closeDialog(close.dataset.close);
  const tab = event.target.closest("[data-evidence-tab]"); if (tab) { state.evidenceTab = tab.dataset.evidenceTab; renderEvidence(); }
  const platform = event.target.closest("[data-platform]"); if (platform && !state.busy && platform.dataset.platform !== state.platform) { const next = platform.dataset.platform; if (state.task?.draft) run(`正在转换为${platformName(next)}格式`,() => generate("根据平台规则重新编排现有任务内容，保留已确认事实和来源。",next)); else if (state.task) run("正在保存发布平台",async () => { useTask(await api(taskPath("/brief"),{method:"POST",body:{brief:{...state.task.brief,platform:next}}})); }); else { state.platform = next; renderPlatforms(); renderControls(); } }
  if (event.target.closest("[data-open-connection]")) openSettings();
  const test = event.target.closest("[data-test-connection]"); if (test) run("正在测试真实连接",async () => { const result = await api("/api/connections/test",{method:"POST",body:{connection:test.dataset.testConnection},timeout:90000}); await refreshStatus(); const connection = state.status?.connections?.[test.dataset.testConnection]; const connected = result.connected === true || connection?.connected === true; if (connected) toast(result.message || "连接测试通过。"); else { const message = result.message || connection?.message || "连接尚未验证，请检查配置。"; toast(message,/失败|HTTP|超时/.test(message)); } });
  const open = event.target.closest("[data-open-task]"); if (open) run("正在打开历史任务",async () => { useTask(await api(`/api/tasks/${encodeURIComponent(open.dataset.openTask)}`)); closeDialog("history-dialog"); toast("已打开保存的任务。"); });
  const restore = event.target.closest("[data-restore-version]"); if (restore) run("正在恢复内容版本",async () => { useTask(await api(taskPath(`/versions/${encodeURIComponent(restore.dataset.restoreVersion)}/restore`),{method:"POST",body:{}})); closeDialog("versions-dialog"); toast("版本已恢复。"); });
  if (event.target.closest("#retrieve-btn")) run("正在检索知识库与核对型号",async () => { await ensureTask(); useTask(await api(taskPath("/retrieve"),{method:"POST",body:{refresh:true}})); toast("依据已更新，请查看来源与核验结果。"); });
  if (event.target.closest("#manage-source-assets-btn")) openAssets();
  if (event.target.closest("#verify-btn") && state.task) run("正在重新核验事实、图片与营销表达",async () => { state.evidenceTab = "checks"; useTask(await api(taskPath("/verify"),{method:"POST",body:{}})); toast("本轮核验已完成，请查看待处理事项。"); });
  if (event.target.closest("#import-quotes-btn")) openQuotes();
  if (event.target.closest("#search-prices-btn")) run("正在搜索价格与活动依据",async () => { await ensureTask(); useTask(await api(taskPath("/prices/search"),{method:"POST",body:{}})); await refreshStatus(); state.evidenceTab = "quotes"; renderEvidence(); toast("价格资料检索已结束，请核实可计算的报价。"); });
  if (event.target.closest("#use-example-btn")) { $("#chat-input").value = "面向杭州大学新生，在小红书介绍适合日常学习和多设备协同的华为电脑，预算6000元左右，目标是帮助选购。产品尚未选定。"; $("#chat-input").focus(); }
});
$("#new-task-btn").addEventListener("click",() => run("正在创建任务",async () => { useTask(await api("/api/tasks",{method:"POST",body:{}})); $("#chat-input").value = ""; $("#chat-input").focus(); toast("新任务已创建。"); }));
$("#edit-brief-btn").addEventListener("click",openBrief);
$("#brief-form").addEventListener("submit",event => { event.preventDefault(); if (state.busy) return; const form = new FormData(event.currentTarget); const brief = {...(state.task?.brief || {})}; ["audience","scenario","platform","goal","product","budget","region","purchase_stage","software"].forEach(k => { brief[k] = String(form.get(k) || "").trim(); }); brief.channels = form.getAll("channel"); run("正在保存需求",async () => { await ensureTask(); useTask(await api(taskPath("/brief"),{method:"POST",body:{brief},timeout:30000})); closeDialog("brief-dialog"); toast("创作需求已保存。"); }); });
$("#chat-form").addEventListener("submit",event => { event.preventDefault(); const message = $("#chat-input").value.trim(); if (!message) return; run("正在理解需求并处理任务",async () => { await ensureTask(); useTask(await api(taskPath("/chat"),{method:"POST",body:{message}})); $("#chat-input").value = ""; }); });
$("#chat-input").addEventListener("keydown",event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!state.busy) $("#chat-form").requestSubmit(); } });
$("#scroll-chat-btn").addEventListener("click",() => { const el = $("#chat-messages"); el.scrollTop = el.scrollHeight; });
$("#generate-btn").addEventListener("click",() => run("正在检索、编排内容并核验",() => generate()));
$("#revision-form").addEventListener("submit",event => { event.preventDefault(); const instruction = $("#revision-input").value.trim(); if (!instruction) { $("#revision-input").focus(); return; } run("正在按要求修改并重新核验",async () => { await generate(instruction); $("#revision-input").value = ""; }); });
$("#edit-draft-btn").addEventListener("click",openEdit);
$("#edit-form").addEventListener("submit",event => { event.preventDefault(); if (state.busy) return; const form = new FormData(event.currentTarget); const draft = {...state.task.draft}; ["title","lead","body","cta"].forEach(k => { draft[k] = String(form.get(k) || "").trim(); }); draft.tags = String(form.get("tags") || "").split(/[\s,，]+/).filter(Boolean); run("正在保存内容并重新核验",async () => { useTask(await api(taskPath("/draft"),{method:"POST",body:{draft,revision:state.editRevision}})); closeDialog("edit-dialog"); toast("成品文字已保存，核验结果已更新。"); }); });
$("#assets-btn").addEventListener("click",openAssets);
$("#background-btn").addEventListener("click",() => { $("#background-form").reset(); showDialog("background-dialog"); });
$("#background-form").addEventListener("submit",event => { event.preventDefault(); const prompt = String(new FormData(event.currentTarget).get("prompt") || "").trim(); if (!prompt) return; run("正在生成背景，并与产品原图合成",async () => { useTask(await api(taskPath("/background"),{method:"POST",body:{prompt},timeout:300000})); closeDialog("background-dialog"); await refreshStatus(); toast("背景已生成，产品原图已独立合成。请执行视觉核验。"); }); });
$("#vision-btn").addEventListener("click",() => run("正在比较海报与产品原图",async () => { state.evidenceTab = "checks"; useTask(await api(taskPath("/vision"),{method:"POST",body:{}})); await refreshStatus(); toast("视觉辅助核验已完成，请查看核验结果。"); }));
$("#asset-picker").addEventListener("change",updateAssetCount);
$("#assets-form").addEventListener("submit",event => { event.preventDefault(); if (!state.task?.draft) { toast("请先生成文字草稿，再保存成品配图。",true); return; } const images = $$("[data-asset-index]",$("#asset-picker")).filter(row => $('input[name="asset"]',row).checked).map(row => ({...state.task.assets[Number(row.dataset.assetIndex)],caption:$('input[name="caption"]',row).value.trim(),position:$('select[name="position"]',row).value})); const p = platforms().find(p => p.id === state.platform); if (p && images.length > p.max_images) { toast(`${p.name}最多选择 ${p.max_images} 张图片。`,true); return; } run("正在保存配图并核对型号",async () => { useTask(await api(taskPath("/draft"),{method:"POST",body:{draft:{...state.task.draft,images},revision:state.assetRevision}})); closeDialog("assets-dialog"); toast("配图编排已保存。"); }); });
$("#quotes-form").addEventListener("submit",event => { event.preventDefault(); let offers,buyer; try { if ($("#use-json-quotes").checked) { offers = JSON.parse($("#offers-json").value); buyer = JSON.parse($("#buyer-json").value); } else ({offers,buyer} = humanQuotes()); if (!Array.isArray(offers) || !offers.length) throw new Error("请至少提供一条实际商家报价。"); if (!buyer || Array.isArray(buyer) || typeof buyer !== "object") throw new Error("购买人条件应是 JSON 对象。"); $("#quotes-error").hidden = true; } catch (error) { quoteFormError(error.message); return; } run("正在按独立规则计算报价",async () => { useTask(await api(taskPath("/quotes"),{method:"POST",body:{offers,buyer}})); state.evidenceTab = "quotes"; renderEvidence(); closeDialog("quotes-dialog"); toast("报价计算已完成，请查看条件与排除说明。"); }); });
$("#add-offer-btn").addEventListener("click",() => { const card = addOfferRow(); card.scrollIntoView({block:"start",behavior:"smooth"}); field(card,"channel").focus(); });
$("#use-json-quotes").addEventListener("change",toggleQuoteMode);
$("#quote-offer-list").addEventListener("click",event => {
  const card = event.target.closest(".quote-entry-card"); if (!card) return;
  if (event.target.closest("[data-add-discount]")) addDiscountRow(card);
  if (event.target.closest("[data-remove-offer]")) { quoteOriginals.delete(card.dataset.quoteKey); card.remove(); updateOfferLabels(); }
  const remove = event.target.closest("[data-remove-discount]"); if (remove) { remove.closest(".discount-row").remove(); updateDiscountOrder(card); }
  const up = event.target.closest("[data-discount-up]"); if (up) { const row = up.closest(".discount-row"); if (row.previousElementSibling) row.parentElement.insertBefore(row,row.previousElementSibling); updateDiscountOrder(card); }
});
$("#quote-offer-list").addEventListener("change",event => { if (event.target.dataset.field === "subsidy-enabled") { const card = event.target.closest(".quote-entry-card"); $(".subsidy-fields",card).disabled = !event.target.checked; } });
$("#quote-file").addEventListener("change",async event => { const file = event.target.files[0]; if (!file) return; try { if (file.size > 2000000) throw new Error("报价文件超过 2 MB，请缩小后导入。"); const data = JSON.parse(await file.text()); if (Array.isArray(data)) $("#offers-json").value = JSON.stringify(data,null,2); else if (data && Array.isArray(data.offers)) { $("#offers-json").value = JSON.stringify(data.offers,null,2); if (data.buyer) $("#buyer-json").value = JSON.stringify(data.buyer,null,2); } else throw new Error("文件需包含报价数组，或 offers 数组与 buyer 对象。"); $("#quote-file-name").textContent = file.name; $("#use-json-quotes").checked = true; toggleQuoteMode(); $("#quotes-error").hidden = true; } catch (error) { $("#quotes-error").textContent = error.message; $("#quotes-error").hidden = false; } });
document.addEventListener("submit",event => { if (event.target.id !== "source-search-form") return; event.preventDefault(); const query = $("#source-query").value.trim(); if (!query) { $("#source-query").focus(); return; } run("正在按型号检索资料与图片",async () => { await ensureTask(); useTask(await api(taskPath("/retrieve"),{method:"POST",body:{query}})); toast("检索已完成，请查看依据与待确认事项。"); }); });
$("#settings-btn").addEventListener("click",openSettings);
$("#settings-form").addEventListener("submit",event => { event.preventDefault(); if (!state.status || state.status.managed_config === true) { toast(state.status ? "托管配置由部署者安全管理，此处仅可查看和测试连接。" : "尚未确认配置权限，请等待服务状态加载。",true); return; } const data = {}; new FormData(event.currentTarget).forEach((value,key) => { if (String(value).trim()) data[key] = String(value).trim(); }); if (!Object.keys(data).length) { toast("未填写需要更新的配置。"); return; } run("正在安全保存连接配置",async () => { const result = await api("/api/settings",{method:"POST",body:data}); if (result.status !== "saved") throw new Error("服务未确认配置保存成功。"); $$('input[type="password"]',$("#settings-form")).forEach(el => { el.value = ""; }); await refreshStatus(); $("#settings-save-status").textContent = "已保存 · 请测试连接"; toast("配置已保存；连接是否可用以测试结果为准。"); }); });
$("#logout-btn").addEventListener("click",() => run("正在退出登录",async () => { await api("/api/logout",{method:"POST",body:{},timeout:30000}); try { localStorage.removeItem("huawei-pc-active-task"); } catch {} state.redirectingToLogin = true; location.replace("/login"); }));
$("#settings-dialog").addEventListener("close",() => { $$('input[type="password"]',$("#settings-form")).forEach(el => { el.value = ""; }); });
$("#history-btn").addEventListener("click",() => run("正在读取历史任务",async () => { await refreshTaskList(); $("#history-search").value = ""; renderHistory(); showDialog("history-dialog"); }));
$("#history-search").addEventListener("input",renderHistory);
$("#versions-btn").addEventListener("click",openVersions);
$("#copy-btn").addEventListener("click",() => run("正在重新核价并检查可复制内容",async () => {
  if (!state.task?.draft) return;
  const result = await api(taskPath("/copy"),{method:"GET"});
  if (typeof result.text !== "string" || !result.text.trim()) throw new Error("服务未返回可复制的成品文字，未写入剪贴板。");
  try { await navigator.clipboard.writeText(result.text); } catch { throw new Error("浏览器未允许剪贴板访问，请导出 TXT 获取经核验的成品文字。"); }
  toast("经核验的成品文字已复制，包含必要的广告与 AI 标识。");
}));
$("#export-format").addEventListener("change",renderControls);
$("#export-btn").addEventListener("click",() => run("正在打包并核验导出文件",exportFile));
$("#retry-status-btn").addEventListener("click",() => run("正在重新连接服务",async () => { await refreshStatus(); toast("服务状态已刷新。"); }));
$("#dismiss-error-btn").addEventListener("click",() => { $("#global-error").hidden = true; });
document.addEventListener("error",event => { if (event.target.tagName !== "IMG") return; const img = event.target; const box = document.createElement("div"); box.className = "image-load-error"; box.textContent = "图片加载失败，请检查来源或刷新资料。"; img.replaceWith(box); },true);
$$('dialog').forEach(dialog => { dialog.addEventListener("cancel",event => { if (state.busy) event.preventDefault(); }); dialog.addEventListener("click",event => { if (event.target !== dialog || state.busy) return; const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeDialog(dialog.id); }); });

async function init() {
  renderIcons(); renderAll();
  const results = await Promise.allSettled([refreshStatus(),refreshTaskList()]);
  results.forEach(result => { if (result.status === "rejected") showError(result.reason.message); });
  let saved; try { saved = localStorage.getItem("huawei-pc-active-task"); } catch {}
  if (saved && state.tasks.some(t => t.id === saved)) { try { useTask(await api(`/api/tasks/${encodeURIComponent(saved)}`)); } catch (error) { showError(error.message); } }
  renderAll();
}
init();
