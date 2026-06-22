import type { PlatformId } from "../shared/protocol";
import { ensureContentScript } from "../background/command-router";
import { detectPlatformFromUrl, isPlatformUrl } from "./platform-hosts";
import { pinLabSession, readLabSession } from "./lab-context";
import { closeDetailWindow } from "./detail-window";
import { isUsablePlatformTab } from "./platforms/shared/tab-health";
import { log, warn } from "../shared/logger";

const PLATFORM_URLS: Record<PlatformId, string> = {
  douyin: "https://www.douyin.com",
  xiaohongshu: "https://www.xiaohongshu.com/explore",
  kuaishou: "https://www.kuaishou.com",
  unknown: "https://www.douyin.com",
};

const PLATFORM_TAB_PATTERNS: Record<PlatformId, string[]> = {
  douyin: ["https://www.douyin.com/*", "https://*.douyin.com/*"],
  xiaohongshu: ["https://www.xiaohongshu.com/*", "https://*.xiaohongshu.com/*"],
  kuaishou: ["https://www.kuaishou.com/*", "https://*.kuaishou.com/*"],
  unknown: ["https://www.douyin.com/*", "https://*.douyin.com/*"],
};

export interface OpenBrowserPayload {
  platform?: PlatformId | string;
  url?: string;
  /** @deprecated use reuse_existing */
  new_tab?: boolean;
  /** 为 true 时聚焦已有平台工作窗；默认 true。显式传 false 才新建独立窗口 */
  reuse_existing?: boolean;
  wait_load?: boolean;
  /** 任务开始时若不在合法起始页，则导航到平台首页 */
  reset_to_start?: boolean;
}

export interface OpenBrowserResult {
  ok: boolean;
  platform: PlatformId;
  url: string;
  tab_id: number;
  window_id: number;
  opened: boolean;
  new_window: boolean;
  focused: boolean;
  bounds?: WindowBounds;
  title?: string;
  message: string;
}

export interface WindowBounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function resolvePlatform(raw?: string | null): PlatformId {
  const value = String(raw ?? "douyin").trim().toLowerCase();
  if (value === "xhs" || value === "xiaohongshu" || value === "redbook") return "xiaohongshu";
  if (value === "kuaishou" || value === "ks") return "kuaishou";
  if (value === "douyin" || value === "dy") return "douyin";
  return "douyin";
}

function resolveTargetUrl(payload: OpenBrowserPayload, platform: PlatformId): string {
  const custom = String(payload.url ?? "").trim();
  if (custom) return custom;
  return PLATFORM_URLS[platform] ?? PLATFORM_URLS.douyin;
}

function shouldReuseExisting(payload: OpenBrowserPayload): boolean {
  if (payload.reuse_existing === false) return false;
  if (payload.new_tab === true) return false;
  return true;
}

function needsJobStartReset(url: string | undefined, platform: PlatformId): boolean {
  if (!url) return true;
  if (platform === "douyin") {
    try {
      const parsed = new URL(url);
      if (!parsed.hostname.includes("douyin.com")) return true;
      if (/\/video\/\d/i.test(url) || /\/note\/\d/i.test(url)) return true;
      if (/\/user\//i.test(url)) return true;
      // 搜索结果页（含 modal_id 浮层）保持不动，避免任务开始时「重复搜索」
      if (/\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(parsed.pathname) || /modal_id=\d/i.test(url)) {
        return false;
      }
      return false;
    } catch {
      return true;
    }
  }
  if (platform === "xiaohongshu") {
    try {
      if (!url.includes("xiaohongshu.com")) return true;
      if (/search_result|\/explore\/[0-9a-fA-F]|\/discovery\/item\//i.test(url)) return true;
      return !url.includes("/explore");
    } catch {
      return true;
    }
  }
  if (platform === "kuaishou") {
    try {
      if (!url.includes("kuaishou.com")) return true;
      if (/\/short-video\/|\/search\//i.test(url)) return true;
      const path = new URL(url).pathname;
      return path === "/" || path === "";
    } catch {
      return true;
    }
  }
  return false;
}

/** 等待 content script 就绪（统一走 command-router 注入/重载逻辑） */
async function ensureContentScriptReady(tabId: number) {
  await ensureContentScript(tabId);
}

async function sleep(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function focusTab(tab: chrome.tabs.Tab) {
  if (!tab.id || tab.windowId === undefined) return;
  try {
    await chrome.windows.update(tab.windowId, { focused: true });
    await chrome.tabs.update(tab.id, { active: true });
  } catch (err) {
    warn("focusTab failed", err);
  }
}

async function waitForPlatformUrl(tabId: number, platform: PlatformId, timeoutMs = 8_000): Promise<chrome.tabs.Tab> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.url && isPlatformUrl(tab.url) && detectPlatformFromUrl(tab.url) === platform) {
        return tab;
      }
    } catch {
      break;
    }
    await sleep(200);
  }
  return chrome.tabs.get(tabId);
}

