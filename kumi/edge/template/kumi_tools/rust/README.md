# Kumi Edge — Rust

## Quick Start

1. Edit `kumi_tools/rust/src/kumi_setup.rs` and register your tools.
2. From `kumi_tools/rust/`, run:

```bash
cargo run
```

The bundled `kumi_sdk` crate is copied from Kumi; point your own crate at it with:

```toml
kumi_sdk = { path = "kumi_tools/rust/kumi_sdk" }
```

## Configure

Set `kumi_tools/.env` or environment variables:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My Rust App
```

Runtime: Tokio + `tokio-tungstenite`.
