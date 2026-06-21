use crate::connection::resolve_connection;
use crate::env::load_env_file;
use crate::schema::build_tool_schema;
use crate::types::{AgentOptions, RegisterOptions, ToolArguments};
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tokio::sync::Mutex as AsyncMutex;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream};

type WsWrite = futures_util::stream::SplitSink<WebSocketStream<MaybeTlsStream<tokio::net::TcpStream>>, Message>;

const LOG_PREFIX: &str = "[Yumi]";
const TOOL_CONFIRMATION_FILENAME: &str = ".yumi_tool_confirmation.json";

struct RegisteredTool {
    schema: Value,
    handler: std::sync::Arc<dyn Fn(ToolArguments) -> String + Send + Sync>,
}

pub struct YumiAgent {
    inner: Arc<Inner>,
}

struct Inner {
    connection_code: String,
    edge_name: String,
    policy_base_dir: String,
    tools: Mutex<HashMap<String, RegisteredTool>>,
    stopped: Arc<AtomicBool>,
}

impl YumiAgent {
    pub fn new(opts: AgentOptions) -> Self {
        let env_file = resolve_env_path(opts.env_path);
        load_env_file(&env_file);
        let policy_base_dir = Path::new(&env_file)
            .parent()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| ".".into());

        let mut connection_code = opts.connection_code.unwrap_or_default();
        if connection_code.is_empty() {
            connection_code = std::env::var("YUMI_CONNECTION_CODE").unwrap_or_default();
        }
        if connection_code.is_empty() {
            connection_code = std::env::var("BRAIN_URL").unwrap_or_default();
        }

        let mut edge_name = opts.edge_name.unwrap_or_default();
        if edge_name.is_empty() {
            edge_name = std::env::var("EDGE_NAME").unwrap_or_default();
        }
        if edge_name.is_empty() {
            edge_name = hostname::get()
                .map(|h| h.to_string_lossy().to_string())
                .unwrap_or_else(|_| "yumi-edge".into());
        }

        Self {
            inner: Arc::new(Inner {
                connection_code,
                edge_name,
                policy_base_dir,
                tools: Mutex::new(HashMap::new()),
                stopped: Arc::new(AtomicBool::new(false)),
            }),
        }
    }

    /// Register a tool.
    ///
    /// # Panics
    ///
    /// Panics if `opts.mode` is not one of `"dynamic"`, `"pinned"`, or
    /// `"autorun"` — a programming error that should surface loudly at
    /// startup (consistent with the SDK's use of `.expect()` elsewhere).
    pub fn register(&self, mut opts: RegisterOptions) {
        // Map the `mode` API onto the existing wire flags (one mode per tool).
        match opts.mode.as_str() {
            "pinned" => {
                opts.always_include = true;
            }
            "autorun" => {
                opts.proactive_context = true;
                if opts.context_args.is_some() {
                    opts.proactive_context_args = opts.context_args.clone();
                }
                if opts.context_label.is_some() {
                    opts.proactive_context_description = opts.context_label.clone();
                }
            }
            "dynamic" => {}
            other => panic!(
                "mode must be 'dynamic', 'pinned', or 'autorun'; got {other:?}"
            ),
        }

        let schema = build_tool_schema(&opts);
        let name = opts.name;
        let mut g = self.inner.tools.lock().expect("tools mutex");
        g.insert(
            name,
            RegisteredTool {
                schema,
                handler: opts.handler,
            },
        );
    }

    /// Spawn the WebSocket loop on the current Tokio runtime.
    pub fn run_in_background(&self) {
        let inner = self.inner.clone();
        tokio::spawn(async move {
            inner.connect_loop().await;
        });
    }

    pub fn stop(&self) {
        self.inner.stopped.store(true, Ordering::SeqCst);
    }
}

