const BRIDGE_URL = "http://127.0.0.1:17321";
const CLIENT_ID_KEY = "codexBrowserTakeoverClientId";
const ADVANCED_CONTROL_KEY = "browserTakeoverAdvancedControl";
const AUTOMATION_ENABLED_KEY = "browserTakeoverAutomationEnabled";
const SITE_POLICY_KEY = "browserTakeoverSitePolicy";
const TRUSTED_HOSTS_KEY = "browserTakeoverTrustedHosts";
const PROTOCOL_VERSION = 2;
const RECONNECT_ALARM = "browserTakeoverReconnect";

let clientIdPromise = null;
let bridgeToken = "";
let pollIntervalMs = 250;
const trackedDownloadIds = new Set();
let bridgeState = {
  connected: false,
  protocolVersion: PROTOCOL_VERSION,
  tabCount: 0,
  lastConnectedAt: null,
  lastPollAt: null,
  lastCommandAt: null,
  lastErrorAt: null,
  lastError: "",
};

async function publishState() {
  try {
    if (!chrome.action) return;
    const text = bridgeState.connected ? "ON" : "!";
    const color = bridgeState.connected ? "#15803d" : "#b91c1c";
    await chrome.action.setBadgeText?.({ text });
    await chrome.action.setBadgeBackgroundColor?.({ color });
    await chrome.action.setTitle?.({
      title: bridgeState.connected
        ? `Browser Takeover connected · ${bridgeState.tabCount} tabs`
        : `Browser Takeover disconnected${bridgeState.lastError ? ` · ${bridgeState.lastError}` : ""}`,
    });
  } catch (_error) {
    // Status UI must never break bridge operation.
  }
}

function markConnected(extra = {}) {
  bridgeState = {
    ...bridgeState,
    ...extra,
    connected: true,
    lastConnectedAt: Date.now(),
    lastError: "",
  };
  void publishState();
}

