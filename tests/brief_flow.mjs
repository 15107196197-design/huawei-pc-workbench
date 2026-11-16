// Run with Node.js: node tests/brief_flow.mjs. No browser, network, or credentials.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
assert.match(source, /\ninit\(\);\s*$/);
// Exercise the shipped handlers, API wrapper and run() without starting page hydration.
const handlersOnly = source.replace(/\ninit\(\);\s*$/, "\n");
const fields = { audience: "  大学新生  ", scenario: "school", platform: "xiaohongshu", goal: "  帮助选购  ", product: "  Synthetic Model A  ", budget: "  6000元  ", region: "  杭州  ", purchase_stage: "对比选型", software: "  课程软件待确认  ", channel: ["华为商城", "线下门店"] };
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));

function element(id) {
  const classes = new Set();
  return {
    id, hidden: true, disabled: false, open: false, textContent: "", value: "", attrs: {}, handlers: new Map(),
    classList: { toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); }, contains(name) { return classes.has(name); } },
    addEventListener(name, handler) { this.handlers.set(name, handler); },
    setAttribute(name, value) { this.attrs[name] = value; }, removeAttribute(name) { delete this.attrs[name]; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    showModal() { this.open = true; }, close() { this.open = false; }, focus() {},
  };
}

function createFlow(dialogId = "brief-dialog") {
  const elements = new Map(), documentHandlers = new Map(), calls = [], snapshots = [], timers = [], storage = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, element(id)); return elements.get(id); };
  const dialog = get(dialogId), form = get(dialogId === "brief-dialog" ? "brief-form" : "edit-form");
  const feedback = element("feedback"), submit = element("submit"), cancel = element("cancel"), close = element("close"), initiallyDisabled = element("initially-disabled");
  initiallyDisabled.disabled = true;
  const buttons = [submit, cancel, close, initiallyDisabled];
  dialog.open = true;
  dialog.querySelector = selector => selector === "[data-dialog-feedback]" ? feedback : null;
  dialog.querySelectorAll = () => buttons;
  form.values = dialogId === "brief-dialog" ? plain(fields) : { title: "  修改后的标题  ", lead: "  导语  ", body: "  正文  ", cta: "  咨询门店  ", tags: "  校园，选购 #电脑  " };
  const document = {
    body: element("body"), querySelector: selector => get(selector.replace(/^#/, "")),
    querySelectorAll: selector => selector === "dialog[open]" ? (dialog.open ? [dialog] : []) : selector === "dialog" ? [dialog] : [],
    getElementById: get, addEventListener: (name, handler) => documentHandlers.set(name, handler),
    createElement: () => element("created"),
  };
  class SnapshotFormData {
    constructor(target) {
      assert.equal(target, form, "Read the actual form while the submit event is active");
      snapshots.push({ values: plain(target.values), submitDisabled: submit.disabled });
      this.values = plain(target.values);
    }
    get(key) { const value = this.values[key]; return Array.isArray(value) ? value[0] : value ?? null; }
    getAll(key) { const value = this.values[key]; return value === undefined ? [] : Array.isArray(value) ? [...value] : [value]; }
  }
  const context = vm.createContext({
    document, FormData: SnapshotFormData, AbortController,
    localStorage: { setItem: (key, value) => storage.set(key, value) },
    location: { origin: "https://synthetic.example", pathname: "/", replace() { throw new Error("Unexpected login redirect"); } },
    setTimeout: (fn, delay) => { timers.push(delay); return timers.length; }, clearTimeout() {},
    fetch: (url, options) => new Promise(resolve => { calls.push({ url, options, resolve }); }),
  });
  vm.runInContext(handlersOnly, context, { filename: "static/app.js" });
  // Rendering is independent of form submission. Keep its output out of the DOM stub.
  vm.runInContext("renderAll = () => {}; renderControls = () => {};", context);
  const state = vm.runInContext("state", context);
  state.task = { id: "synthetic-task", revision: 7, brief: { ...plain(fields), product: "Old Model", channels: ["淘宝"], retained: "unchanged" }, draft: { title: "旧标题", fact_ids: ["synthetic-fact"], tags: [] } };
  state.editRevision = 7;
  state.platform = "xiaohongshu";
  const dispatch = () => {
    const event = { currentTarget: form, prevented: false, preventDefault() { this.prevented = true; } };
    form.handlers.get("submit")(event);
    assert.equal(event.prevented, true);
    event.currentTarget = null; // Browsers clear currentTarget when event dispatch ends.
  };
  const respond = (index, status, body) => calls[index].resolve({ status, ok: status >= 200 && status < 300, headers: { get: () => "application/json" }, json: async () => body });
  return { state, dialog, form, feedback, submit, cancel, close, initiallyDisabled, calls, snapshots, timers, get, dispatch, respond, context, documentHandlers };
}

async function settle(flow) {
  for (let i = 0; i < 20 && flow.state.busy; i++) await tick();
  assert.equal(flow.state.busy, false, "Operation should settle after its response");
}

const flow = createFlow();
const originalBrief = plain(flow.state.task.brief);
flow.dispatch();
assert.equal(flow.state.busy, true);
assert.equal(flow.feedback.hidden, false);
assert.match(flow.feedback.textContent, /正在保存需求/);
assert.equal(flow.feedback.attrs.role, "status");
assert.equal(flow.dialog.attrs["aria-busy"], "true");
assert.equal(flow.submit.disabled, true);
assert.equal(flow.cancel.disabled, true);
assert.equal(flow.close.disabled, true);
assert.equal(flow.snapshots.length, 1);
assert.equal(flow.snapshots[0].submitDisabled, false, "Snapshot before run() disables submit controls");
assert.deepEqual(flow.snapshots[0].values, fields);
flow.dispatch();
await tick();
assert.equal(flow.snapshots.length, 1, "Duplicate submit must not read another form snapshot");
assert.equal(flow.calls.length, 1, "Duplicate submit must not send another request");
assert.equal(flow.calls[0].url, "/api/tasks/synthetic-task/brief");
assert.equal(flow.calls[0].options.method, "POST");
assert.equal(flow.calls[0].options.credentials, "same-origin");
assert.ok(flow.timers.includes(30000), "Brief saves use a 30-second request timeout");
const sent = JSON.parse(flow.calls[0].options.body).brief;
for (const [key, value] of Object.entries(fields)) {
  if (key !== "channel") assert.equal(sent[key], value.trim(), `Save ${key}`);
}
assert.deepEqual(sent.channels, fields.channel);
assert.equal(sent.retained, "unchanged", "Preserve unrelated brief fields");
flow.form.values.audience = "尚未保存的新输入";
assert.equal(sent.audience, "大学新生", "Request uses the synchronous form snapshot");
flow.respond(0, 403, { detail: "测试上游拒绝，请重试" });
await settle(flow);
assert.equal(flow.dialog.open, true);
assert.equal(flow.feedback.hidden, false);
assert.equal(flow.feedback.classList.contains("error"), true);
assert.equal(flow.feedback.attrs.role, "alert");
assert.match(flow.feedback.textContent, /测试上游拒绝/);
assert.equal(flow.form.values.audience, "尚未保存的新输入", "Failure preserves editable input");
assert.deepEqual(plain(flow.state.task.brief), originalBrief, "Failure does not replace the saved task");
for (const button of [flow.submit, flow.cancel, flow.close]) assert.equal(button.disabled, false);
assert.equal(flow.initiallyDisabled.disabled, true, "Restore existing disabled states");
assert.equal(flow.dialog.attrs["aria-busy"], undefined);
flow.dispatch();
await tick();
assert.equal(flow.calls.length, 2);
assert.equal(flow.feedback.classList.contains("error"), false, "Retry clears the prior error");
const retried = JSON.parse(flow.calls[1].options.body).brief;
assert.equal(retried.audience, "尚未保存的新输入");
flow.respond(1, 200, { ...plain(flow.state.task), revision: 8, brief: retried });
await settle(flow);
assert.equal(flow.dialog.open, false, "Only successful persistence closes the editor");
assert.equal(flow.state.task.revision, 8);
assert.deepEqual(plain(flow.state.task.brief), retried);
assert.equal(flow.feedback.hidden, true);
assert.match(flow.get("toast").textContent, /创作需求已保存/);

const edit = createFlow("edit-dialog");
edit.dispatch();
await tick();
assert.equal(edit.snapshots[0].submitDisabled, false);
assert.equal(edit.calls[0].options.method, "POST");
assert.equal(edit.calls[0].url, "/api/tasks/synthetic-task/draft");
const edited = JSON.parse(edit.calls[0].options.body);
assert.equal(edited.revision, 7, "Keep optimistic revision checking");
assert.deepEqual(edited.draft, { title: "修改后的标题", lead: "导语", body: "正文", cta: "咨询门店", tags: ["校园", "选购", "#电脑"], fact_ids: ["synthetic-fact"] });
edit.respond(0, 409, { detail: "该内容已被更新，请重新打开" });
await settle(edit);
assert.equal(edit.dialog.open, true);
assert.equal(edit.feedback.hidden, false);
assert.match(edit.feedback.textContent, /重新打开/);
assert.equal(edit.form.values.title, "  修改后的标题  ");

// An unstarted task saves its selected platform through the same POST alias.
const fresh = createFlow();
fresh.state.task = null;
fresh.state.platform = "xiaohongshu";
fresh.dispatch();
assert.equal(fresh.calls.length, 1);
assert.equal(fresh.calls[0].url, "/api/tasks");
fresh.respond(0, 200, { id: "fresh-task", brief: { platform: "wechat" }, revision: 0 });
await tick();
assert.equal(fresh.calls[1].url, "/api/tasks/fresh-task/brief");
assert.equal(fresh.calls[1].options.method, "POST");
fresh.respond(1, 200, { id: "fresh-task", brief: { platform: "xiaohongshu" }, revision: 1 });
await tick();
assert.equal(fresh.calls[2].url, "/api/tasks/fresh-task/brief");
assert.equal(fresh.calls[2].options.method, "POST");
const freshBrief = JSON.parse(fresh.calls[2].options.body).brief;
assert.equal(freshBrief.product, "Synthetic Model A");
fresh.respond(2, 200, { id: "fresh-task", brief: freshBrief, revision: 2 });
await settle(fresh);
assert.equal(fresh.dialog.open, false);

console.log("Brief and draft form flows passed: pending visibility, snapshot, duplicate guard, failure/retry, revision conflict, initial task save.");
