const $ = (selector) => document.querySelector(selector);
const elements = {
  status: $("#status"),
  statusLabel: $("#statusLabel"),
  protocol: $("#protocol"),
  tabs: $("#tabs"),
  poll: $("#poll"),
  error: $("#error"),
  indicator: $("#indicator"),
  automation: $("#automation"),
  sitePolicy: $("#sitePolicy"),
  policyHint: $("#policyHint"),
  activeHost: $("#activeHost"),
  trustSite: $("#trustSite"),
  advanced: $("#advanced"),
  advancedState: $("#advancedState"),
  toast: $("#toast"),
};

let latestBridge = {};
let latestSecurity = {};
$("#version").textContent = `v${chrome.runtime.getManifest().version}`;

const request = (type, extra = {}) => chrome.runtime.sendMessage({ type, ...extra });
const formatTime = (value) => value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "尚未";

function toast(message) {
  elements.toast.textContent = message;
  setTimeout(() => {
    if (elements.toast.textContent === message) elements.toast.textContent = "";
  }, 2200);
}

function renderBridge(state) {
  latestBridge = state;
  const paused = latestSecurity.automationEnabled === false;
  elements.status.textContent = paused ? "自动化已暂停" : state.connected ? "本地桥接运行正常" : "等待本地桥接服务";
  elements.statusLabel.textContent = paused ? "PAUSED" : state.connected ? "HEALTHY" : "OFFLINE";
  elements.protocol.textContent = `V${state.protocolVersion || "—"}`;
  elements.tabs.textContent = String(state.tabCount ?? "—");
  elements.poll.textContent = formatTime(state.lastPollAt);
  elements.indicator.classList.toggle("connected", Boolean(state.connected && !paused));
  elements.indicator.classList.toggle("paused", paused);
  elements.error.hidden = !state.lastError;
  elements.error.textContent = state.lastError || "";
}

function renderSecurity(state) {
  latestSecurity = state;
  elements.automation.setAttribute("aria-checked", String(state.automationEnabled !== false));
  elements.sitePolicy.value = state.sitePolicy || "all";
  elements.policyHint.textContent = state.sitePolicy === "trusted"
    ? `${state.trustedHosts?.length || 0} 个受信任网站`
    : "允许所有网站";
  elements.activeHost.textContent = state.activeHost || "非网页标签";
  elements.trustSite.disabled = !state.activeHost;
  elements.trustSite.textContent = state.activeTrusted ? "移出信任" : "加入信任";
  elements.advanced.classList.toggle("enabled", Boolean(state.advancedEnabled));
  elements.advancedState.textContent = state.advancedEnabled ? "已开启" : "关闭";
  renderBridge(latestBridge);
}

async function refresh() {
  try {
    const [bridge, security] = await Promise.all([
      request("bridge-status"),
      request("security-status"),
    ]);
    renderSecurity(security || {});
    renderBridge(bridge?.state || {});
  } catch (error) {
    renderBridge({ connected: false, lastError: error?.message || String(error) });
  }
}

elements.automation.addEventListener("click", async () => {
  const enabled = elements.automation.getAttribute("aria-checked") !== "true";
  renderSecurity(await request("automation-enabled", { enabled }));
  toast(enabled ? "自动化已恢复" : "自动化已暂停");
});

elements.sitePolicy.addEventListener("change", async () => {
  renderSecurity(await request("site-policy", { policy: elements.sitePolicy.value }));
  toast(elements.sitePolicy.value === "trusted" ? "已限制为受信任网站" : "已允许所有网站");
});

elements.trustSite.addEventListener("click", async () => {
  const response = await request("trust-current-site", { trusted: !latestSecurity.activeTrusted });
  if (response?.ok === false) return toast(response.error);
  renderSecurity(response);
  toast(response.activeTrusted ? "当前网站已加入信任" : "当前网站已移出信任");
});

elements.advanced.addEventListener("click", async () => {
  const enabled = !latestSecurity.advancedEnabled;
  const response = await request("advanced-control", { enabled });
  renderSecurity({ ...latestSecurity, advancedEnabled: response?.enabled });
  toast(enabled ? "高级控制已开启" : "高级控制已关闭");
});

$("#reconnect").addEventListener("click", async () => {
  elements.status.textContent = "正在重新连接…";
  const response = await request("bridge-reconnect");
  renderBridge(response?.state || {});
  toast(response?.state?.connected ? "连接已恢复" : "仍在等待本地服务");
});

$("#copyDiagnostics").addEventListener("click", async () => {
  const report = {
    product: "Browser Takeover",
    version: chrome.runtime.getManifest().version,
    bridge: latestBridge,
    security: {
      automationEnabled: latestSecurity.automationEnabled,
      sitePolicy: latestSecurity.sitePolicy,
      trustedHostCount: latestSecurity.trustedHosts?.length || 0,
      activeHost: latestSecurity.activeHost,
      activeTrusted: latestSecurity.activeTrusted,
      advancedEnabled: latestSecurity.advancedEnabled,
      localOnly: true,
    },
    generatedAt: new Date().toISOString(),
  };
  await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
  toast("诊断信息已复制");
});

$("#reload").addEventListener("click", () => {
  request("extension-reload");
  window.close();
});

refresh();
