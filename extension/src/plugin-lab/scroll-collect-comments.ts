import { humanPace, sleep } from "./search-input";
import { resolveEffectivePlaybackMode } from "./playback-mode";
import {
  activateCommentSidebar,
  isCommentSidebarReadyForCollect,
} from "./comment-sidebar-dom";
import { scrollFeedCommentSidebar } from "./feed-comment-sidebar-dom";
import { scrollVideoDetailCommentSidebar } from "./video-detail-comment-sidebar-dom";
import {
  enableCommentNetworkHook,
  getAllCachedCommentApiItems,
  getCommentApiItemsForAweme,
  pollCommentApiCache,
} from "./comment-api";

const COMMENT_ITEM_SELECTOR = '[data-e2e="comment-item"]';
const END_MARKERS = ["暂时没有更多评论", "没有更多评论"] as const;
const MAX_PARSE_NODES = 200;
const META_LABELS = new Set(["作者", "回复", "分享", "赞", "置顶", "展开", "收起", "展开更多", "收起更多"]);

function extractAwemeIdFromLocation(): string {
  try {
    const url = new URL(location.href);
    const modalId = url.searchParams.get("modal_id");
    if (modalId && /^\d{8,22}$/.test(modalId)) return modalId;
    const match = location.pathname.match(/\/video\/(\d{8,22})/);
    if (match?.[1]) return match[1];
  } catch {
    // ignore
  }
  return "";
}

function commentSidebarRoot(): HTMLElement | null {
  return (
    (document.querySelector('[data-e2e="feed-active-video"]') as HTMLElement | null) ??
    (document.querySelector('[data-e2e="comment-list"]') as HTMLElement | null) ??
    (document.querySelector('[data-e2e="comment-item"]')?.parentElement as HTMLElement | null)
  );
}

/** 禁止 document.body.innerText — 只在评论侧栏范围内查结束标记 */
function hasCommentEndMarker(): boolean {
  const root = commentSidebarRoot();
  const scope = root ?? document.body;

  for (const marker of END_MARKERS) {
    const xpath = `.//*[contains(normalize-space(text()), "${marker}")]`;
    try {
      const snap = document.evaluate(
        xpath,
        scope,
        null,
        XPathResult.FIRST_ORDERED_NODE_TYPE,
        null,
      );
      const node = snap.singleNodeValue as Element | null;
      if (!node) continue;
      const rect = node.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) return true;
    } catch {
      // ignore invalid xpath in old browsers
    }
  }

  return false;
}

/** 按 playback_mode 在 Feed 侧栏或 /video/ 页滚动评论 */
function scrollCommentSidebar(payload: Record<string, unknown> = {}): boolean {
  return resolveEffectivePlaybackMode(payload) === "video_detail"
    ? scrollVideoDetailCommentSidebar()
    : scrollFeedCommentSidebar();
}

function nodeShortText(node: Element | null, maxLen = 300): string {
  if (!node) return "";
  return (node.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, maxLen);
}

