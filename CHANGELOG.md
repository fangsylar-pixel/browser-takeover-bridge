# Changelog

## 0.6.0

- Repositioned the extension as an independent local-first AI browser bridge.
- Rebuilt the popup as a commercial-grade health and safety control center.
- Added a global automation pause switch.
- Added all-site and trusted-site command policies.
- Added current-site trust management and a privacy-safe diagnostic copy action.
- Added the `browser_takeover_extension_security` management tool.
- Updated customer-facing product, security, and differentiation copy.

## 0.5.0

- Added a command-level timeout so one stalled page cannot permanently block the extension poll loop.
- Made the live snapshot benchmark record per-page failures and continue testing remaining tabs.
- Added a debugger-backed visible screenshot fallback for browsers where `captureVisibleTab` stalls.
- Added advanced browser control with an explicit in-extension enable/disable switch.
- Added browser-level mouse clicks, wheel input, dragging, text insertion, and key dispatch.
- Added true full-page screenshots through the browser debugging protocol.
- Added JavaScript dialog acceptance and dismissal.
- Chromium requires `debugger` as a declared permission; runtime use remains disabled until the
  user enables advanced control in the extension popup.
- Added a repeatable live extension snapshot benchmark CLI.
- Added MCP control for enabling or disabling the advanced channel without opening the popup.
- Added debugger attach/command timeouts so conflicts with another controller fail quickly.
- Routed trusted input through a Windows system-input backend when Edge does not expose the CDP
  `Input` domain to extensions.

## 0.4.0

- Added deep selectors for open Shadow DOM trees.
- Added all-frame and explicit-frame structured actions.
- Added coordinate click and page-level keyboard fallbacks.
- Added local file upload into file inputs.
- Added browser-managed downloads and download status inspection.
- Added tab and download event waiting with incremental cursors.
- Added selector and rectangle screenshot cropping in the extension.
- Added complex-page integration fixtures for Shadow DOM, iframe, coordinates, and uploads.
- Added a claimed-tab workflow engine with retries, evidence checks, and stop/continue policies.
- Added optional advanced debugger permission for browser-level input, dialogs, and true full-page screenshots.

## 0.3.0

- Added extension popup health dashboard and connection badge.
- Added safe Edge fallback when `chrome.alarms` is unavailable.
- Added background-service-worker reconnect and self-reload controls.
- Added protocol diagnostics for registration, tab sync, polling, and result round trips.
- Added incremental browser tab lifecycle events.
- Added evidence-based action verification.
- Added multi-tab batch snapshots with temporary readonly claims.
- Added GitHub Actions CI across Windows, Linux, Python 3.10/3.12, and Node.js 20.
- Added a JavaScript runtime smoke test that executes the real extension background script.
- Added a security policy.

## 0.2.0

- Added protocol V2 capability negotiation and authenticated extension traffic.
- Added readonly and interactive tab claims with renewable leases.
- Added structured browser actions and semantic targeting.
- Preserved all V1 tools, CDP support, and site-specific actions.

## 0.1.0

- Initial extension bridge and CDP takeover implementation.
