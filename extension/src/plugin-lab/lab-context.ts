/** 插件实验室命令所需的页面上下文 */
import { isPlatformUrl, PLATFORM_HOSTS } from "./platform-hosts";
import { getPluginLabAdapter, getPluginLabAdapterForUrl, normalizePlatformId } from "./platforms/registry";

export type LabPageContext = "platform" | "search" | "video" | "profile";

export interface LabSession {
  tabId: number;
  windowId: number;
  platform: string;
  pinnedAt: number;
  lastUrl?: string;
  /** 搜索结果页 URL，用于关闭详情后恢复列表（比 tab sessionStorage 更稳） */
  searchUrl?: string;
  /** 视频播放独立窗口（列表页保持不动） */
  detailTabId?: number;
  detailWindowId?: number;
  /** Huoke 新建的工作窗/标签（任务结束可安全关闭） */
  huokeOwned?: boolean;
  /** huokeOwned 且通过 windows.create 打开 */
  huokeNewWindow?: boolean;
}

/** @deprecated 旧版全局 session，读取时自动迁移到按平台 key */
export const LAB_SESSION_KEY = "huoke:lab-session";

const PLATFORM_IDS = ["douyin", "xiaohongshu", "kuaishou"] as const;

function labSessionKey(platform: string): string {
  return `huoke:lab-session:${normalizePlatformId(platform)}`;
}

function allLabSessionKeys(): string[] {
  return [
    LAB_SESSION_KEY,
    ...PLATFORM_IDS.map((platform) => labSessionKey(platform)),
  ];
}

/** 每个 plugin_lab 命令需要的最低页面上下文（strict = 找不到匹配标签则报错） */
const ACTION_CONTEXT: Record<string, { context: LabPageContext; strict?: boolean }> = {
  "plugin_lab.open_browser": { context: "platform" },
  "plugin_lab.find_search_box": { context: "platform" },
  "plugin_lab.input_search_text": { context: "platform" },
  "plugin_lab.click_search_btn": { context: "platform" },
  "plugin_lab.click_filter_btn": { context: "search", strict: true },
  "plugin_lab.click_filter_overlay": { context: "search", strict: true },
  "plugin_lab.filter_probe": { context: "search" },
  "plugin_lab.filter_find_option": { context: "search" },
  "plugin_lab.fetch_search_results": { context: "search", strict: true },
  "plugin_lab.ensure_search_multi_column": { context: "search", strict: false },
  "plugin_lab.prepare_search_video": { context: "search", strict: false },
  "plugin_lab.search_video_dom_click": { context: "search", strict: true },
  "plugin_lab.swipe_page": { context: "search", strict: true },
  "plugin_lab.click_search_video": { context: "search", strict: true },
  "plugin_lab.search_video_probe": { context: "search", strict: true },
  "plugin_lab.fetch_profile_videos": { context: "profile", strict: true },
  "plugin_lab.prepare_profile_video": { context: "profile", strict: true },
  "plugin_lab.click_profile_video": { context: "profile", strict: true },
  "plugin_lab.profile_video_probe": { context: "profile" },
  "plugin_lab.profile_video_dom_click": { context: "profile" },
  "plugin_lab.back_to_profile": { context: "platform" },
  "plugin_lab.click_comment_btn": { context: "video", strict: true },
  "plugin_lab.comment_sidebar_probe": { context: "video" },
  "plugin_lab.scroll_and_collect_comments": { context: "video", strict: true },
  "plugin_lab.send_comment": { context: "video", strict: true },
  "plugin_lab.reply_comment": { context: "video", strict: true },
  "plugin_lab.reply_comment_probe": { context: "video" },
  "plugin_lab.reply_comment_hover": { context: "video" },
  "plugin_lab.reply_comment_input_probe": { context: "video" },
  "plugin_lab.reply_comment_type": { context: "video" },
  "plugin_lab.close_video_detail": { context: "video" },
  "plugin_lab.click_comment_avatar": { context: "video", strict: true },
  "plugin_lab.click_follow_btn": { context: "profile", strict: true },
  "plugin_lab.click_dm_btn": { context: "profile", strict: true },
  "plugin_lab.dm_button_probe": { context: "profile" },
  "plugin_lab.dm_input_probe": { context: "profile" },
  "plugin_lab.input_dm_text": { context: "profile", strict: true },
  "plugin_lab.dm_send_probe": { context: "profile" },
  "plugin_lab.dm_send_verify": { context: "profile" },
  "plugin_lab.send_dm": { context: "profile", strict: true },
  "plugin_lab.preflight": { context: "platform" },
  "plugin_lab.page_snapshot": { context: "platform" },
  "plugin_lab.search_context_probe": { context: "platform" },
};

