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

`yumi` is a **complete single-user, self-hosted agent**: it runs on your own machine for one user, so by design it does not authenticate requests or scope data per user — there is one user. That is appropriate for a personal local tool, not a missing feature. Accordingly, the local HTTP API is intended for **trusted networks** and binds `127.0.0.1` by default; expose it on a LAN only on a network you trust (`yumi --server --host 0.0.0.0`), and never expose the unauthenticated admin API to the public Internet.

Identity, authorization, and quotas are resolved through the plugin ports under `yumi.core.platform.plugins`, so the same routes can carry per-user authorization in other deployment models without changing route code — but none of that is required to run yumi-agent for yourself. Relay mode and browser CORS have additional considerations; see [docs/HTTP_API.md](docs/HTTP_API.md) and [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

Request bodies are read into memory before handling. Uploads (`POST /uploads`, `POST /stt/transcribe`) reject oversized content (base64 length is checked before decoding), but the JSON body itself still enters the app layer first. For a single-user, trusted-network deployment that's fine; if you expose the API more broadly, cap request body size at a reverse proxy or an ASGI middleware (the same layer where you'd add authentication and rate limiting).

By default, browser CORS is limited to localhost-style origins and credentialed browser requests are disabled. If you need browser access beyond local development, set explicit origins with `YUMI_CORS_ORIGINS` or `YUMI_RELAY_CORS_ORIGINS` and keep TLS termination in front of any public Relay deployment.

For operational guidance, see the “Security and deployment” sections in [docs/HTTP_API.md](docs/HTTP_API.md).
