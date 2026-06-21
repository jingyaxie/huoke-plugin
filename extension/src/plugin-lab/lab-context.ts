/** 插件实验室命令所需的页面上下文 */
import { isPlatformUrl, PLATFORM_HOSTS } from "./platform-hosts";
import { getPluginLabAdapter, getPluginLabAdapterForUrl } from "./platforms/registry";

export type LabPageContext = "platform" | "search" | "video" | "profile";

export interface LabSession {
  tabId: number;
  platform: string;
  pinnedAt: number;
  lastUrl?: string;
}

export const LAB_SESSION_KEY = "huoke:lab-session";

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
  "plugin_lab.prepare_search_video": { context: "search", strict: true },
  "plugin_lab.search_video_dom_click": { context: "search", strict: true },
  "plugin_lab.swipe_page": { context: "platform" },
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

export async function readLabSession(): Promise<LabSession | null> {
  try {
    const stored = await chrome.storage.session.get(LAB_SESSION_KEY);
    const session = stored[LAB_SESSION_KEY] as LabSession | undefined;
    if (!session?.tabId) return null;
    return session;
  } catch {
    return null;
  }
}

export async function pinLabSession(tab: chrome.tabs.Tab, platform = "douyin"): Promise<void> {
  if (!tab.id) return;
  const session: LabSession = {
    tabId: tab.id,
    platform,
    pinnedAt: Date.now(),
    lastUrl: tab.url,
  };
  await chrome.storage.session.set({ [LAB_SESSION_KEY]: session });
}

export async function touchLabSession(tabId: number, url?: string): Promise<void> {
  const session = await readLabSession();
  if (!session || session.tabId !== tabId) return;
  await chrome.storage.session.set({
    [LAB_SESSION_KEY]: {
      ...session,
      lastUrl: url ?? session.lastUrl,
    },
  });
}

export async function clearLabSession(): Promise<void> {
  await chrome.storage.session.remove(LAB_SESSION_KEY);
}
