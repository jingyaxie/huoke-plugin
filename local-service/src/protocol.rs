//! Huoke Bridge Protocol v1 — keep in sync with extension/src/shared/protocol.ts

use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

pub const PROTOCOL_VERSION: i32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum MessageType {
    Command,
    Result,
    Event,
    Error,
    Ping,
    Pong,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BridgeMessage {
    pub v: i32,
    #[serde(rename = "type")]
    pub msg_type: MessageType,
    pub id: String,
    pub ts: i64,
    pub platform: Option<String>,
    pub action: String,
    pub payload: Value,
}

impl BridgeMessage {
    pub fn new(msg_type: MessageType, action: impl Into<String>, payload: Value) -> Self {
        let platform = payload
            .get("platform")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string);
        Self {
            v: PROTOCOL_VERSION,
            msg_type,
            id: Uuid::new_v4().to_string(),
            ts: chrono_now_ms(),
            platform,
            action: action.into(),
            payload,
        }
    }

    pub fn pong_from(ping: &BridgeMessage) -> Self {
        Self {
            v: PROTOCOL_VERSION,
            msg_type: MessageType::Pong,
            id: ping.id.clone(),
            ts: chrono_now_ms(),
            platform: ping.platform.clone(),
            action: "pong".into(),
            payload: Value::Object(Default::default()),
        }
    }
}

fn chrono_now_ms() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

pub fn parse_message(text: &str) -> Result<BridgeMessage, String> {
    let msg: BridgeMessage = serde_json::from_str(text).map_err(|e| e.to_string())?;
    if msg.v != PROTOCOL_VERSION {
        return Err(format!("unsupported protocol version: {}", msg.v));
    }
    Ok(msg)
}
