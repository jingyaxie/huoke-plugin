import {
  collectSearchResultCards,
  isSearchResultsPage,
  pickSearchCardClickTarget,
  scrollCardIntoView,
  serializeCardRect,
  waitForSearchResultCards,
} from "./search-results-dom";
import {
  classifyDouyinSearchPhase,
  clickSearchPosterAtIndex,
  isSearchFeedOverlay,
  isStandaloneVideoPage,
  openFeedViaModalId,
  readStoredSearchResultsUrl,
  recoverSearchFeedFromDetailPage,
  rememberSearchResultsUrl,
  resolveAwemeHint,
  stripModalFromSearchUrl,
  waitForSearchFeedOverlay,
} from "./search-feed-open";
import { humanClick, humanPace, randDelay, sleep } from "./search-input";
import { closeVideoDetail } from "./close-video-detail";

export interface DomPoint {
  x: number;
  y: number;
}

export interface DomRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

function centerOf(rect: DomRect): DomPoint {
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function isValidRect(rect?: DomRect | null): rect is DomRect {
  return Boolean(rect && rect.width >= 24 && rect.height >= 24);
}

async function ensureSearchListReady(): Promise<void> {
  rememberSearchResultsUrl();

  if (isStandaloneVideoPage()) {
    const searchUrl = readStoredSearchResultsUrl();
    if (searchUrl) {
      location.assign(searchUrl);
      await sleep(randDelay(700, 1000));
    } else {
      history.back();
      await sleep(randDelay(700, 1000));
    }
  }

  if (isSearchFeedOverlay()) {
    await closeVideoDetail();
    await sleep(randDelay(450, 700));
    const searchUrl = readStoredSearchResultsUrl();
    if (searchUrl && /modal_id=/i.test(location.href)) {
      location.assign(searchUrl);
      await sleep(randDelay(500, 750));
    }
  }
}

/** 打开下一个视频前：关闭浮层、滚到列表顶部、等待卡片出现 */
export async function prepareSearchForVideoClick(payload: {
  skip_restore?: boolean;
  fresh_search?: boolean;
} = {}) {
  if (!payload.skip_restore) {
    await ensureSearchListReady();
  } else if (!payload.fresh_search && !isSearchResultsPage()) {
    return {
      ok: false,
      card_count: 0,
      on_search_page: false,
      url: location.href,
      message: `不在搜索结果页（${location.href}）`,
    };
  }

  if (!isSearchResultsPage()) {
    return {
      ok: false,
      card_count: 0,
      on_search_page: false,
      url: location.href,
      message: `不在搜索结果页（${location.href}）`,
    };
  }

  rememberSearchResultsUrl(stripModalFromSearchUrl(location.href));
  window.scrollTo({ top: 0, behavior: "auto" });
  const cardWaitAttempts = payload.fresh_search ? 4 : 10;
  await sleep(payload.fresh_search ? randDelay(180, 320) : humanPace.listPrepare());
  const cards = await waitForSearchResultCards(cardWaitAttempts, payload.fresh_search);

  return {
    ok: cards.length > 0,
    card_count: cards.length,
    on_search_page: true,
    url: location.href,
    message:
      cards.length > 0
        ? `搜索列表就绪（${cards.length} 个卡片）`
        : "搜索结果页无可见视频卡片",
  };
}

export async function openSearchFeedAtIndex(payload: {
  video_index?: number;
  index?: number;
  aweme_id?: string;
  aweme_hint?: string;
  strategy?: "modal_only" | "full";
  fresh_search?: boolean;
} = {}) {
  const index = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  const awemeHint = resolveAwemeHint({ ...payload, video_index: index });
  const feedWaitMs = payload.fresh_search ? 5000 : 9000;

  if (payload.strategy === "modal_only") {
    rememberSearchResultsUrl();
    if (!awemeHint) {
      return {
        ok: false,
        feed_open: false,
        is_search_feed: false,
        mode: "modal_id",
        video_index: index,
        url: location.href,
        message: "缺少 aweme_id，无法通过 modal_id 打开 Feed 浮层",
      };
    }
    const modal = await openFeedViaModalId(awemeHint);
    const phase = classifyDouyinSearchPhase();
    return {
      ok: modal.ok && phase.is_search_feed,
      feed_open: modal.ok && phase.is_search_feed,
      is_search_feed: phase.is_search_feed,
      mode: modal.mode,
      video_index: index,
      aweme_id: awemeHint,
      url: modal.url,
      message: modal.message,
    };
  }

  const prep = await prepareSearchForVideoClick({
    skip_restore: Boolean(payload.fresh_search),
    fresh_search: Boolean(payload.fresh_search),
  });
  if (!prep.ok) {
    const { ok: _ignored, url: prepUrl, ...prepRest } = prep;
    return {
      ok: false,
      feed_open: false,
      is_search_feed: false,
      video_index: index,
      url: prepUrl ?? location.href,
      ...prepRest,
    };
  }

  if (awemeHint) {
    const modal = await openFeedViaModalId(awemeHint);
    if (modal.ok) {
      return {
        ok: true,
        feed_open: true,
        is_search_feed: true,
        mode: modal.mode,
        video_index: index,
        aweme_id: awemeHint,
        url: modal.url,
        message: modal.message,
      };
    }
  }

  const clicked = await clickSearchPosterAtIndex(index);
  let feedOpen = await waitForSearchFeedOverlay(feedWaitMs);
  let awemeId = clicked.aweme_id || awemeHint;

  if (!feedOpen && isStandaloneVideoPage() && awemeId) {
    const recovered = await recoverSearchFeedFromDetailPage(awemeId);
    feedOpen = recovered.ok;
  }

  if (!feedOpen && awemeId) {
    const retryModal = await openFeedViaModalId(awemeId);
    feedOpen = retryModal.ok;
  }

  const phase = classifyDouyinSearchPhase();
  return {
    ok: feedOpen && phase.is_search_feed,
    clicked: clicked.clicked,
    feed_open: feedOpen && phase.is_search_feed,
    is_search_feed: phase.is_search_feed,
    is_standalone_video: phase.is_standalone_video,
    phase: phase.phase,
    mode: feedOpen ? "dom_poster" : "dom_poster_failed",
    video_index: index,
    aweme_id: awemeId,
    url: location.href,
    message: phase.is_search_feed
      ? `已打开第 ${index} 个搜索 Feed 浮层`
      : phase.is_standalone_video
        ? "误入独立视频详情页（评论在下方），未能恢复 Feed 浮层"
        : clicked.message,
  };
}

/** Content 侧 DOM 点击（CDP 失败时的兜底） */
export async function clickSearchVideoInContent(payload: {
  video_index?: number;
  index?: number;
  aweme_id?: string;
  aweme_hint?: string;
  strategy?: "modal_only" | "full";
  fresh_search?: boolean;
} = {}) {
  const result = await openSearchFeedAtIndex(payload);
  return {
    ...result,
    mode: result.mode ?? "dom_click",
  };
}

/** 供 background 探测搜索结果视频点击坐标（按序号，不依赖 aweme_id） */
export function probeSearchVideoCard(payload: {
  video_index?: number;
  index?: number;
  rect?: DomRect;
  status_only?: boolean;
  aweme_id?: string;
  aweme_hint?: string;
} = {}) {
  const index = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  const url = location.href;
  const phase = classifyDouyinSearchPhase(url);
  const feedOpen = phase.is_search_feed;

  if (payload.status_only) {
    return {
      ok: true,
      video_index: index,
      feed_open: feedOpen,
      is_search_feed: feedOpen,
      is_standalone_video: phase.is_standalone_video,
      phase: phase.phase,
      url,
      message: feedOpen ? "搜索 Feed 浮层已打开" : "等待搜索 Feed 浮层",
    };
  }

  if (feedOpen) {
    return {
      ok: false,
      video_index: index,
      available: 0,
      feed_open: true,
      is_search_feed: true,
      click_by: "needs_close",
      url,
      message: "搜索 Feed 浮层已打开，需先关闭再点击下一个",
    };
  }

  if (phase.is_standalone_video) {
    const awemeHint = resolveAwemeHint({ ...payload, video_index: index });
    return {
      ok: false,
      video_index: index,
      feed_open: false,
      is_standalone_video: true,
      phase: phase.phase,
      aweme_id: awemeHint,
      url,
      message: "当前在独立视频详情页，需通过 modal_id 恢复搜索 Feed",
    };
  }

  if (isValidRect(payload.rect)) {
    const cards = collectSearchResultCards();
    if (cards.length > 0) {
      const targetIndex = Math.min(index, cards.length);
      const target = cards[targetIndex - 1];
      scrollCardIntoView(target);
      const clickTarget = pickSearchCardClickTarget(target);
      const rect = serializeCardRect(clickTarget);
      return {
        ok: true,
        video_index: targetIndex,
        available: cards.length,
        center: centerOf(rect),
        rect,
        feed_open: false,
        click_by: "dom_index",
        aweme_id: resolveAwemeHint({ ...payload, video_index: targetIndex }),
        url,
        message: `找到第 ${targetIndex} 个视频海报（DOM 坐标点击）`,
      };
    }

    return {
      ok: true,
      video_index: index,
      available: 0,
      center: centerOf(payload.rect),
      rect: payload.rect,
      feed_open: false,
      click_by: "cached_rect",
      url,
      message: `使用步骤 8 缓存的第 ${index} 个卡片坐标`,
    };
  }

  const cards = collectSearchResultCards();
  if (cards.length > 0) {
    const targetIndex = Math.min(index, cards.length);
    const target = cards[targetIndex - 1];
    scrollCardIntoView(target);
    const clickTarget = pickSearchCardClickTarget(target);
    const rect = serializeCardRect(clickTarget);
    return {
      ok: true,
      video_index: targetIndex,
      available: cards.length,
      center: centerOf(rect),
      rect,
      feed_open: false,
      click_by: "dom_index",
      aweme_id: resolveAwemeHint({ ...payload, video_index: targetIndex }),
      url,
      message: `找到第 ${targetIndex} 个视频海报（DOM 坐标点击）`,
    };
  }

  return {
    ok: false,
    video_index: index,
    available: 0,
    feed_open: false,
    url,
    message: "未找到搜索结果视频卡片",
  };
}

export async function clickSearchVideoFallback(payload: {
  video_index?: number;
  index?: number;
  aweme_id?: string;
  aweme_hint?: string;
} = {}) {
  return clickSearchVideoInContent(payload);
}
