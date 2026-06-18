# Security Policy

## Reporting a vulnerability

Please do not open a public issue for vulnerabilities that could expose authenticated browser
content, execute commands in an unintended tab, bypass a claim boundary, or allow another local
process to impersonate the extension.

Use GitHub private vulnerability reporting when available. Include:

- affected version and browser;
- reproduction steps;
- expected and actual behavior;
- whether authenticated page data or write actions are involved.

## Security boundaries

- The bridge binds to `127.0.0.1` only.
- Protocol V2 extension traffic uses a per-extension bearer token.
- Browser CORS responses are restricted to extension origins.
- Structured actions default to the isolated execution world.
- Arbitrary JavaScript execution is an advanced compatibility feature and should be treated as
  privileged.

## Supported versions

Security fixes are applied to the latest development version until the first stable release is
published.
