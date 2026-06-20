import type { PlatformId } from "../shared/protocol";

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

async function focusTab(tab: chrome.tabs.Tab) {
  if (!tab.id || tab.windowId === undefined) return;
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
}

async function waitForTabLoad(tabId: number, timeoutMs = 20_000): Promise<void> {
  const tab = await chrome.tabs.get(tabId);
  if (tab.status === "complete") return;

  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error("tab load timeout"));
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
  const waitLoad = payload.wait_load !== false;

  if (reuseExisting) {
    const existing = await findExistingPlatformTab(platform);
    if (existing) {
      let bounds: WindowBounds | undefined;
      if (existing.windowId !== undefined) {
        bounds = await applyLeftHalfLayout(existing.windowId);
      }
      await focusTab(existing);
      if (existing.id && waitLoad) {
        try {
          await waitForTabLoad(existing.id);
        } catch {
          // ignore load timeout when reusing window
        }
      }
      const refreshed = existing.id ? await chrome.tabs.get(existing.id) : existing;
      return buildResult(platform, refreshed, {
        opened: false,
        newWindow: false,
        bounds,
        message: `已聚焦已有 ${platform} 窗口（左侧半屏）`,
      });
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
    try {
      await waitForTabLoad(tab.id);
    } catch {
      // page may still be loading; return window info anyway
    }
  }

  const refreshed = await chrome.tabs.get(tab.id);
  return buildResult(platform, refreshed, {
    opened: true,
    newWindow: true,
    bounds,
    message: `已在屏幕左侧半屏打开 ${platform} 页面`,
  });
}
