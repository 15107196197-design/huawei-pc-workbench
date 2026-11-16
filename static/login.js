"use strict";

const form = document.getElementById("login-form");
const username = document.getElementById("username");
const password = document.getElementById("password");
const submit = document.getElementById("login-submit");
const errorMessage = document.getElementById("login-error");
const statusMessage = document.getElementById("login-status");
let submitting = false;

form.addEventListener("submit",async event => {
  event.preventDefault();
  if (submitting || !form.reportValidity()) return;
  const account = username.value.trim();
  if (!account) { username.focus(); return; }
  submitting = true;
  errorMessage.hidden = true;
  statusMessage.textContent = "正在验证登录信息…";
  submit.textContent = "正在登录…";
  username.disabled = password.disabled = submit.disabled = true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(),30000);
  let confirmingSession = false;
  try {
    const response = await fetch("/api/login",{
      method:"POST",mode:"cors",credentials:"same-origin",cache:"no-store",
      headers:{"Content-Type":"application/json","Accept":"application/json"},
      body:JSON.stringify({username:account,password:password.value}),signal:controller.signal
    });
    if (!response.ok) {
      let data;
      try { data = await response.json(); } catch {}
      const fallback = response.status === 429 ? "登录尝试过于频繁，请稍后重试。" : response.status === 401 ? "账号或密码不正确，请重新输入。" : "暂时无法登录，请稍后重试或联系部署者。";
      throw new Error(typeof data?.detail === "string" ? data.detail : fallback);
    }
    password.value = "";
    confirmingSession = true;
    statusMessage.textContent = "正在确认登录会话…";
    const sessionResponse = await fetch("/api/status",{
      method:"GET",mode:"cors",credentials:"same-origin",cache:"no-store",
      headers:{"Accept":"application/json"},signal:controller.signal
    });
    if (sessionResponse.status === 401) {
      throw new Error("浏览器可能限制了嵌入页面的跨站 Cookie，登录会话未能生效。请在独立浏览器窗口打开工作台后重新登录。");
    }
    if (!sessionResponse.ok) {
      throw new Error(`登录已提交，但会话确认失败（HTTP ${sessionResponse.status}），请重新登录或联系部署者。`);
    }
    let session;
    try { session = await sessionResponse.json(); } catch { throw new Error("服务器未返回有效的登录会话状态，请重试或联系部署者。"); }
    if (session?.authentication?.method !== "session") {
      throw new Error("尚未确认有效的登录会话，请重试或联系部署者检查登录配置。");
    }
    statusMessage.textContent = "登录成功，正在打开工作台…";
    location.replace("/");
  } catch (error) {
    const message = error.name === "AbortError" ? (confirmingSession ? "登录会话确认超时，请检查网络后重新登录。" : "登录请求超时，请检查网络后重试。") : error instanceof TypeError ? (confirmingSession ? "登录已提交，但确认会话时无法连接服务，请检查网络后重新登录。" : "无法连接工作台服务，请检查网络后重试。") : error.message;
    errorMessage.textContent = message || "登录未完成，请重试。";
    errorMessage.hidden = false;
    statusMessage.textContent = "";
    password.value = "";
    username.disabled = password.disabled = submit.disabled = false;
    submit.textContent = "登录工作台";
    password.focus();
  } finally {
    password.value = "";
    clearTimeout(timer);
    submitting = false;
  }
});