function markError(error) {
  bridgeState = {
    ...bridgeState,
    connected: false,
    lastErrorAt: Date.now(),
    lastError: error?.message || String(error || "Unknown bridge error"),
  };
  void publishState();
}

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
  const headers = { "Content-Type": "application/json" };
  if (bridgeToken) headers["X-Browser-Takeover-Token"] = bridgeToken;
  const response = await fetch(`${BRIDGE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

async function get(path) {
  const headers = bridgeToken ? { "X-Browser-Takeover-Token": bridgeToken } : {};
  const response = await fetch(`${BRIDGE_URL}${path}`, { headers });
  if (!response.ok) throw new Error(`${path} failed with HTTP ${response.status}`);
  return response.json();
}

async function register() {
  const clientId = await getClientId();
  const advancedEnabled = await hasDebuggerPermission();
  const registration = await post("/extension/register", {
    clientId,
    browser: "chromium-extension",
    userAgent: navigator.userAgent,
    protocolVersion: PROTOCOL_VERSION,
    capabilities: [
      "tabs",
      "evaluate",
      "inspect",
      "action",
      "navigate",
      "screenshot",
      "site-actions",
      "image-transfer",
      "shadow-dom",
      "all-frames",
      "coordinate-actions",
      "file-upload",
      "browser-downloads",
      "event-stream",
      "verified-actions",
      "paginate",
      ...(advancedEnabled ? ["native-input", "full-page-screenshot", "dialog-control"] : []),
    ],
  });
  bridgeToken = registration.token || bridgeToken;
  pollIntervalMs = Number(registration.pollIntervalMs || pollIntervalMs);
  markConnected({ protocolVersion: Number(registration.protocolVersion || PROTOCOL_VERSION) });
  return registration;
}

async function securitySettings() {
  const stored = await chrome.storage.local.get([
    AUTOMATION_ENABLED_KEY,
    SITE_POLICY_KEY,
    TRUSTED_HOSTS_KEY,
  ]);
  return {
    automationEnabled: stored[AUTOMATION_ENABLED_KEY] !== false,
    sitePolicy: stored[SITE_POLICY_KEY] === "trusted" ? "trusted" : "all",
    trustedHosts: Array.isArray(stored[TRUSTED_HOSTS_KEY]) ? stored[TRUSTED_HOSTS_KEY] : [],
  };
}

function hostFromUrl(url) {
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.hostname : "";
  } catch (_error) {
    return "";
  }
}

async function activeSiteStatus() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const settings = await securitySettings();
  const activeHost = hostFromUrl(tab?.url || "");
  return {
    ...settings,
    activeHost,
    activeTitle: tab?.title || "",
    activeTrusted: Boolean(activeHost && settings.trustedHosts.includes(activeHost)),
    localOnly: true,
  };
}

async function assertCommandAllowed(command) {
  if (!command?.tabId) return;
  const settings = await securitySettings();
  if (!settings.automationEnabled) {
    throw new Error("Automation is paused in the extension");
  }
  if (settings.sitePolicy !== "trusted") return;
  const tab = await chrome.tabs.get(Number(command.tabId));
  const host = hostFromUrl(tab.url || "");
  if (!host || !settings.trustedHosts.includes(host)) {
    throw new Error(`Site is not trusted: ${host || tab.url || "unknown"}`);
  }
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
  markConnected({ tabCount: tabs.length });
}

async function reportEvent(type, tabId, details = {}) {
  const clientId = await getClientId();
  await post("/extension/events", {
    clientId,
    events: [{ type, tabId, details, timestamp: Date.now() / 1000 }],
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

async function paginateTab(command) {
  const config = command.config || {};
  const injection = await chrome.scripting.executeScript({
    target: { tabId: Number(command.tabId) },
    world: "MAIN",
    args: [config],
    func: async (options) => {
      const rowSelector = String(options.rowSelector || "");
      const nextSelector = String(options.nextSelector || "");
      const mode = options.mode === "scroll" ? "scroll" : "pagination";
      if (!rowSelector || (mode === "pagination" && !nextSelector)) throw new Error("rowSelector and nextSelector are required for pagination mode");
      const maxPages = Math.max(1, Math.min(Number(options.maxPages || 50), 200));
      const waitTimeout = Math.max(500, Math.min(Number(options.waitTimeout || 10000), 30000));
      const scrollWaitTimeout = Math.max(250, Math.min(Number(options.scrollWaitTimeout || 2000), 30000));
      const stableRoundsRequired = Math.max(1, Math.min(Number(options.stableRounds || 2), 10));
      const fields = options.fields && typeof options.fields === "object" ? options.fields : null;
      const keyField = String(options.keyField || "");
      const continueOnTimeout = options.continueOnTimeout !== false;
      const rows = [];
      const seen = new Set();
      const pageSignatures = new Set();
      const warnings = [];
      const readValue = (root, descriptor) => {
        if (Array.isArray(descriptor)) {
          for (const candidate of descriptor) {
            const value = readValue(root, candidate);
            if (value !== null && value !== "") return value;
          }
          return null;
        }
        const spec = typeof descriptor === "string" ? { css: descriptor } : (descriptor || {});
        const selectors = Array.isArray(spec.css) ? spec.css : [spec.css];
        let node = root;
        if (spec.css) {
          node = null;
          for (const selector of selectors) {
            node = root.querySelector(selector);
            if (node) break;
          }
        }
        if (!node) return null;
        if (spec.attribute) return node.getAttribute(spec.attribute);
        const text = (node.innerText || node.textContent || "").trim();
        if (spec.textPattern) {
          const match = text.match(new RegExp(spec.textPattern, spec.flags || ""));
          return match ? (match[Number(spec.group ?? 1)] ?? match[0]) : null;
        }
        return text;
      };
      const signature = () => {
        const nodes = Array.from(document.querySelectorAll(rowSelector));
        const samples = [...nodes.slice(0, 2), ...nodes.slice(-3)];
        return `${nodes.length}\n${samples.map((node) => node.innerText || node.textContent || "").join("\n")}`;
      };
      const waitForChange = (before, timeoutMs = waitTimeout) => new Promise((resolve, reject) => {
        const started = Date.now();
        let timer;
        const observer = new MutationObserver(() => {
          if (signature() !== before) { clearInterval(timer); observer.disconnect(); resolve(true); }
          else if (Date.now() - started >= timeoutMs) { clearInterval(timer); observer.disconnect(); reject(new Error("collection DOM did not change")); }
        });
        observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
        timer = setInterval(() => {
          if (signature() !== before) { clearInterval(timer); observer.disconnect(); resolve(true); }
          else if (Date.now() - started >= timeoutMs) { clearInterval(timer); observer.disconnect(); reject(new Error("collection DOM did not change")); }
        }, 100);
      });
      let pages = 0;
      let stopReason = "max-pages";
      let stableRounds = 0;
      for (; pages < maxPages; pages += 1) {
        const pageRows = Array.from(document.querySelectorAll(rowSelector));
        const currentSignature = signature();
        if (mode === "pagination" && pageSignatures.has(currentSignature)) {
          stopReason = "repeated-page";
          warnings.push(`Stopped before page ${pages + 1}: repeated page content`);
          break;
        }
        pageSignatures.add(currentSignature);
        for (const node of pageRows) {
          const value = fields ? Object.fromEntries(Object.entries(fields).map(([name, descriptor]) => [name, readValue(node, descriptor)])) : (node.innerText || node.textContent || "").trim();
          const key = keyField && value && typeof value === "object" ? value[keyField] : JSON.stringify(value);
          if (!seen.has(String(key))) { seen.add(String(key)); rows.push(value); }
        }
        if (mode === "scroll") {
          const scroller = options.scrollContainer ? document.querySelector(options.scrollContainer) : document.scrollingElement;
          if (!scroller) { stopReason = "scroll-container-missing"; break; }
          const before = currentSignature;
          const amount = Number(options.scrollStep || scroller.clientHeight || window.innerHeight || 800);
          if (scroller === document.scrollingElement) window.scrollBy({ top: amount, behavior: "instant" });
          else scroller.scrollBy({ top: amount, behavior: "instant" });
          try {
            await waitForChange(before, scrollWaitTimeout);
            stableRounds = 0;
          } catch (error) {
            stableRounds += 1;
            if (stableRounds >= stableRoundsRequired) {
              stopReason = "scroll-stable";
              break;
            }
          }
          continue;
        }
        const next = document.querySelector(nextSelector);
        const disabled = !next || next.disabled || next.getAttribute("aria-disabled") === "true" || next.classList.contains("disabled");
        if (disabled) { stopReason = next ? "next-disabled" : "next-missing"; break; }
        const before = currentSignature;
        next.scrollIntoView({ block: "center" });
        next.click();
        try {
          await waitForChange(before);
        } catch (error) {
          stopReason = "page-change-timeout";
          warnings.push(String(error?.message || error));
          if (!continueOnTimeout) throw error;
          break;
        }
      }
      const completedPages = pageSignatures.size;
      return {
        ok: true,
        rows,
        count: rows.length,
        pages: completedPages,
        truncated: pages >= maxPages || stopReason === "page-change-timeout",
        mode,
        stopReason,
        warnings,
      };
    },
  });
  return injection?.[0]?.result || { ok: false, rows: [], count: 0, pages: 0 };
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

async function performAction(command) {
  const action = command.action || {};
  const target = { tabId: Number(command.tabId) };
  if (action.frameId !== undefined && action.frameId !== null) target.frameIds = [Number(action.frameId)];
  else if (action.frameScope === "all") target.allFrames = true;
  const injections = await chrome.scripting.executeScript({
    target,
    func: async (request) => {
      const startedAt = performance.now();
      const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
      const deepElements = (root = document) => {
        const elements = [];
        const visit = (node) => {
          for (const child of node.querySelectorAll("*")) {
            elements.push(child);
            if (child.shadowRoot) visit(child.shadowRoot);
          }
        };
        visit(root);
        return elements;
      };
      const queryDeep = (selector, root = document) => {
        if (!selector) return [];
        if (selector.shadowPath?.length) {
          let scopes = [root];
          for (const part of selector.shadowPath) {
            const next = [];
            for (const scope of scopes) {
              for (const match of scope.querySelectorAll(part)) {
                next.push(match.shadowRoot || match);
              }
            }
            scopes = next;
          }
          return scopes.filter((scope) => scope instanceof Element);
        }
        if (selector.css) {
          const direct = [...root.querySelectorAll(selector.css)];
          const shadows = deepElements(root)
            .filter((element) => element.shadowRoot)
            .flatMap((element) => [...element.shadowRoot.querySelectorAll(selector.css)]);
          return [...new Set([...direct, ...shadows])];
        }
        return deepElements(root);
      };
      const visible = (element) => {
        if (!element) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
      };
      const controlSelector = "button, a, input, textarea, select, [role], [contenteditable='true'], [onclick], [tabindex]";
      const looksInteractive = (element) => {
        if (!element || !visible(element)) return false;
        if (element.matches("button, a, input, textarea, select, [role], [contenteditable='true'], [onclick]")) return true;
        const tabIndex = element.getAttribute("tabindex");
        if (tabIndex !== null && Number(tabIndex) >= 0) return true;
        const style = getComputedStyle(element);
        const text = clean(element.getAttribute("aria-label") || element.innerText || element.textContent);
        return style.cursor === "pointer" && text.length > 0 && text.length <= 200;
      };
      const stableSelector = (element) => {
        if (element.id) return `#${CSS.escape(element.id)}`;
        for (const attribute of ["data-testid", "data-id", "name"]) {
          const value = element.getAttribute(attribute);
          if (value) return `${element.tagName.toLowerCase()}[${attribute}="${CSS.escape(value)}"]`;
        }
        const parts = [];
        let node = element;
        while (node && node !== document.body && parts.length < 5) {
          let part = node.tagName.toLowerCase();
          const classes = [...node.classList].filter((name) => /^[a-zA-Z_-][\w-]*$/.test(name)).slice(0, 2);
          if (classes.length) part += classes.map((name) => `.${CSS.escape(name)}`).join("");
          const siblings = node.parentElement ? [...node.parentElement.children].filter((item) => item.tagName === node.tagName) : [];
          if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
          parts.unshift(part);
          node = node.parentElement;
        }
        return parts.join(" > ");
      };
      const candidates = (selector) => {
        if (!selector) return [];
        if (selector.css || selector.shadowPath?.length) return queryDeep(selector);
        if (selector.testId) return queryDeep({ css: `[data-testid="${CSS.escape(selector.testId)}"]` });
        const all = deepElements().filter((element) =>
          element.matches("button, a, input, textarea, select, [role], [contenteditable='true'], label")
        );
        return all.filter((element) => {
          const role = element.getAttribute("role") || (
            element.tagName === "BUTTON" ? "button" :
            element.tagName === "A" ? "link" :
            ["INPUT", "TEXTAREA"].includes(element.tagName) ? "textbox" : ""
          );
          const name = clean(
            element.getAttribute("aria-label") ||
            element.getAttribute("placeholder") ||
            element.innerText ||
            element.value
          );
          if (selector.role && role !== selector.role) return false;
          if (selector.name && !name.toLocaleLowerCase().includes(String(selector.name).toLocaleLowerCase())) return false;
          if (selector.text && !clean(element.innerText || element.textContent).includes(selector.text)) return false;
          if (selector.label) {
            const id = element.id;
            const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : element.closest("label");
            if (!label || !clean(label.innerText).includes(selector.label)) return false;
          }
          return true;
        });
      };
      const resolveMatches = () => candidates(request.target).filter((element) => request.options?.includeHidden || visible(element));
      let matches = resolveMatches();
      const index = Number(request.target?.index || 0);
      let element = matches[index];
      if (request.type === "clickAt") {
        const x = Number(request.x);
        const y = Number(request.y);
        const hit = document.elementFromPoint(x, y);
        if (!hit) return { ok: false, error: "no element at coordinates", x, y };
        const init = { bubbles: true, cancelable: true, clientX: x, clientY: y, view: window };
        hit.dispatchEvent(new PointerEvent("pointerdown", init));
        hit.dispatchEvent(new MouseEvent("mousedown", init));
        hit.dispatchEvent(new PointerEvent("pointerup", init));
        hit.dispatchEvent(new MouseEvent("mouseup", init));
        hit.click();
        return {
          ok: true,
          type: request.type,
          method: "coordinates",
          target: clean(hit.getAttribute("aria-label") || hit.innerText || hit.tagName).slice(0, 200),
          x,
          y,
          title: document.title,
          href: location.href,
          durationMs: Math.round(performance.now() - startedAt),
        };
      }
      if (request.type === "keypressPage") {
        const key = String(request.key || "Enter");
        const targetElement = document.activeElement || document.body;
        targetElement.dispatchEvent(new KeyboardEvent("keydown", {
          bubbles: true,
          key,
          code: request.code || key,
          ctrlKey: Boolean(request.ctrlKey),
          shiftKey: Boolean(request.shiftKey),
          altKey: Boolean(request.altKey),
          metaKey: Boolean(request.metaKey),
        }));
        targetElement.dispatchEvent(new KeyboardEvent("keyup", {
          bubbles: true,
          key,
          code: request.code || key,
        }));
        return { ok: true, type: request.type, method: "page-keyboard", key, title: document.title, href: location.href };
      }
      if (request.type === "wait") {
        const timeout = Math.max(0, Number(request.timeout || 10000));
        const state = request.state || "visible";
        const deadline = performance.now() + timeout;
        while (performance.now() <= deadline) {
          matches = resolveMatches();
          element = matches[index];
          const satisfied =
            state === "hidden" ? !element :
            state === "attached" ? Boolean(element) :
            Boolean(element && visible(element));
          if (satisfied) {
            return {
              ok: true,
              type: request.type,
              state,
              matchCount: matches.length,
              durationMs: Math.round(performance.now() - startedAt),
              title: document.title,
              href: location.href,
            };
          }
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
        return { ok: false, error: `wait timed out for state: ${state}`, matchCount: matches.length };
      }
      if (!element && request.type !== "snapshot" && !(request.type === "scroll" && !request.target)) {
        return { ok: false, error: "target not found", matchCount: matches.length };
      }
      const emitInput = (target, value) => {
        const prototype = target.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
        if (descriptor?.set) descriptor.set.call(target, value);
        else target.value = value;
        target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        target.dispatchEvent(new Event("change", { bubbles: true }));
      };
      let value = null;
      if (request.type === "click") {
        element.scrollIntoView({ block: "center", inline: "center" });
        element.click();
      } else if (request.type === "doubleClick") {
        element.scrollIntoView({ block: "center", inline: "center" });
        element.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, cancelable: true, view: window }));
      } else if (request.type === "hover") {
        element.scrollIntoView({ block: "center", inline: "center" });
        element.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
        element.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      } else if (request.type === "fill") {
        element.focus();
        if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
          emitInput(element, String(request.value ?? ""));
        } else {
          element.textContent = String(request.value ?? "");
          element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: request.value }));
        }
      } else if (request.type === "upload") {
        if (!(element instanceof HTMLInputElement) || element.type !== "file") {
          return { ok: false, error: "target is not a file input" };
        }
        const response = await fetch(request.dataUrl);
        const blob = await response.blob();
        const file = new File([blob], request.fileName || "upload.bin", {
          type: request.mimeType || blob.type || "application/octet-stream",
        });
        const transfer = new DataTransfer();
        transfer.items.add(file);
        element.files = transfer.files;
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
        value = { fileName: file.name, size: file.size, type: file.type };
      } else if (request.type === "press") {
        element.focus();
        const key = String(request.key || "Enter");
        element.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key, code: key }));
        element.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key, code: key }));
      } else if (request.type === "read") {
        value = request.attribute
          ? element.getAttribute(request.attribute)
          : clean(element.innerText || element.value || element.textContent);
      } else if (request.type === "check") {
        if (!("checked" in element)) return { ok: false, error: "target is not checkable" };
        element.checked = request.checked !== false;
        element.dispatchEvent(new Event("change", { bubbles: true }));
        value = element.checked;
      } else if (request.type === "select") {
        if (!(element instanceof HTMLSelectElement)) return { ok: false, error: "target is not a select" };
        element.value = String(request.value ?? "");
        element.dispatchEvent(new Event("change", { bubbles: true }));
        value = element.value;
      } else if (request.type === "scroll") {
        (element || window).scrollBy({
          left: Number(request.x || 0),
          top: Number(request.y || 0),
          behavior: request.behavior === "smooth" ? "smooth" : "instant",
        });
      } else if (request.type === "snapshot") {
        const explicit = [...document.querySelectorAll(controlSelector)];
        const pointerCandidates = deepElements().filter((item) => {
          if (!["DIV", "SPAN", "LI"].includes(item.tagName)) return false;
          return getComputedStyle(item).cursor === "pointer";
        });
        value = {
          title: document.title,
          href: location.href,
          text: clean(document.body?.innerText || "").slice(0, Number(request.maxText || 20000)),
          controls: explicit.concat(pointerCandidates)
            .concat(deepElements().filter((item) => item.shadowRoot).flatMap((item) =>
              [...item.shadowRoot.querySelectorAll(controlSelector)]
            ))
            .filter((item, index, all) => all.indexOf(item) === index && looksInteractive(item))
            .slice(0, Number(request.maxControls || 500))
            .map((item, itemIndex) => ({
              index: itemIndex,
              tag: item.tagName.toLowerCase(),
              role: item.getAttribute("role"),
              name: clean(item.getAttribute("aria-label") || item.getAttribute("placeholder") || item.innerText || item.value).slice(0, 200),
              selector: stableSelector(item),
              href: item.href || null,
              interactiveBy: item.matches("button, a, input, textarea, select") ? "native" : item.getAttribute("role") ? "role" : item.onclick || item.hasAttribute("onclick") ? "handler" : item.hasAttribute("tabindex") ? "tabindex" : "pointer",
              disabled: Boolean(item.disabled || item.getAttribute("aria-disabled") === "true"),
            })),
        };
      } else {
        return { ok: false, error: `unsupported action: ${request.type}` };
      }
      return {
        ok: true,
        type: request.type,
        method: request.target?.css ? "css" : request.target ? "semantic" : "page",
        matchCount: matches.length,
        value,
        title: document.title,
        href: location.href,
        durationMs: Math.round(performance.now() - startedAt),
      };
    },
    args: [action],
    world: action.world === "MAIN" ? "MAIN" : "ISOLATED",
  });
  const frameResults = injections.map((injection) => ({
    frameId: injection.frameId,
    documentId: injection.documentId,
    result: injection.result,
  }));
  const preferred = frameResults.find((item) => item.result?.ok && (item.result.matchCount || 0) > 0)
    || frameResults.find((item) => item.result?.ok)
    || frameResults[0];
  const result = preferred?.result || null;
  if (action.frameScope === "all") {
    if (!result?.ok || !action.expect) {
      return { ...result, frameId: preferred?.frameId, frameResults };
    }
  }
  if (!result?.ok || !action.expect) return result;
  const verification = await verifyAction(Number(command.tabId), action.expect);
  return {
    ...result,
    ok: verification.ok,
    verified: verification.ok,
    verification,
    error: verification.ok ? undefined : verification.error,
  };
}

