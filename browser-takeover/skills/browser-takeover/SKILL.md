---
name: browser-takeover
description: Attach Codex to local Chrome or Edge tabs through a companion extension for already-open authenticated pages, or through CDP for debug-enabled browsers and persistent takeover profiles.
---

# Browser Takeover

Use this skill when the user wants an agent to control a browser that is already open, avoid repeated login flows, or start a browser profile that Codex can keep reusing.

## Important boundary

A normal Chrome or Edge window cannot be attached after launch unless it was started with a DevTools remote debugging port such as `--remote-debugging-port=9222`. This is a browser security boundary, not a Codex limitation.

To work with already-open authenticated tabs in the user's normal profile, use the companion extension bridge. The extension must be installed once in that browser profile; after that it can report and control currently open tabs without relaunching the browser or repeating login.

When the extension is not installed and the current browser is not CDP-attachable, use the plugin's MCP tools to launch a persistent takeover browser. The first login happens once in that takeover profile; later agent sessions can reconnect without repeating authentication.

## Workflow

1. Call `browser_takeover_status` or `browser_takeover_extension_bridge_status`.
2. Prefer extension tools when the user's goal depends on an already-open, logged-in tab:
   - `browser_takeover_extension_diagnostics`
   - `browser_takeover_extension_list_tabs`
   - `browser_takeover_claim_tab`
   - `browser_takeover_extension_action`
   - `browser_takeover_release_tab`
   - `browser_takeover_extension_batch_snapshot`
   - `browser_takeover_extension_events`
   - `browser_takeover_extension_wait_event`
   - `browser_takeover_extension_upload`
   - `browser_takeover_extension_download`
   - `browser_takeover_extension_download_status`
   - `browser_takeover_extension_workflow`
   - `browser_takeover_extension_full_screenshot`
   - `browser_takeover_extension_native_input`
   - `browser_takeover_extension_handle_dialog`
   - `browser_takeover_extension_evaluate`
   - `browser_takeover_extension_paginate`
   - `browser_takeover_extension_navigate`
   - `browser_takeover_extension_screenshot`
   - `browser_takeover_monitor_create`
   - `browser_takeover_monitor_check`
   - `browser_takeover_monitor_list`
   - `browser_takeover_monitor_history`
   - `browser_takeover_monitor_update`
   - `browser_takeover_monitor_delete`
3. If a CDP port is reachable, call `browser_takeover_list_pages`.
4. Use `browser_takeover_navigate`, `browser_takeover_evaluate`, or `browser_takeover_screenshot` against the chosen CDP port and page.
5. If neither the extension nor a CDP port is reachable, call `browser_takeover_launch` with `browser` set to `edge` or `chrome`. This opens a persistent profile under the user's local app data.
6. Ask the user to install the extension or log in once in the takeover window when authentication is required.

## Extension setup

The extension lives at `browser-takeover/extension` inside the plugin. Install it once:

1. Open `edge://extensions` or `chrome://extensions`.
2. Enable developer mode.
3. Choose "Load unpacked".
4. Select the `browser-takeover/extension` directory.

The MCP server listens only on `127.0.0.1:17321`. The extension polls that local bridge, reports open tabs, and executes requested commands inside those tabs.

Use structured V2 actions for normal reading and interaction. Keep arbitrary JavaScript evaluation
for advanced compatibility cases. For write actions, include an `expect` block when possible so
the result is verified by URL, text, element visibility, or final value evidence.

For SPA navigation, pass `urlPattern`, `selector`, or `text` to
`browser_takeover_extension_navigate` whenever a reliable readiness signal is known. Treat
`ok: false`, `timedOut: true`, or an unexpected final URL as evidence that the route was rejected or
the business content did not load. If a site rejects deep links, follow the redirect with a verified
menu click instead of repeatedly navigating to the same URL.

Snapshot controls include a reusable CSS `selector` and an `interactiveBy` reason. Prefer that
selector for custom `div`/`span` controls before falling back to arbitrary JavaScript.

Before diagnosing a connection problem, call `browser_takeover_extension_diagnostics`. A healthy
client reports fresh registration, tab sync, and polling. `roundTrip` becomes true after at least
one command result is returned.

Use `health.connected` for current connectivity. Do not treat `roundTrip: false` as a disconnect by
itself; it expires after 30 seconds without a command and is reported as `resultChannel: "idle"`
while polling remains healthy. Compare `server.instanceId`, PID, and uptime across observations to
prove an MCP process restart before attributing lost in-memory claims to the browser extension.

For large DOM-paginated lists, prefer `browser_takeover_extension_paginate` over an agent-side
page loop. It performs SPA change waits, row deduplication, and structured field extraction within
the tab while the bridge automatically keeps the interactive claim alive.

Pagination requires an interactive claim because it clicks the next-page control. Provide
`rowSelector`, `nextSelector`, and optional `fields`, `keyField`, `maxPages`, and `waitTimeout`.
Inspect `stopReason` and `warnings`; partial rows are retained after a page-change timeout unless
`continueOnTimeout` is false. If a command returns `EXTENSION_COMMAND_TIMEOUT`, inspect
diagnostics after the automatic recovery attempt before retrying; do not immediately start an
unbounded retry loop.

For infinite-scroll pages, use the same tool with `mode: "scroll"`, omit `nextSelector`, and provide
an optional `scrollContainer`, `scrollStep`, `scrollWaitTimeout`, and `stableRounds`. Field mappings
may use candidate descriptor arrays or multiple CSS selectors; use `textPattern` and `group` when a
site renders alternate labels for the same reporting slot. Preserve the original label when the
metrics are semantically different.

Browser-level native input, true full-page screenshots, and JavaScript dialog handling require the
optional advanced control permission. The user enables it once from the extension popup. Do not
fall back to arbitrary JavaScript when the task specifically requires trusted input semantics.

## Monitor webpage content

Use persistent monitors when the user asks to watch a page for changes, prices, stock, keywords,
registration availability, announcements, or similar conditions.

1. Ask for or infer the target page and trigger condition.
2. Make sure the page is open in the connected Chrome or Edge profile.
3. Call `browser_takeover_monitor_create` with a stable URL substring. Prefer a narrow `target`
   selector over monitoring the entire page so timestamps and rotating content do not cause noise.
4. Call `browser_takeover_monitor_check` once to establish a baseline.
5. For recurring checks, use the host agent's scheduled-task feature to call the check tool. The MCP
   server stores state but does not create an operating-system scheduler.
6. Notify the user when `newlyTriggered` is true. Include `diff`, `currentPreview`, and source URL as
   evidence. Do not purchase, submit, or publish automatically unless separately authorized.

Use `changed` for any content change; `contains`, `not_contains`, `equals`, or `regex` for text; and
`number_above` or `number_below` for prices and numeric thresholds. Pause noisy monitors before
changing their selector or rule. Treat monitor history as sensitive because it may contain text from
authenticated pages.

## Practical setup

For true "attach to my already opened daily browser" behavior, the user should start Chrome or Edge with a remote debugging port before browsing:

```powershell
msedge.exe --remote-debugging-port=9222
chrome.exe --remote-debugging-port=9222
```

If their normal browser is already running without that flag, the extension bridge is the path that can still use already-open authenticated pages. Launch the persistent takeover profile only when the extension is unavailable or a clean automation profile is preferred.
