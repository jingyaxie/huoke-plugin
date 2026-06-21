import { randDelay, sleep } from "./search-input";

const COMMENT_ITEM_SELECTOR = '[data-e2e="comment-item"]';
const END_MARKERS = ["暂时没有更多评论", "没有更多评论"] as const;
const MAX_PARSE_NODES = 200;

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

/** 对齐 Python `COMMENT_SIDEBAR_SCROLL_JS` */
function scrollCommentSidebar(): boolean {
  const items = document.querySelectorAll(COMMENT_ITEM_SELECTOR);
  const anchors: Element[] = [];

  if (items.length > 0) {
    anchors.push(items[items.length - 1]);
  }

  const headers = document.querySelectorAll("div, span, p");
  for (let i = 0; i < headers.length && i < 60; i += 1) {
    const el = headers[i];
    const text = (el.textContent ?? "").trim();
    if (text.startsWith("全部评论")) {
      anchors.push(el);
      break;
    }
  }

  const feed = document.querySelector('[data-e2e="feed-active-video"]');
  if (feed) anchors.push(feed);

  for (let a = 0; a < anchors.length; a += 1) {
    let node: HTMLElement | null = anchors[a] as HTMLElement;
    for (let depth = 0; depth < 12 && node; depth += 1) {
      const sh = node.scrollHeight || 0;
      const ch = node.clientHeight || 0;
      if (sh > ch + 30) {
        const before = node.scrollTop || 0;
        node.scrollTop = Math.min(before + 520, sh);
        if (node.scrollTop > before || sh > ch + 120) return true;
      }
      node = node.parentElement;
    }
  }

  return false;
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

function pickCommentTime(node: HTMLElement): number | null {
  const selectors = [
    '[class*="time"]',
    '[class*="date"]',
    '[class*="Time"]',
    "span",
  ];
  for (const selector of selectors) {
    const nodes = node.querySelectorAll(selector);
    for (let i = 0; i < nodes.length && i < 8; i += 1) {
      const text = nodeShortText(nodes[i], 40);
      const ts = parseCommentTimeText(text);
      if (ts) return ts;
    }
  }
  return null;
}

function parseCommentItem(node: HTMLElement, index: number) {
  const textNode =
    node.querySelector('[class*="comment-content"]') ??
    node.querySelector('[class*="content"]') ??
    node.querySelector("span");
  const authorNode =
    node.querySelector('[class*="nickname"]') ??
    node.querySelector('[class*="name"]') ??
    node.querySelector('a[href*="/user/"]');
  const avatar = node.querySelector('a[href*="/user/"]') as HTMLAnchorElement | null;

  const content = nodeShortText(textNode) || nodeShortText(node.querySelector("p"));
  const author = nodeShortText(authorNode, 60) || "—";
  const createTime = pickCommentTime(node);

  return {
    index,
    content: content || "—",
    author,
    user_url: avatar?.href ?? "",
    comment_id: node.getAttribute("data-comment-id") ?? "",
    create_time: createTime,
  };
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
}

/** 步骤 11：滑动评论列表并采集可见评论（按 comment_days 与时间窗停止） */
export async function scrollAndCollectComments(payload: ScrollCollectCommentsPayload = {}) {
  const maxRounds = Math.max(1, Math.min(Number(payload.scroll_rounds ?? 12), 60));
  const maxComments = Math.max(1, Math.min(Number(payload.max_comments ?? 80), 300));
  const commentDays = Math.max(0, Number(payload.comment_days ?? 0));

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
      if (!parsed.content || parsed.content === "—") continue;

      const key = `${parsed.author}|${parsed.content.slice(0, 80)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      comments.push({ ...parsed, index: comments.length + 1 });

      if (comments.length >= maxComments) return;
    }
  }

  collectVisible();

  let scrolledRounds = 0;
  let stoppedReason = comments.length > 0 ? "initial" : "no_visible_comments";

  for (let r = 0; r < maxRounds && comments.length < maxComments; r += 1) {
    if (hasCommentEndMarker()) {
      stoppedReason = "end_marker";
      break;
    }
    if (shouldStopForTimeWindow(comments, commentDays, r)) {
      stoppedReason = "comment_days";
      break;
    }

    if (scrollCommentSidebar()) scrolledRounds += 1;
    await sleep(randDelay(320, 520));
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

  if (stoppedReason === "initial" || stoppedReason === "no_visible_comments") {
    stoppedReason = scrolledRounds > 0 ? "rounds_exhausted" : stoppedReason;
  }

  const inWindow = commentDays > 0
    ? comments.filter((c) => {
        if (!c.create_time) return true;
        const cutoff = cutoffTs(commentDays);
        return cutoff === null || c.create_time >= cutoff;
      })
    : comments;

  return {
    ok: inWindow.length > 0,
    count: inWindow.length,
    comments: inWindow,
    items: inWindow,
    scroll_rounds: scrolledRounds,
    max_rounds: maxRounds,
    comment_days: commentDays,
    stopped_reason: stoppedReason,
    url: location.href,
    message:
      inWindow.length > 0
        ? `已采集 ${inWindow.length} 条评论（滚动 ${scrolledRounds} 轮，停止原因: ${stoppedReason}）`
        : "评论区无可见评论，请先执行步骤 10 打开评论区",
  };
}