async function downloadUrl(command) {
  if (!chrome.downloads?.download) throw new Error("downloads API is unavailable");
  const downloadId = await chrome.downloads.download({
    url: command.url,
    filename: command.filename || undefined,
    saveAs: Boolean(command.saveAs),
    conflictAction: command.conflictAction || "uniquify",
  });
  trackedDownloadIds.add(downloadId);
  await safe(() => reportEvent("download.created", null, {
    downloadId,
    url: command.url,
    filename: command.filename || "",
    state: "in_progress",
  }));
  return { ok: true, downloadId };
}

async function downloadStatus(command) {
  if (!chrome.downloads?.search) throw new Error("downloads API is unavailable");
  const matches = await chrome.downloads.search({ id: Number(command.downloadId) });
  const item = matches[0];
  if (!item) return { ok: false, error: "download not found" };
  return {
    ok: true,
    download: {
      id: item.id,
      filename: item.filename,
      url: item.url,
      state: item.state,
      paused: item.paused,
      bytesReceived: item.bytesReceived,
      totalBytes: item.totalBytes,
      error: item.error,
      endTime: item.endTime,
    },
  };
}

async function verifyAction(tabId, expectation) {
  const timeout = Math.max(0, Number(expectation.timeout || 10000));
  const deadline = Date.now() + timeout;
  let lastEvidence = null;
  while (Date.now() <= deadline) {
    try {
      const [injection] = await chrome.scripting.executeScript({
        target: { tabId },
        func: (expected) => {
          const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
          const element = expected.css ? document.querySelector(expected.css) : null;
          const style = element ? getComputedStyle(element) : null;
          const rect = element?.getBoundingClientRect();
          const elementVisible = Boolean(
            element &&
            style?.visibility !== "hidden" &&
            style?.display !== "none" &&
            rect?.width > 0 &&
            rect?.height > 0
          );
          const bodyText = clean(document.body?.innerText || "");
          const checks = {
            url: !expected.urlIncludes || location.href.includes(expected.urlIncludes),
            text: !expected.textIncludes || bodyText.includes(expected.textIncludes),
            visible: !expected.cssVisible || Boolean(document.querySelector(expected.cssVisible)),
            hidden: !expected.cssHidden || !document.querySelector(expected.cssHidden),
            value: expected.value === undefined || String(element?.value ?? element?.textContent ?? "") === String(expected.value),
            elementVisible: expected.visible === undefined || elementVisible === Boolean(expected.visible),
          };
          return {
            ok: Object.values(checks).every(Boolean),
            checks,
            href: location.href,
            title: document.title,
            matchedText: expected.textIncludes ? bodyText.includes(expected.textIncludes) : undefined,
          };
        },
        args: [expectation],
        world: "ISOLATED",
      });
      lastEvidence = injection?.result || null;
      if (lastEvidence?.ok) return { ...lastEvidence, durationMs: timeout - Math.max(0, deadline - Date.now()) };
    } catch (error) {
      lastEvidence = { ok: false, error: error?.message || String(error) };
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  return {
    ok: false,
    error: "action verification timed out",
    evidence: lastEvidence,
    durationMs: timeout,
  };
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
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(editor);
        selection.removeAllRanges();
        selection.addRange(range);
        document.execCommand("delete");
        document.execCommand("insertText", false, prompt);
        if (!(editor.innerText || "").trim()) {
          editor.innerHTML = "";
          const paragraph = document.createElement("p");
          paragraph.textContent = prompt;
          editor.appendChild(paragraph);
        }
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

async function sendPromptToTab(command) {
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: Number(command.tabId) },
    func: async (prompt, editorSelector) => {
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const editor =
        (editorSelector ? document.querySelector(editorSelector) : null) ||
        document.querySelector('[contenteditable="true"][role="textbox"]') ||
        document.querySelector('[role="textbox"]') ||
        document.querySelector('[contenteditable="true"]') ||
        document.querySelector("textarea");
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
      await sleep(500);

      const buttons = [...document.querySelectorAll("button")];
      const sendButton = buttons.find((button) => {
        const label = `${button.getAttribute("aria-label") || ""} ${button.innerText || ""}`.trim();
        return /send|submit|发送|提交|运行/i.test(label) && !button.disabled && button.getAttribute("aria-disabled") !== "true";
      });
      if (sendButton) {
        sendButton.click();
        return { ok: true, method: "button", title: document.title, href: location.href };
      }

      editor.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter", code: "Enter", ctrlKey: true }));
      await sleep(100);
      return { ok: true, method: "ctrl-enter-fallback", title: document.title, href: location.href };
    },
    args: [command.prompt, command.editorSelector || ""],
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

async function pasteImageDataIntoTab(command) {
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: Number(command.tabId) },
    func: async (dataUrl, fileName, mimeType, markerText) => {
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const response = await fetch(dataUrl);
      const blob = await response.blob();
      const file = new File([blob], fileName || "image.png", { type: mimeType || blob.type || "image/png" });
      const editor = document.querySelector(".ProseMirror") || document.querySelector('[contenteditable="true"]');
      if (!editor) return { ok: false, error: "Editor not found" };

      editor.focus();
      if (markerText) {
        const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
        let node = null;
        while ((node = walker.nextNode())) {
          const index = node.nodeValue.indexOf(markerText);
          if (index !== -1) {
            const range = document.createRange();
            range.setStart(node, index);
            range.setEnd(node, index + markerText.length);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            break;
          }
        }
      }

      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(file);
      const pasteEvent = new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: dataTransfer,
      });
      editor.dispatchEvent(pasteEvent);
      await sleep(2500);
      return {
        ok: true,
        imageCount: editor.querySelectorAll("img").length,
        text: (editor.innerText || "").slice(0, 1000),
        htmlTail: (editor.innerHTML || "").slice(-2000),
      };
    },
    args: [command.dataUrl, command.fileName || "image.png", command.mimeType || "image/png", command.markerText || ""],
    world: "ISOLATED",
  });
  return injection ? injection.result : null;
}

