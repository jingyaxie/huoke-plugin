import { findSearchInputMatch, humanClick, randDelay, sleep } from "../../search-input";
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

  if (button) {
    humanClick(button);
    await sleep(randDelay(600, 1000));
  } else if (inputMatch?.input) {
    inputMatch.input.focus();
    inputMatch.input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
    );
    await sleep(randDelay(700, 1100));
  } else {
    return {
      ok: false,
      method: "none",
      url: location.href,
      on_search_page: false,
      message: "未找到小红书搜索按钮或搜索框",
    };
  }

  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    if (isXhsSearchResultsPage(location.href)) break;
    if (location.href !== beforeUrl && /search/i.test(location.href)) break;
    await sleep(250);
  }

  return {
    ok: isXhsSearchResultsPage(location.href) || collectXhsNoteCards().length > 0,
    method: button ? "click_button" : "enter_key",
    url: location.href,
    on_search_page: isXhsSearchResultsPage(location.href),
    message: isXhsSearchResultsPage(location.href) ? "已进入小红书搜索结果页" : "已触发搜索，等待结果加载",
  };
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
  const noteId = extractNoteIdFromHref(location.href) || location.pathname.match(/\/explore\/([0-9a-fA-F]{16,32})/)?.[1] || "";

  await xhsActivateComments();
  enableXhsCommentNetworkHook();

  const merged = new Map<string, Record<string, unknown>>();
  let scrolledRounds = 0;
  let stoppedReason = "initial";

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
        avatar_url: row.avatar_url ?? "",
        digg_count: row.digg_count ?? 0,
        create_time: row.create_time ?? null,
        source: row.source ?? "api",
      });
    }
  };

  await mergeApi();
  for (let round = 0; round < maxRounds && merged.size < maxComments; round += 1) {
    if (scrollXhsComments()) scrolledRounds += 1;
    await sleep(400 + Math.floor(Math.random() * 300));
    await mergeApi();
    if (merged.size >= maxComments) {
      stoppedReason = "max_comments";
      break;
    }
  }
  if (stoppedReason === "initial" && merged.size === 0) {
    stoppedReason = "no_comments";
  } else if (stoppedReason === "initial") {
    stoppedReason = "rounds_exhausted";
  }

  const comments = Array.from(merged.values()).slice(0, maxComments).map((item, index) => ({
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
    comment_days: Number(payload.comment_days ?? 0),
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

export async function xhsCloseNoteDetail() {
  const closeBtn = document.querySelector('[class*="close"], .close-circle, .close-box') as HTMLElement | null;
  if (closeBtn) {
    humanClick(closeBtn);
    await sleep(400);
  } else if (window.history.length > 1) {
    window.history.back();
    await sleep(500);
  }
  return {
    ok: !isXhsNotePage() || isXhsSearchResultsPage(),
    message: "已尝试关闭笔记详情",
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
    case "plugin_lab.search_prepare":
      return xhsPrepareSearchCapture();
    case "plugin_lab.search_submit":
    case "plugin_lab.click_search_btn":
      return xhsSubmitSearchClick();
    case "plugin_lab.fetch_search_results":
      return xhsFetchSearchResults((payload ?? {}) as { limit?: number; api_timeout_ms?: number });
    case "plugin_lab.prepare_search_video":
      return { ok: true, on_search_page: isXhsSearchResultsPage(), card_count: collectXhsNoteCards().length };
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
