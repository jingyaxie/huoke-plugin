import { humanClick, humanPace, randDelay, sleep } from "./search-input";
import { rememberPlatformSearchUrl } from "./search-session";
import {
  collectSearchResultCards,
  extractAwemeFromCard,
  isSearchResultsPage,
  pickSearchCardClickTarget,
  scrollCardIntoView,
} from "./search-results-dom";

export const SEARCH_URL_STORAGE_KEY = "huoke:douyin-search-url";

const FEED_OVERLAY_SELECTORS = [
  '[data-e2e="feed-active-video"]',
  '[data-e2e="feed-comment-icon"]',
  '[data-e2e="comment-icon"]',
  '[data-e2e="detail-tab-comment"]',
  '[data-e2e="browse-comment-icon"]',
  '[data-e2e="video-player-container"]',
  '[class*="PlayerContainer"]',
  '[class*="playerContainer"]',
  '[class*="BasicPlayer"]',
] as const;

const COMMENT_SIDEBAR_MARKERS = [
  '[data-e2e="comment-item"]',
  '[class*="CommentItem"]',
] as const;

export function isStandaloneVideoPage(url = location.href): boolean {
  return /\/video\/\d{8,22}/i.test(url) || /\/note\/\d{8,22}/i.test(url);
}

export function feedOverlayVisible(): boolean {
  for (const selector of FEED_OVERLAY_SELECTORS) {
    const el = document.querySelector(selector);
    if (!el) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width >= 10 && rect.height >= 10) return true;
  }
  for (const selector of COMMENT_SIDEBAR_MARKERS) {
    const el = document.querySelector(selector);
    if (!el) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width >= 10 && rect.height >= 10) return true;
  }
  const headers = document.querySelectorAll("div, span, p");
  for (let i = 0; i < headers.length && i < 120; i += 1) {
    const text = (headers[i].textContent ?? "").trim();
    if (!text.startsWith("全部评论")) continue;
    const rect = headers[i].getBoundingClientRect();
    if (rect.width >= 10 && rect.height >= 10) return true;
  }
  return false;
}

