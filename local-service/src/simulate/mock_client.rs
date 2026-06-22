use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::sync::Mutex;
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{info, warn};

use crate::protocol::{BridgeMessage, MessageType, PROTOCOL_VERSION};
use crate::simulate::fixtures::{
    aweme_from_url, comment_capture_body, extract_aweme_from_payload, search_capture_body,
    SIM_VIDEO_IDS,
};

struct MockState {
    hook_enabled: bool,
    comment_batch: u64,
    last_aweme: Option<String>,
}

impl MockState {
    fn new() -> Self {
        Self {
            hook_enabled: false,
            comment_batch: 0,
            last_aweme: None,
        }
    }
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn bridge_message(msg_type: MessageType, id: &str, action: &str, payload: Value) -> String {
    let msg = BridgeMessage {
        v: PROTOCOL_VERSION,
        msg_type,
        id: id.to_string(),
        ts: now_ms(),
        platform: Some("douyin".into()),
        action: action.to_string(),
        payload,
    };
    serde_json::to_string(&msg).unwrap_or_else(|_| "{}".into())
}

fn command_result(command: &BridgeMessage, data: Value) -> String {
    bridge_message(
        MessageType::Result,
        &command.id,
        &command.action,
        json!({ "ok": true, "data": data }),
    )
}

fn mock_lab_data(action: &str, payload: &Value) -> Value {
    match action {
        "plugin_lab.open_browser" => {
            let url = payload
                .get("url")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .unwrap_or("https://www.douyin.com/");
            json!({
                "ok": true,
                "simulated": true,
                "platform": "douyin",
                "url": url,
                "tab_id": 1,
                "window_id": 1,
                "message": "mock open_browser"
            })
        }
        "plugin_lab.swipe_page" => json!({
            "ok": true,
            "simulated": true,
            "scroll_delta": 900,
            "message": "mock swipe"
        }),
        "plugin_lab.find_search_box" => json!({ "ok": true, "simulated": true, "found": true }),
        "plugin_lab.input_search_text" => json!({
            "ok": true,
            "simulated": true,
            "search_text": payload.get("search_text").cloned().unwrap_or(json!(""))
        }),
        "plugin_lab.click_filter_btn" | "plugin_lab.click_search_btn" => {
            json!({ "ok": true, "simulated": true, "clicked": true })
        }
        "plugin_lab.click_filter_overlay" => json!({
            "ok": true,
            "simulated": true,
            "days": payload.get("days").cloned().unwrap_or(json!(7))
        }),
        "plugin_lab.fetch_search_results" => json!({
            "ok": true,
            "simulated": true,
            "count": SIM_VIDEO_IDS.len(),
            "items": SIM_VIDEO_IDS
        }),
        "plugin_lab.click_search_video" => json!({ "ok": true, "simulated": true, "video_index": 1, "is_search_feed": true }),
        "plugin_lab.swipe_search_feed_next" => json!({
            "ok": true,
            "simulated": true,
            "is_search_feed": true,
            "aweme_id": "sim_aweme_next"
        }),
        "plugin_lab.swipe_video_detail_next" => json!({
            "ok": true,
            "simulated": true,
            "is_standalone_video": true,
            "aweme_id": "sim_aweme_detail_next"
        }),
        "plugin_lab.probe_video_detail" => json!({
            "ok": true,
            "simulated": true,
            "is_standalone_video": true,
            "aweme_id": "sim_aweme_detail_probe"
        }),
        "plugin_lab.search_video_probe" => json!({
            "ok": true,
            "simulated": true,
            "is_search_feed": true,
            "aweme_id": "sim_aweme_probe"
        }),
        "plugin_lab.click_comment_btn" => json!({ "ok": true, "simulated": true, "sidebar_open": true }),
        "plugin_lab.scroll_and_collect_comments" => json!({
            "ok": true,
            "simulated": true,
            "scroll_rounds": payload.get("scroll_rounds").cloned().unwrap_or(json!(3)),
            "comment_count": 5
        }),
        "plugin_lab.reply_comment" => json!({
            "ok": true,
            "simulated": true,
            "reply_text": payload.get("reply_text").cloned().unwrap_or(json!(""))
        }),
        "plugin_lab.send_comment" => json!({ "ok": true, "simulated": true, "method": "enter_key" }),
        "plugin_lab.click_comment_avatar" => json!({
            "ok": true,
            "simulated": true,
            "url": "https://www.douyin.com/user/sim_profile"
        }),
        "plugin_lab.click_follow_btn" => json!({ "ok": true, "simulated": true, "followed": true }),
        "plugin_lab.click_dm_btn" => json!({ "ok": true, "simulated": true, "dm_open": true }),
        "plugin_lab.input_dm_text" => json!({
            "ok": true,
            "simulated": true,
            "dm_text": payload.get("dm_text").cloned().unwrap_or(json!(""))
        }),
        "plugin_lab.send_dm" => json!({ "ok": true, "simulated": true, "sent": true }),
        "plugin_lab.close_video_detail" => json!({ "ok": true, "simulated": true, "closed": true }),
        "plugin_lab.close_browser" => json!({ "ok": true, "simulated": true, "closed": true }),
        "network.hook.enable" => json!({ "enabled": true, "simulated": true, "patterns": payload.get("patterns").cloned() }),
        "network.hook.disable" => json!({ "enabled": false, "simulated": true }),
        "network.hook.status" => json!({ "enabled": true, "simulated": true }),
        _ => json!({ "ok": true, "simulated": true, "action": action }),
    }
}

async fn emit_network_captured(
    write: &Arc<Mutex<futures_util::stream::SplitSink<tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>, Message>>>,
    url: &str,
    body: Value,
) {
    let event = BridgeMessage {
        v: PROTOCOL_VERSION,
        msg_type: MessageType::Event,
        id: uuid::Uuid::new_v4().to_string(),
        ts: now_ms(),
        platform: Some("douyin".into()),
        action: "network.captured".into(),
        payload: json!({ "url": url, "body": body }),
    };
    let text = serde_json::to_string(&event).unwrap_or_default();
    let mut guard = write.lock().await;
    let _ = guard.send(Message::Text(text)).await;
}

async fn handle_command(
    command: BridgeMessage,
    write: &Arc<Mutex<futures_util::stream::SplitSink<tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>, Message>>>,
    state: &Arc<Mutex<MockState>>,
) {
    let action = command.action.as_str();
    info!("mock handle {action}");

    let side_effects = {
        let mut st = state.lock().await;
        if action == "network.hook.enable" {
            st.hook_enabled = true;
        }
        if action == "network.hook.disable" {
            st.hook_enabled = false;
        }

        let mut emit_search = false;
        let mut emit_comment: Option<String> = None;

        if st.hook_enabled && action == "plugin_lab.swipe_page" {
            emit_search = true;
        }

        if st.hook_enabled
            && (action == "plugin_lab.scroll_and_collect_comments"
                || action == "plugin_lab.open_browser")
        {
            let aweme = extract_aweme_from_payload(&command.payload)
                .or_else(|| {
                    command
                        .payload
                        .get("url")
                        .and_then(|v| v.as_str())
                        .and_then(aweme_from_url)
                })
                .or_else(|| st.last_aweme.clone())
                .unwrap_or_else(|| SIM_VIDEO_IDS[0].to_string());
            st.last_aweme = Some(aweme.clone());
            st.comment_batch += 1;
            emit_comment = Some(aweme);
        }

        (emit_search, emit_comment, st.comment_batch)
    };

    if side_effects.0 {
        emit_network_captured(
            write,
            "https://www.douyin.com/aweme/v1/web/general/search/single/?aid=6383",
            search_capture_body(),
        )
        .await;
    }

    if let Some(aweme) = &side_effects.1 {
        emit_network_captured(
            write,
            &format!("https://www.douyin.com/aweme/v1/web/comment/list/?aid=6383&aweme_id={aweme}"),
            comment_capture_body(aweme, side_effects.2),
        )
        .await;
    }

    let data = mock_lab_data(action, &command.payload);
    let response = command_result(&command, data);
    {
        let mut guard = write.lock().await;
        let _ = guard.send(Message::Text(response)).await;
    }
}

pub async fn run_mock_extension(ws_url: &str) -> Result<(), String> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,mock_extension=info".into()),
        )
        .init();

    info!("mock extension connecting to {ws_url}");
    let (ws, _) = connect_async(ws_url)
        .await
        .map_err(|err| format!("ws connect failed: {err}"))?;

    let (write, mut read) = ws.split();
    let write = Arc::new(Mutex::new(write));
    let state = Arc::new(Mutex::new(MockState::new()));

    let connected = BridgeMessage {
        v: PROTOCOL_VERSION,
        msg_type: MessageType::Event,
        id: uuid::Uuid::new_v4().to_string(),
        ts: now_ms(),
        platform: Some("douyin".into()),
        action: "bridge.connected".into(),
        payload: json!({ "extensionVersion": "mock-simulate", "simulated": true }),
    };
    {
        let mut guard = write.lock().await;
        guard
            .send(Message::Text(serde_json::to_string(&connected).unwrap_or_default()))
            .await
            .map_err(|err| err.to_string())?;
    }
    info!("mock extension connected");

    while let Some(msg) = read.next().await {
        match msg {
            Ok(Message::Text(text)) => {
                let parsed: BridgeMessage = match serde_json::from_str(&text) {
                    Ok(v) => v,
                    Err(err) => {
                        warn!("invalid message: {err}");
                        continue;
                    }
                };

                if parsed.msg_type == MessageType::Ping {
                    let pong = BridgeMessage::pong_from(&parsed);
                    let mut guard = write.lock().await;
                    let _ = guard
                        .send(Message::Text(serde_json::to_string(&pong).unwrap_or_default()))
                        .await;
                    continue;
                }

                if parsed.msg_type == MessageType::Command {
                    handle_command(parsed, &write, &state).await;
                }
            }
            Ok(Message::Ping(payload)) => {
                let mut guard = write.lock().await;
                let _ = guard.send(Message::Pong(payload)).await;
            }
            Ok(Message::Close(_)) | Err(_) => break,
            _ => {}
        }
    }

    info!("mock extension disconnected");
    Ok(())
}
