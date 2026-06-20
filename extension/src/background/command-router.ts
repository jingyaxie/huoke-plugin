import type { BridgeMessage } from "../shared/protocol";
import { isPluginLabBackgroundAction } from "../plugin-lab/background-actions";
import { resolveLabTargetTab } from "../plugin-lab/resolve-lab-tab";
import { log, warn } from "../shared/logger";
import { extensionVersion } from "../shared/runtime";

const DOUYIN_URL_PATTERNS = ["https://www.douyin.com/*", "https://*.douyin.com/*"];

function isDouyinUrl(url?: string | null): boolean {
  if (!url) return false;
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host === "www.douyin.com" || host.endsWith(".douyin.com");
  } catch {
    return /douyin\.com/i.test(url);
  }
}

async function sleep(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function focusTab(tab: chrome.tabs.Tab) {
  if (!tab.id || tab.windowId === undefined) return;
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
}

async function resolveTargetTab(command: BridgeMessage): Promise<chrome.tabs.Tab> {
  const lastFocused = await chrome.windows.getLastFocused({ populate: true });
  const activeInFocused = lastFocused.tabs?.find((tab) => tab.active);
  if (activeInFocused?.id && isDouyinUrl(activeInFocused.url)) {
    return activeInFocused;
  }

  const douyinTabs = await chrome.tabs.query({ url: DOUYIN_URL_PATTERNS });
  if (douyinTabs.length === 0) {
    throw new Error("no douyin tab open — open https://www.douyin.com in Chrome first");
  }

  const platform = command.platform;
  if (platform === "douyin" || command.action.startsWith("douyin.")) {
    const preferred = [...douyinTabs].sort(
      (a, b) => (b.lastAccessed ?? 0) - (a.lastAccessed ?? 0),
    )[0];
    await focusTab(preferred);
    return preferred;
  }

  const activeAny = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (activeAny[0]?.id) {
    return activeAny[0];
  }

  const fallback = douyinTabs[0];
  await focusTab(fallback);
  return fallback;
}

async function pingContentScript(tabId: number): Promise<{ ok?: boolean; version?: string } | null> {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: "huoke:ping" });
  } catch {
    return null;
  }
}

export async function ensureContentScript(tabId: number) {
  const expectedVersion = extensionVersion();

  async function waitForReady(maxAttempts = 5): Promise<boolean> {
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const pong = await pingContentScript(tabId);
      if (pong?.ok && pong.version === expectedVersion) return true;
      await sleep(attempt === 0 ? 300 : 600);
    }
    return false;
  }

  if (await waitForReady(3)) return;

  const pong = await pingContentScript(tabId);
  if (pong?.ok && pong.version !== expectedVersion) {
    warn("content script stale, reloading tab", tabId, pong.version, "expected", expectedVersion);
    await chrome.tabs.reload(tabId);
    await sleep(2500);
    if (await waitForReady(6)) return;
  }

  const manifest = typeof chrome.runtime.getManifest === "function"
    ? chrome.runtime.getManifest()
    : null;
  const warEntry = manifest?.web_accessible_resources?.[0];
  const warResources = Array.isArray(warEntry)
    ? warEntry
    : (warEntry && typeof warEntry === "object" && "resources" in warEntry
        ? warEntry.resources
        : []);
  const chunk = warResources.find(
    (file: string) => /assets\/index\.ts-[^/]+\.js$/.test(file) && !file.endsWith(".map"),
  );
  if (chunk) {
    const chunkUrl = chrome.runtime.getURL(chunk);
    warn("injecting content chunk into tab", tabId, chunk);
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        func: (url: string) => import(url),
        args: [chunkUrl],
      });
      await sleep(900);
      if (await waitForReady(5)) return;
    } catch (err) {
      warn("content chunk inject failed", err);
    }
  }

  const files = manifest?.content_scripts?.flatMap((entry) => entry.js ?? []) ?? [];
  const bootstrap = files.find((file) => file.includes("bootstrap"));
  if (bootstrap) {
    warn("injecting bootstrap into tab", tabId, bootstrap);
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: [bootstrap],
      });
      await sleep(900);
      if (await waitForReady(5)) return;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(`${msg} — reload extension/dist in chrome://extensions`);
    }
  }

  throw new Error("content script failed to start on douyin tab — reload extension/dist in chrome://extensions");
}

async function sendCommandToTab(tabId: number, command: BridgeMessage) {
  await ensureContentScript(tabId);
  return chrome.tabs.sendMessage(tabId, {
    type: "huoke:command",
    command,
  });
}

export async function routeCommandToTab(command: BridgeMessage): Promise<unknown> {
  const tab = command.action.startsWith("plugin_lab.") && !isPluginLabBackgroundAction(command.action)
    ? await resolveLabTargetTab()
    : await resolveTargetTab(command);
  if (!tab.id) {
    throw new Error("target tab has no id");
  }

  log("route command", command.action, "tab", tab.id, tab.url);

  let response: { ok?: boolean; data?: unknown; error?: string } | undefined;
  try {
    response = await sendCommandToTab(tab.id, command);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (!msg.includes("Receiving end does not exist")) {
      throw err;
    }
    warn("content script missing, reload tab and retry", tab.id);
    await chrome.tabs.reload(tab.id);
    await sleep(3500);
    response = await sendCommandToTab(tab.id, command);
  }

  if (!response?.ok) {
    throw new Error(response?.error ?? `content script failed: ${command.action}`);
  }
  return response.data;
}