async function waitForTabLoad(tabId: number, timeoutMs = 5_000): Promise<void> {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") return;
  } catch {
    return;
  }

  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, timeoutMs);

    function listener(updatedId: number, info: chrome.tabs.TabChangeInfo) {
      if (updatedId !== tabId || info.status !== "complete") return;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }

    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function resolvePinnedSessionTab(platform: PlatformId): Promise<chrome.tabs.Tab | undefined> {
  const session = await readLabSession(platform);
  if (!session?.tabId) return undefined;
  try {
    const tab = await chrome.tabs.get(session.tabId);
    if (!tab.id || !isPlatformUrl(tab.url)) return undefined;
    if (detectPlatformFromUrl(tab.url) !== platform) return undefined;
    if (!isUsablePlatformTab(tab)) return undefined;
    return tab;
  } catch {
    return undefined;
  }
}

async function findWorkWindowTab(platform: PlatformId): Promise<chrome.tabs.Tab | undefined> {
  const session = await readLabSession(platform);
  if (session?.windowId !== undefined && session.windowId >= 0) {
    try {
      const win = await chrome.windows.get(session.windowId, { populate: true });
      const matches = (win.tabs ?? []).filter(
        (tab) =>
          tab.url &&
          isPlatformUrl(tab.url) &&
          detectPlatformFromUrl(tab.url) === platform &&
          isUsablePlatformTab(tab),
      );
      if (matches.length > 0) {
        return matches.find((tab) => tab.active) ?? matches[0];
      }
    } catch {
      // work window closed
    }
  }
  return undefined;
}

/** 无工作窗会话时，复用任意已登录且非验证码的平台标签（比新建窗口快） */
async function findAnyUsablePlatformTab(platform: PlatformId): Promise<chrome.tabs.Tab | undefined> {
  const patterns = PLATFORM_TAB_PATTERNS[platform] ?? PLATFORM_TAB_PATTERNS.douyin;
  const tabs = await chrome.tabs.query({ url: patterns });
  const usable = tabs.filter(
    (tab) =>
      tab.url &&
      isPlatformUrl(tab.url) &&
      detectPlatformFromUrl(tab.url) === platform &&
      isUsablePlatformTab(tab),
  );
  if (usable.length === 0) return undefined;
  return usable.find((tab) => tab.active) ?? usable[0];
}

/** 仅复用已注册的平台工作窗标签；无会话时降级到任意可用标签 */
async function findExistingPlatformTab(platform: PlatformId): Promise<chrome.tabs.Tab | undefined> {
  const pinned = await resolvePinnedSessionTab(platform);
  if (pinned) return pinned;
  const work = await findWorkWindowTab(platform);
  if (work) return work;
  return findAnyUsablePlatformTab(platform);
}

async function resolveLeftHalfBounds(): Promise<WindowBounds> {
  try {
    if (chrome.system?.display?.getInfo) {
      const displays = await withTimeout(chrome.system.display.getInfo(), 3_000, "system.display.getInfo");
      const primary = displays.find((item) => item.isPrimary) ?? displays[0];
      const workArea = primary?.workArea;
      if (workArea) {
        return {
          left: workArea.left,
          top: workArea.top,
          width: Math.floor(workArea.width / 2),
          height: workArea.height,
        };
      }
    }
  } catch (err) {
    warn("resolveLeftHalfBounds failed", err);
  }
  return { left: 0, top: 0, width: 960, height: 1080 };
}

async function tryApplyLeftHalfLayout(windowId: number): Promise<WindowBounds | undefined> {
  const bounds = await resolveLeftHalfBounds();
  try {
    await chrome.windows.update(windowId, {
      left: bounds.left,
      top: bounds.top,
      width: bounds.width,
      height: bounds.height,
      state: "normal",
      focused: true,
    });
    return bounds;
  } catch (err) {
    warn("applyLeftHalfLayout failed", windowId, err);
    try {
      await chrome.windows.update(windowId, { focused: true, state: "normal" });
    } catch {
      // ignore
    }
    return bounds;
  }
}

async function createPlatformWindow(url: string): Promise<{ tab: chrome.tabs.Tab; bounds?: WindowBounds; newWindow: boolean }> {
  const bounds = await resolveLeftHalfBounds();

  // 插件实验室：优先新建独立窗口（左侧半屏），避免在用户日常浏览器里开标签
  try {
    const created = await withTimeout(
      chrome.windows.create({
        url,
        focused: true,
        type: "normal",
        left: bounds.left,
        top: bounds.top,
        width: bounds.width,
        height: bounds.height,
      }),
      10_000,
      "windows.create",
    );
    const tab = created.tabs?.[0];
    if (tab?.id) {
      log("open_browser windows.create ok", url, tab.id);
      return { tab, bounds, newWindow: true };
    }
  } catch (err) {
    warn("windows.create failed, fallback tabs.create", err);
  }

  try {
    const tab = await withTimeout(chrome.tabs.create({ url, active: true }), 8_000, "tabs.create");
    if (!tab.id) throw new Error("failed to create platform tab");
    let applied: WindowBounds | undefined;
    if (tab.windowId !== undefined) {
      applied = await tryApplyLeftHalfLayout(tab.windowId);
    }
    log("open_browser tabs.create fallback ok", url, tab.id);
    return { tab, bounds: applied ?? bounds, newWindow: false };
  } catch (err) {
    warn("tabs.create failed", err);
  }

  throw new Error(
    "failed to open browser window — reload extension in chrome://extensions, then retry",
  );
}

