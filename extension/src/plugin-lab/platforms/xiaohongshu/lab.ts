import { findAndFocusSearchBox } from "../../find-search-box";
import { inputSearchText, type InputSearchTextPayload } from "../../input-search-text";
import { findSearchInputMatch, humanClick, isVisible, randDelay, sleep } from "../../search-input";
import { swipePage, type SwipePagePayload } from "../../swipe-page";
import { rememberPlatformSearchUrl, restorePlatformSearchList } from "../../search-session";
import { buildSearchResultPayload } from "../shared/content-item";
import {
  clearXhsSearchApiCache,
  enableXhsSearchNetworkHook,
  getXhsSearchApiResults,
  waitForXhsSearchApiResults,
} from "./search-api";
import {
  buildDomSearchItems,
  clickXhsCommentTab,
  clickXhsNoteAtIndex,
  collectXhsNoteCards,
  extractNoteIdFromHref,
  isXhsCommentReady,
  isXhsNotePage,
  isXhsSearchResultsPage,
  noteDetailReady,
  scrollXhsComments,
} from "./search-dom";
import {
  enableXhsCommentNetworkHook,
  getXhsCommentApiItems,
} from "./comment-api";

const XHS_COMMENT_ITEM_SELECTORS = [
  '[class*="comment-item"]',
  '[class*="CommentItem"]',
  ".note-comment-item",
  ".parent-comment",
  ".comment-inner-container",
] as const;

function xhsShortText(node: Element | null, max = 240): string {
  return (node?.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, max);
}

function parseXhsCommentTime(text: string): number | null {
  const value = String(text || "").replace(/\s+/g, "").trim();
  if (!value) return null;
  const now = Date.now();
  const minutes = value.match(/(\d+)分钟前/);
  if (minutes) return Math.floor((now - Number(minutes[1]) * 60_000) / 1000);
  const hours = value.match(/(\d+)小时前/);
  if (hours) return Math.floor((now - Number(hours[1]) * 3_600_000) / 1000);
  const days = value.match(/(\d+)天前/);
  if (days) return Math.floor((now - Number(days[1]) * 86_400_000) / 1000);
  const monthDay = value.match(/(?:\d{4}-)?(\d{1,2})-(\d{1,2})/);
  if (monthDay) {
    const year = value.match(/\d{4}-/) ? Number(value.slice(0, 4)) : new Date().getFullYear();
    const ts = new Date(year, Number(monthDay[1]) - 1, Number(monthDay[2])).getTime();
    return Number.isFinite(ts) ? Math.floor(ts / 1000) : null;
  }
  return null;
}

function xhsProfileUrl(userId: unknown): string {
  const id = String(userId ?? "").trim();
  return id ? `https://www.xiaohongshu.com/user/profile/${id}` : "";
}

