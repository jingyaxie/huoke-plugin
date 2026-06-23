use std::collections::HashMap;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

use axum::extract::ws::{Message, WebSocket};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::{broadcast, mpsc, Mutex};
use tracing::{info, warn};
use uuid::Uuid;

use crate::protocol::{parse_message, BridgeMessage, MessageType};

#[derive(Clone)]
pub struct BridgeHub {
    inner: Arc<HubInner>,
}

struct HubInner {
    clients: Mutex<Vec<BridgeClient>>,
    active_extension_id: Mutex<Option<String>>,
    extension_client_count: AtomicUsize,
    connected_extension_version: Mutex<Option<String>>,
    connected_extension_build_id: Mutex<Option<String>>,
    events: broadcast::Sender<BridgeMessage>,
    pending: Mutex<HashMap<String, mpsc::Sender<BridgeMessage>>>,
}

struct BridgeClient {
    id: String,
    sender: mpsc::UnboundedSender<Message>,
    is_extension: bool,
}

impl BridgeHub {
    pub fn new() -> Self {
        let (events, _) = broadcast::channel(512);
        Self {
            inner: Arc::new(HubInner {
                clients: Mutex::new(Vec::new()),
                active_extension_id: Mutex::new(None),
                extension_client_count: AtomicUsize::new(0),
                connected_extension_version: Mutex::new(None),
                connected_extension_build_id: Mutex::new(None),
                events,
                pending: Mutex::new(HashMap::new()),
            }),
        }
    }

    pub fn client_count(&self) -> usize {
        self.extension_client_count()
    }

    pub fn total_client_count(&self) -> usize {
        self.inner
            .clients
            .try_lock()
            .map(|guard| guard.len())
            .unwrap_or(0)
    }

    pub fn extension_client_count(&self) -> usize {
        self.inner
            .extension_client_count
            .load(Ordering::Relaxed)
    }

    pub fn connected_extension_version(&self) -> Option<String> {
        self.inner
            .connected_extension_version
            .try_lock()
            .ok()
            .and_then(|guard| guard.clone())
    }

    pub fn connected_extension_build_id(&self) -> Option<String> {
        self.inner
            .connected_extension_build_id
            .try_lock()
            .ok()
            .and_then(|guard| guard.clone())
    }

    pub fn subscribe_events(&self) -> broadcast::Receiver<BridgeMessage> {
        self.inner.events.subscribe()
    }

    pub async fn broadcast_command(&self, action: &str, payload: serde_json::Value) -> bool {
        let msg = BridgeMessage::new(MessageType::Command, action, payload);
        self.publish(msg.clone());
        self.send_to_extensions(Message::Text(serde_json::to_string(&msg).unwrap_or_default()))
            .await
    }

    pub async fn request_command(
        &self,
        action: &str,
        payload: serde_json::Value,
        timeout: std::time::Duration,
    ) -> Result<serde_json::Value, String> {
        if self.extension_client_count() == 0 {
            return Err(
                "no extension connected — load extension/dist and ensure badge shows OK".into(),
            );
        }

        let msg = BridgeMessage::new(MessageType::Command, action, payload);
        let command_id = msg.id.clone();
        let (tx, mut rx) = mpsc::channel(16);

        {
            let mut pending = self.inner.pending.lock().await;
            pending.insert(command_id.clone(), tx);
        }

        self.publish(msg.clone());
        let queued = self
            .send_to_extensions(Message::Text(serde_json::to_string(&msg).unwrap_or_default()))
            .await;
        if !queued {
            let mut pending = self.inner.pending.lock().await;
            pending.remove(&command_id);
            return Err("failed to queue command to extension".into());
        }

        let deadline = tokio::time::Instant::now() + timeout;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() {
                break;
            }

            match tokio::time::timeout(remaining, rx.recv()).await {
                Ok(Some(result)) => match extract_command_result(&result) {
                    CommandOutcome::Success(data) => {
                        let mut pending = self.inner.pending.lock().await;
                        pending.remove(&command_id);
                        return Ok(data);
                    }
                    CommandOutcome::Failure(err) => {
                        let mut pending = self.inner.pending.lock().await;
                        pending.remove(&command_id);
                        return Err(err);
                    }
                    CommandOutcome::Ignore => {}
                },
                _ => break,
            }
        }

        let mut pending = self.inner.pending.lock().await;
        pending.remove(&command_id);

