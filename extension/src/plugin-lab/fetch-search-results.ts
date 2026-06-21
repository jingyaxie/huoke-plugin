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
  scrollCardIntoView,
  serializeCardRect,
  waitForSearchResultCards,
} from "./search-results-dom";
import { getLastSearchApiResults, waitForSearchApiResults } from "./search-api";

export interface FetchSearchResultsPayload {
  limit?: number;
}

/** 步骤 8：优先用步骤 7 缓存的 search/single 接口结果，否则 DOM 抓取 */
export async function fetchSearchResults(payload: FetchSearchResultsPayload = {}) {
  const limit = Math.max(1, Math.min(Number(payload.limit ?? 20), 50));

  let apiItems = (await getLastSearchApiResults()) ?? [];
  if (!apiItems.length) {
    apiItems = await waitForSearchApiResults({ timeoutMs: 2500, minItems: 1 });
  }
  if (apiItems.length > 0) {
    const items = apiItems.slice(0, limit);
    return {
      ok: true,
      count: items.length,
      items,
      results: items,
      url: location.href,
      on_search_page: isSearchResultsPage(),
      capture_method: "api",
      dom_link_count: 0,
      poster_count: 0,
      feed_overlay_open: isFeedOverlayOpen(),
      message: `已从 search/single 接口获取 ${items.length} 条结果`,
    };
  }

  const onSearchPage = isSearchResultsPage();
  const cards = onSearchPage ? await waitForSearchResultCards() : collectSearchResultCards();

  const items: Array<{
    index: number;
    title: string;
    author: string;
    url: string | null;
    aweme_id: string | null;
    click_by: "dom_rect";
    rect: { top: number; left: number; width: number; height: number };
  }> = [];

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
      click_by: "dom_rect",
      rect: serializeCardRect(clickTarget),
    });
  }

  const linkCount = document.querySelectorAll('a[href*="/video/"], a[href*="modal_id="]').length;
  const posterCount = cards.length;
  const feedOpen = isFeedOverlayOpen();

  return {
    ok: items.length > 0,
    count: items.length,
    items,
    results: items,
    url: location.href,
    on_search_page: onSearchPage,
    capture_method: "dom",
    dom_link_count: linkCount,
    poster_count: posterCount,
    feed_overlay_open: feedOpen,
    message:
      items.length > 0
        ? `已抓取 ${items.length} 条搜索结果（按序号+坐标点击，无需 aweme_id）`
        : feedOpen && onSearchPage
          ? "未找到搜索结果卡片：当前为视频浮层，请先关闭视频详情或返回搜索列表"
          : onSearchPage
            ? `未找到搜索结果卡片（已在搜索页，海报 ${posterCount} 个、视频链接 ${linkCount} 个；请确认「视频」筛选已选且列表已加载）`
            : `未找到搜索结果卡片，当前不在搜索结果页（${location.href}），请先执行步骤 7 或手动进入搜索页`,
  };
}
