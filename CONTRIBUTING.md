# Contributing

Contributions are welcome, especially reproducible browser compatibility fixes, safety
improvements, tests, and documentation.

## Development setup

Requirements:

- Python 3.10 or newer
- Node.js 20 or newer
- Chrome or Edge for live extension testing

Load `browser-takeover/extension` as an unpacked extension, then run:

```powershell
python browser-takeover/scripts/verify_release.py
```

That command validates versions and manifests, runs automated tests and syntax checks, builds the
website, and creates release archives under `dist/`.

## Pull requests

- Keep changes focused and explain the user-visible behavior.
- Add or update tests for protocol, safety, or browser-runtime changes.
- Do not commit credentials, authenticated page data, screenshots, or downloaded customer files.
- Update `CHANGELOG.md` for notable changes.
- Confirm the global pause and trusted-site controls still fail closed.

## Live browser checks

Automated tests do not replace testing against a real browser. Before proposing a release, verify
tab discovery, readonly snapshots, a structured write action on a local fixture, pause enforcement,
and trusted-site rejection. Optional advanced-control changes should also verify debugger detach
and cleanup behavior.