        Err(format!("command timeout: {action}"))
    }

    fn publish(&self, msg: BridgeMessage) {
        let _ = self.inner.events.send(msg);
    }

    async fn register(&self, client: BridgeClient) {
        let mut guard = self.inner.clients.lock().await;
        guard.push(client);
        let active = self.inner.active_extension_id.lock().await.clone();
        self.sync_extension_count(&guard, active.as_deref());
    }

    fn sync_extension_count(&self, clients: &[BridgeClient], active: Option<&str>) {
        let count = if active.is_some() && clients.iter().any(|c| c.is_extension) {
            1
        } else {
            0
        };
        self.inner
            .extension_client_count
            .store(count, Ordering::Relaxed);
    }

    /// 服务启动后清空连接表（新进程一般为空）。
    pub fn reset_on_boot(&self) {
        if let Ok(mut guard) = self.inner.clients.try_lock() {
            guard.clear();
        }
        if let Ok(mut active) = self.inner.active_extension_id.try_lock() {
            *active = None;
        }
        if let Ok(mut version) = self.inner.connected_extension_version.try_lock() {
            *version = None;
        }
        if let Ok(mut build_id) = self.inner.connected_extension_build_id.try_lock() {
            *build_id = None;
        }
        self.inner.extension_client_count.store(0, Ordering::Relaxed);
        info!("bridge hub reset on boot");
    }

    /// 取消所有进行中的插件命令，使等待中的 `request_command` 尽快失败退出。
    pub async fn cancel_pending_commands(&self) -> usize {
        let mut pending = self.inner.pending.lock().await;
        let dropped = pending.len();
        pending.clear();
        dropped
    }

    /// 运行环境重新初始化：取消未完成的命令、刷新连接计数。
    pub async fn reset_runtime(&self) {
        let dropped = self.cancel_pending_commands().await;

        let mut guard = self.inner.clients.lock().await;
        let extension_count = guard.iter().filter(|c| c.is_extension).count();
        self.inner
            .extension_client_count
            .store(extension_count, Ordering::Relaxed);
        drop(guard);

        if dropped > 0 {
            warn!("bridge hub cleared {dropped} pending command(s)");
        }
        info!("bridge hub runtime reset (extension_clients={extension_count})");
    }

    fn kick_client(client: &BridgeClient) {
        let frame = axum::extract::ws::CloseFrame {
            code: 4000,
            reason: "replaced".into(),
        };
        let _ = client.sender.send(Message::Close(Some(frame)));
    }

    /// 新插件握手成功后：关闭并移除其它所有 WS，只保留当前这一条。
    /// 若已有活跃插件连接仍在线，拒绝重复握手，避免任务执行中 WS 被抢占。
    async fn adopt_single_extension(&self, client_id: &str) {
        {
            let active = self.inner.active_extension_id.lock().await;
            if active.as_deref() == Some(client_id) {
                let mut guard = self.inner.clients.lock().await;
                if let Some(client) = guard.iter_mut().find(|c| c.id == client_id) {
                    client.is_extension = true;
                }
                self.sync_extension_count(&guard, Some(client_id));
                return;
            }

            if let Some(active_id) = active.as_deref() {
                let guard = self.inner.clients.lock().await;
                if guard
                    .iter()
                    .any(|c| c.id == active_id && c.is_extension)
                {
                    drop(guard);
                    let mut guard = self.inner.clients.lock().await;
                    if let Some(dup) = guard.iter().find(|c| c.id == client_id) {
                        Self::kick_client(dup);
                    }
                    guard.retain(|c| c.id != client_id);
                    info!(
                        "bridge: ignored duplicate extension handshake from {client_id}, keeping active {active_id}"
                    );
                    return;
                }
            }
        }

        let mut guard = self.inner.clients.lock().await;
        let mut kicked = 0usize;

        for client in guard.iter() {
            if client.id != client_id {
                Self::kick_client(client);
                kicked += 1;
            }
        }

        guard.retain(|c| c.id == client_id);
        if let Some(client) = guard.iter_mut().find(|c| c.id == client_id) {
            client.is_extension = true;
        }

        *self.inner.active_extension_id.lock().await = Some(client_id.to_string());
        self.sync_extension_count(&guard, Some(client_id));

        if kicked > 0 {
            info!("bridge cleanup: kept extension {client_id}, closed {kicked} stale ws client(s)");
        }
    }

    async fn unregister(&self, client_id: &str) {
        let mut guard = self.inner.clients.lock().await;
        guard.retain(|item| item.id != client_id);
        let mut active = self.inner.active_extension_id.lock().await;
        if active.as_deref() == Some(client_id) {
            *active = None;
            *self.inner.connected_extension_version.lock().await = None;
            *self.inner.connected_extension_build_id.lock().await = None;
        }
        self.sync_extension_count(&guard, active.as_deref());
    }

    async fn send_to_extensions(&self, message: Message) -> bool {
        let active_id = self.inner.active_extension_id.lock().await.clone();
        let Some(active_id) = active_id else {
            return false;
        };

        let mut guard = self.inner.clients.lock().await;
        let Some(client) = guard.iter().find(|c| c.id == active_id && c.is_extension) else {
            *self.inner.active_extension_id.lock().await = None;
            self.sync_extension_count(&guard, None);
            return false;
        };

        match client.sender.send(message) {
            Ok(()) => true,
            Err(_) => {
                guard.retain(|c| c.id != active_id);
                *self.inner.active_extension_id.lock().await = None;
                self.sync_extension_count(&guard, None);
                false
            }
        }
    }

    pub async fn handle_socket(self, socket: WebSocket) {
        let (mut ws_tx, mut ws_rx) = socket.split();
        let (client_tx, mut client_rx) = tokio::sync::mpsc::unbounded_channel();
        let client_id = Uuid::new_v4().to_string();
        self.register(BridgeClient {
            id: client_id.clone(),
            sender: client_tx.clone(),
            is_extension: false,
        })
        .await;
        info!(
            "ws client connected id={client_id} (total={}, extension={})",
            self.total_client_count(),
            self.extension_client_count()
        );

        loop {
            tokio::select! {
                Some(outgoing) = client_rx.recv() => {
                    let is_close = matches!(&outgoing, Message::Close(_));
                    if ws_tx.send(outgoing).await.is_err() {
                        break;
                    }
                    if is_close {
                        break;
                    }
                }
                incoming = ws_rx.next() => {
                    match incoming {
                        Some(Ok(Message::Text(text))) => {
                            self.handle_text(&text, &client_id, &client_tx).await;
                        }
                        Some(Ok(Message::Ping(payload))) => {
                            let _ = ws_tx.send(Message::Pong(payload)).await;
                        }
                        Some(Ok(Message::Close(_))) | None => break,
                        Some(Err(err)) => {
                            warn!("ws error: {err}");
                            break;
                        }
                        _ => {}
                    }
                }
            }
        }

        self.unregister(&client_id).await;
        info!(
            "ws client disconnected id={client_id} (total={}, extension={})",
            self.total_client_count(),
            self.extension_client_count()
        );
    }

    async fn handle_text(&self, text: &str, client_id: &str, client_tx: &mpsc::UnboundedSender<Message>) {
        let msg = match parse_message(text) {
            Ok(msg) => msg,
            Err(err) => {
                warn!("invalid message: {err}");
                return;
            }
        };

        match msg.msg_type {
            MessageType::Ping => {
                let pong = crate::protocol::BridgeMessage::pong_from(&msg);
                let _ = client_tx.send(Message::Text(serde_json::to_string(&pong).unwrap_or_default()));
            }
            MessageType::Event => {
                if msg.action == "bridge.connected" {
                    let version = msg
                        .payload
                        .get("extensionVersion")
                        .and_then(|v| v.as_str())
                        .map(str::to_string);
                    let build_id = msg
                        .payload
                        .get("buildId")
                        .and_then(|v| v.as_str())
                        .map(str::to_string);
                    let mut version_guard = self.inner.connected_extension_version.lock().await;
                    *version_guard = version.clone();
                    let mut build_guard = self.inner.connected_extension_build_id.lock().await;
                    *build_guard = build_id.clone();
                    self.adopt_single_extension(client_id).await;
                    info!(
                        "extension ready id={client_id} version={:?} build={:?}",
                        version, build_id
                    );
                }
                info!("event {} platform={:?}", msg.action, msg.platform);
                self.publish(msg);
            }
            MessageType::Result | MessageType::Error => {
                info!("{} {}", msg.msg_type_as_str(), msg.action);
                let tx = {
                    let mut pending = self.inner.pending.lock().await;
                    if matches!(extract_command_result(&msg), CommandOutcome::Success(_)) {
                        pending.remove(&msg.id)
                    } else {
                        pending.get(&msg.id).cloned()
                    }
                };
                if let Some(tx) = tx {
                    let _ = tx.send(msg.clone()).await;
                }
                self.publish(msg);
            }
            _ => {
                warn!("unexpected message type from extension: {:?}", msg.msg_type);
            }
        }
    }
}

