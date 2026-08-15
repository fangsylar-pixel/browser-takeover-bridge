import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs.readFileSync(path.join(root, "extension", "background.js"), "utf8");
const requests = [];
const listeners = {};
const badge = {};
const debuggerListeners = new Set();

const chrome = {
  storage: {
    local: {
      async get() {
        return { codexBrowserTakeoverClientId: "runtime-test-client", browserTakeoverAdvancedControl: true };
      },
      async set() {},
    },
  },
  tabs: {
    async query() {
      return [{ id: 1, windowId: 1, active: true, title: "Test", url: "https://example.test", status: "complete" }];
    },
    async update(id, changes) {
      return { id, windowId: 1, title: "Ready", url: changes.url, status: "loading" };
    },
    async get(id) {
      return { id, windowId: 1, title: "Ready", url: "https://example.test/ready", status: "complete" };
    },
    onCreated: { addListener() {} },
    onUpdated: { addListener() {} },
    onRemoved: { addListener() {} },
    onActivated: { addListener() {} },
  },
  scripting: {
    async executeScript(details) {
      if (details.args?.[0]?.urlPattern) {
        return [{ result: { selectorMatched: true, textMatched: true, urlMatched: true, href: "https://example.test/ready", title: "Ready", readyState: "complete" } }];
      }
      return [{ result: null }];
    },
  },
  runtime: {
    onInstalled: { addListener() {} },
    onStartup: { addListener() {} },
    onMessage: {
      addListener(listener) {
        listeners.message = listener;
      },
    },
    reload() {},
  },
  action: {
    async setBadgeText(value) { badge.text = value.text; },
    async setBadgeBackgroundColor(value) { badge.color = value.color; },
    async setTitle(value) { badge.title = value.title; },
  },
  downloads: {
    async download() { return 99; },
    async search() { return []; },
  },
  debugger: {
    onEvent: {
      addListener(listener) { debuggerListeners.add(listener); },
      removeListener(listener) { debuggerListeners.delete(listener); },
    },
    attach(target, version, callback) { callback(); },
    detach(target, callback) { callback(); },
    sendCommand(target, method, params, callback) {
      if (method === "Page.enable") {
        for (const listener of debuggerListeners) {
          listener(target, "Page.javascriptDialogOpening", { type: "alert", message: "Test dialog", hasBrowserHandler: false });
        }
      }
      callback({});
    },
  },
  // Intentionally omit chrome.alarms to cover Edge environments where it is unavailable.
};

async function fetchMock(url, options = {}) {
  requests.push({ url, options });
  if (url.endsWith("/extension/register")) {
    return {
      ok: true,
      async json() {
        return { ok: true, token: "test-token", protocolVersion: 2, pollIntervalMs: 250 };
      },
    };
  }
  if (url.includes("/extension/poll")) {
    return { ok: true, async json() { return { ok: true, command: null }; } };
  }
  return { ok: true, async json() { return { ok: true }; } };
}

const context = vm.createContext({
  chrome,
  crypto: globalThis.crypto,
  fetch: fetchMock,
  navigator: { userAgent: "Runtime Test" },
  console,
  setInterval() { return 1; },
  clearInterval() {},
  setTimeout() { return 1; },
  clearTimeout() {},
  URL,
  TextEncoder,
  TextDecoder,
});

vm.runInContext(source, context, { filename: "background.js" });
await new Promise((resolve) => setTimeout(resolve, 50));

assert.ok(requests.some((request) => request.url.endsWith("/extension/register")), "extension should register");
assert.ok(requests.some((request) => request.url.endsWith("/extension/tabs")), "extension should sync tabs");
assert.ok(requests.some((request) => request.url.includes("/extension/poll")), "extension should poll commands");
assert.equal(typeof listeners.message, "function", "status message listener should be installed");
assert.equal(badge.text, "ON", "connected badge should be visible");

const navigation = await context.navigateTab({
  tabId: 1,
  url: "https://example.test/ready",
  options: { waitTimeout: 1000, settleMs: 0, urlPattern: "/ready$", selector: "main", text: "Loaded" },
});
assert.equal(navigation.ok, true, "navigation should wait for readiness evidence");
assert.equal(navigation.timedOut, false);
assert.equal(navigation.evidence.selectorMatched, true);

const browserReadyNavigation = await context.navigateTab({
  tabId: 1,
  url: "https://example.test/ready",
  options: { waitTimeout: 1000, settleMs: 0 },
});
assert.equal(browserReadyNavigation.ok, true, "navigation without business evidence should finish at browser readiness");
assert.equal(browserReadyNavigation.evidence.source, "browser-tab");

const dialogResult = await context.handleJavaScriptDialog({ tabId: 1, accept: true, waitTimeout: 0 });
assert.equal(dialogResult.ok, true, "dialog handler should use debugger dialog evidence");
assert.equal(dialogResult.dialog.type, "alert");
assert.equal(debuggerListeners.size, 0, "dialog listener should always be removed");

let response;
listeners.message({ type: "bridge-status" }, {}, (value) => { response = value; });
assert.equal(response.ok, true);
assert.equal(response.state.connected, true);
assert.equal(response.state.tabCount, 1);

console.log("background runtime smoke test passed");
