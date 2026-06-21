import { DEFAULT_WS_URL, createMessage, type BridgeMessage } from "../shared/protocol";
import { log, warn, error } from "../shared/logger";
import { extensionVersion, extensionBuildId } from "../shared/runtime";

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const HEARTBEAT_MS = 15000;
const BRIDGE_PORT = "huoke-bridge";
const OUTBOUND_QUEUE_MAX = 128;

let socket: WebSocket | null = null;
let reconnectAttempt = 0;
let heartbeatTimer: number | null = null;
let wsUrl = DEFAULT_WS_URL;
let bridgePort: chrome.runtime.Port | null = null;
let requestSeq = 0;
let lastWsError = "";
let reconnectTimer: number | null = null;
let intentionalClose = false;
const outboundQueue: BridgeMessage[] = [];

function connectionState(): "connected" | "connecting" | "disconnected" {
  if (!socket) return "disconnected";
  if (socket.readyState === WebSocket.OPEN) return "connected";
  if (socket.readyState === WebSocket.CONNECTING) return "connecting";
  return "disconnected";
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function notifyState() {
  chrome.runtime.sendMessage({
    type: "huoke:offscreen-state",
    state: connectionState(),
    wsUrl,
    lastError: lastWsError || undefined,
  }).catch(() => {
    /* background may be asleep */
  });
}

function clearHeartbeat() {
  if (heartbeatTimer !== null) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function startHeartbeat() {
  clearHeartbeat();
  heartbeatTimer = setInterval(() => {
    sendWs(createMessage({ type: "ping", action: "ping", payload: {} }));
  }, HEARTBEAT_MS) as unknown as number;
}

function flushOutboundQueue() {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  while (outboundQueue.length > 0) {
    const message = outboundQueue.shift();
    if (!message) break;
    socket.send(JSON.stringify(message));
  }
}

function enqueueOrSendWs(message: BridgeMessage) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
    return;
  }
  if (outboundQueue.length >= OUTBOUND_QUEUE_MAX) {
    outboundQueue.shift();
  }
  outboundQueue.push(message);
  const state = socket?.readyState;
  if (state !== WebSocket.CONNECTING && state !== WebSocket.OPEN) {
    connect(wsUrl);
  }
}

function sendWs(message: BridgeMessage) {
  enqueueOrSendWs(message);
}

function clearReconnectTimer() {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function scheduleReconnect() {
  if (intentionalClose || reconnectTimer !== null) return;
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempt, RECONNECT_MAX_MS);
  reconnectAttempt += 1;
  // 用 log 而非 warn，避免 Chrome 扩展页把正常重连标成「错误」
  if (reconnectAttempt >= 5) {
    warn(`ws 重连第 ${reconnectAttempt} 次（${delay}ms 后）— 请确认 local-service 已启动（端口 18766）`);
  } else {
    log(`ws 重连第 ${reconnectAttempt} 次（${delay}ms 后）`);
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect(wsUrl);
  }, delay) as unknown as number;
}

function ensureBridgePort(): chrome.runtime.Port {
  if (bridgePort) return bridgePort;
  const port = chrome.runtime.connect({ name: BRIDGE_PORT });
  bridgePort = port;
  port.onDisconnect.addListener(() => {
    if (bridgePort === port) bridgePort = null;
  });
  return port;
}

async function runCommandViaPort(command: BridgeMessage): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const port = ensureBridgePort();
      const requestId = `req-${Date.now()}-${requestSeq += 1}`;
      const result = await new Promise<{ ok: boolean; data?: unknown; error?: string }>((resolve, reject) => {
        const timer = setTimeout(() => {
          port.onMessage.removeListener(onMessage);
          reject(new Error(`background command timeout: ${command.action}`));
        }, 55000);

        function onMessage(message: { type?: string; requestId?: string; ok?: boolean; data?: unknown; error?: string }) {
          if (message?.type !== "run-command-result" || message.requestId !== requestId) return;
          clearTimeout(timer);
          port.onMessage.removeListener(onMessage);
          resolve({ ok: Boolean(message.ok), data: message.data, error: message.error });
        }

        port.onMessage.addListener(onMessage);
        port.postMessage({ type: "run-command", requestId, command });
      });
      return result;
    } catch (err) {
      bridgePort = null;
      if (attempt === 3) throw err;
      await sleep(400 * (attempt + 1));
    }
  }
  return { ok: false, error: "command failed" };
}

