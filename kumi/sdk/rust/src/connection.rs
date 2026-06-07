use crate::auth::{bootstrap_profile, is_lan_code, is_relay_token, parse_lan_code_to_server_url};
use std::env;

#[derive(Debug, Clone)]
pub struct ConnectionConfig {
    pub mode: &'static str,
    pub base_url: String,
    pub access_token: String,
}

fn http_to_ws(u: &str) -> String {
    let u = u.trim_end_matches('/');
    if u.starts_with("https://") {
        format!("wss://{}", &u["https://".len()..])
    } else if u.starts_with("http://") {
        format!("ws://{}", &u["http://".len()..])
    } else {
        u.to_string()
    }
}

impl ConnectionConfig {
    pub fn websocket_url(&self) -> String {
        if self.mode == "relay" {
            format!("{}/ws/edge", http_to_ws(&self.base_url))
        } else {
            self.base_url.clone()
        }
    }
}

/// Resolve WebSocket target from env and connection code (same order as Go SDK).
pub fn resolve_connection(code: &str, edge_name: &str) -> Result<ConnectionConfig, String> {
    let relay_url = env::var("KUMI_RELAY_URL").unwrap_or_default();
    let access_token = env::var("KUMI_ACCESS_TOKEN").unwrap_or_default();
    if !relay_url.is_empty() && !access_token.is_empty() {
        return Ok(ConnectionConfig {
            mode: "relay",
            base_url: relay_url.trim_end_matches('/').to_string(),
            access_token,
        });
    }

    if code.starts_with("ws://") || code.starts_with("wss://") {
        return Ok(ConnectionConfig {
            mode: "direct",
            base_url: code.to_string(),
            access_token: String::new(),
        });
    }

    if is_lan_code(code) {
        let server_url = parse_lan_code_to_server_url(code)?;
        let ws_url = format!("{}/ws/edge", http_to_ws(&server_url));
        return Ok(ConnectionConfig {
            mode: "direct",
            base_url: ws_url,
            access_token: String::new(),
        });
    }

    if is_relay_token(code) {
        let profile = bootstrap_profile(code, "edge", edge_name)?;
        env::set_var("KUMI_RELAY_URL", &profile.relay_url);
        env::set_var("KUMI_ACCESS_TOKEN", &profile.access_token);
        return Ok(ConnectionConfig {
            mode: "relay",
            base_url: profile.relay_url,
            access_token: profile.access_token,
        });
    }

    if code.starts_with("http://") || code.starts_with("https://") {
        let base = code.trim_end_matches('/');
        let ws_url = format!("{}/ws/edge", http_to_ws(base));
        return Ok(ConnectionConfig {
            mode: "direct",
            base_url: ws_url,
            access_token: String::new(),
        });
    }

    Ok(ConnectionConfig {
        mode: "direct",
        base_url: "ws://127.0.0.1:8000/ws/edge".to_string(),
        access_token: String::new(),
    })
}
