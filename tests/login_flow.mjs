// Run with Node.js: node tests/login_flow.mjs. No browser, network, or credentials.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../static/login.js", import.meta.url), "utf8");

function response(status, body) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

function createFlow(responses) {
  const elements = new Map();
  const handlers = new Map();
  for (const name of ["login-form", "username", "password", "login-submit", "login-error", "login-status"]) {
    elements.set(name, {
      value: name === "username" ? "  synthetic-operator  " : name === "password" ? "synthetic-password" : "",
      disabled: false, hidden: true, textContent: "", focus() {}, reportValidity() { return true; },
      addEventListener(event, handler) { handlers.set(event, handler); },
    });
  }
  const calls = [], redirects = [];
  const context = vm.createContext({
    document: { getElementById: id => elements.get(id) },
    location: { replace: target => redirects.push(target) },
    AbortController, setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, options) => {
      calls.push({ url, options });
      assert.ok(responses.length, "Unexpected additional request");
      return await responses.shift();
    },
  });
  vm.runInContext(source, context, { filename: "static/login.js" });
  return { elements, calls, redirects, run: () => handlers.get("submit")({ preventDefault() {} }) };
}

function assertRequestBoundary(flow) {
  assert.equal(flow.calls[0].url, "/api/login");
  assert.equal(flow.calls[0].options.method, "POST");
  const body = JSON.parse(flow.calls[0].options.body);
  assert.equal(body.username, "synthetic-operator");
  assert.equal(body.password, "synthetic-password");
  for (const { url, options } of flow.calls) {
    assert.ok(["/api/login", "/api/status"].includes(url), "Credentials must remain on fixed relative endpoints");
    // In same-origin fetch mode, no-referrer can serialize POST Origin as null.
    // CORS mode preserves the real Origin without permitting cross-origin cookies.
    assert.equal(options.mode, "cors");
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    assert.equal(Object.hasOwn(options, "referrerPolicy"), false);
    assert.equal(Object.keys(options.headers).some(name => ["origin", "authorization"].includes(name.toLowerCase())), false);
  }
  if (flow.calls.length > 1) {
    assert.equal(flow.calls[1].url, "/api/status");
    assert.equal(flow.calls[1].options.method, "GET");
    assert.equal(flow.calls[1].options.signal, flow.calls[0].options.signal);
    assert.equal(flow.calls[1].options.body, undefined);
  }
}

let confirmSession;
const confirmation = new Promise(resolve => { confirmSession = resolve; });
const success = createFlow([response(200, { status: "authenticated" }), confirmation]);
const pending = success.run();
await new Promise(resolve => setImmediate(resolve));
assert.equal(success.calls.length, 2);
assert.deepEqual(success.redirects, [], "POST success alone cannot open the workspace");
confirmSession(response(200, { authentication: { method: "session" } }));
await pending;
assertRequestBoundary(success);
assert.deepEqual(success.redirects, ["/"]);
assert.equal(success.elements.get("password").value, "");

const blockedCookie = createFlow([response(200, {}), response(401, {})]);
await blockedCookie.run();
assertRequestBoundary(blockedCookie);
assert.deepEqual(blockedCookie.redirects, []);
assert.match(blockedCookie.elements.get("login-error").textContent, /Cookie/);
assert.match(blockedCookie.elements.get("login-error").textContent, /独立浏览器窗口/);
assert.equal(blockedCookie.elements.get("login-submit").disabled, false);
assert.equal(blockedCookie.elements.get("password").value, "");

const wrongPassword = createFlow([response(401, { detail: "合成账号或密码不正确" })]);
await wrongPassword.run();
assertRequestBoundary(wrongPassword);
assert.equal(wrongPassword.calls.length, 1);
assert.deepEqual(wrongPassword.redirects, []);
assert.equal(wrongPassword.elements.get("login-submit").disabled, false);
assert.equal(wrongPassword.elements.get("password").value, "");

const invalidSession = createFlow([response(200, {}), response(200, { authentication: { method: "basic" } })]);
await invalidSession.run();
assertRequestBoundary(invalidSession);
assert.deepEqual(invalidSession.redirects, []);
assert.equal(invalidSession.elements.get("login-submit").disabled, false);
assert.equal(invalidSession.elements.get("password").value, "");

console.log("PASS: four login flows; fixed endpoints, CORS mode, same-origin credentials, session confirmation and retry boundaries.");