function closeSocket(opts?: { intentional?: boolean }) {
  clearHeartbeat();
  clearReconnectTimer();
  if (!socket) return;
  intentionalClose = Boolean(opts?.intentional);
  try {
    socket.onclose = null;
    socket.onerror = null;
    socket.onmessage = null;
    socket.onopen = null;
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.close(1000, "reconnect");
    }
  } catch {
    /* ignore */
  }
  socket = null;
  notifyState();
}

function connect(url = DEFAULT_WS_URL) {
  try {
    wsUrl = url;
    const state = socket?.readyState;
    if (state === WebSocket.OPEN && socket?.url === url) {
      return;
    }
    // 正在连接时不要打断，否则会造成 connect → close → reconnect 循环
    if (state === WebSocket.CONNECTING) {
      return;
    }
    closeSocket();

    socket = new WebSocket(url);
    notifyState();

    socket.addEventListener("open", () => {
      reconnectAttempt = 0;
      clearReconnectTimer();
      lastWsError = "";
      log("offscreen connected to local-service", url);
      ensureBridgePort();
      notifyState();
      startHeartbeat();
      sendWs(
        createMessage({
          type: "event",
          action: "bridge.connected",
          payload: { extensionVersion: extensionVersion(), buildId: extensionBuildId() },
        }),
      );
      flushOutboundQueue();
    });

    socket.addEventListener("message", async (event) => {
      let message: BridgeMessage;
      try {
        message = JSON.parse(String(event.data)) as BridgeMessage;
      } catch (err) {
        error("invalid ws message", err);
        return;
      }

      if (message.type === "pong" || message.action === "pong") {
        return;
      }

      if (message.type === "command") {
        try {
          const response = await runCommandViaPort(message);
          if (response.ok) {
            sendWs(
              createMessage({
                type: "result",
                id: message.id,
                platform: message.platform,
                action: message.action,
                payload: { ok: true, data: response.data },
              }),
            );
          } else {
            sendWs(
              createMessage({
                type: "error",
                id: message.id,
                platform: message.platform,
                action: message.action,
                payload: { ok: false, error: response.error ?? "command failed" },
              }),
            );
          }
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          sendWs(
            createMessage({
              type: "error",
              id: message.id,
              platform: message.platform,
              action: message.action,
              payload: { ok: false, error: msg },
            }),
          );
        }
      }
    });

    socket.addEventListener("close", (event) => {
      clearHeartbeat();
      socket = null;
      notifyState();
      if (intentionalClose) {
        intentionalClose = false;
        return;
      }
      // 服务端因「另一个插件实例上线」踢掉本连接 — 不要重连，否则会互相抢占
      if (event.code === 4000) {
        lastWsError = "已有其它插件实例连接 local-service，本 offscreen 已停止重连";
        warn(lastWsError);
        return;
      }
      if (event.code === 1000 && event.reason === "reconnect") {
        return;
      }
      scheduleReconnect();
    });

    socket.addEventListener("error", (event) => {
      lastWsError = "WebSocket 连接失败，请确认 local-service 已启动（npm run dev，端口 18766）";
      error("websocket error", event);
      notifyState();
    });
  } catch (err) {
    lastWsError = err instanceof Error ? err.message : String(err);
    error("offscreen connect failed", err);
    notifyState();
    scheduleReconnect();
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "huoke:ws-send" && message.event) {
    sendWs(message.event as BridgeMessage);
    sendResponse({ ok: true });
    return true;
  }
  if (message?.type === "huoke:offscreen-get-state") {
    sendResponse({ state: connectionState(), wsUrl });
    return true;
  }
  if (message?.type === "huoke:offscreen-reconnect") {
    closeSocket({ intentional: true });
    reconnectAttempt = 0;
    connect(wsUrl);
    sendResponse({ ok: true });
    return true;
  }
  return false;
});

log("offscreen bridge boot");
ensureBridgePort();
connect();
