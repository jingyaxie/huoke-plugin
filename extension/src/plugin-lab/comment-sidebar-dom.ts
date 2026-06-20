const FEED_SCOPED_ICON_SELECTORS = [
  '[data-e2e="feed-active-video"] [data-e2e="feed-comment-icon"]',
  '[data-e2e="feed-active-video"] [data-e2e="comment-icon"]',
  '[data-e2e="feed-active-video"] [data-e2e="detail-tab-comment"]',
  '[class*="comment"] [data-e2e="feed-comment-icon"]',
] as const;

const COMMENT_ICON_SELECTORS = [
  '[data-e2e="feed-comment-icon"]',
  '[data-e2e="comment-icon"]',
  '[data-e2e="detail-tab-comment"]',
] as const;

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

export interface IconTarget {
  selector: string;
  center: DomPoint;
  rect: DomRect;
  priority: number;
}

function serializeRect(rect: DOMRect): DomRect {
  return {
    top: Math.round(rect.top),
    left: Math.round(rect.left),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
}

function centerOf(rect: DOMRect): DomPoint {
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

/** 对齐 Python `_CLICK_COMMENT_ICON_JS` 可见性 */
function isVisible(el: Element): boolean {
  const rect = el.getBoundingClientRect();
  if (rect.width < 10 || rect.height < 10) return false;
  if (rect.top < 0 || rect.bottom > window.innerHeight + 4) return false;
  if (rect.left < 0 || rect.right > window.innerWidth + 4) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden") return false;
  if (Number(style.opacity || 1) < 0.05) return false;
  return true;
}

/** 点击 SVG 图标时扩大命中区域到父级 button/div */
function resolveClickTarget(el: HTMLElement): HTMLElement {
  let node: HTMLElement | null = el;
  for (let i = 0; i < 8 && node; i += 1) {
    const rect = node.getBoundingClientRect();
    if (rect.width >= 24 && rect.height >= 24) return node;
    node = node.parentElement;
  }
  return el;
}

export function countVisibleCommentItems(): number {
  let count = 0;
  const selectors = [
    '[data-e2e="feed-active-video"] [data-e2e="comment-item"]',
    '[data-e2e="comment-item"]',
    '[class*="CommentItem"]',
  ];
  for (const selector of selectors) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length && i < 60; i += 1) {
      if (isVisible(nodes[i])) count += 1;
    }
  }
  return count;
}

export function hasVisibleCommentItems(): boolean {
  return countVisibleCommentItems() > 0;
}

function findAllCommentsHeader(): HTMLElement | null {
  const roots: Element[] = [];
  const feed = document.querySelector('[data-e2e="feed-active-video"]');
  if (feed) roots.push(feed);
  roots.push(document.body);

  for (const root of roots) {
    const nodes = root.querySelectorAll("div, span, p, h1, h2, h3, h4");
    for (let i = 0; i < nodes.length && i < 400; i += 1) {
      const el = nodes[i] as HTMLElement;
      const text = (el.textContent ?? "").trim();
      if (!text.startsWith("全部评论")) continue;
      if (!isVisible(el)) continue;
      if (el.children.length > 2 && text.length > 40) continue;
      return el;
    }
  }
  return null;
}

export function isCommentSidebarActive(): boolean {
  return hasVisibleCommentItems() || findAllCommentsHeader() !== null;
}

const FEED_OVERLAY_SELECTORS = [
  '[data-e2e="feed-active-video"]',
  '[data-e2e="feed-comment-icon"]',
  '[data-e2e="comment-icon"]',
  '[data-e2e="detail-tab-comment"]',
  '[data-e2e="comment-item"]',
] as const;

export function isFeedOverlayOpen(): boolean {
  for (const selector of FEED_OVERLAY_SELECTORS) {
    const el = document.querySelector(selector);
    if (el && isVisible(el)) return true;
  }
  if (findAllCommentsHeader()) return true;
  return false;
}

export function isSearchFeedOverlay(): boolean {
  const url = location.href.toLowerCase();
  if (/\/video\/\d+/.test(url)) return false;
  const onSearch = url.includes("/search/") || url.includes("/jingxuan/search/");
  if (!onSearch && !url.includes("modal_id=")) return false;
  return isFeedOverlayOpen();
}

function pushIconTarget(
  out: IconTarget[],
  el: HTMLElement,
  selector: string,
  priority: number,
) {
  if (!isVisible(el)) return;
  const clickEl = resolveClickTarget(el);
  const rect = clickEl.getBoundingClientRect();
  out.push({
    selector,
    center: centerOf(rect),
    rect: serializeRect(rect),
    priority,
  });
}

export function collectCommentIconTargets(): IconTarget[] {
  const out: IconTarget[] = [];
  const seen = new Set<string>();

  for (const selector of FEED_SCOPED_ICON_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i] as HTMLElement;
      const key = `${selector}:${Math.round(el.getBoundingClientRect().top)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      pushIconTarget(out, el, selector, 0);
    }
  }

  for (const selector of COMMENT_ICON_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i] as HTMLElement;
      const key = `${selector}:${Math.round(el.getBoundingClientRect().top)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      pushIconTarget(out, el, selector, 10);
    }
  }

  const tabs = document.querySelectorAll('div[role="tab"], span, button');
  for (let i = 0; i < tabs.length && i < 80; i += 1) {
    const el = tabs[i] as HTMLElement;
    const text = (el.textContent ?? "").replace(/\s+/g, "");
    if (text !== "评论" && !text.startsWith("评论(")) continue;
    const key = `tab:${Math.round(el.getBoundingClientRect().top)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    pushIconTarget(out, el, "tab:评论", 20);
  }

  out.sort((a, b) => a.priority - b.priority || a.center.y - b.center.y);
  return out;
}

function findVideoPlayerCenter(): DomPoint | null {
  const feed = document.querySelector('[data-e2e="feed-active-video"]');
  const scope = feed ?? document;
  const selectors = ["video", '[data-e2e="video-player"]'];
  for (const selector of selectors) {
    const el = scope.querySelector(selector) as HTMLElement | null;
    if (!el || !isVisible(el)) continue;
    return centerOf(el.getBoundingClientRect());
  }
  return null;
}

/** 供 background CDP 探测 */
export function probeCommentSidebar() {
  const icons = collectCommentIconTargets();
  const commentCount = countVisibleCommentItems();
  const feedOpen = isFeedOverlayOpen();
  const sidebarActive = isCommentSidebarActive();
  const hasHeader = findAllCommentsHeader() !== null;

  return {
    ok: true,
    active: sidebarActive,
    sidebar_active: sidebarActive,
    feed_open: feedOpen,
    is_search_feed: isSearchFeedOverlay(),
    comment_item_count: commentCount,
    has_visible_comments: commentCount > 0,
    has_comments_header: hasHeader,
    icon_targets: icons,
    video_player_center: findVideoPlayerCenter(),
    url: location.href,
    message: sidebarActive
      ? hasHeader && commentCount === 0
        ? "评论区已打开（可见「全部评论」标题）"
        : `评论区已打开（${commentCount} 条可见评论）`
      : feedOpen
        ? icons.length
          ? `Feed 已打开，找到 ${icons.length} 个评论入口`
          : "Feed 已打开，但未找到评论入口"
        : "视频 Feed 未打开，请先执行步骤 9",
  };
}

export async function clickCommentButtonFallback() {
  const { ok: _ignored, ...probe } = probeCommentSidebar();
  return {
    ...probe,
    ok: false,
    mode: "content_fallback",
    message: "请重新加载扩展以启用 CDP 评论点击",
  };
}