function collectXhsDomComments(): Array<Record<string, unknown>> {
  const nodes: HTMLElement[] = [];
  const seenNodes = new Set<HTMLElement>();
  for (const selector of XHS_COMMENT_ITEM_SELECTORS) {
    document.querySelectorAll(selector).forEach((node) => {
      if (!(node instanceof HTMLElement) || seenNodes.has(node) || !isVisible(node)) return;
      const rect = node.getBoundingClientRect();
      if (rect.height < 18 || rect.width < 80) return;
      const text = xhsShortText(node, 500);
      if (text.length < 2 || !/回复|点赞|分钟前|小时前|天前|\d{1,2}-\d{1,2}/.test(text)) return;
      seenNodes.add(node);
      nodes.push(node);
    });
  }

  const rows: Array<Record<string, unknown>> = [];
  const seenKeys = new Set<string>();
  for (const node of nodes.slice(0, 120)) {
    const author = xhsShortText(
      node.querySelector('[class*="author"], [class*="name"], [class*="nickname"], a[href*="/user/profile"]'),
      60,
    ).replace(/^(作者|博主)\s*/, "") || "—";
    const content =
      xhsShortText(node.querySelector('[class*="content"], [class*="text"], .note-text'), 400) ||
      xhsShortText(node, 400);
    const cleaned = content
      .replace(author, "")
      .replace(/(\d+分钟前|\d+小时前|\d+天前|(?:\d{4}-)?\d{1,2}-\d{1,2}).*$/u, "")
      .replace(/回复|点赞|展开\d*条?回复/g, "")
      .trim();
    if (!cleaned || cleaned.length < 2 || cleaned === author) continue;

    let createTime: number | null = null;
    const timeNodes = node.querySelectorAll('[class*="time"], [class*="date"], span, div');
    for (let i = 0; i < timeNodes.length && i < 24; i += 1) {
      createTime = parseXhsCommentTime(xhsShortText(timeNodes[i], 48));
      if (createTime) break;
    }
    if (!createTime) createTime = parseXhsCommentTime(xhsShortText(node, 500));

    const directId = node.getAttribute("data-comment-id") || node.getAttribute("data-id") || "";
    const key = directId || `${author}|${cleaned.slice(0, 80)}`;
    if (seenKeys.has(key)) continue;
    seenKeys.add(key);
    const userUrl = (node.querySelector('a[href*="/user/profile"]') as HTMLAnchorElement | null)?.href ?? "";
    const userId = userUrl.match(/\/user\/profile\/([^/?#]+)/)?.[1] ?? "";
    rows.push({
      comment_id: directId || `dom_${Math.abs(key.split("").reduce((acc, ch) => ((acc << 5) - acc + ch.charCodeAt(0)) | 0, 0))}`,
      parent_comment_id: null,
      content: cleaned,
      author,
      user_id: userId,
      sec_uid: "",
      user_url: userUrl || xhsProfileUrl(userId),
      profile_url: userUrl || xhsProfileUrl(userId),
      avatar_url: (node.querySelector("img") as HTMLImageElement | null)?.currentSrc || "",
      digg_count: 0,
      create_time: createTime,
      source: "dom",
    });
  }
  return rows;
}

const XHS_SEARCH_BTN_SELECTORS = [
  "#search-input-in-feeds .submit-button-wrapper:not(.disabled)",
  "#search-input-in-feeds .bottom-box-right-submit-button",
  ".search-box-in-content .submit-button-wrapper:not(.disabled)",
  ".search-area-in-header .submit-button-wrapper:not(.disabled)",
] as const;

function findXhsSearchButton(): HTMLElement | null {
  for (const selector of XHS_SEARCH_BTN_SELECTORS) {
    const node = document.querySelector(selector);
    if (node instanceof HTMLElement && node.getBoundingClientRect().width > 8) {
      return node;
    }
  }
  const nodes = document.querySelectorAll("button, span, div");
  for (let i = 0; i < nodes.length && i < 120; i += 1) {
    const node = nodes[i] as HTMLElement;
    const text = (node.textContent ?? "").replace(/\s+/g, "");
    if (text !== "搜索") continue;
    const rect = node.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 14 || rect.top > 260) continue;
    return node;
  }
  return null;
}

export async function xhsPrepareSearchCapture() {
  await clearXhsSearchApiCache();
  enableXhsSearchNetworkHook();
  await sleep(150);
  return { ok: true, message: "xhs search hook ready" };
}

export async function xhsSubmitSearchClick() {
  const beforeUrl = location.href;
  const inputMatch = findSearchInputMatch("xiaohongshu");
  const button = findXhsSearchButton();
  const beforeCards = collectXhsNoteCards().length;

  if (inputMatch?.input) {
    inputMatch.input.focus();
    inputMatch.input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
    );
    inputMatch.input.dispatchEvent(
      new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
    );
    await sleep(randDelay(900, 1300));
  }

  if (location.href === beforeUrl && button) {
    humanClick(button);
    await sleep(randDelay(700, 1100));
  } else if (!inputMatch?.input && !button) {
    return {
      ok: false,
      method: "none",
      url: location.href,
      on_search_page: false,
      message: "未找到小红书搜索按钮或搜索框",
    };
  }

  if (inputMatch?.input) {
    inputMatch.input.blur();
  }

  if (location.href === beforeUrl && inputMatch?.input) {
    inputMatch.input.focus();
    inputMatch.input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
    );
    inputMatch.input.dispatchEvent(
      new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
    );
    await sleep(randDelay(900, 1300));
  }

  const isSubmitted = () => {
    if (location.href !== beforeUrl && /search/i.test(location.href)) return true;
    if (/search_result/i.test(location.href)) return true;
    return collectXhsNoteCards().length > beforeCards;
  };

  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    if (isSubmitted()) break;
    await sleep(250);
  }

  if (!isSubmitted()) {
    return {
      ok: false,
      method: inputMatch?.input ? (button ? "enter_key_then_click" : "enter_key") : "click_button",
      url: location.href,
      on_search_page: false,
      message: "已输入关键词，但小红书未进入搜索结果页",
    };
  }

  if (isXhsSearchResultsPage(location.href)) {
    await rememberPlatformSearchUrl(location.href, "xiaohongshu");
  }

  const onSearchPage = /search_result/i.test(location.href) || (location.href !== beforeUrl && /search/i.test(location.href));
  return {
    ok: true,
    method: inputMatch?.input ? (button ? "enter_key_then_click" : "enter_key") : "click_button",
    url: location.href,
    on_search_page: onSearchPage,
    message: onSearchPage ? "已进入小红书搜索结果页" : "已触发搜索，等待结果加载",
  };
}