function isProfilePageUrl(url = location.href): boolean {
  if (!/\/user\//i.test(url)) return false;
  if (/\/video\/\d{8,22}/i.test(url)) return false;
  return true;
}

/** 搜索页 Feed 浮层（左视频 + 右评论），非 /video/ 独立详情页 */
export function isSearchFeedOverlay(url = location.href): boolean {
  if (isStandaloneVideoPage(url)) return false;
  const onSearch = isSearchResultsPage(url);
  if (!onSearch && !/modal_id=\d{8,22}/i.test(url)) return false;
  return feedOverlayVisible();
}

/** 博主主页 Feed 浮层（作品列表上 modal 播放） */
export function isProfileFeedOverlay(url = location.href): boolean {
  if (isStandaloneVideoPage(url)) return false;
  if (!feedOverlayVisible()) return false;
  return isProfilePageUrl(url) || (/\/user\//i.test(url) && /modal_id=\d{8,22}/i.test(url));
}

/** 抖音搜索/主页共用的 Feed 浮层（用于 Feed 内切下一个视频） */
export function isDouyinFeedOverlay(url = location.href): boolean {
  return isSearchFeedOverlay(url) || isProfileFeedOverlay(url);
}

export function rememberSearchResultsUrl(url = location.href): void {
  if (!isSearchResultsPage(url)) return;
  try {
    sessionStorage.setItem(SEARCH_URL_STORAGE_KEY, url.split("#")[0] ?? url);
  } catch {
    // ignore quota / private mode
  }
  void rememberPlatformSearchUrl(url, "douyin");
}

export function clearStoredSearchResultsUrl(): void {
  try {
    sessionStorage.removeItem(SEARCH_URL_STORAGE_KEY);
  } catch {
    // ignore quota / private mode
  }
}

export function readStoredSearchResultsUrl(): string {
  try {
    const stored = sessionStorage.getItem(SEARCH_URL_STORAGE_KEY)?.trim();
    if (stored && isSearchResultsPage(stored)) return stripModalFromSearchUrl(stored);
  } catch {
    // ignore
  }
  if (isSearchResultsPage()) return stripModalFromSearchUrl(location.href);
  return "";
}

export function stripModalFromSearchUrl(url: string): string {
  try {
    const parsed = new URL(url);
    parsed.searchParams.delete("modal_id");
    parsed.hash = "";
    return parsed.toString();
  } catch {
    return url.replace(/([?&])modal_id=[^&]+&?/i, "$1").replace(/[?&]$/, "");
  }
}

export function buildSearchModalUrl(awemeId: string, baseUrl?: string): string | null {
  const aweme = awemeId.trim();
  if (!/^\d{8,22}$/.test(aweme)) return null;

  const candidates = [
    baseUrl?.trim(),
    readStoredSearchResultsUrl(),
    isSearchResultsPage() ? location.href : "",
  ].filter(Boolean) as string[];

  for (const candidate of candidates) {
    if (!isSearchResultsPage(candidate)) continue;
    try {
      const url = new URL(candidate);
      url.searchParams.set("modal_id", aweme);
      if (!url.searchParams.get("type")) url.searchParams.set("type", "general");
      url.hash = "";
      return url.toString();
    } catch {
      continue;
    }
  }
  return null;
}

export async function waitForSearchFeedOverlay(maxMs = 9000): Promise<boolean> {
  const deadline = Date.now() + maxMs;
  const pollMs = maxMs <= 5000 ? 160 : 280;
  while (Date.now() < deadline) {
    if (isSearchFeedOverlay()) return true;
    await sleep(pollMs);
  }
  return isSearchFeedOverlay();
}

export async function openFeedViaModalId(
  awemeId: string,
  baseUrl?: string,
): Promise<{ ok: boolean; mode: "modal_id"; url: string; message: string }> {
  const target = buildSearchModalUrl(awemeId, baseUrl);
  if (!target) {
    return {
      ok: false,
      mode: "modal_id",
      url: location.href,
      message: "无法构造搜索 Feed modal_id URL（缺少搜索结果页地址）",
    };
  }

  const currentBase = location.href.split("#")[0];
  const targetBase = target.split("#")[0];
  if (currentBase !== targetBase) {
    location.assign(target);
  } else if (!isSearchFeedOverlay()) {
    location.replace(target);
    await sleep(400);
    if (!isSearchFeedOverlay()) {
      location.reload();
      await sleep(500);
    }
  }

  const opened = await waitForSearchFeedOverlay(9000);
  return {
    ok: opened,
    mode: "modal_id",
    url: location.href,
    message: opened
      ? `已通过 modal_id 打开搜索 Feed 浮层（aweme=${awemeId.slice(0, 12)}…）`
      : isStandaloneVideoPage()
        ? "modal_id 导航后仍落在独立视频详情页"
        : "modal_id 导航后 Feed 浮层未就绪",
  };
}

export function resolveAwemeHint(payload: {
  aweme_id?: string;
  aweme_hint?: string;
  video_index?: number;
  index?: number;
}): string {
  for (const key of ["aweme_id", "aweme_hint"] as const) {
    const value = String(payload[key] ?? "").trim();
    if (/^\d{8,22}$/.test(value)) return value;
  }

  const index = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  const cards = collectSearchResultCards();
  if (cards.length === 0) return "";
  const card = cards[Math.min(index, cards.length) - 1];
  return extractAwemeFromCard(card) ?? "";
}

export async function recoverSearchFeedFromDetailPage(
  awemeId: string,
): Promise<{ ok: boolean; message: string }> {
  if (!isStandaloneVideoPage()) {
    return { ok: isSearchFeedOverlay(), message: "当前不在独立详情页" };
  }
  const result = await openFeedViaModalId(awemeId);
  return { ok: result.ok, message: result.message };
}

export function classifyDouyinSearchPhase(url = location.href): {
  phase: "search_list" | "search_feed" | "video_page" | "other";
  is_search_feed: boolean;
  is_standalone_video: boolean;
  feed_visible: boolean;
} {
  const standalone = isStandaloneVideoPage(url);
  const feedVisible = feedOverlayVisible();
  const searchFeed = isSearchFeedOverlay(url);
  let phase: "search_list" | "search_feed" | "video_page" | "other" = "other";

  if (standalone) phase = "video_page";
  else if (searchFeed) phase = "search_feed";
  else if (isSearchResultsPage(url)) phase = "search_list";

  return {
    phase,
    is_search_feed: searchFeed,
    is_standalone_video: standalone,
    feed_visible: feedVisible,
  };
}

export async function clickSearchPosterAtIndex(index: number): Promise<{
  ok: boolean;
  clicked: boolean;
  aweme_id: string;
  message: string;
}> {
  const cards = collectSearchResultCards();
  if (cards.length === 0) {
    return { ok: false, clicked: false, aweme_id: "", message: "未找到搜索结果卡片" };
  }

  const targetIndex = Math.min(Math.max(1, index), cards.length);
  const card = cards[targetIndex - 1];
  const awemeId = extractAwemeFromCard(card) ?? "";
  scrollCardIntoView(card);
  await sleep(humanPace.posterClick());
  const clickTarget = pickSearchCardClickTarget(card);
  humanClick(clickTarget);
  await sleep(humanPace.videoFeedSettle());

  return {
    ok: true,
    clicked: true,
    aweme_id: awemeId,
    message: `已点击第 ${targetIndex} 个搜索海报`,
  };
}
