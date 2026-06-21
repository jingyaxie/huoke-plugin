import type { BridgeMessage } from "../shared/protocol";
import { isPluginLabBackgroundAction } from "../plugin-lab/background-actions";
import { resolveLabTabForAction, resolveLabTargetTab } from "../plugin-lab/resolve-lab-tab";
import { ensureLabCommandReady } from "../plugin-lab/lab-preflight";
import { readLabSession } from "../plugin-lab/lab-context";
import { detectPlatformFromUrl, isPlatformUrl } from "../plugin-lab/platform-hosts";
import { getPluginLabAdapter, normalizePlatformId, tabQueryPatternsForPlatform } from "../plugin-lab/platforms/registry";
import { log, warn } from "../shared/logger";
import { extensionVersion } from "../shared/runtime";

async function sleep(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function focusTab(tab: chrome.tabs.Tab) {
  if (!tab.id || tab.windowId === undefined) return;
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
}

function resolveCommandPlatform(command: BridgeMessage): string {
  if (command.platform) return normalizePlatformId(command.platform);
  const payloadPlatform = (command.payload as { platform?: string } | undefined)?.platform;
  if (payloadPlatform) return normalizePlatformId(payloadPlatform);
  return "douyin";
}

async function resolveNetworkHookTab(platform?: string): Promise<chrome.tabs.Tab> {
  const normalized = platform ? normalizePlatformId(platform) : undefined;
  const session = normalized ? await readLabSession(normalized) : await readLabSession();
  if (session?.tabId) {
    try {
      const tab = await chrome.tabs.get(session.tabId);
      if (tab.id && isPlatformUrl(tab.url)) {
        await focusTab(tab);
        return tab;
      }
    } catch {
      // pinned tab closed — fall through
    }
  }
  return resolveLabTargetTab(normalized ? { platform: normalized } : {});
}

async function resolvePinnedOrWorkTab(platform: string): Promise<chrome.tabs.Tab | null> {
  const session = await readLabSession(platform);
  if (session?.tabId) {
    try {
      const tab = await chrome.tabs.get(session.tabId);
      if (
        tab.id &&
        isPlatformUrl(tab.url) &&
        detectPlatformFromUrl(tab.url) === platform
      ) {
        await focusTab(tab);
        return tab;
      }
    } catch {
      // fall through
    }
  }

  if (session?.windowId !== undefined && session.windowId >= 0) {
    try {
      const win = await chrome.windows.get(session.windowId, { populate: true });
      const match =
        win.tabs?.find(
          (tab) =>
            tab.active &&
            tab.url &&
            isPlatformUrl(tab.url) &&
            detectPlatformFromUrl(tab.url) === platform,
        ) ??
        win.tabs?.find(
          (tab) =>
            tab.url &&
            isPlatformUrl(tab.url) &&
            detectPlatformFromUrl(tab.url) === platform,
        );
      if (match?.id) {
        await focusTab(match);
        return match;
      }
    } catch {
      // work window closed
    }
  }

  return null;
}

async function resolveTargetTab(command: BridgeMessage): Promise<chrome.tabs.Tab> {
  const platform = resolveCommandPlatform(command);
  const adapter = getPluginLabAdapter(platform);

  const pinned = await resolvePinnedOrWorkTab(platform);
  if (pinned) return pinned;

  const tabPatterns = tabQueryPatternsForPlatform(platform);
  const platformTabs = await chrome.tabs.query({ url: tabPatterns });
  if (platformTabs.length === 0) {
    throw new Error(`no ${adapter.label} tab open — run open_browser with platform=${platform} first`);
  }

  throw new Error(
    `no ${adapter.label} work window — run open_browser with platform=${platform} first`,
  );
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
    `${detail} — open chrome://extensions, click Reload on Huoke, then refresh the platform tab`,
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
    ? await resolveNetworkHookTab(resolveCommandPlatform(command))
    : command.action.startsWith("plugin_lab.") && !isPluginLabBackgroundAction(command.action)
      ? await resolveLabTabForAction(tabAction, resolveCommandPlatform(command))
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
