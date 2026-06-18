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

const chrome = {
  storage: {
    local: {
      async get() {
        return { codexBrowserTakeoverClientId: "runtime-test-client" };
      },
      async set() {},
    },
  },
  tabs: {
    async query() {
      return [{ id: 1, windowId: 1, active: true, title: "Test", url: "https://example.test", status: "complete" }];
    },
    onCreated: { addListener() {} },
    onUpdated: { addListener() {} },
    onRemoved: { addListener() {} },
    onActivated: { addListener() {} },
  },
  scripting: { async executeScript() { return [{ result: null }]; } },
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

let response;
listeners.message({ type: "bridge-status" }, {}, (value) => { response = value; });
assert.equal(response.ok, true);
assert.equal(response.state.connected, true);
assert.equal(response.state.tabCount, 1);

console.log("background runtime smoke test passed");