impl Inner {
    async fn connect_loop(self: Arc<Self>) {
        let config = match tokio::task::spawn_blocking({
            let code = self.connection_code.clone();
            let edge = self.edge_name.clone();
            move || resolve_connection(&code, &edge)
        })
        .await
        {
            Ok(Ok(c)) => c,
            Ok(Err(e)) => {
                eprintln!("{LOG_PREFIX} Failed to resolve connection: {e}");
                return;
            }
            Err(_) => return,
        };

        let ws_url = config.websocket_url();
        let token = config.access_token;
        let mut reconnect_delay = std::time::Duration::from_secs(3);

        while !self.stopped.load(Ordering::SeqCst) {
            match self.run_session(&ws_url, &token).await {
                Ok(()) => break,
                Err(e) => {
                    if self.stopped.load(Ordering::SeqCst) {
                        break;
                    }
                    eprintln!("{LOG_PREFIX} Connection lost: {e}. Reconnecting in {reconnect_delay:?}...");
                    tokio::time::sleep(add_jitter(reconnect_delay)).await;
                    reconnect_delay = (reconnect_delay * 2).min(std::time::Duration::from_secs(30));
                }
            }
        }
    }

    async fn run_session(self: &Arc<Self>, ws_url: &str, access_token: &str) -> Result<(), String> {
        let (ws_stream, _) = tokio_tungstenite::connect_async(ws_url)
            .await
            .map_err(|e| format!("dial: {e}"))?;
        let (write, mut read) = ws_stream.split();
        let write: Arc<AsyncMutex<WsWrite>> = Arc::new(AsyncMutex::new(write));

        let tool_list: Vec<Value> = {
            let tools = self.tools.lock().expect("tools mutex");
            tools.values().map(|t| t.schema.clone()).collect()
        };
        let tool_count = tool_list.len();

        let policy = self.load_confirmation_policy();
        let mut register_payload = json!({
            "type": "register",
            "edge_name": self.edge_name,
            "tools": tool_list,
            "tool_confirmation_policy": policy,
        });
        if !access_token.is_empty() {
            register_payload
                .as_object_mut()
                .unwrap()
                .insert("access_token".to_string(), json!(access_token));
        }

        {
            let mut w = write.lock().await;
            w.send(Message::Text(
                serde_json::to_string(&register_payload).map_err(|e| e.to_string())?,
            ))
            .await
            .map_err(|e| format!("register: {e}"))?;
        }

        eprintln!(
            "{LOG_PREFIX} Connected as [{}] with {tool_count} tool(s).",
            self.edge_name
        );

        let this = Arc::clone(self);
        let write_clone = Arc::clone(&write);

        while !this.stopped.load(Ordering::SeqCst) {
            let msg = read.next().await;
            let Some(msg) = msg else {
                if this.stopped.load(Ordering::SeqCst) {
                    return Ok(());
                }
                return Err("websocket closed".into());
            };
            let msg = msg.map_err(|e| e.to_string())?;
            if msg.is_close() {
                return Err("websocket closed".into());
            }
            if !msg.is_text() {
                continue;
            }
            let text = msg.to_text().map_err(|e| e.to_string())?;
            let v: Value = serde_json::from_str(text).map_err(|e| e.to_string())?;
            let msg_type = v.get("type").and_then(|t| t.as_str()).unwrap_or("");

            match msg_type {
                "persist_tool_confirmation_policy" => {
                    this.handle_persist_policy(&v);
                }
                "tool_call" => {
                    let this = Arc::clone(&this);
                    let write = Arc::clone(&write_clone);
                    tokio::spawn(async move {
                        this.handle_tool_call(write, v).await;
                    });
                }
                "register_warning" => {
                    let dropped = v
                        .get("skipped_tools")
                        .and_then(|s| s.as_array())
                        .map(|a| a.len())
                        .unwrap_or(0);
                    eprintln!("{LOG_PREFIX} Server did not mount {dropped} tool(s).");
                }
                "register_rejected" => {
                    // Refused (edge_name in use). Stop — don't reconnect to be rejected again.
                    let reason = v
                        .get("reason")
                        .and_then(|r| r.as_str())
                        .unwrap_or("edge_name already in use");
                    eprintln!("{LOG_PREFIX} Edge registration rejected by server: {reason}");
                    this.stopped.store(true, Ordering::SeqCst);
                }
                _ => {}
            }
        }
        Ok(())
    }