const CONTEXT_LABEL: Record<LabPageContext, string> = {
  platform: "平台首页/任意平台页",
  search: "搜索结果页",
  video: "视频详情/Feed",
  profile: "用户主页",
};

export function contextRequirementForAction(action: string): {
  context: LabPageContext;
  strict: boolean;
} {
  const entry = ACTION_CONTEXT[action];
  if (!entry) {
    return { context: "platform", strict: false };
  }
  return { context: entry.context, strict: entry.strict ?? false };
}

export { isPlatformUrl, PLATFORM_HOSTS } from "./platform-hosts";

/** 主页/搜索页上的 modal_id 视频浮层（非 /video/ 独立详情页） */
export function isFeedOverlayUrl(url?: string | null): boolean {
  return getPluginLabAdapterForUrl(url).isFeedOverlayUrl(url);
}

export function detectPageContext(url?: string | null, platform?: string | null): LabPageContext | null {
  if (!url || !isPlatformUrl(url)) return null;
  const adapter = platform ? getPluginLabAdapter(platform) : getPluginLabAdapterForUrl(url);
  return adapter.detectPageContext(url);
}

export function contextMatchesUrl(
  required: LabPageContext,
  url?: string | null,
  platform?: string | null,
): boolean {
  const adapter = platform ? getPluginLabAdapter(platform) : getPluginLabAdapterForUrl(url);
  return adapter.contextMatchesUrl(required, url);
}

export function scoreTabForContext(
  tab: chrome.tabs.Tab,
  required: LabPageContext,
  sessionTabId?: number,
  platform?: string | null,
): number {
  const adapter = platform
    ? getPluginLabAdapter(platform)
    : getPluginLabAdapterForUrl(tab.url);
  return adapter.scoreTabForContext(tab, required, sessionTabId);
}

export function contextLabel(context: LabPageContext): string {
  return CONTEXT_LABEL[context];
}

async function readStoredSession(key: string): Promise<LabSession | null> {
  const stored = await chrome.storage.session.get(key);
  const session = stored[key] as LabSession | undefined;
  if (!session?.tabId) return null;
  return {
    ...session,
    platform: normalizePlatformId(session.platform),
    windowId: session.windowId ?? -1,
  };
}

/** 读取指定平台的工作区 session；未传 platform 时返回最近 pin 的一个 */
export async function readLabSession(platform?: string): Promise<LabSession | null> {
  try {
    if (platform) {
      const normalized = normalizePlatformId(platform);
      const keyed = await readStoredSession(labSessionKey(normalized));
      if (keyed) return keyed;

      const legacy = await readStoredSession(LAB_SESSION_KEY);
      if (legacy && legacy.platform === normalized) return legacy;
      return null;
    }

    let latest: LabSession | null = null;
    for (const id of PLATFORM_IDS) {
      const session = await readLabSession(id);
      if (!session) continue;
      if (!latest || session.pinnedAt > latest.pinnedAt) latest = session;
    }
    if (latest) return latest;

    return readStoredSession(LAB_SESSION_KEY);
  } catch {
    return null;
  }
}

export async function pinLabSession(
  tab: chrome.tabs.Tab,
  platform = "douyin",
  options?: { huokeOwned?: boolean; huokeNewWindow?: boolean; adoptedUserTab?: boolean },
): Promise<void> {
  if (!tab.id) return;
  const normalized = normalizePlatformId(platform);
  const existing = await readLabSession(normalized);
  const huokeOwned = options?.adoptedUserTab
    ? false
    : (options?.huokeOwned ?? existing?.huokeOwned ?? false);
  const huokeNewWindow = options?.adoptedUserTab
    ? false
    : (options?.huokeNewWindow ?? existing?.huokeNewWindow ?? false);
  const session: LabSession = {
    tabId: tab.id,
    windowId: tab.windowId ?? -1,
    platform: normalized,
    pinnedAt: Date.now(),
    lastUrl: tab.url,
    searchUrl: existing?.searchUrl,
    huokeOwned,
    huokeNewWindow,
  };
  await chrome.storage.session.set({
    [labSessionKey(normalized)]: session,
  });
}

