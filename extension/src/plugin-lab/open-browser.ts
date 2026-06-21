import type { PlatformId } from "../shared/protocol";
import { ensureContentScript } from "../background/command-router";
import { isPlatformUrl, pinLabSession, readLabSession } from "./lab-context";

const PLATFORM_URLS: Record<PlatformId, string> = {
  douyin: "https://www.douyin.com",
  xiaohongshu: "https://www.xiaohongshu.com",
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
  /** 为 true 时聚焦已有平台窗口，否则新建独立 Chrome 窗口 */
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

function resolvePlatform(raw?: string | null): PlatformId {
  const value = String(raw ?? "douyin").trim().toLowerCase();
  if (value === "xhs" || value === "xiaohongshu" || value === "redbook") return "xiaohongshu";
  if (value === "kuaishou" || value === "ks") return "kuaishou";
  if (value === "douyin" || value === "dy") return "douyin";
  return "douyin";
}

function resolveTargetUrl(payload: OpenBrowserPayload, platform: PlatformId): string {
  const custom = String(payload.url ?? "").trim();
  if (custom) {
    return custom;
  }
  return PLATFORM_URLS[platform] ?? PLATFORM_URLS.douyin;
}

function shouldReuseExisting(payload: OpenBrowserPayload): boolean {
  if (payload.reuse_existing === true) return true;
  // 兼容旧字段：new_tab=false 表示复用
  if (payload.new_tab === false) return true;
  return false;
}

/** 关键词采集任务的起始页：抖音首页/精选，而非视频详情、个人页、搜索页或 Feed 浮层 */
function needsJobStartReset(url: string | undefined, platform: PlatformId): boolean {
  if (!url) return true;
  if (platform === "douyin") {
    try {
      const parsed = new URL(url);
      if (!parsed.hostname.includes("douyin.com")) return true;
      if (/\/video\/\d/i.test(url) || /\/note\/\d/i.test(url)) return true;
      if (/\/user\//i.test(url)) return true;
      if (/modal_id=\d/i.test(url)) return true;
      if (/\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(parsed.pathname)) return true;
      return false;
    } catch {
      return true;
    }
  }
  return false;
}

async function focusTab(tab: chrome.tabs.Tab) {
  if (!tab.id || tab.windowId === undefined) return;
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
}

async function waitForTabLoad(tabId: number, timeoutMs = 8_000): Promise<boolean> {
  const tab = await chrome.tabs.get(tabId);
  if (tab.status === "complete") return true;

  return new Promise<boolean>((resolve) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(false);
    }, timeoutMs);

    function listener(updatedId: number, info: chrome.tabs.TabChangeInfo) {
      if (updatedId !== tabId || info.status !== "complete") return;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(true);
    }

    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function resolvePinnedSessionTab(): Promise<chrome.tabs.Tab | undefined> {
  const session = await readLabSession();
  if (!session?.tabId) return undefined;
  try {
    const tab = await chrome.tabs.get(session.tabId);
    if (!tab.id || !isPlatformUrl(tab.url)) return undefined;
    return tab;
  } catch {
    return undefined;
  }
}

async function findExistingPlatformTab(platform: PlatformId): Promise<chrome.tabs.Tab | undefined> {
  const patterns = PLATFORM_TAB_PATTERNS[platform];
  const existing = await chrome.tabs.query({ url: patterns });
  if (existing.length === 0) return undefined;
  return [...existing].sort((a, b) => (b.lastAccessed ?? 0) - (a.lastAccessed ?? 0))[0];
}

/** 主屏工作区左半屏：left=0 相对 workArea，宽=一半，高=满工作区 */
async function resolveLeftHalfBounds(): Promise<WindowBounds> {
  if (chrome.system?.display?.getInfo) {
    const displays = await chrome.system.display.getInfo();
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

  return { left: 0, top: 0, width: 960, height: 1080 };
}

async function applyLeftHalfLayout(windowId: number): Promise<WindowBounds> {
  const bounds = await resolveLeftHalfBounds();
  await chrome.windows.update(windowId, {
    left: bounds.left,
    top: bounds.top,
    width: bounds.width,
    height: bounds.height,
    state: "normal",
    focused: true,
  });
  return bounds;
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
  const platform = resolvePlatform(payload.platform);
  const url = resolveTargetUrl(payload, platform);
  const reuseExisting = shouldReuseExisting(payload);
  const waitLoad = payload.wait_load === true;
  const resetToStart = payload.reset_to_start === true;
  const customUrl = String(payload.url ?? "").trim();
  const startUrl = PLATFORM_URLS[platform] ?? PLATFORM_URLS.douyin;

  async function openInExistingTab(existing: chrome.tabs.Tab): Promise<OpenBrowserResult> {
    if (!existing.id) throw new Error("target tab has no id");
    let bounds: WindowBounds | undefined;
    if (existing.windowId !== undefined) {
      bounds = await applyLeftHalfLayout(existing.windowId);
    }
    await focusTab(existing);

    const shouldReset =
      resetToStart && !customUrl && needsJobStartReset(existing.url, platform);
    const navigatedToCustom = Boolean(customUrl && existing.url !== customUrl);
    const navigated = navigatedToCustom || shouldReset;

    if (navigated) {
      const targetUrl = customUrl || startUrl;
      await chrome.tabs.update(existing.id, { url: targetUrl });
      await waitForTabLoad(existing.id, shouldReset ? 15_000 : 8_000);
    } else if (waitLoad) {
      await waitForTabLoad(existing.id);
    }

    const refreshed = await chrome.tabs.get(existing.id);
    await pinLabSession(refreshed, platform);
    await ensureContentScript(refreshed.id!);
    return buildResult(platform, refreshed, {
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
    const pinned = await resolvePinnedSessionTab();
    if (pinned) {
      return openInExistingTab(pinned);
    }
    const existing = await findExistingPlatformTab(platform);
    if (existing?.id) {
      return openInExistingTab(existing);
    }
  }

  const bounds = await resolveLeftHalfBounds();
  const created = await chrome.windows.create({
    url,
    focused: true,
    type: "normal",
    left: bounds.left,
    top: bounds.top,
    width: bounds.width,
    height: bounds.height,
  });

  const tab = created.tabs?.[0];
  if (!tab?.id) {
    throw new Error("failed to create browser window");
  }

  if (waitLoad) {
    await waitForTabLoad(tab.id);
  }

  const refreshed = await chrome.tabs.get(tab.id);
  await pinLabSession(refreshed, platform);
  await ensureContentScript(refreshed.id!);
  return buildResult(platform, refreshed, {
    opened: true,
    newWindow: true,
    bounds,
    message: `已在屏幕左侧半屏打开 ${platform} 页面`,
  });
}
