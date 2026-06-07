# Yumi Edge — Rust

## Quick Start

1. Edit `yumi_tools/rust/src/yumi_setup.rs` and register your tools.
2. From `yumi_tools/rust/`, run:

```bash
cargo run
```

The bundled `yumi_sdk` crate is copied from Yumi; point your own crate at it with:

```toml
yumi_sdk = { path = "yumi_tools/rust/yumi_sdk" }
```

## Configure

Set `yumi_tools/.env` or environment variables:

```env
YUMI_CONNECTION_CODE=yumi-lan_...
EDGE_NAME=My Rust App
```

Runtime: Tokio + `tokio-tungstenite`.
