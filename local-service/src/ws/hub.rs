use std::collections::HashMap;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

use axum::extract::ws::{Message, WebSocket};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::{broadcast, mpsc, Mutex};
use tracing::{info, warn};

use crate::protocol::{parse_message, BridgeMessage, MessageType};

#[derive(Clone)]
pub struct BridgeHub {
    inner: Arc<HubInner>,
}

struct HubInner {
    clients: Mutex<Vec<ClientSender>>,
    client_count: AtomicUsize,
    events: broadcast::Sender<BridgeMessage>,
    pending: Mutex<HashMap<String, mpsc::Sender<BridgeMessage>>>,
}

type ClientSender = tokio::sync::mpsc::UnboundedSender<Message>;

impl BridgeHub {
    pub fn new() -> Self {
        let (events, _) = broadcast::channel(512);
        Self {
            inner: Arc::new(HubInner {
                clients: Mutex::new(Vec::new()),
                client_count: AtomicUsize::new(0),
                events,
                pending: Mutex::new(HashMap::new()),
            }),
        }
    }

    pub fn client_count(&self) -> usize {
        self.inner.client_count.load(Ordering::Relaxed)
    }

    pub fn subscribe_events(&self) -> broadcast::Receiver<BridgeMessage> {
        self.inner.events.subscribe()
    }

    pub async fn broadcast_command(&self, action: &str, payload: serde_json::Value) -> bool {
        let msg = BridgeMessage::new(MessageType::Command, action, payload);
        self.publish(msg.clone());
        self.send_to_all(Message::Text(serde_json::to_string(&msg).unwrap_or_default()))
            .await
    }

    pub async fn request_command(
        &self,
        action: &str,
        payload: serde_json::Value,
        timeout: std::time::Duration,
    ) -> Result<serde_json::Value, String> {
        if self.client_count() == 0 {
            return Err("no extension connected".into());
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
            .send_to_all(Message::Text(serde_json::to_string(&msg).unwrap_or_default()))
            .await;
        if !queued {
            let mut pending = self.inner.pending.lock().await;
            pending.remove(&command_id);
            return Err("failed to queue command to extension".into());
        }

        let deadline = tokio::time::Instant::now() + timeout;
        let mut last_error: Option<String> = None;

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
                        last_error = Some(err);
                    }
                    CommandOutcome::Ignore => {}
                },
                _ => break,
            }
        }

        let mut pending = self.inner.pending.lock().await;
        pending.remove(&command_id);

        Err(last_error.unwrap_or_else(|| format!("command timeout: {action}")))
    }

    fn publish(&self, msg: BridgeMessage) {
        let _ = self.inner.events.send(msg);
    }

    async fn register(&self, sender: ClientSender) {
        let mut guard = self.inner.clients.lock().await;
        guard.push(sender);
        self.inner.client_count.store(guard.len(), Ordering::Relaxed);
    }

    async fn unregister(&self, sender: &ClientSender) {
        let mut guard = self.inner.clients.lock().await;
        guard.retain(|item| !sender.same_channel(item));
        self.inner.client_count.store(guard.len(), Ordering::Relaxed);
    }

    async fn send_to_all(&self, message: Message) -> bool {
        let guard = self.inner.clients.lock().await;
        if guard.is_empty() {
            return false;
        }
        for client in guard.iter() {
            let _ = client.send(message.clone());
        }
        true
    }

    pub async fn handle_socket(self, socket: WebSocket) {
        let (mut ws_tx, mut ws_rx) = socket.split();
        let (client_tx, mut client_rx) = tokio::sync::mpsc::unbounded_channel();
        self.register(client_tx.clone()).await;
        info!("extension connected (clients={})", self.client_count());

        loop {
            tokio::select! {
                Some(outgoing) = client_rx.recv() => {
                    if ws_tx.send(outgoing).await.is_err() {
                        break;
                    }
                }
                incoming = ws_rx.next() => {
                    match incoming {
                        Some(Ok(Message::Text(text))) => {
                            self.handle_text(&text, &client_tx).await;
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

        self.unregister(&client_tx).await;
        info!("extension disconnected (clients={})", self.client_count());
    }

    async fn handle_text(&self, text: &str, client_tx: &ClientSender) {
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