async function xhsPrepareSearchForVideo(payload: { skip_restore?: boolean } = {}) {
  let restored: { restored?: boolean } = { restored: false };
  if (!payload.skip_restore) {
    if (noteDetailReady() || isXhsNotePage()) {
      await xhsCloseNoteDetail();
      await sleep(randDelay(400, 650));
    }
    const restoredResult = await restorePlatformSearchList("xiaohongshu");
    restored = restoredResult;
    if (!isXhsSearchResultsPage(location.href)) {
      return {
        ok: false,
        on_search_page: false,
        card_count: 0,
        url: location.href,
        message: restoredResult.message,
      };
    }
  } else if (!isXhsSearchResultsPage(location.href)) {
    return {
      ok: false,
      on_search_page: false,
      card_count: 0,
      url: location.href,
      message: `不在搜索结果页（${location.href}）`,
    };
  }
  await rememberPlatformSearchUrl(location.href, "xiaohongshu");
  window.scrollTo({ top: 0, behavior: "auto" });
  await sleep(randDelay(350, 550));
  const cards = collectXhsNoteCards();
  const apiItems = cards.length > 0 ? [] : await getXhsSearchApiResults();
  const available = cards.length || apiItems.length;
  return {
    ok: available > 0,
    on_search_page: true,
    card_count: cards.length,
    api_count: apiItems.length,
    url: location.href,
    restored: restored.restored,
    message:
      cards.length > 0
        ? `搜索列表就绪（${cards.length} 条笔记）`
        : apiItems.length > 0
          ? `搜索接口结果就绪（${apiItems.length} 条笔记），当前无可见卡片`
        : "已在搜索结果页，但暂无可见笔记卡片",
  };
}

export async function xhsClickSearchButton() {
  await xhsPrepareSearchCapture();
  return xhsSubmitSearchClick();
}

