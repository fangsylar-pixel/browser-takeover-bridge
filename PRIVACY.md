# Privacy Policy

Browser Takeover Bridge is designed as a local-first browser control tool.

## Data processing

- The bridge listens only on `127.0.0.1` and does not provide a public network endpoint.
- Page content, screenshots, form values, and browser events are processed locally when an
  authorized agent requests them.
- The project does not include analytics, advertising SDKs, or hosted telemetry.
- Trusted-site settings, the global pause state, and advanced-control preferences are stored in
  the browser extension's local storage.
- Browser data is not uploaded by this project. A connected AI client may process data according
  to that client's own configuration and privacy policy.

## Browser permissions

The extension requests broad page access because it must work with tabs the user chooses across
Chrome and Edge. The downloads permission supports user-requested downloads. The debugger
permission supports optional browser-level input, dialog handling, and full-page screenshots, but
the advanced channel remains disabled until the user enables it in the popup.

Users can pause all automation at any time or restrict commands to an explicit trusted-site list.

## Retention

The local bridge keeps command results, claims, and event history in memory for the active process.
It does not create a browsing-history database. Generated screenshots and downloaded files are
saved only when explicitly requested.

## Contact

For privacy or security concerns, use GitHub private vulnerability reporting when available.
Do not post authenticated page content, access tokens, or signed URLs in a public issue.
