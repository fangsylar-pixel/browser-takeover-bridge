# Browser Takeover

Browser Takeover is a local-first AI browser control plugin for attaching agents to authenticated
Chrome and Edge tabs through an extension bridge or the Chrome DevTools Protocol (CDP).

It supports:

- Connecting to already-open authenticated tabs through the companion browser extension.
- Detecting Chrome and Edge processes.
- Checking common CDP ports such as `9222`.
- Listing open tabs.
- Navigating an existing tab.
- Evaluating JavaScript in a tab.
- Capturing screenshots.
- Launching a persistent takeover profile that keeps cookies and login state for future sessions.
- Claiming tabs with renewable readonly or interactive leases.
- Running structured browser actions without requiring arbitrary JavaScript.
- Authenticating extension-to-bridge traffic with a per-extension token.
- Pausing automation instantly and restricting commands to trusted hostnames.
- Copying support diagnostics without exposing trusted-host details.

## Version 0.6 commercial trust controls

Version 0.6 turns the extension popup into a customer-facing control center. It communicates the
local-only architecture, connection health, supported workflow capabilities, and advanced-control
status at a glance.

Customers can pause all automation, choose between all-site and trusted-site modes, add or remove
the current hostname, and copy a privacy-safe diagnostic report. The same controls are available
through `browser_takeover_extension_security` for managed and team deployments.

## Version 0.2 compatibility upgrade

Version 0.2 keeps every version 0.1 MCP tool and adds an opt-in V2 control path. Existing
`evaluate`, `navigate`, `screenshot`, site-specific prompt, image transfer, extension bridge,
and CDP behavior remains available.

The V2 flow is:

1. Call `browser_takeover_extension_list_tabs`.
2. Call `browser_takeover_claim_tab` with the returned `clientId` and tab `id`.
3. Run one or more `browser_takeover_extension_action` calls with the returned `claimId`.
4. Call `browser_takeover_release_tab` when finished.

Claims can be `readonly` or `interactive`. Multiple readonly claims may observe a tab, while
an interactive claim prevents a different owner from writing to the same tab. Claims expire
automatically and can be extended with `browser_takeover_renew_claim`.

Structured actions currently support:

- `snapshot`
- `read`
- `click`
- `doubleClick`
- `hover`
- `fill`
- `press`
- `wait`
- `check`
- `select`
- `scroll`

Targets can use CSS, test IDs, ARIA-style role and name matching, visible text, or form labels.
The original arbitrary JavaScript tools remain available for advanced and site-specific work.

Write actions can include an `expect` block so success is based on observable evidence instead of
only a dispatched click or input event. Verification can wait for URL changes, visible text,
elements appearing or disappearing, and final field values.

`browser_takeover_extension_batch_snapshot` can read up to 20 existing tabs in one operation.
Temporary readonly claims prevent accidental writes while enabling multi-tab research and account
comparison workflows.

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
- `browser_takeover_claim_tab`
- `browser_takeover_renew_claim`
- `browser_takeover_release_tab`
- `browser_takeover_extension_action`

### Local bridge security

The extension registers with protocol version and capability metadata. The bridge returns a
random per-extension token, and subsequent tab sync, polling, and result messages must present
that token. Browser CORS responses are limited to Chrome and Edge extension origins instead of
using a wildcard origin.

After updating from version 0.1, reload the unpacked extension once so its background worker
uses the authenticated protocol.

The extension also uses a Manifest V3 alarm as a reconnect watchdog. This allows it to rediscover
the localhost bridge after Edge or Chrome suspends the background service worker, including when
the bridge starts after the extension.

## Tests

Run the complete release verification:

```powershell
python scripts/verify_release.py
```

Or run individual checks:

```powershell
python -m unittest discover -s tests -v
python -m py_compile scripts/browser_takeover_mcp.py scripts/benchmark_extension.py scripts/release_tools.py scripts/verify_release.py tests/test_bridge.py tests/test_release_tools.py
node --check extension/background.js
node --check extension/popup.js
node tests/test_background_runtime.mjs
```

For a live check against already-open HTTP(S) tabs:

```powershell
python scripts/benchmark_extension.py --iterations 3
```

The benchmark records per-tab failures instead of aborting the whole run. Extension commands also
have a hard timeout so a stalled page cannot permanently block later browser work.

### CDP: debug-enabled browser instances

An already open normal Chrome or Edge window cannot be attached unless it was launched with a remote debugging port:

```powershell
msedge.exe --remote-debugging-port=9222
chrome.exe --remote-debugging-port=9222
```

If that flag was not present and the companion extension is not installed, use the plugin's launch tool. It creates a reusable profile under local app data. Log in once there, then agents can reconnect later.

The extension bridge is preferred for already-open user pages. CDP is still useful for automation-only sessions, clean-room profiles, and pages launched specifically for agent control.

## Version 0.3 reliability and observability

The extension popup shows connection state, protocol version, synchronized tab count, last poll
time, and the latest bridge error. The toolbar badge displays `ON` when connected and `!` when
disconnected.

Protocol diagnostics distinguish extension registration, fresh tab synchronization, active
command polling, and successful command/result round trips.

The bridge also exposes incremental tab lifecycle events, evidence-based action verification, and
readonly multi-tab snapshots.

## Version 0.4 complex-page controls

Structured actions can target open Shadow DOM using `shadowPath`, run against every accessible
frame with `frameScope: "all"`, or select a specific `frameId`. Coordinate click and page-keyboard
fallbacks are available for canvas-style or weakly accessible controls.

Local uploads use `browser_takeover_extension_upload`. Browser-managed downloads use
`browser_takeover_extension_download`, and completion can be observed through download status or
the event stream.

## Version 0.5 optional advanced control

Chromium requires the `debugger` permission to be declared in the manifest. Its runtime use remains
disabled until the user enables advanced control in the extension popup. When enabled, Browser Takeover
can dispatch browser-level mouse, wheel, drag, text, and keyboard input; capture true full-page
screenshots; and accept or dismiss JavaScript dialogs.

Existing DOM actions, extension bridging, downloads, CDP mode, and site-specific tools do not use
the debugger channel while advanced control is switched off.