export async function xhsFetchSearchResults(payload: { limit?: number; api_timeout_ms?: number } = {}) {
  const limit = Math.max(1, Math.min(Number(payload.limit ?? 20), 50));
  const timeoutMs = Math.max(2000, Math.min(Number(payload.api_timeout_ms ?? 12_000), 30_000));
  enableXhsSearchNetworkHook();

  let items = await getXhsSearchApiResults();
  if (!items.length) {
    items = await waitForXhsSearchApiResults(timeoutMs, 1);
  }
  items = items.slice(0, limit);

  if (items.length > 0) {
    await rememberPlatformSearchUrl(location.href, "xiaohongshu");
    return {
      ok: true,
      ...buildSearchResultPayload(items, "api"),
      url: location.href,
      on_search_page: isXhsSearchResultsPage(),
      capture_method: "api" as const,
      message: `已从搜索接口获取 ${items.length} 条笔记`,
    };
  }

  const domItems = buildDomSearchItems(limit);
  return {
    ok: domItems.length > 0,
    ...buildSearchResultPayload(domItems, domItems.length ? "dom" : "none"),
    url: location.href,
    on_search_page: isXhsSearchResultsPage(),
    capture_method: domItems.length ? ("dom" as const) : ("none" as const),
    message:
      domItems.length > 0
        ? `接口未截获，已用 DOM 兜底 ${domItems.length} 条笔记`
        : "未找到搜索结果，请确认已登录并完成搜索",
  };
}

export async function xhsClickSearchNote(payload: { video_index?: number; index?: number } = {}) {
  const index = Number(payload.video_index ?? payload.index ?? 1);
  return clickXhsNoteAtIndex(index);
}

export function xhsProbeSearchNote(payload: { video_index?: number; index?: number } = {}) {
  const cards = collectXhsNoteCards();
  const index = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  return {
    ok: cards.length >= index,
    available: cards.length,
    video_index: index,
    on_search_page: isXhsSearchResultsPage(),
  };
}

export async function xhsActivateComments() {
  if (isXhsCommentReady()) {
    return { ok: true, sidebar_ready: true, message: "评论区已就绪" };
  }
  const clicked = await clickXhsCommentTab();
  return {
    ok: clicked || isXhsCommentReady(),
    sidebar_ready: isXhsCommentReady(),
    message: clicked ? "已打开评论 Tab" : "未找到评论 Tab，尝试滚动到评论区",
  };
}

