# Browser Takeover

Browser Takeover is a local Codex plugin for attaching agents to a local Chromium browser through the Chrome DevTools Protocol (CDP).

It supports:

- Connecting to already-open authenticated tabs through the companion browser extension.
- Detecting Chrome and Edge processes.
- Checking common CDP ports such as `9222`.
- Listing open tabs.
- Navigating an existing tab.
- Evaluating JavaScript in a tab.
- Capturing screenshots.
- Launching a persistent takeover profile that keeps cookies and login state for future sessions.

## Two takeover modes

### Extension bridge: already-open authenticated tabs

This is the mode to use when the user already has a logged-in page open in their normal Chrome or Edge profile.

Install the extension once:

1. Open `edge://extensions` or `chrome://extensions`.
2. Enable developer mode.
3. Choose "Load unpacked".
4. Select this folder:

```text
browser-takeover/extension
```

When Codex runs the MCP server, it starts a local bridge on `127.0.0.1:17321`. The extension reports normal browser tabs to that bridge and executes commands in those tabs. This avoids a new login flow because commands run inside the user's existing browser profile and page session.

Available extension tools:

- `browser_takeover_extension_bridge_status`
- `browser_takeover_extension_list_tabs`
- `browser_takeover_extension_evaluate`
- `browser_takeover_extension_navigate`
- `browser_takeover_extension_screenshot`

### CDP: debug-enabled browser instances

An already open normal Chrome or Edge window cannot be attached unless it was launched with a remote debugging port:

```powershell
msedge.exe --remote-debugging-port=9222
chrome.exe --remote-debugging-port=9222
```

If that flag was not present and the companion extension is not installed, use the plugin's launch tool. It creates a reusable profile under local app data. Log in once there, then agents can reconnect later.

The extension bridge is preferred for already-open user pages. CDP is still useful for automation-only sessions, clean-room profiles, and pages launched specifically for agent control.
