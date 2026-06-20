import { randDelay, sleep } from "./search-input";

const COMMENT_ITEM_SELECTOR = '[data-e2e="comment-item"]';
const END_MARKERS = ["暂时没有更多评论", "没有更多评论"] as const;
const MAX_PARSE_NODES = 80;

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

  return {
    index,
    content: content || "—",
    author,
    user_url: avatar?.href ?? "",
    comment_id: node.getAttribute("data-comment-id") ?? "",
  };
}

export interface ScrollCollectCommentsPayload {
  scroll_rounds?: number;
  max_comments?: number;
}

/** 步骤 11：滑动评论列表并采集可见评论 */
export async function scrollAndCollectComments(payload: ScrollCollectCommentsPayload = {}) {
  const rounds = Math.max(1, Math.min(Number(payload.scroll_rounds ?? 3), 12));
  const maxComments = Math.max(1, Math.min(Number(payload.max_comments ?? 30), 100));

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
  for (let r = 0; r < rounds && comments.length < maxComments; r += 1) {
    if (hasCommentEndMarker()) break;

    if (scrollCommentSidebar()) scrolledRounds += 1;
    await sleep(randDelay(280, 480));
    collectVisible();
  }

  return {
    ok: comments.length > 0,
    count: comments.length,
    comments,
    items: comments,
    scroll_rounds: scrolledRounds,
    url: location.href,
    message:
      comments.length > 0
        ? `已采集 ${comments.length} 条可见评论（滚动 ${scrolledRounds} 轮）`
        : "评论区无可见评论，请先执行步骤 10 打开评论区",
  };
}