export async function xhsScrollCollectComments(payload: {
  scroll_rounds?: number;
  max_comments?: number;
  comment_days?: number;
} = {}) {
  const maxRounds = Math.max(1, Math.min(Number(payload.scroll_rounds ?? 8), 30));
  const maxComments = Math.max(1, Math.min(Number(payload.max_comments ?? 50), 500));
  const commentDays = Math.max(0, Number(payload.comment_days ?? 0));
  const noteId = extractNoteIdFromHref(location.href) || location.pathname.match(/\/explore\/([0-9a-fA-F]{16,32})/)?.[1] || "";
  const cutoff = commentDays > 0 ? Math.floor(Date.now() / 1000) - commentDays * 86400 : null;

  await xhsActivateComments();
  enableXhsCommentNetworkHook();

  const merged = new Map<string, Record<string, unknown>>();
  let scrolledRounds = 0;
  let stoppedReason = "initial";
  let unchangedRounds = 0;

  const mergeApi = async () => {
    if (!noteId) return;
    const rows = await getXhsCommentApiItems(noteId);
    for (const row of rows) {
      merged.set(row.comment_id, {
        comment_id: row.comment_id,
        parent_comment_id: row.parent_comment_id ?? null,
        content: row.content,
        author: row.username,
        user_id: row.user_id,
        sec_uid: row.sec_uid ?? "",
        user_url: xhsProfileUrl(row.user_id),
        profile_url: xhsProfileUrl(row.user_id),
        avatar_url: row.avatar_url ?? "",
        digg_count: row.digg_count ?? 0,
        create_time: row.create_time ?? null,
        source: row.source ?? "api",
      });
    }
  };
  const mergeDom = () => {
    const rows = collectXhsDomComments();
    for (const row of rows) {
      const commentId = String(row.comment_id ?? "").trim();
      if (!commentId) continue;
      if (!merged.has(commentId)) {
        merged.set(commentId, row);
        continue;
      }
      const prev = merged.get(commentId) ?? {};
      merged.set(commentId, {
        ...prev,
        author: prev.author || row.author,
        user_id: prev.user_id || row.user_id,
        user_url: prev.user_url || row.user_url,
        profile_url: prev.profile_url || row.profile_url,
        avatar_url: prev.avatar_url || row.avatar_url,
        create_time: prev.create_time || row.create_time,
      });
    }
  };

  const validComments = () =>
    Array.from(merged.values()).filter((item) => {
      const ts = Number(item.create_time ?? 0);
      return cutoff === null || !ts || ts >= cutoff;
    });
  const allKnownTimesOlderThanCutoff = () => {
    if (cutoff === null || merged.size === 0) return false;
    const times = Array.from(merged.values())
      .map((item) => Number(item.create_time ?? 0))
      .filter((ts) => ts > 0);
    return times.length > 0 && Math.max(...times) < cutoff;
  };

  await mergeApi();
  mergeDom();
  for (let round = 0; round < maxRounds && validComments().length < maxComments; round += 1) {
    const before = merged.size;
    if (scrollXhsComments()) scrolledRounds += 1;
    await sleep(700 + Math.floor(Math.random() * 500));
    await mergeApi();
    mergeDom();
    unchangedRounds = merged.size === before ? unchangedRounds + 1 : 0;
    if (validComments().length >= maxComments) {
      stoppedReason = "max_comments";
      break;
    }
    if (commentDays > 0 && unchangedRounds >= 3 && allKnownTimesOlderThanCutoff()) {
      stoppedReason = "comment_days";
      break;
    }
    if (unchangedRounds >= 4) {
      stoppedReason = "no_more_comments";
      break;
    }
  }
  if (stoppedReason === "initial" && merged.size === 0) {
    stoppedReason = "no_comments";
  } else if (stoppedReason === "initial" && validComments().length === 0 && commentDays > 0) {
    stoppedReason = "comment_days_all_filtered";
  } else if (stoppedReason === "initial") {
    stoppedReason = "rounds_exhausted";
  }

  const skippedByDays = merged.size - validComments().length;
  const comments = validComments().slice(0, maxComments).map((item, index) => ({
    ...item,
    index: index + 1,
  })) as Array<Record<string, unknown> & { index: number; source?: string }>;

  return {
    ok: comments.length > 0,
    count: comments.length,
    comments,
    items: comments,
    aweme_id: noteId,
    capture_method: comments.some((c) => c.source === "api") ? "api" : "dom",
    scroll_rounds: scrolledRounds,
    max_rounds: maxRounds,
    seen_total: merged.size,
    skipped_by_days: skippedByDays,
    comment_days: commentDays,
    unchanged_rounds: unchangedRounds,
    stopped_reason: stoppedReason,
    url: location.href,
    message:
      comments.length > 0
        ? `已采集 ${comments.length} 条评论（滚动 ${scrolledRounds} 轮）`
        : "未采集到评论，请确认笔记页已打开且已登录",
  };
}

export function xhsProbeCommentSidebar() {
  return {
    ok: isXhsCommentReady() || noteDetailReady(),
    sidebar_ready: isXhsCommentReady(),
    is_standalone_video: isXhsNotePage(),
    feed_open: isXhsNotePage(),
    comment_item_count: 0,
  };
}

const XHS_CLOSE_SELECTORS = [
  ".close-circle",
  ".close-box",
  '[class*="close-circle"]',
  '[class*="close-box"]',
  '[class*="close-wrapper"]',
  '[aria-label="关闭"]',
  'button[aria-label="关闭"]',
] as const;