function buildResult(
  platform: PlatformId,
  tab: chrome.tabs.Tab,
  options: {
    opened: boolean;
    newWindow: boolean;
    message: string;
    bounds?: WindowBounds;
  },
): OpenBrowserResult {
  return {
    ok: true,
    platform,
    url: tab.url ?? "",
    tab_id: tab.id ?? -1,
    window_id: tab.windowId ?? -1,
    opened: options.opened,
    new_window: options.newWindow,
    focused: true,
    bounds: options.bounds,
    title: tab.title,
    message: options.message,
  };
}

export async function openBrowser(payload: OpenBrowserPayload = {}): Promise<OpenBrowserResult> {
  if (!chrome.tabs?.create || !chrome.windows?.create) {
    throw new Error(
      "open_browser 必须在 Service Worker 中运行 — 请在 chrome://extensions 重新加载 extension/dist",
    );
  }

  const platform = resolvePlatform(payload.platform);
  const url = resolveTargetUrl(payload, platform);
  const reuseExisting = shouldReuseExisting(payload);
  const waitLoad = payload.wait_load === true;
  const resetToStart = payload.reset_to_start === true;
  const customUrl = String(payload.url ?? "").trim();
  const startUrl = PLATFORM_URLS[platform] ?? PLATFORM_URLS.douyin;

  async function openInExistingTab(existing: chrome.tabs.Tab): Promise<OpenBrowserResult> {
    if (!existing.id) throw new Error("target tab has no id");

    if (resetToStart && !customUrl) {
      await closeDetailWindow(platform).catch(() => undefined);
    }

    let bounds: WindowBounds | undefined;
    if (existing.windowId !== undefined) {
      bounds = await tryApplyLeftHalfLayout(existing.windowId);
    }
    await focusTab(existing);

    const shouldReset =
      resetToStart && !customUrl && (needsJobStartReset(existing.url, platform) || !isUsablePlatformTab(existing));
    const navigatedToCustom = Boolean(customUrl && existing.url !== customUrl);
    const navigated = navigatedToCustom || shouldReset;

    if (navigated) {
      const targetUrl = customUrl || startUrl;
      await chrome.tabs.update(existing.id, { url: targetUrl });
      if (waitLoad) await waitForTabLoad(existing.id, 8_000);
      else await waitForTabLoad(existing.id, 2_000);
    } else if (waitLoad) {
      await waitForTabLoad(existing.id, 8_000);
    }

    const refreshed = await waitForPlatformUrl(existing.id, platform);
    let readyTab = refreshed;
    if (!isUsablePlatformTab(readyTab) && !customUrl) {
      await chrome.tabs.update(existing.id, { url: startUrl });
      await waitForTabLoad(existing.id, 10_000);
      readyTab = await chrome.tabs.get(existing.id);
    }
    await pinLabSession(readyTab, platform);
    await ensureContentScriptReady(readyTab.id!);
    return buildResult(platform, readyTab, {
      opened: false,
      newWindow: false,
      bounds,
      message: shouldReset
        ? `已重置到 ${platform} 任务起始页`
        : navigatedToCustom
          ? `已聚焦 ${platform} 并打开 ${customUrl}`
          : `已聚焦已有 ${platform} 窗口（左侧半屏）`,
    });
  }

  if (reuseExisting) {
    const pinned = await resolvePinnedSessionTab(platform);
    if (pinned) return openInExistingTab(pinned);
    const existing = await findExistingPlatformTab(platform);
    if (existing?.id) return openInExistingTab(existing);
  }

  const { tab, bounds, newWindow } = await createPlatformWindow(url);
  if (waitLoad) await waitForTabLoad(tab.id!, 10_000);

  let refreshed = await waitForPlatformUrl(tab.id!, platform);
  if (!isUsablePlatformTab(refreshed)) {
    await chrome.tabs.update(tab.id!, { url: startUrl });
    await waitForTabLoad(tab.id!, 10_000);
    refreshed = await chrome.tabs.get(tab.id!);
  }
  await pinLabSession(refreshed, platform);
  await ensureContentScriptReady(refreshed.id!);
  return buildResult(platform, refreshed, {
    opened: true,
    newWindow,
    bounds,
    message: newWindow
      ? `已在屏幕左侧半屏打开 ${platform} 独立窗口`
      : `已在现有窗口打开 ${platform} 标签页（独立窗口创建失败，已降级）`,
  });
}
