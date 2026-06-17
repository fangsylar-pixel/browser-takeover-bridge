const BRIDGE_URL = "http://127.0.0.1:17321";
const CLIENT_ID_KEY = "codexBrowserTakeoverClientId";

let clientIdPromise = null;

function getClientId() {
  if (clientIdPromise) return clientIdPromise;
  clientIdPromise = chrome.storage?.local
    ? chrome.storage.local.get(CLIENT_ID_KEY).then((stored) => {
        if (stored[CLIENT_ID_KEY]) return stored[CLIENT_ID_KEY];
        const id = `ext-${crypto.randomUUID()}`;
        return chrome.storage.local.set({ [CLIENT_ID_KEY]: id }).then(() => id);
      })
    : Promise.resolve(`ext-${crypto.randomUUID()}`);
  return clientIdPromise;
}

async function post(path, payload) {
  const response = await fetch(`${BRIDGE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

async function get(path) {
  const response = await fetch(`${BRIDGE_URL}${path}`);
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

async function register() {
  const clientId = await getClientId();
  await post("/extension/register", {
    clientId,
    browser: "chromium-extension",
    userAgent: navigator.userAgent,
  });
}

async function syncTabs() {
  const clientId = await getClientId();
  const tabs = await chrome.tabs.query({});
  await post("/extension/tabs", {
    clientId,
    tabs: tabs.map((tab) => ({
      id: tab.id,
      windowId: tab.windowId,
      active: tab.active,
      highlighted: tab.highlighted,
      title: tab.title || "",
      url: tab.url || "",
      status: tab.status || "",
    })),
  });
}

async function evaluateInTab(command) {
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: Number(command.tabId) },
    func: async (expression) => {
      const indirectEval = eval;
      return await indirectEval(expression);
    },
    args: [command.expression],
    world: "MAIN",
  });
  return injection ? injection.result : null;
}

async function inspectTab(command) {
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: Number(command.tabId) },
    func: () => {
      const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
      const inputs = [...document.querySelectorAll('textarea, input, [contenteditable="true"], [role="textbox"]')].map((el, index) => ({
        index,
        tag: el.tagName,
        role: el.getAttribute("role"),
        id: el.id,
        aria: el.getAttribute("aria-label"),
        placeholder: el.getAttribute("placeholder"),
        text: clean(el.innerText || el.value || "").slice(0, 200),
      }));
      const buttons = [...document.querySelectorAll("button")].map((el, index) => ({
        index,
        id: el.id,
        testid: el.getAttribute("data-testid"),
        aria: el.getAttribute("aria-label"),
        text: clean(el.innerText || el.textContent).slice(0, 100),
        disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
      })).slice(-50);
      return {
        title: document.title,
        href: location.href,
        bodyText: clean(document.body?.innerText || "").slice(0, 1000),
        inputs,
        buttons,
      };
    },
    world: "ISOLATED",
  });
  return injection ? injection.result : null;
}

async function sendChatGptPrompt(command) {
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: Number(command.tabId) },
    func: async (prompt, useImageTool) => {
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      if (useImageTool) {
        const imageTool = [...document.querySelectorAll("button")].find((button) =>
          /生成图片|create image|image/i.test(button.innerText || button.getAttribute("aria-label") || "")
        );
        if (imageTool) {
          imageTool.click();
          await sleep(500);
        }
      }
      const editor =
        document.querySelector('#prompt-textarea') ||
        document.querySelector('[contenteditable="true"][role="textbox"]') ||
        document.querySelector('[contenteditable="true"]') ||
        document.querySelector('textarea');
      if (!editor) return { ok: false, error: "Prompt editor not found" };

      editor.focus();
      if (editor.tagName === "TEXTAREA" || editor.tagName === "INPUT") {
        editor.value = prompt;
        editor.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: prompt }));
      } else {
        editor.innerHTML = "";
        const paragraph = document.createElement("p");
        paragraph.textContent = prompt;
        editor.appendChild(paragraph);
        editor.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: prompt }));
      }
      await sleep(250);

      const buttons = [...document.querySelectorAll("button")];
      const sendButton =
        document.querySelector('[data-testid="send-button"]') ||
        document.querySelector('[aria-label*="Send"]') ||
        document.querySelector('[aria-label*="发送"]') ||
        buttons.find((button) => /send|发送/i.test(button.getAttribute("aria-label") || button.innerText || ""));
      if (!sendButton) {
        return { ok: false, error: "Send button not found", editorText: editor.innerText || editor.value || "" };
      }
      if (sendButton.disabled || sendButton.getAttribute("aria-disabled") === "true") {
        return { ok: false, error: "Send button disabled", editorText: editor.innerText || editor.value || "" };
      }
      sendButton.click();
      return { ok: true, title: document.title, href: location.href };
    },
    args: [command.prompt, Boolean(command.useImageTool)],
    world: "ISOLATED",
  });
  return injection ? injection.result : null;
}

async function getImagesFromTab(command) {
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: Number(command.tabId) },
    func: async (minWidth, minHeight) => {
      const images = [...document.images]
        .map((img) => ({
          src: img.currentSrc || img.src,
          alt: img.alt || "",
          naturalWidth: img.naturalWidth || 0,
          naturalHeight: img.naturalHeight || 0,
          width: img.width || 0,
          height: img.height || 0,
        }))
        .filter((img) => img.src && img.naturalWidth >= minWidth && img.naturalHeight >= minHeight);

      const backgrounds = [...document.querySelectorAll("*")]
        .map((el) => {
          const style = getComputedStyle(el);
          const match = /url\\([\"']?([^\"')]+)[\"']?\\)/.exec(style.backgroundImage || "");
          if (!match) return null;
          const rect = el.getBoundingClientRect();
          return {
            src: new URL(match[1], location.href).href,
            alt: "",
            naturalWidth: Math.round(rect.width),
            naturalHeight: Math.round(rect.height),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          };
        })
        .filter(Boolean)
        .filter((img) => img.width >= minWidth && img.height >= minHeight);

      return {
        title: document.title,
        href: location.href,
        images: [...images, ...backgrounds].slice(0, 30),
      };
    },
    args: [Number(command.minWidth || 200), Number(command.minHeight || 120)],
    world: "ISOLATED",
  });
  return injection ? injection.result : null;
}

async function fetchImageDataFromTab(command) {
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: Number(command.tabId) },
    func: async (src) => {
      const response = await fetch(src, { credentials: "include" });
      if (!response.ok) {
        return { ok: false, status: response.status, statusText: response.statusText };
      }
      const blob = await response.blob();
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
      });
      return { ok: true, type: blob.type, size: blob.size, dataUrl };
    },
    args: [command.src],
    world: "ISOLATED",
  });
  return injection ? injection.result : null;
}

async function navigateTab(command) {
  const tab = await chrome.tabs.update(Number(command.tabId), { url: command.url });
  return {
    id: tab.id,
    title: tab.title || "",
    url: tab.url || "",
    status: tab.status || "",
  };
}

async function screenshotTab(command) {
  const tab = await chrome.tabs.get(Number(command.tabId));
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: command.format === "jpeg" ? "jpeg" : "png",
  });
  return { dataUrl };
}

async function runCommand(command) {
  if (!command) return;
  if (command.type === "reload") {
    setTimeout(() => chrome.runtime.reload(), 100);
    return { reloading: true };
  }
  if (command.type === "evaluate") return evaluateInTab(command);
  if (command.type === "inspect") return inspectTab(command);
  if (command.type === "chatgptPrompt") return sendChatGptPrompt(command);
  if (command.type === "getImages") return getImagesFromTab(command);
  if (command.type === "fetchImageData") return fetchImageDataFromTab(command);
  if (command.type === "navigate") return navigateTab(command);
  if (command.type === "screenshot") return screenshotTab(command);
  throw new Error(`Unknown command type: ${command.type}`);
}

async function pollOnce() {
  const clientId = await getClientId();
  const payload = await get(`/extension/poll?clientId=${encodeURIComponent(clientId)}`);
  const command = payload.command;
  if (!command) return;
  try {
    const result = await runCommand(command);
    await post("/extension/result", {
      clientId,
      commandId: command.id,
      ok: true,
      result,
    });
    await syncTabs();
  } catch (error) {
    await post("/extension/result", {
      clientId,
      commandId: command.id,
      ok: false,
      error: error && error.message ? error.message : String(error),
    });
  }
}

async function safe(task) {
  try {
    await task();
  } catch (_error) {
    // The MCP bridge is available only while Codex is running.
  }
}

chrome.runtime.onInstalled.addListener(() => {
  safe(register);
  safe(syncTabs);
});

chrome.runtime.onStartup.addListener(() => {
  safe(register);
  safe(syncTabs);
});

chrome.tabs.onCreated.addListener(() => safe(syncTabs));
chrome.tabs.onUpdated.addListener(() => safe(syncTabs));
chrome.tabs.onRemoved.addListener(() => safe(syncTabs));
chrome.tabs.onActivated.addListener(() => safe(syncTabs));

setInterval(() => safe(register), 5000);
setInterval(() => safe(syncTabs), 2000);
setInterval(() => safe(pollOnce), 500);

safe(register);
safe(syncTabs);