async function navigateTab(command) {
  const tabId = Number(command.tabId);
  const options = command.options || {};
  const timeout = Math.max(1000, Math.min(Number(options.waitTimeout || 30000), 120000));
  const settleMs = Math.max(0, Math.min(Number(options.settleMs ?? 500), 10000));
  if (options.urlPattern) new RegExp(options.urlPattern);
  const started = Date.now();
  await chrome.tabs.update(tabId, { url: command.url });
  let tab;
  let evidence = null;
  let lastError = null;
  const hasBusinessEvidence = Boolean(options.selector || options.text || options.urlPattern);
  while (Date.now() - started < timeout) {
    tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") {
      if (!hasBusinessEvidence) {
        evidence = {
          selectorMatched: true,
          textMatched: true,
          urlMatched: true,
          href: tab.url || "",
          title: tab.title || "",
          readyState: "complete",
          source: "browser-tab",
        };
        break;
      }
      try {
        const [injection] = await chrome.scripting.executeScript({
          target: { tabId },
          world: "ISOLATED",
          args: [options],
          func: (expect) => {
            const bodyText = (document.body?.innerText || "").replace(/\s+/g, " ").trim();
            const selectorMatched = !expect.selector || Boolean(document.querySelector(expect.selector));
            const textMatched = !expect.text || bodyText.includes(String(expect.text));
            const urlMatched = !expect.urlPattern || new RegExp(expect.urlPattern).test(location.href);
            return { selectorMatched, textMatched, urlMatched, href: location.href, title: document.title, readyState: document.readyState };
          },
        });
        evidence = injection?.result || null;
        if (evidence?.selectorMatched && evidence?.textMatched && evidence?.urlMatched) break;
      } catch (error) {
        lastError = String(error?.message || error);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  tab = await chrome.tabs.get(tabId);
  const ready = Boolean(tab.status === "complete" && evidence?.selectorMatched && evidence?.textMatched && evidence?.urlMatched);
  if (ready && settleMs) await new Promise((resolve) => setTimeout(resolve, settleMs));
  return {
    id: tab.id,
    title: tab.title || "",
    url: tab.url || "",
    status: tab.status || "",
    ok: ready,
    timedOut: !ready,
    redirected: Boolean(tab.url && tab.url !== command.url),
    expectedUrl: command.url,
    durationMs: Date.now() - started,
    evidence,
    error: ready ? null : (lastError || "Navigation readiness conditions were not met before timeout"),
  };
}

async function screenshotTab(command) {
  const tab = await chrome.tabs.get(Number(command.tabId));
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  let clip = command.clip || null;
  if (!clip && command.selector) {
    const [injection] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (selector) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        return {
          x: Math.max(0, rect.x),
          y: Math.max(0, rect.y),
          width: Math.max(1, rect.width),
          height: Math.max(1, rect.height),
          devicePixelRatio: window.devicePixelRatio || 1,
        };
      },
      args: [command.selector],
      world: "ISOLATED",
    });
    clip = injection?.result || null;
    if (!clip) throw new Error("screenshot selector was not found");
  }
  let dataUrl;
  try {
    dataUrl = await withTimeout(
      chrome.tabs.captureVisibleTab(tab.windowId, {
        format: command.format === "jpeg" ? "jpeg" : "png",
      }),
      Number(command.captureTimeout || 5000),
      "captureVisibleTab",
    );
  } catch (error) {
    if (!await hasDebuggerPermission()) throw error;
    dataUrl = await withDebugger(tab.id, async (target) => {
      await debuggerSend(target, "Page.enable");
      const capture = await debuggerSend(target, "Page.captureScreenshot", {
        format: command.format === "jpeg" ? "jpeg" : "png",
        quality: command.format === "jpeg" ? Number(command.quality || 90) : undefined,
        fromSurface: true,
        captureBeyondViewport: false,
      });
      return `data:image/${command.format === "jpeg" ? "jpeg" : "png"};base64,${capture.data}`;
    });
  }
  if (clip) dataUrl = await cropDataUrl(dataUrl, clip, command.format);
  return { dataUrl, clip };
}

