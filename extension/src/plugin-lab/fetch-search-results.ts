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
  /** 分页滚动后抓数：不滚回顶部，并等待 API 缓存条目数超过 baseline_count */
  preserve_scroll_position?: boolean;
  /** 与 preserve_scroll_position 联用：仅当截获条目数大于该值时才视为成功 */
  baseline_count?: number;
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
  options: { minItems?: number; waitForGrowth?: boolean } = {},
): Promise<{ items: SearchApiItem[]; eventsSeen: number; lastBodyKind?: string }> {
  enableSearchNetworkHook();

  const minItems = Math.max(1, options.minItems ?? 1);
  const initialDebug = await getSearchApiDebug();
  const initialEvents = initialDebug.eventsSeen ?? 0;
  const initialItems = (await getLastSearchApiResults()) ?? [];
  const initialCount = initialItems.length;

  let items = initialItems;

  if (options.waitForGrowth) {
    const growthTimeout = Math.min(timeoutMs, 8_000);
    const deadline = Date.now() + growthTimeout;
    while (Date.now() < deadline) {
      const debug = await getSearchApiDebug();
      const next = (await getLastSearchApiResults()) ?? [];
      if (
        next.length > initialCount ||
        (debug.eventsSeen ?? 0) > initialEvents
      ) {
        items = next;
        break;
      }
      await sleep(250);
    }
  } else if (!items.length || items.length < minItems) {
    items = await waitForSearchApiResults({ timeoutMs, minItems });
  }

  const debug = await getSearchApiDebug();
  return {
    items: items.slice(0, limit),
    eventsSeen: debug.eventsSeen ?? 0,
    lastBodyKind: debug.lastBodyKind,
  };
}

/** DOM 兜底：仅在 API 完全截获不到时使用（坐标点击，aweme_id 可能缺失） */
async function collectViaDom(
  limit: number,
  preserveScroll = false,
  indexOffset = 0,
): Promise<{
  items: DomSearchResultItem[];
  onSearchPage: boolean;
  linkCount: number;
  posterCount: number;
}> {
  const onSearchPage = isSearchResultsPage();
  if (onSearchPage) rememberSearchResultsUrl();
  if (!preserveScroll) {
    await scrollSearchResultsIntoView();
  }

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
      index: indexOffset + items.length + 1,
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
  const preserveScroll = Boolean(payload.preserve_scroll_position);
  const baselineCount = Math.max(0, Number(payload.baseline_count ?? 0));
  const minApiItems = preserveScroll && baselineCount > 0 ? baselineCount + 1 : 1;

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

  const apiResult = await collectViaApi(limit, apiTimeoutMs, {
    minItems: minApiItems,
    waitForGrowth: preserveScroll && baselineCount > 0,
  });
  const feedOpen = isFeedOverlayOpen();

  const apiHasNewItems =
    apiResult.items.length > 0 &&
    (!preserveScroll || baselineCount <= 0 || apiResult.items.length > baselineCount);

  if (apiHasNewItems) {
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

  const domResult = await collectViaDom(limit, preserveScroll, baselineCount);
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
