/** 插件实验室命令所需的页面上下文 */
export type LabPageContext = "platform" | "search" | "video" | "profile";

export interface LabSession {
  tabId: number;
  platform: string;
  pinnedAt: number;
  lastUrl?: string;
}

export const LAB_SESSION_KEY = "huoke:lab-session";

const SEARCH_URL_RE = /\/search\/|\/jingxuan\/search\/|\/root\/search\//i;
const VIDEO_URL_RE = /\/video\/\d+|modal_id=\d+/i;
const PROFILE_URL_RE = /\/user\//i;
const MODAL_ID_RE = /modal_id=\d{8,22}/i;

/** 主页/搜索页上的 modal_id 视频浮层（非 /video/ 独立详情页） */
export function isFeedOverlayUrl(url?: string | null): boolean {
  if (!url || !MODAL_ID_RE.test(url)) return false;
  if (/\/video\/\d{8,22}/i.test(url)) return false;
  return PROFILE_URL_RE.test(url) || SEARCH_URL_RE.test(url);
}

const PLATFORM_HOSTS = [
  "douyin.com",
  "xiaohongshu.com",
  "kuaishou.com",
];

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

export function isPlatformUrl(url?: string | null): boolean {
  if (!url) return false;
  try {
    const host = new URL(url).hostname.toLowerCase();
    return PLATFORM_HOSTS.some((item) => host === item || host.endsWith(`.${item}`));
  } catch {
    return PLATFORM_HOSTS.some((item) => url.includes(item));
  }
}

export function detectPageContext(url?: string | null): LabPageContext | null {
  if (!url || !isPlatformUrl(url)) return null;
  if (PROFILE_URL_RE.test(url)) return "profile";
  if (VIDEO_URL_RE.test(url)) return "video";
  if (SEARCH_URL_RE.test(url)) return "search";
  return "platform";
}

export function contextMatchesUrl(required: LabPageContext, url?: string | null): boolean {
  const detected = detectPageContext(url);
  if (!detected) return false;
  const feedOverlay = isFeedOverlayUrl(url);
  if (required === "platform") return true;
  if (required === "search") return detected === "search" || detected === "video" || feedOverlay;
  if (required === "video") return detected === "video" || detected === "search" || feedOverlay;
  if (required === "profile") return detected === "profile" && !feedOverlay;
  return false;
}

export function scoreTabForContext(
  tab: chrome.tabs.Tab,
  required: LabPageContext,
  sessionTabId?: number,
): number {
  const url = tab.url ?? "";
  if (!isPlatformUrl(url)) return -1;

  let score = 0;
  const detected = detectPageContext(url);

  if (tab.id !== undefined && tab.id === sessionTabId) {
    if (required === "platform" || contextMatchesUrl(required, url)) {
      score += 10_000;
    } else {
      score += 300;
    }
  }

  if (required === "platform") {
    score += 100;
  } else if (required === "search") {
    if (detected === "search") score += 5_000;
    else if (detected === "video") score += 3_000;
    else if (detected === "platform") score += 200;
    else score -= 500;
  } else if (required === "video") {
    if (detected === "video") score += 5_000;
    else if (isFeedOverlayUrl(url)) score += 4_500;
    else if (detected === "search") score += 2_000;
    else score -= 500;
  } else if (required === "profile") {
    if (detected === "profile" && !isFeedOverlayUrl(url)) score += 5_000;
    else if (detected === "profile") score += 500;
    else score -= 500;
  }

  score += (tab.lastAccessed ?? 0) / 1_000_000_000;
  return score;
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