async function cropDataUrl(dataUrl, clip, format) {
  const response = await fetch(dataUrl);
  const bitmap = await createImageBitmap(await response.blob());
  const ratio = Number(clip.devicePixelRatio || 1);
  const sourceX = Math.max(0, Math.round(Number(clip.x || 0) * ratio));
  const sourceY = Math.max(0, Math.round(Number(clip.y || 0) * ratio));
  const sourceWidth = Math.min(bitmap.width - sourceX, Math.max(1, Math.round(Number(clip.width) * ratio)));
  const sourceHeight = Math.min(bitmap.height - sourceY, Math.max(1, Math.round(Number(clip.height) * ratio)));
  const canvas = new OffscreenCanvas(sourceWidth, sourceHeight);
  const context = canvas.getContext("2d");
  context.drawImage(bitmap, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, sourceWidth, sourceHeight);
  const mimeType = format === "jpeg" ? "image/jpeg" : "image/png";
  const blob = await canvas.convertToBlob({ type: mimeType, quality: 0.92 });
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

async function hasDebuggerPermission() {
  if (!chrome.debugger) return false;
  const stored = await chrome.storage.local.get(ADVANCED_CONTROL_KEY);
  return stored[ADVANCED_CONTROL_KEY] === true;
}

function withTimeout(promise, timeoutMs, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs)),
  ]);
}

