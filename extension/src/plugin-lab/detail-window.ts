import { detectPlatformFromUrl } from "./platform-hosts";
import { normalizePlatformId } from "./platforms/registry";
import {
  readLabSession,
  rememberLabSearchUrl,
  pinDetailSession,
  clearDetailSession,
  readDetailTabId,
} from "./lab-context";
import { sendContentPluginLabCommand } from "./tab-command";
import { warn } from "../shared/logger";

export interface DetailWindowResult {
  ok: boolean;
  detail_window: boolean;
  detail_tab_id: number;
  detail_window_id: number;
  list_tab_id: number;
  url: string;
  aweme_id?: string;
  feed_open: boolean;
  is_search_feed: boolean;
  is_content_detail: boolean;
  mode: string;
  message: string;
}

interface WindowBounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

async function resolveRightHalfBounds(): Promise<WindowBounds> {
  try {
    if (chrome.system?.display?.getInfo) {
      const displays = await chrome.system.display.getInfo();
      const primary = displays.find((item) => item.isPrimary) ?? displays[0];
      const workArea = primary?.workArea;
      if (workArea) {
        const width = Math.floor(workArea.width / 2);
        return {
          left: workArea.left + width,
          top: workArea.top,
          width,
          height: workArea.height,
        };
      }
    }
  } catch (err) {
    warn("resolveRightHalfBounds failed", err);
  }
  return { left: 960, top: 0, width: 960, height: 1080 };
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForTabLoad(tabId: number, timeoutMs = 12_000): Promise<void> {
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

async function focusListTab(platform: string): Promise<void> {
  const session = await readLabSession(platform);
  if (!session?.tabId) return;
  try {
    const tab = await chrome.tabs.get(session.tabId);
    if (!tab.id || tab.windowId === undefined) return;
    await chrome.windows.update(tab.windowId, { focused: true });
    await chrome.tabs.update(tab.id, { active: true });
  } catch {
    // list tab may be gone
  }
}

export async function readDetailTab(platform?: string): Promise<chrome.tabs.Tab | undefined> {
  const detailTabId = await readDetailTabId(platform);
  if (!detailTabId) return undefined;
  try {
    const tab = await chrome.tabs.get(detailTabId);
    if (!tab.id) return undefined;
    return tab;
  } catch {
    const session = platform ? await readLabSession(platform) : await readLabSession();
    if (session?.platform) await clearDetailSession(session.platform);
    return undefined;
  }
}

/** 在右侧独立窗口打开视频，列表工作窗保持不变 */
export async function openVideoInDetailWindow(options: {
  platform: string;
  url: string;
  listTabId: number;
  aweme_id?: string;
  video_index?: number;
}): Promise<DetailWindowResult> {
  const platform = normalizePlatformId(options.platform);
  const url = options.url.trim();
  const listTabId = options.listTabId;

  if (!url) {
    return {
      ok: false,
      detail_window: false,
      detail_tab_id: -1,
      detail_window_id: -1,
      list_tab_id: listTabId,
      url: "",
      feed_open: false,
      is_search_feed: false,
      is_content_detail: false,
      mode: "detail_window",
      message: "缺少视频 URL",
    };
  }

  const listTab = await chrome.tabs.get(listTabId);
  if (listTab.url) {
    await rememberLabSearchUrl(platform, listTab.url);
  }

  const existingDetail = await readDetailTab(platform);
  if (existingDetail?.windowId !== undefined) {
    try {
      await chrome.windows.remove(existingDetail.windowId);
    } catch {
      // already closed
    }
    await clearDetailSession(platform);
  }

  const bounds = await resolveRightHalfBounds();
  const created = await chrome.windows.create({
    url,
    type: "normal",
    focused: true,
    left: bounds.left,
    top: bounds.top,
    width: bounds.width,
    height: bounds.height,
  });

  const detailTab = created.tabs?.[0];
  if (!created.id || !detailTab?.id) {
    return {
      ok: false,
      detail_window: false,
      detail_tab_id: -1,
      detail_window_id: created.id ?? -1,
      list_tab_id: listTabId,
      url,
      feed_open: false,
      is_search_feed: false,
      is_content_detail: false,
      mode: "detail_window",
      message: "创建视频窗口失败",
    };
  }

  await waitForTabLoad(detailTab.id, 14_000);
  await sleep(900);
  await pinDetailSession(platform, detailTab.id, created.id);

  return {
    ok: true,
    detail_window: true,
    detail_tab_id: detailTab.id,
    detail_window_id: created.id,
    list_tab_id: listTabId,
    url: detailTab.url ?? url,
    aweme_id: options.aweme_id,
    feed_open: true,
    is_search_feed: false,
    is_content_detail: true,
    mode: "detail_window",
    message: `已在独立窗口打开${options.video_index ? `第 ${options.video_index} 条` : ""}视频`,
  };
}

export async function closeDetailWindow(platform?: string): Promise<{
  ok: boolean;
  detail_window_closed: boolean;
  list_tab_id?: number;
  message: string;
}> {
  const normalized = platform ? normalizePlatformId(platform) : undefined;
  const session = normalized ? await readLabSession(normalized) : await readLabSession();
  const resolvedPlatform = normalized ?? session?.platform ?? "douyin";

  const detailWindowId = session?.detailWindowId;
  const detailTabId = session?.detailTabId;
  const listTabId = session?.tabId;

  if (detailWindowId !== undefined && detailWindowId >= 0) {
    try {
      await chrome.windows.remove(detailWindowId);
    } catch {
      if (detailTabId) {
        try {
          await chrome.tabs.remove(detailTabId);
        } catch {
          // ignore
        }
      }
    }
    await clearDetailSession(resolvedPlatform);
    if (listTabId) await focusListTab(resolvedPlatform);
    return {
      ok: true,
      detail_window_closed: true,
      list_tab_id: listTabId,
      message: "已关闭视频独立窗口，列表页保持不变",
    };
  }

  if (detailTabId) {
    try {
      const tab = await chrome.tabs.get(detailTabId);
      if (tab.windowId !== undefined && tab.windowId !== session?.windowId) {
        await chrome.windows.remove(tab.windowId);
        await clearDetailSession(resolvedPlatform);
        if (listTabId) await focusListTab(resolvedPlatform);
        return {
          ok: true,
          detail_window_closed: true,
          list_tab_id: listTabId,
          message: "已关闭视频独立窗口",
        };
      }
    } catch {
      await clearDetailSession(resolvedPlatform);
    }
  }

  return {
    ok: false,
    detail_window_closed: false,
    message: "无视频独立窗口可关闭",
  };
}

export async function closeVideoDetailBackground(payload: Record<string, unknown> = {}) {
  const platform = String(
    payload.platform ?? detectPlatformFromUrl(String(payload.url ?? "")) ?? "douyin",
  );
  const closed = await closeDetailWindow(platform);
  if (closed.detail_window_closed) return closed;

  const detailTab = await readDetailTab(platform);
  if (detailTab?.id) {
    return sendContentPluginLabCommand(
      detailTab.id,
      "plugin_lab.close_video_detail",
      payload,
      { skipPreflight: true },
    );
  }

  const session = await readLabSession(platform);
  if (session?.tabId) {
    return sendContentPluginLabCommand(
      session.tabId,
      "plugin_lab.close_video_detail",
      payload,
      { skipPreflight: true },
    );
  }

  return closed;
}

export async function resolveSearchVideoUrl(
  listTabId: number,
  videoIndex: number,
  payload: Record<string, unknown>,
): Promise<{ url: string; aweme_id?: string }> {
  const direct = String(payload.video_url ?? payload.url ?? "").trim();
  if (direct && !direct.includes("/search")) {
    return {
      url: direct,
      aweme_id: String(payload.aweme_id ?? payload.aweme_hint ?? "").trim() || undefined,
    };
  }

  const awemeId = String(payload.aweme_id ?? payload.aweme_hint ?? "").trim();
  const listTab = await chrome.tabs.get(listTabId);
  const platform = normalizePlatformId(
    String(payload.platform ?? detectPlatformFromUrl(listTab.url) ?? "douyin"),
  );

  if (/^\d{8,22}$/.test(awemeId)) {
    if (platform === "douyin") {
      return { url: `https://www.douyin.com/video/${awemeId}`, aweme_id: awemeId };
    }
    if (platform === "kuaishou") {
      return { url: `https://www.kuaishou.com/short-video/${awemeId}`, aweme_id: awemeId };
    }
  }

  const apiResult = (await sendContentPluginLabCommand(
    listTabId,
    "plugin_lab.fetch_search_results",
    { limit: Math.max(videoIndex, 20), platform },
    { skipPreflight: true },
  )) as { items?: Array<{ url?: string; aweme_id?: string }> };

  const item = apiResult.items?.[videoIndex - 1];
  const itemAweme = String(item?.aweme_id ?? "").trim();
  const url = String(item?.url ?? "").trim();
  const resolvedAweme = /^\d{8,22}$/.test(itemAweme)
    ? itemAweme
    : /^\d{8,22}$/.test(awemeId)
      ? awemeId
      : undefined;
  if (!url && resolvedAweme && platform === "douyin") {
    return { url: `https://www.douyin.com/video/${resolvedAweme}`, aweme_id: resolvedAweme };
  }
  return { url, aweme_id: resolvedAweme };
}
