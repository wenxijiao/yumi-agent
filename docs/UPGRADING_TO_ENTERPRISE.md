# Upgrading from `yumi-agent` (OSS) to `yumi-enterprise`

The OSS `yumi-agent` package is a complete, single-user / LAN agent. You
do not need anything else to chat with an agent, register tools across
eleven languages, or run a personal Telegram / LINE bot.

If you reach a point where you need any of the following, the closed-source
companion package `yumi-enterprise` is what you want:

- multi-user identity (per-user `Bearer` tokens, signup / login / refresh)
- per-user quotas, billing, and audit
- PostgreSQL-backed storage instead of local SQLite
- the public **relay server** for remote pairing across NATs
- the admin HTTP API + interactive admin CLI
- per-user data-key encryption

This document explains how the two packages relate, and what you have to
change to switch.

## Architecture in one paragraph

The OSS core defines a **plugin port** layer at
[`yumi/core/platform/plugins/`](../yumi/core/platform/plugins/) — small abstract interfaces
for identity, quotas, billing, session scoping, bot pooling, memory
factory, edge scoping, audit, route extension, and middleware extension.
The OSS package registers permissive single-user defaults for every port.
`yumi-enterprise` ships an `entry_point` (group `yumi.plugins`) named
`enterprise` that, on first import of the OSS app, swaps in real
implementations and mounts the extra HTTP routes (`/admin/*`, `/auth/*`,
`/tenancy/*`, `/relay/*`) onto the same FastAPI app.

This means:

- **The OSS core never imports enterprise code.** It is fully usable
  without the private package installed.
- **The enterprise package depends on the OSS package.** Bug fixes and
  features added to OSS are immediately available to the enterprise build,
  no copy-paste required.
- **One FastAPI app**, two binaries: `yumi --server` is the OSS shape,
  `yumi-enterprise serve` is the same shape plus the registered plugin.

## Switching from OSS to Enterprise

1. **Get access to the private wheel / image.** The enterprise package is
   not on PyPI. Ask the maintainers for the private registry URL.

2. **Install the image (recommended)** or wheel:

   ```bash
   # Recommended: Docker
   docker pull ${REGISTRY_URL}/yumi-enterprise:latest

   # Or, on a Python host (private wheel)
   pip install yumi-agent==0.3.*           # OSS, from PyPI
   pip install /path/to/yumi_enterprise-*.whl --no-deps
   ```

3. **Provision Postgres** and set `YUMI_DB_URL`. Generate
   `YUMI_SECRET_KEY` (≥ 32 random bytes) and `YUMI_KEK` (base64 32-byte
   key). Store both in your secrets manager.

4. **Apply database migrations** (empty Postgres or first deploy):

   ```bash
   export YUMI_DB_URL="postgresql://user:pass@host:5432/dbname"
   yumi-enterprise db-upgrade
   ```

5. **Start the enterprise server.** Use `yumi-enterprise serve` instead
   of `yumi --server`:

   ```bash
   yumi-enterprise serve            # API + LINE sidecar
   yumi-enterprise relay            # optional: public relay daemon
   ```

6. **Bootstrap the first tenant + admin user**:

   ```bash
   yumi-enterprise tenant-create "Primary"
   yumi-enterprise user-add <TENANT_ID> "admin@example.com"
   yumi-enterprise user-set-scope <USER_ID> admin
   yumi-enterprise user-token <USER_ID>     # prints yumi_… Bearer
   ```

7. **Tell every client to send `Authorization: Bearer yumi_…`.** The OSS
   bots (`yumi --telegram`, `yumi --line`, `yumi --edge`) accept
   `YUMI_USER_ACCESS_TOKEN` for this purpose. The Telegram bot also
   accepts `/link <token>` over the chat itself.

See `docs/MULTI_TENANT.md` and `deploy/README.md` in the private
`yumi-enterprise` repo for the full operations guide.

## Going back to OSS

`yumi-enterprise` is additive. Stopping the enterprise binary and starting
`yumi --server` yields the original single-user behaviour — no migration
needed. The Postgres database keeps your data; you can resume enterprise
mode at any time.

## Compatibility promise

`yumi-enterprise` pins a narrow OSS range (`yumi-agent>=0.3,<0.4`).
Within that range the OSS team commits to:

- not removing or renaming any class in `yumi.core.platform.plugins`
- not changing the on-the-wire shape of `/health`, `/chat`, `/config/*`,
  `/ws/edge`
- bumping the OSS minor version when introducing breaking changes that
  the enterprise plugin would have to follow

Any change that would break the enterprise plugin must come with a
matching enterprise release on the same day.