/** 解析抖音评论相对时间文案为 unix 秒（近似） */
export function parseCommentTimeText(text: string): number | null {
  const raw = text.replace(/\s+/g, "").trim();
  if (!raw) return null;
  const now = Math.floor(Date.now() / 1000);

  if (/^(刚刚|刚才)$/.test(raw)) return now;
  if (/^昨天/.test(raw)) return now - 86400;

  const minute = raw.match(/^(\d+)分钟前$/);
  if (minute) return now - Number(minute[1]) * 60;

  const hour = raw.match(/^(\d+)小时前$/);
  if (hour) return now - Number(hour[1]) * 3600;

  const day = raw.match(/^(\d+)天前$/);
  if (day) return now - Number(day[1]) * 86400;

  const week = raw.match(/^(\d+)周前$/);
  if (week) return now - Number(week[1]) * 7 * 86400;

  const month = raw.match(/^(\d+)月前$/);
  if (month) return now - Number(month[1]) * 30 * 86400;

  const yearAgo = raw.match(/^(\d+)年前$/);
  if (yearAgo) return now - Number(yearAgo[1]) * 365 * 86400;

  const yearOnly = raw.match(/^(\d+)年$/);
  if (yearOnly) return now - Number(yearOnly[1]) * 365 * 86400;

  const cnDate = raw.match(/^(\d{2,4})年(\d{1,2})月(\d{1,2})号?$/);
  if (cnDate) {
    const year = Number(cnDate[1]);
    const fullYear = year < 100 ? 2000 + year : year;
    const ts = Date.parse(
      `${fullYear}-${cnDate[2].padStart(2, "0")}-${cnDate[3].padStart(2, "0")}T12:00:00`,
    );
    if (!Number.isNaN(ts)) return Math.floor(ts / 1000);
  }

  const md = raw.match(/^(\d{1,2})-(\d{1,2})$/);
  if (md) {
    const year = new Date().getFullYear();
    const ts = Date.parse(`${year}-${md[1].padStart(2, "0")}-${md[2].padStart(2, "0")}T12:00:00`);
    if (!Number.isNaN(ts)) return Math.floor(ts / 1000);
  }

  const ymd = raw.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (ymd) {
    const ts = Date.parse(`${ymd[1]}-${ymd[2].padStart(2, "0")}-${ymd[3].padStart(2, "0")}T12:00:00`);
    if (!Number.isNaN(ts)) return Math.floor(ts / 1000);
  }

  return null;
}

const DOM_TIME_IN_TEXT =
  /(\d{2,4}年\d{1,2}月\d{1,2}号|\d+分钟前|\d+小时前|\d+天前|\d+周前|\d+月前|\d+年前|\d+年)(?:·[^0-9分享回复展开]+)?/;

const DOM_META_TAIL =
  /(?:·[^·\d]+)?\d*分享(?:回复(?:展开\d*条回复)?)?\s*$/u;

function extractTimeFromBlob(text: string): { createTime: number | null; rest: string } {
  const match = text.match(DOM_TIME_IN_TEXT);
  if (!match || match.index === undefined) {
    return { createTime: null, rest: text.trim() };
  }
  const token = match[1].replace(/·.*/, "");
  const createTime = parseCommentTimeText(token);
  const rest = `${text.slice(0, match.index)}${text.slice(match.index + match[0].length)}`
    .replace(DOM_META_TAIL, "")
    .trim();
  return { createTime, rest };
}

/** 抖音 DOM 常把昵称、正文、时间拼成「昵称...正文4周前·四川0分享回复」 */
function refineDomCommentFields(input: {
  author: string;
  content: string;
  create_time: number | null;
}) {
  let author = input.author.trim() || "—";
  let content = input.content.trim();
  let createTime = input.create_time;

  const blob = content.match(/^([^.\n]{1,48}?)\.\.\.([\s\S]+)$/);
  if (blob) {
    if (author === "—") author = blob[1].trim() || author;
    content = blob[2].trim();
  } else if (author === "—" && content.includes("...")) {
    const alt = content.match(/^([^.\n]{1,48}?)\.\.\.([\s\S]+)$/);
    if (alt) {
      author = alt[1].trim() || author;
      content = alt[2].trim();
    }
  }

  if (!createTime) {
    const extracted = extractTimeFromBlob(content);
    createTime = extracted.createTime;
    content = extracted.rest || content;
  } else {
    content = content.replace(DOM_META_TAIL, "").trim();
  }

  content = content.replace(/^(?:回复@|@)[^\s]+/u, "").trim();
  return {
    author: author || "—",
    content: content || input.content.trim() || "—",
    create_time: createTime,
  };
}

function pickCommentTime(node: HTMLElement): number | null {
  const selectors = [
    '[data-e2e="comment-time"]',
    '[class*="comment-item-info-time"]',
    '[class*="comment-time"]',
    '[class*="CommentTime"]',
    '[class*="time"]',
    '[class*="date"]',
    '[class*="Time"]',
    "span",
  ];
  for (const selector of selectors) {
    const nodes = node.querySelectorAll(selector);
    for (let i = 0; i < nodes.length && i < 12; i += 1) {
      const text = nodeShortText(nodes[i], 40);
      const ts = parseCommentTimeText(text);
      if (ts) return ts;
    }
  }
  return null;
}

