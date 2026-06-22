import { buildSearchUrl } from "../../../content/platforms/kuaishou/search";
import { findAndFocusSearchBox } from "../../find-search-box";
import { inputSearchText, type InputSearchTextPayload } from "../../input-search-text";
import { findSearchInputMatch, humanClick, isVisible, randDelay, sleep } from "../../search-input";
import { swipePage, type SwipePagePayload } from "../../swipe-page";
import { rememberPlatformSearchUrl, restorePlatformSearchList } from "../../search-session";
import { buildSearchResultPayload } from "../shared/content-item";
import {
  clearKsSearchApiCache,
  enableKsSearchNetworkHook,
  extractKsSearchKeyword,
  fireKsSearchFeedRequest,
  getKsSearchApiResults,
  waitForKsSearchApiResults,
} from "./search-api";
import {
  buildDomSearchItems,
  clickKsCommentTab,
  clickKsVideoAtIndex,
  collectKsVideoCards,
  extractPhotoIdFromHref,
  isKsCommentReady,
  isKsSearchResultsPage,
  isKsVideoPage,
  scrollKsComments,
  videoDetailReady,
} from "./search-dom";
import {
  enableKsCommentNetworkHook,
  fetchKsCommentsViaApi,
  getKsCommentApiItems,
} from "./comment-api";

function findKsSearchButton(): HTMLElement | null {
  const selectors = [
    'button[class*="search"]',
    '[class*="search"] button',
    '[class*="Search"] button',
    'svg[class*="search"]',
  ];
  for (const selector of selectors) {
    const node = document.querySelector(selector) as HTMLElement | null;
    if (!node || !isVisible(node)) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width < 12 || rect.height < 12 || rect.top > 220) continue;
    return node;
  }

  const nodes = document.querySelectorAll("button, span, div, svg");
  for (let i = 0; i < nodes.length && i < 120; i += 1) {
    const node = nodes[i] as HTMLElement;
    const text = (node.textContent ?? "").replace(/\s+/g, "");
    if (text !== "搜索") continue;
    const rect = node.getBoundingClientRect();
    if (rect.width < 16 || rect.height < 12 || rect.top > 220) continue;
    return node;
  }
  return null;
}

function submitKsSearchViaInput(input: HTMLInputElement | HTMLTextAreaElement) {
  input.focus();
  input.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
  );
  input.dispatchEvent(
    new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
  );
}

async function waitForKsSearchReady(timeoutMs = 8000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (isKsSearchResultsPage(location.href)) return true;
    if (isKsSearchResultsPage() && collectKsVideoCards().length > 0) return true;
    await sleep(250);
  }
  return isKsSearchResultsPage(location.href) || collectKsVideoCards().length > 0;
}

export async function ksPrepareSearchCapture() {
  await clearKsSearchApiCache();
  enableKsSearchNetworkHook();
  await sleep(150);
  return { ok: true, message: "ks search hook ready" };
}

export async function ksSubmitSearchClick() {
  const inputMatch = findSearchInputMatch("kuaishou");
  const keyword = (inputMatch?.input?.value ?? "").trim();
  const button = findKsSearchButton();
  let method: "click_button" | "enter_key" | "navigate" | "none" = "none";

  if (button) {
    humanClick(button);
    method = "click_button";
    await sleep(randDelay(600, 1000));
  } else if (inputMatch?.input) {
    submitKsSearchViaInput(inputMatch.input);
    method = "enter_key";
    await sleep(randDelay(700, 1100));
  } else {
    return {
      ok: false,
      method: "none",
      url: location.href,
      on_search_page: false,
      message: "未找到快手搜索按钮或搜索框",
    };
  }

  if (inputMatch?.input && method === "click_button") {
    submitKsSearchViaInput(inputMatch.input);
    await sleep(randDelay(500, 800));
  }

  let ready = await waitForKsSearchReady(8000);

  const onSearchPage = isKsSearchResultsPage(location.href);
  const cardCount = collectKsVideoCards().length;
  if (onSearchPage || cardCount > 0) {
    await rememberPlatformSearchUrl(location.href, "kuaishou");
  }
  return {
    ok: ready || onSearchPage || cardCount > 0,
    method,
    keyword,
    url: location.href,
    on_search_page: onSearchPage,
    card_count: cardCount,
    needs_navigate: !ready && !onSearchPage && cardCount === 0 && keyword.length > 0,
    message: onSearchPage
      ? "已进入快手搜索结果页"
      : cardCount > 0
        ? `已加载 ${cardCount} 条搜索结果`
        : ready
          ? "已触发搜索，等待结果加载"
          : keyword
            ? "已点击搜索，等待跳转搜索结果页"
            : "未找到搜索关键词",
  };
}

