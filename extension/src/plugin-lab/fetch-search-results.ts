import {
  buildCardUrl,
  collectSearchResultCards,
  findVideoLink,
  isFeedOverlayOpen,
  isSearchResultsPage,
  pickCardAuthor,
  pickCardTitle,
  pickSearchCardClickTarget,
  resolveCardAwemeId,
  serializeCardRect,
  waitForSearchResultCards,
} from "./search-results-dom";
import { sleep } from "./search-input";
import { rememberSearchResultsUrl } from "./search-feed-open";
import {
  enableSearchNetworkHook,
  getLastSearchApiResults,
  getSearchApiDebug,
  type SearchApiItem,
  waitForSearchApiResults,
} from "./search-api";
import { detectSearchLayoutMode, ensureSearchMultiColumnLayout } from "./search-layout";

export interface FetchSearchResultsPayload {
  limit?: number;
  api_timeout_ms?: number;
}

export interface DomSearchResultItem {
  index: number;
  title: string;
  author: string;
  url: string | null;
  aweme_id: string | null;
  source: "dom";
  click_by: "dom_rect";
  rect: { top: number; left: number; width: number; height: number };
}

export type SearchResultItem = SearchApiItem | DomSearchResultItem;

const DEFAULT_API_TIMEOUT_MS = 20_000;

async function scrollSearchResultsIntoView(): Promise<void> {
  window.scrollTo({ top: 0, behavior: "auto" });
  await sleep(300);
}

/** API 截获：优先读 hook 缓存，必要时轮询等待 search/single 响应 */
async function collectViaApi(
  limit: number,
  timeoutMs: number,
): Promise<{ items: SearchApiItem[]; eventsSeen: number; lastBodyKind?: string }> {
  enableSearchNetworkHook();

  let items = (await getLastSearchApiResults()) ?? [];
  if (!items.length) {
    items = await waitForSearchApiResults({ timeoutMs, minItems: 1 });
  }

  const debug = await getSearchApiDebug();
  return {
    items: items.slice(0, limit),
    eventsSeen: debug.eventsSeen ?? 0,
    lastBodyKind: debug.lastBodyKind,
  };
}

/** DOM 兜底：仅在 API 完全截获不到时使用（坐标点击，aweme_id 可能缺失） */
async function collectViaDom(limit: number): Promise<{
  items: DomSearchResultItem[];
  onSearchPage: boolean;
  linkCount: number;
  posterCount: number;
}> {
  const onSearchPage = isSearchResultsPage();
  if (onSearchPage) rememberSearchResultsUrl();
  await scrollSearchResultsIntoView();

  let cards = await waitForSearchResultCards(12);
  if (cards.length === 0) {
    cards = collectSearchResultCards();
  }

  const items: DomSearchResultItem[] = [];

  for (let i = 0; i < cards.length && items.length < limit; i += 1) {
    const card = cards[i];
    const link = findVideoLink(card);
    const awemeId = resolveCardAwemeId(card);
    const clickTarget = pickSearchCardClickTarget(card);

    items.push({
      index: items.length + 1,
      title: pickCardTitle(card) || `搜索结果 ${items.length + 1}`,
      author: pickCardAuthor(card),
      url: awemeId ? buildCardUrl(awemeId, link) : null,
      aweme_id: awemeId,
      source: "dom",
      click_by: "dom_rect",
      rect: serializeCardRect(clickTarget),
    });
  }

  const linkCount = document.querySelectorAll('a[href*="/video/"], a[href*="modal_id="]').length;
  return {
    items,
    onSearchPage,
    linkCount,
    posterCount: cards.length,
  };
}

function buildFailureMessage(options: {
  onSearchPage: boolean;
  feedOpen: boolean;
  posterCount: number;
  linkCount: number;
  eventsSeen: number;
  lastBodyKind?: string;
}): string {
  const { onSearchPage, feedOpen, posterCount, linkCount, eventsSeen, lastBodyKind } = options;
  if (feedOpen && onSearchPage) {
    return "未找到搜索结果：当前为视频浮层，请先关闭视频详情或返回搜索列表";
  }
  if (onSearchPage) {
    return `接口与 DOM 均未获取到结果（events=${eventsSeen}, body=${lastBodyKind ?? "none"}；海报 ${posterCount} 个、链接 ${linkCount} 个）`;
  }
  return `未找到搜索结果，当前不在搜索结果页（${location.href}），请先执行步骤 7 或手动进入搜索页`;
}

/** 步骤 8：hook 截获 search 接口 → 失败再 DOM 兜底（无 CDP / Debugger） */
export async function fetchSearchResults(payload: FetchSearchResultsPayload = {}) {
  const limit = Math.max(1, Math.min(Number(payload.limit ?? 20), 50));
  const apiTimeoutMs = Math.max(
    2000,
    Math.min(Number(payload.api_timeout_ms ?? DEFAULT_API_TIMEOUT_MS), 30_000),
  );

  let layoutNote = "";
  if (isSearchResultsPage() && (detectSearchLayoutMode() === "single" || isFeedOverlayOpen())) {
    const layout = await ensureSearchMultiColumnLayout();
    layoutNote = layout.message;
    if (!layout.ok) {
      return {
        ok: false,
        count: 0,
        items: [],
        results: [],
        url: location.href,
        on_search_page: true,
        capture_method: "none" as const,
        api_count: 0,
        dom_count: 0,
        dom_link_count: 0,
        poster_count: 0,
        feed_overlay_open: isFeedOverlayOpen(),
        api_events_seen: 0,
        last_body_kind: "none",
        search_layout: detectSearchLayoutMode(),
        message: layout.message,
      };
    }
  }

  const apiResult = await collectViaApi(limit, apiTimeoutMs);
  const feedOpen = isFeedOverlayOpen();

  if (apiResult.items.length > 0) {
    return {
      ok: true,
      count: apiResult.items.length,
      items: apiResult.items,
      results: apiResult.items,
      url: location.href,
      on_search_page: isSearchResultsPage(),
      capture_method: "api" as const,
      api_count: apiResult.items.length,
      dom_count: 0,
      dom_link_count: 0,
      poster_count: 0,
      feed_overlay_open: feedOpen,
      api_events_seen: apiResult.eventsSeen,
      last_body_kind: apiResult.lastBodyKind ?? "json",
      search_layout: detectSearchLayoutMode(),
      message: layoutNote
        ? `已从 search 接口获取 ${apiResult.items.length} 条结果；${layoutNote}`
        : `已从 search 接口获取 ${apiResult.items.length} 条结果（含完整 aweme 字段）`,
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
    on_search_page: domResult.onSearchPage,
    capture_method: "dom" as const,
    api_count: 0,
    dom_count: items.length,
    dom_link_count: domResult.linkCount,
    poster_count: domResult.posterCount,
    feed_overlay_open: feedOpen,
    api_events_seen: apiResult.eventsSeen,
    last_body_kind: apiResult.lastBodyKind ?? "none",
    search_layout: detectSearchLayoutMode(),
    message:
      items.length > 0
        ? layoutNote
          ? `接口未截获到数据，已用 DOM 兜底 ${items.length} 条；${layoutNote}`
          : `接口未截获到数据，已用 DOM 兜底 ${items.length} 条（按序号+坐标点击，字段较 API 精简）`
        : buildFailureMessage({
            onSearchPage: domResult.onSearchPage,
            feedOpen,
            posterCount: domResult.posterCount,
            linkCount: domResult.linkCount,
            eventsSeen: apiResult.eventsSeen,
            lastBodyKind: apiResult.lastBodyKind,
          }),
  };
}