function commandTimeout(command) {
  const requested = Number(command?.commandTimeout || command?.action?.commandTimeout || 0);
  if (Number.isFinite(requested) && requested > 0) return Math.max(1000, requested);
  if (command?.type === "action" && command.action?.type === "wait") {
    return Math.max(15000, Number(command.action.timeout || 10000) + 3000);
  }
  return 15000;
}

function debuggerAttach(target, version = "1.3", timeoutMs = 5000) {
  return withTimeout(new Promise((resolve, reject) => {
    chrome.debugger.attach(target, version, () => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(error.message));
      else resolve();
    });
  }), timeoutMs, "debugger attach");
}

function debuggerDetach(target, timeoutMs = 3000) {
  return withTimeout(new Promise((resolve) => {
    chrome.debugger.detach(target, () => resolve());
  }), timeoutMs, "debugger detach").catch(() => {});
}

function debuggerSend(target, method, params = {}, timeoutMs = 15000) {
  return withTimeout(new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(target, method, params, (result) => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(error.message));
      else resolve(result);
    });
  }), timeoutMs, method);
}

async function withDebugger(tabId, task) {
  if (!await hasDebuggerPermission()) {
    throw new Error("Advanced control permission is not enabled");
  }
  const target = { tabId: Number(tabId) };
  await debuggerAttach(target);
  try {
    return await task(target);
  } finally {
    await debuggerDetach(target);
  }
}

async function fullPageScreenshot(command) {
  return withDebugger(command.tabId, async (target) => {
    await debuggerSend(target, "Page.enable");
    const metrics = await debuggerSend(target, "Page.getLayoutMetrics");
    const size = metrics.cssContentSize || metrics.contentSize;
    const capture = await debuggerSend(target, "Page.captureScreenshot", {
      format: command.format === "jpeg" ? "jpeg" : "png",
      quality: command.format === "jpeg" ? Number(command.quality || 90) : undefined,
      fromSurface: true,
      captureBeyondViewport: true,
      clip: {
        x: 0,
        y: 0,
        width: Math.max(1, size.width),
        height: Math.max(1, size.height),
        scale: Number(command.scale || 1),
      },
    });
    return {
      ok: true,
      dataUrl: `data:image/${command.format === "jpeg" ? "jpeg" : "png"};base64,${capture.data}`,
      width: size.width,
      height: size.height,
      method: "debugger",
    };
  });
}

function modifierMask(action) {
  return (action.altKey ? 1 : 0) |
    (action.ctrlKey ? 2 : 0) |
    (action.metaKey ? 4 : 0) |
    (action.shiftKey ? 8 : 0);
}