export async function ksClickSearchButton() {
  await ksPrepareSearchCapture();
  const clickResult = await ksSubmitSearchClick();
  if (clickResult.needs_navigate && clickResult.keyword) {
    location.assign(buildSearchUrl(String(clickResult.keyword)));
    await waitForKsSearchReady(8_000);
  }
  return clickResult;
}

export async function ksFetchSearchResults(payload: { limit?: number; api_timeout_ms?: number } = {}) {
  const limit = Math.max(1, Math.min(Number(payload.limit ?? 20), 50));
  const timeoutMs = Math.max(2000, Math.min(Number(payload.api_timeout_ms ?? 12_000), 30_000));
  enableKsSearchNetworkHook();

  let items = await getKsSearchApiResults();
  if (!items.length) {
    items = await waitForKsSearchApiResults(timeoutMs, 1);
  }
  if (!items.length) {
    const keyword = extractKsSearchKeyword();
    if (keyword) {
      items = await fireKsSearchFeedRequest(keyword);
    }
  }
  items = items.slice(0, limit);

  if (items.length > 0) {
    await rememberPlatformSearchUrl(location.href, "kuaishou");
    return {
      ok: true,
      ...buildSearchResultPayload(items, "api"),
      url: location.href,
      on_search_page: isKsSearchResultsPage(),
      capture_method: "api" as const,
      message: `已从搜索接口获取 ${items.length} 条视频`,
    };
  }

  const domItems = buildDomSearchItems(limit);
  return {
    ok: domItems.length > 0,
    ...buildSearchResultPayload(domItems, domItems.length ? "dom" : "none"),
    url: location.href,
    on_search_page: isKsSearchResultsPage(),
    capture_method: domItems.length ? ("dom" as const) : ("none" as const),
    message:
      domItems.length > 0
        ? `接口未截获，已用 DOM 兜底 ${domItems.length} 条视频`
        : "未找到搜索结果，请确认已登录并完成搜索",
  };
}

export async function ksClickSearchVideo(payload: { video_index?: number; index?: number } = {}) {
  const index = Number(payload.video_index ?? payload.index ?? 1);
  return clickKsVideoAtIndex(index);
}

export function ksProbeSearchVideo(payload: { video_index?: number; index?: number } = {}) {
  const cards = collectKsVideoCards();
  const index = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  return {
    ok: cards.length >= index || isKsVideoPage(),
    available: cards.length,
    video_index: index,
    on_search_page: isKsSearchResultsPage(),
    is_standalone_video: isKsVideoPage(),
  };
}

export async function ksActivateComments() {
  if (isKsCommentReady()) {
    return { ok: true, sidebar_ready: true, message: "评论区已就绪" };
  }
  const clicked = await clickKsCommentTab();
  return {
    ok: clicked || isKsCommentReady(),
    sidebar_ready: isKsCommentReady(),
    message: clicked ? "已打开评论 Tab" : "未找到评论 Tab",
  };
}

export async function ksScrollCollectComments(payload: {
  scroll_rounds?: number;
  max_comments?: number;
  comment_days?: number;
} = {}) {
  const maxRounds = Math.max(1, Math.min(Number(payload.scroll_rounds ?? 8), 30));
  const maxComments = Math.max(1, Math.min(Number(payload.max_comments ?? 50), 500));
  const photoId = extractPhotoIdFromHref(location.href)
    || location.pathname.match(/\/short-video\/([0-9a-zA-Z]{8,32})/)?.[1]
    || "";

  await ksActivateComments();
  enableKsCommentNetworkHook();

  const merged = new Map<string, Record<string, unknown>>();
  let scrolledRounds = 0;
  let stoppedReason = "initial";

  const mergeApi = async () => {
    if (!photoId) return;
    let rows = await getKsCommentApiItems(photoId);
    if (!rows.length) {
      rows = await fetchKsCommentsViaApi(photoId, maxComments);
    }
    for (const row of rows) {
      merged.set(row.comment_id, {
        comment_id: row.comment_id,
        parent_comment_id: row.parent_comment_id ?? null,
        content: row.content,
        author: row.username,
        user_id: row.user_id,
        sec_uid: row.sec_uid ?? "",
        avatar_url: row.avatar_url ?? "",
        digg_count: row.digg_count ?? 0,
        create_time: row.create_time ?? null,
        source: row.source ?? "api",
      });
    }
  };

  await mergeApi();
  for (let round = 0; round < maxRounds && merged.size < maxComments; round += 1) {
    if (scrollKsComments()) scrolledRounds += 1;
    await sleep(400 + Math.floor(Math.random() * 300));
    await mergeApi();
    if (merged.size >= maxComments) {
      stoppedReason = "max_comments";
      break;
    }
  }
  if (stoppedReason === "initial" && merged.size === 0) stoppedReason = "no_comments";
  else if (stoppedReason === "initial") stoppedReason = "rounds_exhausted";

  const comments = Array.from(merged.values()).slice(0, maxComments).map((item, index) => ({
    ...item,
    index: index + 1,
  })) as Array<Record<string, unknown> & { index: number; source?: string }>;

  return {
    ok: comments.length > 0,
    count: comments.length,
    comments,
    items: comments,
    aweme_id: photoId,
    capture_method: comments.some((c) => c.source === "api") ? "api" : "dom",
    scroll_rounds: scrolledRounds,
    max_rounds: maxRounds,
    comment_days: Number(payload.comment_days ?? 0),
    stopped_reason: stoppedReason,
    url: location.href,
    message:
      comments.length > 0
        ? `已采集 ${comments.length} 条评论（滚动 ${scrolledRounds} 轮）`
        : "未采集到评论，请确认视频页已打开且已登录",
  };
}