export async function xhsCloseNoteDetail() {
  if (!noteDetailReady()) {
    return { ok: true, already_closed: true, message: "笔记详情未打开" };
  }

  for (let i = 0; i < 2; i += 1) {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
    );
    await sleep(randDelay(250, 400));
  }
  if (!noteDetailReady()) {
    return { ok: true, method: "escape", message: "已通过 Escape 关闭笔记详情" };
  }

  for (const selector of XHS_CLOSE_SELECTORS) {
    const node = document.querySelector(selector) as HTMLElement | null;
    if (!node || !isVisible(node)) continue;
    humanClick(node);
    await sleep(randDelay(400, 650));
    if (!noteDetailReady()) break;
  }

  if (noteDetailReady()) {
    const masks = document.querySelectorAll('[class*="mask"], [class*="Mask"], .overlay');
    for (let i = 0; i < masks.length; i += 1) {
      const mask = masks[i] as HTMLElement;
      if (!isVisible(mask)) continue;
      const rect = mask.getBoundingClientRect();
      if (rect.width < window.innerWidth * 0.5) continue;
      humanClick(mask);
      await sleep(randDelay(350, 550));
      if (!noteDetailReady()) break;
    }
  }

  if (noteDetailReady() && /\/explore\/[0-9a-fA-F]{16,32}/i.test(location.href)) {
    window.history.back();
    await sleep(randDelay(500, 800));
  }

  const closed = !noteDetailReady();
  return {
    ok: closed,
    method: closed ? "close" : "attempt",
    message: closed ? "已关闭笔记详情" : "已尝试关闭笔记详情",
  };
}

export function xhsNoOpFilter(action: string) {
  return {
    ok: true,
    skipped: true,
    action,
    message: "小红书暂不支持筛选步骤，已跳过",
  };
}

export function xhsUnsupportedOutreach(action: string) {
  return {
    ok: false,
    unsupported: true,
    action,
    message: "小红书插件触达尚未实现",
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

export function isXiaohongshuLabAction(action: string): boolean {
  return HANDLED.has(action);
}

export async function dispatchXiaohongshuLabCommand(
  action: string,
  payload: unknown,
): Promise<unknown | undefined> {
  if (!isXiaohongshuLabAction(action)) return undefined;

  switch (action) {
    case "plugin_lab.swipe_page":
      return swipePage((payload ?? {}) as SwipePagePayload);
    case "plugin_lab.find_search_box":
      return findAndFocusSearchBox((payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.input_search_text":
      return inputSearchText((payload ?? {}) as InputSearchTextPayload);
    case "plugin_lab.search_prepare":
      return xhsPrepareSearchCapture();
    case "plugin_lab.search_submit":
      return xhsSubmitSearchClick();
    case "plugin_lab.click_search_btn":
      return xhsClickSearchButton();
    case "plugin_lab.fetch_search_results":
      return xhsFetchSearchResults((payload ?? {}) as { limit?: number; api_timeout_ms?: number });
    case "plugin_lab.prepare_search_video":
      return xhsPrepareSearchForVideo((payload ?? {}) as { skip_restore?: boolean });
    case "plugin_lab.click_search_video":
    case "plugin_lab.search_video_dom_click":
      return xhsClickSearchNote((payload ?? {}) as { video_index?: number; index?: number });
    case "plugin_lab.search_video_probe":
      return xhsProbeSearchNote((payload ?? {}) as { video_index?: number; index?: number });
    case "plugin_lab.activate_comment_sidebar":
    case "plugin_lab.click_comment_btn":
      return xhsActivateComments();
    case "plugin_lab.comment_sidebar_probe":
      return xhsProbeCommentSidebar();
    case "plugin_lab.scroll_and_collect_comments":
      return xhsScrollCollectComments((payload ?? {}) as {
        scroll_rounds?: number;
        max_comments?: number;
        comment_days?: number;
      });
    case "plugin_lab.close_video_detail":
      return xhsCloseNoteDetail();
    case "plugin_lab.click_filter_btn":
    case "plugin_lab.click_filter_overlay":
    case "plugin_lab.filter_probe":
    case "plugin_lab.filter_find_option":
      return xhsNoOpFilter(action);
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
      return xhsUnsupportedOutreach(action);
    case "plugin_lab.fetch_profile_videos":
    case "plugin_lab.prepare_profile_video":
    case "plugin_lab.click_profile_video":
    case "plugin_lab.profile_video_dom_click":
    case "plugin_lab.profile_video_probe":
    case "plugin_lab.back_to_profile":
      return { ok: false, message: "小红书主页作品采集尚未实现" };
    default:
      return undefined;
  }
}