function isValidCommentContent(text: string, nickname: string): boolean {
  const value = text.replace(/\s+/g, " ").trim();
  if (!value || value === "—") return false;
  if (META_LABELS.has(value)) return false;
  if (/^\d+$/.test(value)) return false;
  if (nickname && value === nickname) return false;
  if (value === "回复" || value.startsWith("回复@")) return false;
  if (/^\d+[分钟小时天周月]+前$/.test(value.replace(/\s+/g, ""))) return false;
  if (/^\d{1,2}-\d{1,2}$/.test(value)) return false;
  if (/^[\d.]+[wW万]?$/.test(value)) return false;
  return value.length >= 2;
}

function extractCommentId(node: HTMLElement): string {
  const direct =
    node.getAttribute("data-cid") ||
    node.dataset.cid ||
    node.getAttribute("data-comment-id") ||
    "";
  if (direct.trim()) return direct.trim();

  const nested = node.querySelector("[data-cid], [data-comment-id]") as HTMLElement | null;
  if (nested) {
    const nestedId =
      nested.getAttribute("data-cid") ||
      nested.getAttribute("data-comment-id") ||
      "";
    if (nestedId.trim()) return nestedId.trim();
  }

  const idMatch = node.id.match(/^comment-(\d+)/)?.[1];
  return idMatch ?? "";
}

function extractNickname(node: HTMLElement): string {
  const selectors = [
    '[data-e2e="comment-user-name"]',
    '[data-e2e="comment-user"] span',
    'div.comment-item-info-user-name span',
    'div.comment-item-info-user-name a',
    '[class*="nickname"]',
    '[class*="user-name"]',
    '[class*="author-name"]',
    '[class*="name-text"]',
    'a[href*="/user/"] span',
    'a[href*="/user/"]',
  ];
  for (const selector of selectors) {
    const el = node.querySelector(selector);
    if (!el) continue;
    const text = nodeShortText(el, 60);
    if (text && text !== "—" && !META_LABELS.has(text) && !/^\d+$/.test(text)) {
      return text;
    }
  }
  return "—";
}

function extractContent(node: HTMLElement, nickname: string): string {
  const selectors = [
    '[class*="CommentContent"]',
    '[class*="comment-content"]',
    '[class*="CommentText"]',
    '[class*="comment-text"]',
    '[data-e2e="comment-content"]',
  ];
  for (const selector of selectors) {
    const el = node.querySelector(selector);
    const text = nodeShortText(el);
    if (isValidCommentContent(text, nickname)) return text;
  }

  let best = "";
  const nodes = node.querySelectorAll("span, p, div");
  for (let i = 0; i < nodes.length && i < 40; i += 1) {
    const el = nodes[i] as HTMLElement;
    if (el.querySelector(COMMENT_ITEM_SELECTOR)) continue;
    if (el.closest("button")) continue;
    const text = nodeShortText(el, 500);
    if (!isValidCommentContent(text, nickname)) continue;
    if (text.length > best.length) best = text;
  }
  return best;
}

function readImageUrl(img: HTMLImageElement | null): string {
  if (!img) return "";
  const candidates = [
    img.currentSrc,
    img.src,
    img.getAttribute("src"),
    img.getAttribute("data-src"),
    img.getAttribute("data-original"),
  ];
  const srcset = img.getAttribute("srcset");
  if (srcset) candidates.push(srcset.split(/\s+/)[0]);
  for (const value of candidates) {
    const src = String(value || "").trim();
    if (src.startsWith("http")) return src;
  }
  return "";
}