async function nativeInput(command) {
  const action = command.action || {};
  return withDebugger(command.tabId, async (target) => {
    const sendInput = (method, params) => debuggerSend(target, method, params, Number(action.commandTimeout || 3000));
    const modifiers = modifierMask(action);
    if (action.type === "nativeClick") {
      const x = Number(action.x);
      const y = Number(action.y);
      const button = action.button || "left";
      await sendInput("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, modifiers });
      await sendInput("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button, clickCount: Number(action.clickCount || 1), modifiers });
      await sendInput("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button, clickCount: Number(action.clickCount || 1), modifiers });
    } else if (action.type === "nativeWheel") {
      await sendInput("Input.dispatchMouseEvent", {
        type: "mouseWheel",
        x: Number(action.x || 0),
        y: Number(action.y || 0),
        deltaX: Number(action.deltaX || 0),
        deltaY: Number(action.deltaY || 0),
        modifiers,
      });
    } else if (action.type === "nativeDrag") {
      const points = action.points || [];
      if (points.length < 2) throw new Error("nativeDrag requires at least two points");
      const first = points[0];
      await sendInput("Input.dispatchMouseEvent", { type: "mouseMoved", x: Number(first.x), y: Number(first.y), modifiers });
      await sendInput("Input.dispatchMouseEvent", { type: "mousePressed", x: Number(first.x), y: Number(first.y), button: action.button || "left", clickCount: 1, modifiers });
      for (const point of points.slice(1)) {
        await sendInput("Input.dispatchMouseEvent", {
          type: "mouseMoved",
          x: Number(point.x),
          y: Number(point.y),
          button: action.button || "left",
          buttons: 1,
          modifiers,
        });
      }
      const last = points[points.length - 1];
      await sendInput("Input.dispatchMouseEvent", { type: "mouseReleased", x: Number(last.x), y: Number(last.y), button: action.button || "left", clickCount: 1, modifiers });
    } else if (action.type === "nativeText") {
      await sendInput("Input.insertText", { text: String(action.text || "") });
    } else if (action.type === "nativeKey") {
      const key = String(action.key || "Enter");
      const code = String(action.code || key);
      await sendInput("Input.dispatchKeyEvent", { type: "rawKeyDown", key, code, modifiers });
      await sendInput("Input.dispatchKeyEvent", { type: "keyUp", key, code, modifiers });
    } else {
      throw new Error(`Unsupported native input action: ${action.type}`);
    }
    return { ok: true, type: action.type, method: "debugger" };
  });
}

async function handleJavaScriptDialog(command) {
  return withDebugger(command.tabId, async (target) => {
    const waitTimeout = Math.max(0, Math.min(Number(command.waitTimeout ?? 2000), 10000));
    let dialog = null;
    let resolveDialog;
    const observed = new Promise((resolve) => { resolveDialog = resolve; });
    const listener = (source, method, params) => {
      if (source.tabId === Number(command.tabId) && method === "Page.javascriptDialogOpening") {
        dialog = params || {};
        resolveDialog(dialog);
      }
    };
    chrome.debugger.onEvent.addListener(listener);
    try {
      await debuggerSend(target, "Page.enable", {}, 5000);
      if (!dialog && waitTimeout > 0) {
        await Promise.race([
          observed,
          new Promise((resolve) => setTimeout(resolve, waitTimeout)),
        ]);
      }
      let lastError = null;
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        try {
          await debuggerSend(target, "Page.handleJavaScriptDialog", {
            accept: command.accept !== false,
            promptText: command.promptText || "",
          }, 5000);
          return {
            ok: true,
            accepted: command.accept !== false,
            attempt,
            dialog: dialog ? { type: dialog.type, message: dialog.message, hasBrowserHandler: dialog.hasBrowserHandler } : null,
          };
        } catch (error) {
          lastError = String(error?.message || error);
          if (!/no dialog|not showing|no javascript dialog/i.test(lastError) || attempt === 3) break;
          await new Promise((resolve) => setTimeout(resolve, 150));
        }
      }
      return {
        ok: false,
        code: dialog ? "DIALOG_HANDLE_FAILED" : "DIALOG_NOT_FOUND",
        error: dialog ? `JavaScript dialog could not be handled: ${lastError}` : "No JavaScript dialog was detected before the wait timeout",
        waitTimeout,
      };
    } finally {
      chrome.debugger.onEvent.removeListener(listener);
    }
  });
}

async function setAdvancedControl(command) {
  const enabled = Boolean(command.enabled);
  await chrome.storage.local.set({ [ADVANCED_CONTROL_KEY]: enabled });
  await register();
  return { ok: true, enabled };
}

async function securityControl(command) {
  const updates = {};
  if (command.automationEnabled !== undefined) {
    updates[AUTOMATION_ENABLED_KEY] = Boolean(command.automationEnabled);
  }
  if (command.sitePolicy !== undefined) {
    updates[SITE_POLICY_KEY] = command.sitePolicy === "trusted" ? "trusted" : "all";
  }
  if (Array.isArray(command.trustedHosts)) {
    updates[TRUSTED_HOSTS_KEY] = [...new Set(command.trustedHosts.map((host) => String(host).trim()).filter(Boolean))].sort();
  }
  if (Object.keys(updates).length) await chrome.storage.local.set(updates);
  return { ok: true, ...(await activeSiteStatus()), advancedEnabled: await hasDebuggerPermission() };
}

async function prepareSystemInput(command) {
  const tab = await chrome.tabs.get(Number(command.tabId));
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      const horizontalBorder = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
      const verticalChrome = Math.max(0, window.outerHeight - window.innerHeight - horizontalBorder);
      return {
        contentScreenX: window.screenX + horizontalBorder,
        contentScreenY: window.screenY + verticalChrome,
        devicePixelRatio: window.devicePixelRatio || 1,
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        title: document.title,
        href: location.href,
      };
    },
    world: "ISOLATED",
  });
  return { ok: true, ...(injection?.result || {}) };
}