trait MessageTypeLabel {
    fn msg_type_as_str(&self) -> &'static str;
}

enum CommandOutcome {
    Success(serde_json::Value),
    Failure(String),
    Ignore,
}

fn extract_command_result(message: &BridgeMessage) -> CommandOutcome {
    match message.msg_type {
        MessageType::Result => {
            if message.payload.get("ok").and_then(|v| v.as_bool()) == Some(false) {
                let err = message
                    .payload
                    .get("error")
                    .and_then(|v| v.as_str())
                    .unwrap_or("command failed");
                return CommandOutcome::Failure(err.to_string());
            }
            CommandOutcome::Success(
                message
                    .payload
                    .get("data")
                    .cloned()
                    .unwrap_or_else(|| message.payload.clone()),
            )
        }
        MessageType::Error => {
            let err = message
                .payload
                .get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("command failed");
            CommandOutcome::Failure(err.to_string())
        }
        _ => CommandOutcome::Ignore,
    }
}

impl MessageTypeLabel for BridgeMessage {
    fn msg_type_as_str(&self) -> &'static str {
        match self.msg_type {
            MessageType::Command => "command",
            MessageType::Result => "result",
            MessageType::Event => "event",
            MessageType::Error => "error",
            MessageType::Ping => "ping",
            MessageType::Pong => "pong",
        }
    }
}
