---
name: browser-takeover
description: Control already-open authenticated Chrome or Edge tabs through the Browser Takeover companion extension, or attach to debug-enabled and persistent browser profiles through CDP. Use when an agent needs to read or operate an existing signed-in webpage, fill forms, click controls, upload or download files, capture screenshots, or automate multi-tab browser workflows without repeating login.
---

# Browser Takeover

Use the Browser Takeover plugin in this repository to control Chrome and Edge locally while preserving user visibility and control.

## Requirements

- Install the plugin from this repository before using the skill so its MCP tools are available.
- Use the companion extension for an already-open, authenticated browser tab.
- Use CDP or a persistent takeover profile for automation-only sessions.
- Never inspect passwords, cookies, browser profiles, or other session secrets.

## Workflow

1. Call `browser_takeover_status` or `browser_takeover_extension_bridge_status`.
2. When the task depends on an existing signed-in page, call `browser_takeover_extension_diagnostics`, then `browser_takeover_extension_list_tabs`.
3. Claim the selected tab with `browser_takeover_claim_tab`. Use a readonly claim for inspection and an interactive claim for page changes.
4. Prefer structured `browser_takeover_extension_action` operations such as `snapshot`, `read`, `click`, `fill`, `press`, `select`, `scroll`, and `wait`.
5. Add an `expect` condition to write actions when possible so success is verified from observable page state.
6. Use the dedicated upload, download, screenshot, dialog, or native-input tools when the task requires them.
7. Pause before consequential actions such as publishing, sending, purchasing, deleting, or changing account settings unless the user explicitly authorized the final action.
8. Release the tab with `browser_takeover_release_tab` when finished.

## Connection fallback

If the extension bridge is unavailable, check whether Chrome or Edge is running with a DevTools remote debugging port such as `9222`. List CDP pages and attach to the intended tab when available. Otherwise, launch a persistent takeover profile, ask the user to sign in once, and reuse that profile in later sessions.

The companion extension and complete plugin implementation are located in the `browser-takeover/` directory of this repository.