export function ksProbeCommentSidebar() {
  return {
    ok: isKsCommentReady() || videoDetailReady(),
    sidebar_ready: isKsCommentReady(),
    is_standalone_video: isKsVideoPage(),
    feed_open: isKsVideoPage(),
    comment_item_count: 0,
  };
}

async function ksPrepareSearchForVideo(payload: { skip_restore?: boolean } = {}) {
  let restored: { restored?: boolean } = { restored: false };
  if (!payload.skip_restore) {
    if (videoDetailReady() || isKsVideoPage()) {
      await ksCloseVideoDetail();
      await sleep(randDelay(400, 650));
    }
    const restoredResult = await restorePlatformSearchList("kuaishou");
    restored = restoredResult;
    if (!isKsSearchResultsPage(location.href)) {
      return {
        ok: false,
        on_search_page: false,
        card_count: 0,
        url: location.href,
        message: restoredResult.message,
      };
    }
  } else if (!isKsSearchResultsPage(location.href)) {
    return {
      ok: false,
      on_search_page: false,
      card_count: 0,
      url: location.href,
      message: `不在搜索结果页（${location.href}）`,
    };
  }
  await rememberPlatformSearchUrl(location.href, "kuaishou");
  window.scrollTo({ top: 0, behavior: "auto" });
  await sleep(randDelay(350, 550));
  const cards = collectKsVideoCards();
  const onSearch = isKsSearchResultsPage(location.href);
  return {
    ok: onSearch,
    on_search_page: onSearch,
    card_count: cards.length,
    url: location.href,
    restored: restored.restored,
    message:
      cards.length > 0
        ? `搜索列表就绪（${cards.length} 条视频）`
        : "已在搜索结果页，但暂无可见视频卡片",
  };
}

export async function ksCloseVideoDetail() {
  if (!videoDetailReady() && !isKsVideoPage()) {
    return { ok: true, already_closed: true, message: "视频详情未打开" };
  }

  for (let i = 0; i < 2; i += 1) {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
    );
    await sleep(randDelay(250, 400));
  }
  if (!videoDetailReady() && !isKsVideoPage()) {
    return { ok: true, method: "escape", message: "已通过 Escape 关闭视频详情" };
  }

  const closeSelectors = [
    '[class*="close"]',
    ".close-btn",
    ".back-btn",
    '[aria-label*="关闭"]',
    '[aria-label*="返回"]',
  ];
  for (const selector of closeSelectors) {
    const closeBtn = document.querySelector(selector) as HTMLElement | null;
    if (!closeBtn) continue;
    humanClick(closeBtn);
    await sleep(randDelay(400, 650));
    if (!videoDetailReady() && !isKsVideoPage()) break;
  }

  return {
    ok: !isKsVideoPage() || isKsSearchResultsPage() || !videoDetailReady(),
    message:
      !isKsVideoPage() || isKsSearchResultsPage()
        ? "已关闭视频详情"
        : "已尝试关闭视频详情",
  };
}