async function runCommand(command) {
  if (!command) return;
  if (command.type === "reload") {
    setTimeout(() => chrome.runtime.reload(), 100);
    return { reloading: true };
  }
  await assertCommandAllowed(command);
  if (command.type === "evaluate") return evaluateInTab(command);
  if (command.type === "paginate") return paginateTab(command);
  if (command.type === "inspect") return inspectTab(command);
  if (command.type === "action") return performAction(command);
  if (command.type === "chatgptPrompt") return sendChatGptPrompt(command);
  if (command.type === "sendPrompt") return sendPromptToTab(command);
  if (command.type === "getImages") return getImagesFromTab(command);
  if (command.type === "fetchImageData") return fetchImageDataFromTab(command);
  if (command.type === "pasteImageData") return pasteImageDataIntoTab(command);
  if (command.type === "navigate") return navigateTab(command);
  if (command.type === "screenshot") return screenshotTab(command);
  if (command.type === "downloadUrl") return downloadUrl(command);
  if (command.type === "downloadStatus") return downloadStatus(command);
  if (command.type === "fullPageScreenshot") return fullPageScreenshot(command);
  if (command.type === "nativeInput") return nativeInput(command);
  if (command.type === "handleDialog") return handleJavaScriptDialog(command);
  if (command.type === "advancedControl") return setAdvancedControl(command);
  if (command.type === "securityControl") return securityControl(command);
  if (command.type === "prepareSystemInput") return prepareSystemInput(command);
  throw new Error(`Unknown command type: ${command.type}`);
}

async function pollOnce() {
  const clientId = await getClientId();
  const payload = await get(`/extension/poll?clientId=${encodeURIComponent(clientId)}`);
  markConnected({ lastPollAt: Date.now() });
  const command = payload.command;
  if (!command) return;
  bridgeState = { ...bridgeState, lastCommandAt: Date.now() };
  try {
    const timeoutMs = commandTimeout(command);
    const result = await withTimeout(runCommand(command), timeoutMs, `command ${command.id || command.type}`);
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
    return true;
  } catch (error) {
    markError(error);
    return false;
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

chrome.tabs.onCreated.addListener((tab) => {
  safe(syncTabs);
  safe(() => reportEvent("tab.created", tab.id, { title: tab.title || "", url: tab.url || "" }));
});
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  safe(syncTabs);
  safe(() => reportEvent("tab.updated", tabId, {
    status: changeInfo.status,
    title: changeInfo.title || tab.title || "",
    url: changeInfo.url || tab.url || "",
  }));
});
chrome.tabs.onRemoved.addListener((tabId, removeInfo) => {
  safe(syncTabs);
  safe(() => reportEvent("tab.removed", tabId, { windowId: removeInfo.windowId, isWindowClosing: removeInfo.isWindowClosing }));
});
chrome.tabs.onActivated.addListener((activeInfo) => {
  safe(syncTabs);
  safe(() => reportEvent("tab.activated", activeInfo.tabId, { windowId: activeInfo.windowId }));
});

if (chrome.downloads?.onChanged) {
  chrome.downloads.onChanged.addListener((delta) => {
    if (!trackedDownloadIds.has(delta.id)) return;
    safe(() => reportEvent("download.changed", null, {
      downloadId: delta.id,
      state: delta.state?.current,
      filename: delta.filename?.current,
      error: delta.error?.current,
      paused: delta.paused?.current,
    }));
    if (delta.state?.current === "complete" || delta.state?.current === "interrupted") {
      trackedDownloadIds.delete(delta.id);
    }
  });
}

setInterval(() => safe(register), 5000);
setInterval(() => safe(syncTabs), 2000);

async function pollLoop() {
  await safe(pollOnce);
  setTimeout(pollLoop, pollIntervalMs);
}

async function reconnect() {
  await safe(register);
  await safe(syncTabs);
  await safe(pollOnce);
}

if (chrome.alarms?.onAlarm && chrome.alarms?.create) {
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === RECONNECT_ALARM) safe(reconnect);
  });

  chrome.alarms.create(RECONNECT_ALARM, {
    delayInMinutes: 0.1,
    periodInMinutes: 0.5,
  });
}

chrome.runtime.onMessage?.addListener((message, _sender, sendResponse) => {
  if (message?.type === "bridge-status") {
    sendResponse({ ok: true, state: bridgeState });
    return false;
  }
  if (message?.type === "bridge-reconnect") {
    reconnect().then(() => sendResponse({ ok: true, state: bridgeState }));
    return true;
  }
  if (message?.type === "extension-reload") {
    sendResponse({ ok: true, reloading: true });
    setTimeout(() => chrome.runtime.reload(), 100);
    return false;
  }
  if (message?.type === "advanced-control") {
    chrome.storage.local.set({ [ADVANCED_CONTROL_KEY]: Boolean(message.enabled) }).then(async () => {
      await register();
      sendResponse({ ok: true, enabled: Boolean(message.enabled), state: bridgeState });
    });
    return true;
  }
  if (message?.type === "advanced-control-status") {
    hasDebuggerPermission().then((enabled) => sendResponse({ ok: true, enabled }));
    return true;
  }
  if (message?.type === "security-status") {
    Promise.all([activeSiteStatus(), hasDebuggerPermission()]).then(([security, advancedEnabled]) => {
      sendResponse({ ok: true, ...security, advancedEnabled });
    });
    return true;
  }
  if (message?.type === "automation-enabled") {
    chrome.storage.local.set({ [AUTOMATION_ENABLED_KEY]: Boolean(message.enabled) }).then(async () => {
      sendResponse({ ok: true, ...(await activeSiteStatus()) });
    });
    return true;
  }
  if (message?.type === "site-policy") {
    const sitePolicy = message.policy === "trusted" ? "trusted" : "all";
    chrome.storage.local.set({ [SITE_POLICY_KEY]: sitePolicy }).then(async () => {
      sendResponse({ ok: true, ...(await activeSiteStatus()) });
    });
    return true;
  }
  if (message?.type === "trust-current-site") {
    activeSiteStatus().then(async (status) => {
      if (!status.activeHost) {
        sendResponse({ ok: false, error: "Current page is not an HTTP(S) website" });
        return;
      }
      const hosts = new Set(status.trustedHosts);
      if (message.trusted === false) hosts.delete(status.activeHost);
      else hosts.add(status.activeHost);
      await chrome.storage.local.set({ [TRUSTED_HOSTS_KEY]: [...hosts].sort() });
      sendResponse({ ok: true, ...(await activeSiteStatus()) });
    });
    return true;
  }
  return false;
});

safe(register);
safe(syncTabs);
pollLoop();
void publishState();
