const statusElement = document.querySelector("#status");
const protocolElement = document.querySelector("#protocol");
const tabsElement = document.querySelector("#tabs");
const pollElement = document.querySelector("#poll");
const errorElement = document.querySelector("#error");
const indicatorElement = document.querySelector("#indicator");
const advancedButton = document.querySelector("#advanced");

document.querySelector("#version").textContent = `v${chrome.runtime.getManifest().version}`;

function formatTime(value) {
  return value ? new Date(value).toLocaleTimeString() : "尚未";
}

function render(state) {
  statusElement.textContent = state.connected ? "已连接本地接管桥" : "等待本地接管桥";
  protocolElement.textContent = `V${state.protocolVersion || "—"}`;
  tabsElement.textContent = String(state.tabCount ?? "—");
  pollElement.textContent = formatTime(state.lastPollAt);
  indicatorElement.classList.toggle("connected", Boolean(state.connected));
  errorElement.hidden = !state.lastError;
  errorElement.textContent = state.lastError || "";
}

async function request(type, extra = {}) {
  return chrome.runtime.sendMessage({ type, ...extra });
}

async function refresh() {
  try {
    const response = await request("bridge-status");
    render(response?.state || {});
    const advanced = await request("advanced-control-status");
    advancedButton.textContent = advanced?.enabled ? "关闭高级控制" : "启用高级控制";
    advancedButton.dataset.enabled = advanced?.enabled ? "true" : "false";
  } catch (error) {
    render({ connected: false, lastError: error?.message || String(error) });
  }
}

document.querySelector("#reconnect").addEventListener("click", async () => {
  statusElement.textContent = "正在重连…";
  try {
    const response = await request("bridge-reconnect");
    render(response?.state || {});
  } catch (error) {
    render({ connected: false, lastError: error?.message || String(error) });
  }
});

document.querySelector("#reload").addEventListener("click", () => {
  request("extension-reload");
  window.close();
});

advancedButton.addEventListener("click", async () => {
  const enabled = advancedButton.dataset.enabled !== "true";
  const response = await request("advanced-control", { enabled });
  if (response?.ok) {
    advancedButton.dataset.enabled = enabled ? "true" : "false";
    advancedButton.textContent = enabled ? "关闭高级控制" : "启用高级控制";
  }
});

refresh();
