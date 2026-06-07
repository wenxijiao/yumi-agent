use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use reqwest::blocking::Client;
use serde_json::Value;
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

const TOKEN_PREFIX: &str = "kumi_";
const LAN_TOKEN_PREFIX: &str = "kumi-lan_";
const LEGACY_LAN_PREFIXES: [&str; 2] = ["ml1_", "kumi_lan_"];

fn b64url_decode(data: &str) -> Result<Vec<u8>, String> {
    let padding = (4 - data.len() % 4) % 4;
    let padded = format!("{}{}", data, "=".repeat(padding));
    URL_SAFE_NO_PAD
        .decode(padded.as_bytes())
        .map_err(|e| e.to_string())
}

/// Parse a `kumi-lan_...` token into `(host, port)`.
pub fn decode_lan_code(token: &str) -> Result<(String, u16), String> {
    let encoded = if token.starts_with(LAN_TOKEN_PREFIX) {
        &token[LAN_TOKEN_PREFIX.len()..]
    } else {
        let mut found = None;
        for p in LEGACY_LAN_PREFIXES {
            if token.starts_with(p) {
                found = Some(&token[p.len()..]);
                break;
            }
        }
        found.ok_or_else(|| "invalid Kumi LAN code prefix".to_string())?
    };

    let raw = b64url_decode(encoded)?;
    let data: Value = serde_json::from_slice(&raw).map_err(|e| e.to_string())?;
    let obj = data.as_object().ok_or_else(|| "LAN code JSON error".to_string())?;

    let (host, port) = if let Some(h) = obj.get("h") {
        let host = match h {
            Value::String(s) => s.clone(),
            _ => h.to_string(),
        };
        let port = obj
            .get("p")
            .and_then(|p| p.as_u64())
            .unwrap_or(8000) as u16;
        (host, port)
    } else if let Some(bu) = obj.get("base_url") {
        let url_str = bu.as_str().ok_or_else(|| "LAN code base_url invalid".to_string())?;
        let url = url::Url::parse(url_str).map_err(|e| e.to_string())?;
        let host = url
            .host_str()
            .ok_or_else(|| "LAN code missing host".to_string())?
            .to_string();
        let port = url.port().unwrap_or(8000);
        (host, port)
    } else {
        return Err("LAN code missing host".into());
    };

    if let Some(x) = obj.get("x") {
        if let Some(xf) = x.as_f64() {
            let now = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_secs() as i64)
                .unwrap_or(0);
            if xf as i64 > 0 && (xf as i64) < now {
                return Err("LAN code has expired".into());
            }
        }
    }

    Ok((host, port))
}

pub fn parse_lan_code_to_server_url(code: &str) -> Result<String, String> {
    let (host, port) = decode_lan_code(code)?;
    Ok(format!("http://{host}:{port}"))
}

pub fn is_lan_code(code: &str) -> bool {
    if code.starts_with(LAN_TOKEN_PREFIX) {
        return true;
    }
    LEGACY_LAN_PREFIXES.iter().any(|p| code.starts_with(p))
}

pub fn is_relay_token(code: &str) -> bool {
    code.starts_with(TOKEN_PREFIX) && !is_lan_code(code)
}

#[derive(Debug, Clone)]
pub struct BootstrapResult {
    pub relay_url: String,
    pub access_token: String,
}

/// Exchange a relay join code for relay URL + access token.
pub fn bootstrap_profile(join_code: &str, scope: &str, device_name: &str) -> Result<BootstrapResult, String> {
    let cred: HashMap<String, Value> = decode_credential_json(join_code)?;
    let relay_url = cred
        .get("relay_url")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "credential missing relay_url".to_string())?
        .trim_end_matches('/')
        .to_string();

    let body = serde_json::json!({
        "join_code": join_code,
        "scope": scope,
        "device_name": device_name.trim(),
    });

    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .build()
        .map_err(|e| e.to_string())?;

    let resp = client
        .post(format!("{relay_url}/v1/bootstrap"))
        .json(&body)
        .send()
        .map_err(|e| e.to_string())?;

    let status = resp.status();
    let text = resp.text().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(format!("bootstrap failed: {text}"));
    }

    let result: HashMap<String, Value> = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let access_token = result
        .get("access_token")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "bootstrap response missing access_token".to_string())?
        .to_string();

    Ok(BootstrapResult {
        relay_url,
        access_token,
    })
}

fn decode_credential_json(token: &str) -> Result<HashMap<String, Value>, String> {
    if !token.starts_with(TOKEN_PREFIX) {
        return Err("invalid Kumi credential prefix".into());
    }
    let raw = b64url_decode(&token[TOKEN_PREFIX.len()..])?;
    serde_json::from_slice(&raw).map_err(|e| e.to_string())
}