/** 记录当前平台的搜索结果页 URL（扩展 session 级，页面 reload 后仍可恢复） */
export async function rememberLabSearchUrl(platform: string, url: string): Promise<void> {
  try {
    const normalized = normalizePlatformId(platform);
    const trimmed = url.trim();
    if (!trimmed) return;
    const searchUrl = trimmed.split("#")[0];
    const existing = await readLabSession(normalized);
    if (existing?.tabId) {
      await chrome.storage.session.set({
        [labSessionKey(normalized)]: { ...existing, searchUrl },
      });
      return;
    }
    await chrome.storage.session.set({
      [`huoke:lab-search-url:${normalized}`]: searchUrl,
    });
  } catch {
    // content 某些 iframe 上下文可能无法写 session storage
  }
}

/** 新关键词任务开始前清除跨任务残留的搜索结果页 URL */
export async function clearLabSearchUrl(platform: string): Promise<void> {
  try {
    const normalized = normalizePlatformId(platform);
    const existing = await readLabSession(normalized);
    if (existing) {
      const next: LabSession = { ...existing };
      delete next.searchUrl;
      await chrome.storage.session.set({
        [labSessionKey(normalized)]: next,
      });
    }
    await chrome.storage.session.remove(`huoke:lab-search-url:${normalized}`);
  } catch {
    // ignore session storage failures
  }
}

export async function readLabSearchUrl(platform: string): Promise<string> {
  try {
    const normalized = normalizePlatformId(platform);
    const session = await readLabSession(normalized);
    const fromSession = session?.searchUrl?.trim();
    if (fromSession) return fromSession;
    const stored = await chrome.storage.session.get(`huoke:lab-search-url:${normalized}`);
    const fallback = stored[`huoke:lab-search-url:${normalized}`];
    return typeof fallback === "string" ? fallback.trim() : "";
  } catch {
    return "";
  }
}

export async function touchLabSession(
  tabId: number,
  url?: string,
  platform?: string,
): Promise<void> {
  const candidates = platform
    ? [await readLabSession(platform)]
    : await Promise.all(PLATFORM_IDS.map((id) => readLabSession(id)));

  for (const session of candidates) {
    if (!session || session.tabId !== tabId) continue;
    await chrome.storage.session.set({
      [labSessionKey(session.platform)]: {
        ...session,
        lastUrl: url ?? session.lastUrl,
      },
    });
    return;
  }
}

export async function clearLabSession(platform?: string): Promise<void> {
  if (platform) {
    await chrome.storage.session.remove(labSessionKey(platform));
    return;
  }
  await chrome.storage.session.remove(allLabSessionKeys());
}

export async function pinDetailSession(
  platform: string,
  detailTabId: number,
  detailWindowId: number,
): Promise<void> {
  const normalized = normalizePlatformId(platform);
  const existing = await readLabSession(normalized);
  if (!existing?.tabId) return;
  await chrome.storage.session.set({
    [labSessionKey(normalized)]: { ...existing, detailTabId, detailWindowId },
  });
}

export async function clearDetailSession(platform: string): Promise<void> {
  const normalized = normalizePlatformId(platform);
  const existing = await readLabSession(normalized);
  if (!existing) return;
  const next: LabSession = {
    tabId: existing.tabId,
    windowId: existing.windowId,
    platform: existing.platform,
    pinnedAt: existing.pinnedAt,
    lastUrl: existing.lastUrl,
    searchUrl: existing.searchUrl,
  };
  await chrome.storage.session.set({ [labSessionKey(normalized)]: next });
}

export async function readDetailTabId(platform?: string): Promise<number | undefined> {
  const session = platform ? await readLabSession(platform) : await readLabSession();
  return session?.detailTabId;
}

/** 仅返回已注册工作区内的平台标签，避免 hijack 用户日常浏览标签 */
export async function filterWorkWindowTabs(
  tabs: chrome.tabs.Tab[],
  platformHint?: string,
): Promise<chrome.tabs.Tab[]> {
  const platforms = platformHint
    ? [normalizePlatformId(platformHint)]
    : [...PLATFORM_IDS];

  const allowedTabIds = new Set<number>();
  const allowedWindowIds = new Set<number>();

  for (const platform of platforms) {
    const session = await readLabSession(platform);
    if (!session) continue;
    allowedTabIds.add(session.tabId);
    if (session.windowId >= 0) allowedWindowIds.add(session.windowId);
    if (session.detailTabId !== undefined) allowedTabIds.add(session.detailTabId);
    if (session.detailWindowId !== undefined && session.detailWindowId >= 0) {
      allowedWindowIds.add(session.detailWindowId);
    }
  }

  if (allowedTabIds.size === 0 && allowedWindowIds.size === 0) return [];

  return tabs.filter(
    (tab) =>
      (tab.id !== undefined && allowedTabIds.has(tab.id)) ||
      (tab.windowId !== undefined && allowedWindowIds.has(tab.windowId)),
  );
}
