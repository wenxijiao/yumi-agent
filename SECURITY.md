# Security policy

## Supported versions

Security fixes are applied to the latest release line on the default branch (`main`). Older tags may not receive backports unless explicitly stated in release notes.

## Reporting a vulnerability

**Please do not** file a public GitHub issue for undisclosed security vulnerabilities.

Instead:

1. Use **GitHub Security Advisories** for this repository (**Security** tab → **Report a vulnerability**), if enabled; or
2. Email the maintainers at a private address you have been given for this project; if none is listed, open a **non-sensitive** issue asking for a secure contact channel.

Include:

- A description of the issue and its impact
- Steps to reproduce or proof-of-concept (if safe to share)
- Affected versions or commits (if known)

We aim to acknowledge reports within a few business days and coordinate disclosure after a fix is available.

## Threat model (short)

Yumi’s local HTTP API is intended for **trusted networks** (typically `127.0.0.1`). Do not expose an unauthenticated admin API to the public Internet. Relay mode and browser CORS have additional considerations; see [docs/HTTP_API.md](docs/HTTP_API.md) and [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

By default, browser CORS is limited to localhost-style origins and credentialed browser requests are disabled. If you need browser access beyond local development, set explicit origins with `YUMI_CORS_ORIGINS` or `YUMI_RELAY_CORS_ORIGINS` and keep TLS termination in front of any public Relay deployment.

For operational guidance, see the “Security and deployment” sections in [docs/HTTP_API.md](docs/HTTP_API.md).
