import { type BridgeMessage } from "../shared/protocol";
import { log, warn, error } from "../shared/logger";
import { extensionVersion, extensionBuildId } from "../shared/runtime";
import { CONTENT_MESSAGE } from "../shared/constants";
import { routeCommandToTab } from "./command-router";
import { isPluginLabBackgroundAction, runPluginLabBackgroundCommand } from "../plugin-lab";
import { clearLabSession } from "../plugin-lab/lab-context";

log("service worker boot", extensionVersion(), extensionBuildId());

const OFFSCREEN_URL = "src/offscreen/offscreen.html";
const PLATFORM_TAB_PATTERNS = [
  "https://www.douyin.com/*",
  "https://*.douyin.com/*",
  "https://www.xiaohongshu.com/*",
  "https://*.xiaohongshu.com/*",
  "https://www.kuaishou.com/*",
  "https://*.kuaishou.com/*",
];
const KEEPALIVE_ALARM = "huoke-keepalive";
const BRIDGE_PORT = "huoke-bridge";

let bridgeState: "connected" | "connecting" | "disconnected" = "disconnected";
let wsUrl = "ws://127.0.0.1:18766/ws";
let lastWsError = "";
let offscreenReady: Promise<void> | null = null;
let bridgePort: chrome.runtime.Port | null = null;

function updateBadge(state: typeof bridgeState) {
  if (state === "connected") {
    chrome.action.setBadgeBackgroundColor({ color: "#0f766e" });
    chrome.action.setBadgeText({ text: "OK" });
    return;
  }
  chrome.action.setBadgeBackgroundColor({ color: "#b91c1c" });
  chrome.action.setBadgeText({ text: state === "connecting" ? "…" : "!" });
}

async function hasOffscreenDocument(): Promise<boolean> {
  if (!chrome.runtime.getContexts) return false;
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT" as chrome.runtime.ContextType],
  });
  return contexts.some((ctx) => ctx.documentUrl?.includes("offscreen"));
}

async function ensureOffscreenDocument() {
  if (await hasOffscreenDocument()) return;
  if (offscreenReady) {
    await offscreenReady;
    return;
  }

  offscreenReady = chrome.offscreen
    .createDocument({
      url: OFFSCREEN_URL,
      reasons: [chrome.offscreen.Reason.WORKERS],
      justification: "Maintain WebSocket connection to Huoke local-service",
    })
    .catch((err: Error) => {
      if (err.message.includes("Only a single offscreen")) return;
      throw err;
    })
    .then(() => undefined);

  await offscreenReady;
  offscreenReady = null;
}

async function queryOffscreenState() {
  try {
    await ensureOffscreenDocument();
    const res = await chrome.runtime.sendMessage({ type: "huoke:offscreen-get-state" });
    if (res?.state) {
      bridgeState = res.state;
      wsUrl = res.wsUrl ?? wsUrl;
      updateBadge(bridgeState);
    }
  } catch {
    bridgeState = "disconnected";
    updateBadge(bridgeState);
  }
}

function setupKeepAliveAlarm() {
  chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 1 });
}

let alarmListenerReady = false;

function ensureAlarmListener() {
  if (alarmListenerReady) return;
  alarmListenerReady = true;
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name !== KEEPALIVE_ALARM) return;
    void bootstrapBridge();
  });
}

async function bootstrapBridge() {
  try {
    await ensureOffscreenDocument();
    await queryOffscreenState();
  } catch (err) {
    error("bootstrapBridge failed", err);
    bridgeState = "disconnected";
    updateBadge(bridgeState);
  }
}

async function reloadPlatformTabs() {
  const tabs = await chrome.tabs.query({ url: PLATFORM_TAB_PATTERNS });
  for (const tab of tabs) {
    if (!tab.id) continue;
    try {
      await chrome.tabs.reload(tab.id);
    } catch (err) {
      warn("failed to reload platform tab", tab.id, err);
    }
  }
  if (tabs.length > 0) {
    log("reloaded platform tabs after extension update", tabs.length);
  }
}

function forwardToOffscreen(event: BridgeMessage) {
  if (bridgePort) {
    bridgePort.postMessage({ type: "ws-send", event });
    return;
  }
  chrome.runtime.sendMessage({ type: "huoke:ws-send", event }).catch(() => {
    void bootstrapBridge();
  });
}

