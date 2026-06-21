import {
  collectProfileVideoCards,
  isProfileListPage,
  profileFeedOpen,
  rememberProfileUrl,
  waitForProfileVideoCards,
} from "./profile-video-dom";
import { closeVideoDetail } from "./close-video-detail";
import { sleep, randDelay } from "./search-input";
import {
  enableProfileNetworkHook,
  getLastProfileApiResults,
  getProfileApiDebug,
  type ProfileApiItem,
  waitForProfileApiResults,
} from "./profile-api";

export interface FetchProfileVideosPayload {
  limit?: number;
  api_timeout_ms?: number;
}

export interface DomProfileVideoItem {
  index: number;
  title: string;
  author: string;
  url: string | null;
  aweme_id: string | null;
  source: "dom";
  click_by: "dom_rect";
  rect: { top: number; left: number; width: number; height: number };
}

export type ProfileVideoItem = ProfileApiItem | DomProfileVideoItem;

const DEFAULT_API_TIMEOUT_MS = 12_000;

/** 优先截获 aweme/post 接口；首屏主页加载通常已触发，无需滑动 */
async function collectViaApi(
  limit: number,
  timeoutMs: number,
): Promise<{ items: ProfileApiItem[]; eventsSeen: number; lastBodyKind?: string }> {
  enableProfileNetworkHook();

  let items = (await getLastProfileApiResults()) ?? [];
  if (!items.length) {
    items = await waitForProfileApiResults({ timeoutMs, minItems: 1 });
  }

  const debug = await getProfileApiDebug();
  return {
    items: items.slice(0, limit),
    eventsSeen: debug.eventsSeen ?? 0,
    lastBodyKind: debug.lastBodyKind,
  };
}

/** DOM 兜底：不滑动，只读当前可见卡片 */
async function collectViaDom(limit: number): Promise<{
  items: DomProfileVideoItem[];
  onProfilePage: boolean;
  linkCount: number;
  posterCount: number;
}> {
  rememberProfileUrl();
  const onProfilePage = isProfileListPage();
  const cards = onProfilePage ? await waitForProfileVideoCards(limit, 8) : collectProfileVideoCards(limit);

  const items: DomProfileVideoItem[] = cards.slice(0, limit).map((card) => ({
    index: card.index,
    title: `主页作品 ${card.index}`,
    author: "",
    url: `https://www.douyin.com/video/${card.aweme_id}`,
    aweme_id: card.aweme_id,
    source: "dom" as const,
    click_by: "dom_rect" as const,
    rect: card.rect,
  }));

  const linkCount = document.querySelectorAll('a[href*="/video/"], a[href*="modal_id="]').length;
  return {
    items,
    onProfilePage,
    linkCount,
    posterCount: cards.length,
  };
}

function buildFailureMessage(options: {
  onProfilePage: boolean;
  feedOpen: boolean;
  posterCount: number;
  linkCount: number;
  eventsSeen: number;
  lastBodyKind?: string;
}): string {
  const { onProfilePage, feedOpen, posterCount, linkCount, eventsSeen, lastBodyKind } = options;
  if (feedOpen && onProfilePage) {
    return "未找到主页作品：当前为视频浮层，请先关闭视频详情回到作品列表";
  }
  if (onProfilePage) {
    return `接口与 DOM 均未获取到主页作品（events=${eventsSeen}, body=${lastBodyKind ?? "none"}；卡片 ${posterCount} 个、链接 ${linkCount} 个）`;
  }
  return `不在用户主页（${location.href}），请先打开博主主页`;
}

/** 主页作品列表：优先 aweme/post 接口截获，失败再 DOM 兜底（不滑动） */
export async function fetchProfileVideos(payload: FetchProfileVideosPayload = {}) {
  const limit = Math.max(1, Math.min(Number(payload.limit ?? 20), 50));
  const apiTimeoutMs = Math.max(
    2000,
    Math.min(Number(payload.api_timeout_ms ?? DEFAULT_API_TIMEOUT_MS), 30_000),
  );

  if (profileFeedOpen()) {
    await closeVideoDetail();
    await sleep(randDelay(450, 700));
  }
  rememberProfileUrl();

  const apiResult = await collectViaApi(limit, apiTimeoutMs);
  const feedOpen = profileFeedOpen();

  if (apiResult.items.length > 0) {
    return {
      ok: true,
      count: apiResult.items.length,
      items: apiResult.items,
      results: apiResult.items,
      url: location.href,
      on_profile_page: isProfileListPage(),
      capture_method: "api" as const,
      api_count: apiResult.items.length,
      dom_count: 0,
      dom_link_count: 0,
      poster_count: 0,
      feed_overlay_open: feedOpen,
      api_events_seen: apiResult.eventsSeen,
      last_body_kind: apiResult.lastBodyKind ?? "json",
      message: `已从 aweme/post 接口获取 ${apiResult.items.length} 个主页作品`,
    };
  }

  const domResult = await collectViaDom(limit);
  const items = domResult.items;

  return {
    ok: items.length > 0,
    count: items.length,
    items,
    results: items,
    url: location.href,
    on_profile_page: domResult.onProfilePage,
    capture_method: "dom" as const,
    api_count: 0,
    dom_count: items.length,
    dom_link_count: domResult.linkCount,
    poster_count: domResult.posterCount,
    feed_overlay_open: feedOpen,
    api_events_seen: apiResult.eventsSeen,
    last_body_kind: apiResult.lastBodyKind ?? "none",
    message:
      items.length > 0
        ? `接口未截获到数据，已用 DOM 兜底 ${items.length} 个主页作品（不滑动）`
        : buildFailureMessage({
            onProfilePage: domResult.onProfilePage,
            feedOpen,
            posterCount: domResult.posterCount,
            linkCount: domResult.linkCount,
            eventsSeen: apiResult.eventsSeen,
            lastBodyKind: apiResult.lastBodyKind,
          }),
  };
}