    async fn handle_tool_call(self: Arc<Self>, write: Arc<AsyncMutex<WsWrite>>, msg: Value) {
        let tool_name = msg.get("name").and_then(|x| x.as_str()).unwrap_or("");
        let call_id = msg
            .get("call_id")
            .and_then(|x| x.as_str())
            .unwrap_or("unknown")
            .to_string();
        let raw_args = msg
            .get("arguments")
            .and_then(|x| x.as_object())
            .cloned()
            .unwrap_or_default();

        let args = ToolArguments::from_json(raw_args);

        let result = {
            let tools = self.tools.lock().expect("tools mutex");
            if let Some(t) = tools.get(tool_name) {
                let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| (t.handler)(args)));
                match r {
                    Ok(s) => s,
                    Err(_) => "Error: tool handler panicked".to_string(),
                }
            } else {
                format!("Error: Tool '{tool_name}' is not registered on this edge.")
            }
        };

        let reply = json!({
            "type": "tool_result",
            "call_id": call_id,
            "result": result,
            "cancelled": false,
        });

        let mut w = write.lock().await;
        let _ = w
            .send(Message::Text(serde_json::to_string(&reply).unwrap()))
            .await;
    }

    fn handle_persist_policy(self: &Arc<Self>, msg: &Value) {
        let aa: Vec<String> = msg
            .get("always_allow")
            .and_then(|v| serde_json::from_value(v.clone()).ok())
            .unwrap_or_default();
        let fc: Vec<String> = msg
            .get("force_confirm")
            .and_then(|v| serde_json::from_value(v.clone()).ok())
            .unwrap_or_default();
        self.save_confirmation_policy(&aa, &fc);
    }

    fn confirmation_policy_path(&self) -> String {
        if let Ok(p) = std::env::var("YUMI_TOOL_CONFIRMATION_PATH") {
            let p = p.trim();
            if !p.is_empty() {
                return p.to_string();
            }
        }
        Path::new(&self.policy_base_dir)
            .join(TOOL_CONFIRMATION_FILENAME)
            .to_string_lossy()
            .to_string()
    }

    fn load_confirmation_policy(&self) -> Value {
        let path = self.confirmation_policy_path();
        let data = std::fs::read_to_string(&path).unwrap_or_default();
        if data.is_empty() {
            return json!({
                "always_allow": [],
                "force_confirm": [],
            });
        }
        let Ok(raw) = serde_json::from_str::<Map<String, Value>>(&data) else {
            return json!({
                "always_allow": [],
                "force_confirm": [],
            });
        };
        json!({
            "always_allow": raw.get("always_allow").cloned().unwrap_or(json!([])),
            "force_confirm": raw.get("force_confirm").cloned().unwrap_or(json!([])),
        })
    }

    fn save_confirmation_policy(&self, always_allow: &[String], force_confirm: &[String]) {
        let path = self.confirmation_policy_path();
        if let Some(dir) = Path::new(&path).parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        let payload = json!({
            "always_allow": always_allow,
            "force_confirm": force_confirm,
        });
        if let Ok(s) = serde_json::to_string_pretty(&payload) {
            let _ = std::fs::write(&path, s);
        }
    }
}

fn resolve_env_path(explicit: Option<String>) -> String {
    if let Some(p) = explicit {
        if !p.is_empty() {
            return p;
        }
    }
    let cwd = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());
    let yumi_tools = cwd.join("yumi_tools").join(".env");
    let root = cwd.join(".env");
    if yumi_tools.is_file() {
        yumi_tools.to_string_lossy().to_string()
    } else {
        root.to_string_lossy().to_string()
    }
}

fn add_jitter(base: std::time::Duration) -> std::time::Duration {
    let jitter = std::time::Duration::from_millis(fastrand::u64(0..=500));
    base.saturating_add(jitter)
}