async function runCommand(command: BridgeMessage): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  if (command.action === "huoke.extension.reload") {
    chrome.runtime.reload();
    return { ok: true, data: { reloaded: true } };
  }

  if (command.action === "huoke.runtime.init") {
    try {
      await clearLabSession();
      if (bridgePort) {
        bridgePort.disconnect();
        bridgePort = null;
      }
      await ensureOffscreenDocument();
      await chrome.runtime.sendMessage({ type: "huoke:offscreen-reconnect" });
      await queryOffscreenState();
      return { ok: true, data: { reinitialized: true, lab_session_cleared: true } };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ok: false, error: msg };
    }
  }

  if (command.action === "huoke.diag.tabs") {
    try {
      const tabs = await chrome.tabs.query({
        url: ["https://www.douyin.com/*", "https://*.douyin.com/*"],
      });
      const rows = [];
      for (const tab of tabs.slice(0, 5)) {
        if (!tab.id) continue;
        let probe: unknown = null;
        let ping: unknown = null;
        let probeError: string | null = null;
        let pingError: string | null = null;
        try {
          const [result] = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: () => ({ href: location.href, title: document.title }),
          });
          probe = result.result;
        } catch (err) {
          probeError = err instanceof Error ? err.message : String(err);
        }
        try {
          ping = await chrome.tabs.sendMessage(tab.id, { type: "huoke:ping" });
        } catch (err) {
          pingError = err instanceof Error ? err.message : String(err);
        }
        rows.push({
          id: tab.id,
          url: tab.url,
          active: tab.active,
          probe,
          probeError,
          ping,
          pingError,
        });
      }
      return { ok: true, data: { count: tabs.length, tabs: rows } };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ok: false, error: msg };
    }
  }

  if (isPluginLabBackgroundAction(command.action)) {
    try {
      const data = await runPluginLabBackgroundCommand(command);
      return { ok: true, data };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ok: false, error: msg };
    }
  }

  try {
    const data = await routeCommandToTab(command);
    return { ok: true, data };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, error: msg };
  }
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== BRIDGE_PORT) return;
  bridgePort = port;
  log("offscreen bridge port connected");

  port.onMessage.addListener((message) => {
    if (message?.type === "run-command" && message.command) {
      void runCommand(message.command as BridgeMessage).then((result) => {
        port.postMessage({
          type: "run-command-result",
          requestId: message.requestId,
          ...result,
        });
      });
    }
  });

  port.onDisconnect.addListener(() => {
    if (bridgePort === port) {
      bridgePort = null;
      log("offscreen bridge port disconnected");
    }
  });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "huoke:offscreen-state") {
    bridgeState = message.state ?? "disconnected";
    wsUrl = message.wsUrl ?? wsUrl;
    lastWsError = message.lastError ?? "";
    updateBadge(bridgeState);
    return false;
  }

  if (message?.type === "huoke:run-command" && message.command) {
    const command = message.command as BridgeMessage;
    const timeoutMs = command.action === "plugin_lab.open_browser" ? 12_000 : 50_000;
    let responded = false;
    const timer = setTimeout(() => {
      if (responded) return;
      responded = true;
      sendResponse({ ok: false, error: `background command timeout: ${command.action}` });
    }, timeoutMs);

    void runCommand(command)
      .then((result) => {
        if (responded) return;
        responded = true;
        clearTimeout(timer);
        sendResponse(result);
      })
      .catch((err) => {
        if (responded) return;
        responded = true;
        clearTimeout(timer);
        sendResponse({ ok: false, error: err instanceof Error ? err.message : String(err) });
      });
    return true;
  }

  if (message?.type === CONTENT_MESSAGE && message.event) {
    forwardToOffscreen(message.event as BridgeMessage);
    return false;
  }

  if (message?.type === "huoke:get-state") {
    sendResponse({ state: bridgeState, wsUrl, lastError: lastWsError });
    void queryOffscreenState();
    return true;
  }

  if (message?.type === "huoke:reconnect") {
    void (async () => {
      try {
        await ensureOffscreenDocument();
        await chrome.runtime.sendMessage({ type: "huoke:offscreen-reconnect" });
        await queryOffscreenState();
        sendResponse({ ok: true });
      } catch (err) {
        sendResponse({ ok: false, error: err instanceof Error ? err.message : String(err) });
      }
    })();
    return true;
  }

  if (message?.type === "huoke:noop") {
    sendResponse({ ok: true });
    return true;
  }

  return false;
});

chrome.runtime.onStartup.addListener(() => {
  ensureAlarmListener();
  void bootstrapBridge();
});

chrome.runtime.onInstalled.addListener(() => {
  ensureAlarmListener();
  setupKeepAliveAlarm();
  void reloadPlatformTabs();
  void bootstrapBridge();
});

self.addEventListener("unhandledrejection", (event) => {
  error("unhandled rejection", event.reason);
});

try {
  ensureAlarmListener();
  setupKeepAliveAlarm();
  void bootstrapBridge();
} catch (err) {
  error("service worker bootstrap failed", err);
}