function extractAvatarUrl(node: HTMLElement): string {
  const selectors = [
    "div.comment-item-avatar img",
    '[data-e2e="comment-item-avatar"] img',
    '[data-e2e="live-avatar"] img',
    '[class*="avatar"] img',
    'a[href*="/user/"] img',
    "img",
  ];
  for (const selector of selectors) {
    const url = readImageUrl(node.querySelector(selector) as HTMLImageElement | null);
    if (url) return url;
  }
  return "";
}

function parseDouyinUserIdsFromUrl(url: string): { user_id: string; sec_uid: string } {
  const trimmed = String(url || "").trim();
  if (!trimmed) return { user_id: "", sec_uid: "" };
  try {
    const parsed = new URL(trimmed.startsWith("http") ? trimmed : `https://${trimmed}`);
    const match = parsed.pathname.match(/\/user\/([^/?#]+)/i);
    if (match?.[1]) {
      const id = decodeURIComponent(match[1]);
      if (/^\d+$/.test(id)) return { user_id: id, sec_uid: "" };
      return { user_id: "", sec_uid: id };
    }
    return {
      user_id: parsed.searchParams.get("uid") || parsed.searchParams.get("user_id") || "",
      sec_uid: parsed.searchParams.get("sec_uid") || "",
    };
  } catch {
    return { user_id: "", sec_uid: "" };
  }
}

function parseCommentItem(node: HTMLElement, index: number) {
  const nickname = extractNickname(node);
  const rawContent = extractContent(node, nickname);
  const authorNode =
    node.querySelector('a[href*="/user/"]') as HTMLAnchorElement | null;
  const createTime = pickCommentTime(node);
  const refined = refineDomCommentFields({
    author: nickname,
    content: rawContent || "—",
    create_time: createTime,
  });

  return {
    index,
    content: refined.content,
    author: refined.author,
    user_url: authorNode?.href ?? "",
    avatar_url: extractAvatarUrl(node),
    comment_id: extractCommentId(node),
    create_time: refined.create_time,
    source: "dom" as const,
  };
}

function commentMatchKey(author: string, content: string): string {
  return `${author}|${content.slice(0, 80)}`.toLowerCase();
}

function mapApiComment(item: {
  comment_id: string;
  content: string;
  author: string;
  user_id: string;
  sec_uid: string;
  avatar_url: string;
  digg_count: number;
  create_time: number | null;
}, source: "api" | "dom" = "api") {
  const profile =
    item.sec_uid
      ? `https://www.douyin.com/user/${item.sec_uid}`
      : item.user_id
        ? `https://www.douyin.com/user/${item.user_id}`
        : "";
  return {
    index: 0,
    content: item.content,
    author: item.author || "—",
    user_url: profile,
    avatar_url: item.avatar_url || "",
    comment_id: item.comment_id,
    create_time: item.create_time,
    digg_count: item.digg_count,
    user_id: item.user_id,
    sec_uid: item.sec_uid,
    source,
  };
}

type CollectedComment = ReturnType<typeof mapApiComment>;

/** API 截获缺头像/时间时，用当前可见 DOM 评论补齐 */
function enrichCommentsFromDom(items: CollectedComment[]): CollectedComment[] {
  if (!items.some((row) => !row.avatar_url || !row.create_time || row.author === "—")) {
    return items;
  }

  const domRows: CollectedComment[] = [];
  const nodes = document.querySelectorAll(COMMENT_ITEM_SELECTOR);
  const limit = Math.min(nodes.length, MAX_PARSE_NODES);
  for (let i = 0; i < limit; i += 1) {
    const node = nodes[i] as HTMLElement;
    if (node.getBoundingClientRect().height < 8) continue;
    const parsed = parseCommentItem(node, i + 1);
    if (!isValidCommentContent(parsed.content, parsed.author)) continue;
    const ids = parseDouyinUserIdsFromUrl(parsed.user_url || "");
    domRows.push(mapApiComment({
      comment_id: parsed.comment_id,
      content: parsed.content,
      author: parsed.author,
      user_id: ids.user_id,
      sec_uid: ids.sec_uid,
      avatar_url: parsed.avatar_url,
      digg_count: 0,
      create_time: parsed.create_time,
    }, "dom"));
  }

  const domById = new Map<string, CollectedComment>();
  const domByKey = new Map<string, CollectedComment>();
  for (const row of domRows) {
    if (row.comment_id) domById.set(row.comment_id, row);
    domByKey.set(commentMatchKey(row.author, row.content), row);
  }

  return items.map((item) => {
    const dom =
      (item.comment_id ? domById.get(item.comment_id) : undefined) ??
      domByKey.get(commentMatchKey(item.author, item.content)) ??
      domRows.find((row) =>
        row.content.length > 6
        && (item.content.includes(row.content.slice(0, 24))
          || row.content.includes(item.content.slice(0, 24))),
      );
    if (!dom) return item;
    return {
      ...item,
      author: item.author === "—" && dom.author !== "—" ? dom.author : item.author,
      avatar_url: item.avatar_url || dom.avatar_url,
      create_time: item.create_time ?? dom.create_time,
      user_url: item.user_url || dom.user_url,
    };
  });
}

async function absorbApiComments(
  awemeHint: string,
  merged: Map<string, CollectedComment>,
  maxComments: number,
  commentDays: number,
  stats?: { seenTotal: number; skippedByDays: number },
) {
  const items = awemeHint
    ? await getCommentApiItemsForAweme(awemeHint)
    : await getAllCachedCommentApiItems();
  const cutoff = cutoffTs(commentDays);

  for (const item of items) {
    if (stats) stats.seenTotal += 1;
    if (merged.size >= maxComments) break;
    if (merged.has(item.comment_id)) continue;
    if (cutoff !== null && item.create_time && item.create_time < cutoff) {
      if (stats) stats.skippedByDays += 1;
      continue;
    }
    merged.set(item.comment_id, mapApiComment(item));
  }
}

/** 优先截获 comment/list API，滚动触发分页并轮询缓存 */
async function collectViaApi(
  awemeHint: string,
  maxRounds: number,
  maxComments: number,
  commentDays: number,
  scrollPayload: Record<string, unknown>,
) {
  enableCommentNetworkHook();

  const merged = new Map<string, CollectedComment>();
  const stats = { seenTotal: 0, skippedByDays: 0 };
  await pollCommentApiCache({
    timeoutMs: 8000,
    minItems: 1,
    awemeId: awemeHint || undefined,
  });
  await absorbApiComments(awemeHint, merged, maxComments, commentDays, stats);

  let scrolledRounds = 0;
  let stoppedReason = merged.size > 0 ? "api_initial" : "api_empty";

  for (let r = 0; r < maxRounds && merged.size < maxComments; r += 1) {
    if (hasCommentEndMarker()) {
      stoppedReason = "end_marker";
      break;
    }
    const apiComments = Array.from(merged.values());
    if (shouldStopForTimeWindow(apiComments, commentDays, r)) {
      stoppedReason = "comment_days";
      break;
    }

    const sizeBefore = merged.size;
    if (scrollCommentSidebar(scrollPayload)) scrolledRounds += 1;
    await sleep(humanPace.commentScrollRound());

    await pollCommentApiCache({
      timeoutMs: 3500,
      minItems: sizeBefore + 1,
      awemeId: awemeHint || undefined,
    });
    await absorbApiComments(awemeHint, merged, maxComments, commentDays, stats);

    if (merged.size >= maxComments) {
      stoppedReason = "max_comments";
      break;
    }
    if (hasCommentEndMarker()) {
      stoppedReason = "end_marker";
      break;
    }
    if (shouldStopForTimeWindow(Array.from(merged.values()), commentDays, r + 1)) {
      stoppedReason = "comment_days";
      break;
    }
    if (merged.size === sizeBefore && r >= 2 && hasCommentEndMarker()) {
      stoppedReason = "api_no_growth";
      break;
    }
  }

  if (stoppedReason === "api_empty" && scrolledRounds > 0) {
    stoppedReason = "api_rounds_exhausted";
  }
  if (merged.size === 0 && stats.seenTotal > 0 && stats.skippedByDays >= stats.seenTotal) {
    stoppedReason = "comment_days_all_filtered";
  }

  return {
    items: Array.from(merged.values()).map((item, index) => ({
      ...item,
      index: index + 1,
    })),
    scrolledRounds,
    stoppedReason,
    seenTotal: stats.seenTotal,
    skippedByDays: stats.skippedByDays,
  };
}

/** DOM 兜底：仅在 API 截获完全失败时使用 */
async function collectViaDom(
  maxRounds: number,
  maxComments: number,
  commentDays: number,
  scrollPayload: Record<string, unknown>,
) {
  const seen = new Set<string>();
  const comments: ReturnType<typeof parseCommentItem>[] = [];

  function collectVisible() {
    const nodes = document.querySelectorAll(COMMENT_ITEM_SELECTOR);
    const limit = Math.min(nodes.length, MAX_PARSE_NODES);

    for (let i = 0; i < limit; i += 1) {
      const node = nodes[i] as HTMLElement;
      const rect = node.getBoundingClientRect();
      if (rect.height < 8) continue;

      const parsed = parseCommentItem(node, comments.length + 1);
      if (!isValidCommentContent(parsed.content, parsed.author)) continue;

      const key = `${parsed.author}|${parsed.content.slice(0, 80)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      comments.push({ ...parsed, index: comments.length + 1 });

      if (comments.length >= maxComments) return;
    }
  }

  collectVisible();

  let scrolledRounds = 0;
  let stoppedReason = comments.length > 0 ? "dom_initial" : "dom_no_visible_comments";

  for (let r = 0; r < maxRounds && comments.length < maxComments; r += 1) {
    if (hasCommentEndMarker()) {
      stoppedReason = "end_marker";
      break;
    }
    if (shouldStopForTimeWindow(comments, commentDays, r)) {
      stoppedReason = "comment_days";
      break;
    }

    if (scrollCommentSidebar(scrollPayload)) scrolledRounds += 1;
    await sleep(humanPace.commentScrollRound());
    collectVisible();

    if (comments.length >= maxComments) {
      stoppedReason = "max_comments";
      break;
    }
    if (hasCommentEndMarker()) {
      stoppedReason = "end_marker";
      break;
    }
    if (shouldStopForTimeWindow(comments, commentDays, r + 1)) {
      stoppedReason = "comment_days";
      break;
    }
  }

  const seenTotal = comments.length;
  const inWindow = commentDays > 0
    ? comments.filter((c) => {
        if (!c.create_time) return true;
        const cutoff = cutoffTs(commentDays);
        return cutoff === null || c.create_time >= cutoff;
      })
    : comments;
  const skippedByDays = seenTotal - inWindow.length;

  const items = inWindow.map((item, index) => {
    const ids = parseDouyinUserIdsFromUrl(item.user_url || "");
    return mapApiComment({
      comment_id: item.comment_id || `${item.author}|${item.content.slice(0, 80)}`,
      content: item.content,
      author: item.author,
      user_id: ids.user_id,
      sec_uid: ids.sec_uid,
      avatar_url: item.avatar_url || "",
      digg_count: 0,
      create_time: item.create_time,
    }, "dom");
  }).map((item, index) => ({ ...item, index: index + 1 }));

  if (stoppedReason === "dom_initial" || stoppedReason === "dom_no_visible_comments") {
    stoppedReason = scrolledRounds > 0 ? "dom_rounds_exhausted" : stoppedReason;
  }
  if (items.length === 0 && seenTotal > 0 && skippedByDays >= seenTotal) {
    stoppedReason = "comment_days_all_filtered";
  }

  return { items, scrolledRounds, stoppedReason, seenTotal, skippedByDays };
}

function cutoffTs(commentDays: number): number | null {
  if (!commentDays || commentDays <= 0) return null;
  return Math.floor(Date.now() / 1000) - commentDays * 86400;
}

function shouldStopForTimeWindow(
  comments: Array<{ create_time?: number | null }>,
  commentDays: number,
  roundIdx: number,
): boolean {
  const cutoff = cutoffTs(commentDays);
  if (cutoff === null || roundIdx < 1) return false;
  const times = comments
    .map((c) => c.create_time)
    .filter((t): t is number => typeof t === "number" && t > 0);
  if (times.length === 0) return false;
  const newest = Math.max(...times);
  return newest < cutoff;
}

export interface ScrollCollectCommentsPayload {
  scroll_rounds?: number;
  max_comments?: number;
  comment_days?: number;
  playback_mode?: "feed" | "video_detail" | "auto";
}

/** 步骤 11：优先截获 comment/list API，失败再 DOM 解析可见评论 */
export async function scrollAndCollectComments(payload: ScrollCollectCommentsPayload = {}) {
  const maxRounds = Math.max(1, Math.min(Number(payload.scroll_rounds ?? 12), 60));
  const maxComments = Math.max(1, Math.min(Number(payload.max_comments ?? 80), 300));
  const commentDays = Math.max(0, Number(payload.comment_days ?? 0));
  const scrollPayload = payload as Record<string, unknown>;

  if (!isCommentSidebarReadyForCollect(scrollPayload)) {
    await activateCommentSidebar(scrollPayload);
    await sleep(humanPace.afterCommentClick());
  }

  const awemeHint = extractAwemeIdFromLocation();
  const apiResult = await collectViaApi(awemeHint, maxRounds, maxComments, commentDays, scrollPayload);

  let merged = apiResult.items;
  let captureMethod: "api" | "dom" = "api";
  let scrolledRounds = apiResult.scrolledRounds;
  let stoppedReason = apiResult.stoppedReason;
  let seenTotal = apiResult.seenTotal ?? 0;
  let skippedByDays = apiResult.skippedByDays ?? 0;

  if (merged.length === 0) {
    const domResult = await collectViaDom(maxRounds, maxComments, commentDays, scrollPayload);
    merged = domResult.items;
    captureMethod = "dom";
    scrolledRounds = domResult.scrolledRounds;
    stoppedReason = domResult.stoppedReason;
    seenTotal = domResult.seenTotal ?? seenTotal;
    skippedByDays = domResult.skippedByDays ?? skippedByDays;
  } else {
    merged = enrichCommentsFromDom(merged);
  }

  const apiCount = merged.filter((row) => row.source === "api").length;
  const domCount = merged.length - apiCount;
  const emptyBecauseDays =
    merged.length === 0 && seenTotal > 0 && skippedByDays >= seenTotal && commentDays > 0;

  return {
    ok: merged.length > 0,
    count: merged.length,
    comments: merged,
    items: merged,
    aweme_id: awemeHint,
    capture_method: captureMethod,
    api_count: apiCount,
    dom_count: domCount,
    seen_total: seenTotal,
    skipped_by_days: skippedByDays,
    scroll_rounds: scrolledRounds,
    max_rounds: maxRounds,
    comment_days: commentDays,
    stopped_reason: stoppedReason,
    url: location.href,
    message:
      merged.length > 0
        ? captureMethod === "api"
          ? `已采集 ${merged.length} 条评论（API 截获，滚动 ${scrolledRounds} 轮，停止: ${stoppedReason}）`
          : `已采集 ${merged.length} 条评论（API 未截获，DOM 兜底 ${domCount} 条，滚动 ${scrolledRounds} 轮，停止: ${stoppedReason}）`
        : emptyBecauseDays
          ? `可见 ${seenTotal} 条评论均早于 ${commentDays} 天，已全部跳过（可增大「采集几天内评论」）`
          : seenTotal > 0
            ? `可见 ${seenTotal} 条评论，${commentDays > 0 ? `其中 ${skippedByDays} 条早于 ${commentDays} 天已跳过，` : ""}未入库`
            : "评论区无可见评论，请先执行步骤 10 打开评论区",
  };
}
