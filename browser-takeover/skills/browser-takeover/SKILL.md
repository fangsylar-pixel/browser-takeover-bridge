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
   - `browser_takeover_extension_list_tabs`
   - `browser_takeover_extension_evaluate`
   - `browser_takeover_extension_navigate`
   - `browser_takeover_extension_screenshot`
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

## Practical setup

For true "attach to my already opened daily browser" behavior, the user should start Chrome or Edge with a remote debugging port before browsing:

```powershell
msedge.exe --remote-debugging-port=9222
chrome.exe --remote-debugging-port=9222
```

If their normal browser is already running without that flag, the extension bridge is the path that can still use already-open authenticated pages. Launch the persistent takeover profile only when the extension is unavailable or a clean automation profile is preferred.