const HANDLED = new Set([
  "plugin_lab.swipe_page",
  "plugin_lab.find_search_box",
  "plugin_lab.input_search_text",
  "plugin_lab.search_prepare",
  "plugin_lab.search_submit",
  "plugin_lab.click_search_btn",
  "plugin_lab.fetch_search_results",
  "plugin_lab.prepare_search_video",
  "plugin_lab.click_search_video",
  "plugin_lab.search_video_dom_click",
  "plugin_lab.search_video_probe",
  "plugin_lab.activate_comment_sidebar",
  "plugin_lab.click_comment_btn",
  "plugin_lab.comment_sidebar_probe",
  "plugin_lab.scroll_and_collect_comments",
  "plugin_lab.close_video_detail",
  "plugin_lab.click_filter_btn",
  "plugin_lab.click_filter_overlay",
  "plugin_lab.filter_probe",
  "plugin_lab.filter_find_option",
  "plugin_lab.send_comment",
  "plugin_lab.click_comment_avatar",
  "plugin_lab.click_follow_btn",
  "plugin_lab.click_dm_btn",
  "plugin_lab.dm_button_probe",
  "plugin_lab.dm_input_probe",
  "plugin_lab.input_dm_text",
  "plugin_lab.dm_send_probe",
  "plugin_lab.dm_send_verify",
  "plugin_lab.send_dm",
  "plugin_lab.reply_comment_probe",
  "plugin_lab.reply_comment_hover",
  "plugin_lab.reply_comment_input_probe",
  "plugin_lab.reply_comment_type",
  "plugin_lab.fetch_profile_videos",
  "plugin_lab.prepare_profile_video",
  "plugin_lab.click_profile_video",
  "plugin_lab.profile_video_dom_click",
  "plugin_lab.profile_video_probe",
  "plugin_lab.back_to_profile",
]);

export function isKuaishouLabAction(action: string): boolean {
  return HANDLED.has(action);
}

export async function dispatchKuaishouLabCommand(
  action: string,
  payload: unknown,
): Promise<unknown | undefined> {
  if (!isKuaishouLabAction(action)) return undefined;

  switch (action) {
    case "plugin_lab.swipe_page":
      return swipePage((payload ?? {}) as SwipePagePayload);
    case "plugin_lab.find_search_box":
      return findAndFocusSearchBox((payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.input_search_text":
      return inputSearchText((payload ?? {}) as InputSearchTextPayload);
    case "plugin_lab.search_prepare":
      return ksPrepareSearchCapture();
    case "plugin_lab.search_submit":
      return ksSubmitSearchClick();
    case "plugin_lab.click_search_btn":
      return ksClickSearchButton();
    case "plugin_lab.fetch_search_results":
      return ksFetchSearchResults((payload ?? {}) as { limit?: number; api_timeout_ms?: number });
    case "plugin_lab.prepare_search_video":
      return ksPrepareSearchForVideo((payload ?? {}) as { skip_restore?: boolean });
    case "plugin_lab.click_search_video":
    case "plugin_lab.search_video_dom_click":
      return ksClickSearchVideo((payload ?? {}) as { video_index?: number; index?: number });
    case "plugin_lab.search_video_probe":
      return ksProbeSearchVideo((payload ?? {}) as { video_index?: number; index?: number });
    case "plugin_lab.activate_comment_sidebar":
    case "plugin_lab.click_comment_btn":
      return ksActivateComments();
    case "plugin_lab.comment_sidebar_probe":
      return ksProbeCommentSidebar();
    case "plugin_lab.scroll_and_collect_comments":
      return ksScrollCollectComments((payload ?? {}) as {
        scroll_rounds?: number;
        max_comments?: number;
        comment_days?: number;
      });
    case "plugin_lab.close_video_detail":
      return ksCloseVideoDetail();
    case "plugin_lab.click_filter_btn":
    case "plugin_lab.click_filter_overlay":
    case "plugin_lab.filter_probe":
    case "plugin_lab.filter_find_option":
      return { ok: true, skipped: true, action, message: "快手暂不支持筛选步骤，已跳过" };
    case "plugin_lab.send_comment":
    case "plugin_lab.click_comment_avatar":
    case "plugin_lab.click_follow_btn":
    case "plugin_lab.click_dm_btn":
    case "plugin_lab.dm_button_probe":
    case "plugin_lab.dm_input_probe":
    case "plugin_lab.input_dm_text":
    case "plugin_lab.dm_send_probe":
    case "plugin_lab.dm_send_verify":
    case "plugin_lab.send_dm":
    case "plugin_lab.reply_comment_probe":
    case "plugin_lab.reply_comment_hover":
    case "plugin_lab.reply_comment_input_probe":
    case "plugin_lab.reply_comment_type":
      return { ok: false, unsupported: true, action, message: "快手插件触达尚未实现" };
    case "plugin_lab.fetch_profile_videos":
    case "plugin_lab.prepare_profile_video":
    case "plugin_lab.click_profile_video":
    case "plugin_lab.profile_video_dom_click":
    case "plugin_lab.profile_video_probe":
    case "plugin_lab.back_to_profile":
      return { ok: false, message: "快手主页作品采集尚未实现" };
    default:
      return undefined;
  }
}
