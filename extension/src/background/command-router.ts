import type { BridgeMessage } from "../shared/protocol";
import { isPluginLabBackgroundAction } from "../plugin-lab/background-actions";
import { resolveLabTabForAction, resolveLabTargetTab } from "../plugin-lab/resolve-lab-tab";
import { ensureLabCommandReady } from "../plugin-lab/lab-preflight";
import { readLabSession } from "../plugin-lab/lab-context";
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

async function resolveNetworkHookTab(): Promise<chrome.tabs.Tab> {
  const session = await readLabSession();
  if (session?.tabId) {
    try {
      const tab = await chrome.tabs.get(session.tabId);
      if (tab.id && isDouyinUrl(tab.url)) {
        await focusTab(tab);
        return tab;
      }
    } catch {
      // pinned tab closed — fall through
    }
  }
  return resolveLabTargetTab();
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

function pingVersionMatches(pongVersion?: string): boolean {
  if (!pongVersion) return false;
  const expected = extensionVersion();
  return pongVersion === expected || pongVersion.startsWith(`${expected}+`);
}

async function waitForContentScript(
  tabId: number,
  maxAttempts = 5,
): Promise<{ ok: boolean; pong: { ok?: boolean; version?: string } | null }> {
  let lastPong: { ok?: boolean; version?: string } | null = null;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    lastPong = await pingContentScript(tabId);
    if (lastPong?.ok) {
      return { ok: true, pong: lastPong };
    }
    await sleep(attempt === 0 ? 300 : 600);
  }
  return { ok: false, pong: lastPong };
}

async function injectContentScripts(tabId: number): Promise<string | null> {
  const manifest = typeof chrome.runtime.getManifest === "function"
    ? chrome.runtime.getManifest()
    : null;
  const files =
    manifest?.content_scripts
      ?.flatMap((entry) => entry.js ?? [])
      .filter((file) => file.includes("bootstrap") || file.includes("loader")) ?? [];
  if (files.length === 0) {
    return "no isolated-world content scripts in manifest";
  }

  warn("injecting content script into tab", tabId, files.join(", "));
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files,
    });
    await sleep(1200);
    const ready = await waitForContentScript(tabId, 8);
    if (ready.ok) return null;
    return "content script injected but ping failed";
  } catch (err) {
    const lastError = err instanceof Error ? err.message : String(err);
    warn("content script inject failed", lastError);
    return lastError;
  }
}

export async function ensureContentScript(tabId: number) {
  let pong = await pingContentScript(tabId);
  if (pong?.ok && pingVersionMatches(pong.version)) {
    return;
  }

  if (pong?.ok && !pingVersionMatches(pong.version)) {
    warn(
      "content script version stale, reloading tab",
      tabId,
      pong.version,
      "expected",
      extensionVersion(),
    );
    await chrome.tabs.reload(tabId);
    await sleep(2500);
    const afterReload = await waitForContentScript(tabId, 8);
    if (afterReload.ok) return;
    pong = afterReload.pong;
  }

  if (!pong?.ok) {
    const injectError = await injectContentScripts(tabId);
    if (!injectError) return;

    warn("script inject failed, reloading tab", tabId, injectError);
    await chrome.tabs.reload(tabId);
    await sleep(3000);
    const afterReload = await waitForContentScript(tabId, 8);
    if (afterReload.ok) return;
    pong = afterReload.pong;

    const retryError = await injectContentScripts(tabId);
    if (!retryError) return;
  }

  const detail = pong?.ok
    ? `ping ok but version=${pong.version ?? "unknown"}`
    : "content script not responding";
  throw new Error(
    `${detail} — open chrome://extensions, click Reload on Huoke, then refresh the douyin tab`,
  );
}

async function sendCommandToTab(tabId: number, command: BridgeMessage) {
  await ensureContentScript(tabId);
  return chrome.tabs.sendMessage(tabId, {
    type: "huoke:command",
    command,
  });
}

export async function routeCommandToTab(command: BridgeMessage): Promise<unknown> {
  const payload = (command.payload ?? {}) as { target_action?: string };
  const tabAction =
    command.action === "plugin_lab.preflight" && payload.target_action
      ? payload.target_action
      : command.action;

  const tab = command.action.startsWith("network.hook.")
    ? await resolveNetworkHookTab()
    : command.action.startsWith("plugin_lab.") && !isPluginLabBackgroundAction(command.action)
      ? await resolveLabTabForAction(tabAction)
      : await resolveTargetTab(command);
  if (!tab.id) {
    throw new Error("target tab has no id");
  }

  log("route command", command.action, "tab", tab.id, tab.url);

  await ensureContentScript(tab.id);
  if (command.action !== "plugin_lab.preflight") {
    await ensureLabCommandReady(tab.id, command.action);
  }

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
