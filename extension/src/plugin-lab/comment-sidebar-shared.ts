import { humanClick, sleep } from "./search-input";

/** 评论侧栏：面板已展开（有标题或已有评论项） */
export function isCommentSidebarPanelOpen(): boolean {
  return findAllCommentsHeader() !== null || hasVisibleCommentItems();
}

export const COMMENT_SIDEBAR_TIMING = {
  maxDomClicks: 2,
  maxCdpClicks: 2,
  panelPollMs: 12_000,
  afterClickPollMs: 4_000,
  pollIntervalMs: 450,
} as const;

/** 轮询等待评论面板/列表就绪，不触发任何点击 */
export async function pollCommentSidebarState(options: {
  maxMs?: number;
  intervalMs?: number;
  requireVisibleItems?: boolean;
} = {}): Promise<{
  panel_open: boolean;
  comment_item_count: number;
  collect_ready: boolean;
}> {
  const maxMs = options.maxMs ?? COMMENT_SIDEBAR_TIMING.panelPollMs;
  const intervalMs = options.intervalMs ?? COMMENT_SIDEBAR_TIMING.pollIntervalMs;
  const requireVisibleItems = options.requireVisibleItems ?? false;
  const deadline = Date.now() + maxMs;

  while (Date.now() < deadline) {
    const comment_item_count = countVisibleCommentItems();
    const panel_open = isCommentSidebarPanelOpen();
    const collect_ready = requireVisibleItems
      ? comment_item_count > 0
      : panel_open;
    if (collect_ready) {
      return { panel_open, comment_item_count, collect_ready: true };
    }
    await sleep(intervalMs);
  }

  const comment_item_count = countVisibleCommentItems();
  const panel_open = isCommentSidebarPanelOpen();
  return {
    panel_open,
    comment_item_count,
    collect_ready: requireVisibleItems ? comment_item_count > 0 : panel_open,
  };
}

/** 禁止误点的互动按钮（收藏/点赞/分享等） */
export const EXCLUDED_ACTION_E2E =
  /collect|favorite|favourite|digg|like|share|star|forward|转发|收藏/i;

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

export function serializeRect(rect: DOMRect): DomRect {
  return {
    top: Math.round(rect.top),
    left: Math.round(rect.left),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
}

export function centerOf(rect: DOMRect): DomPoint {
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

/** 对齐 Python `_CLICK_COMMENT_ICON_JS` 可见性 */
export function isVisible(el: Element): boolean {
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
export function resolveClickTarget(el: HTMLElement): HTMLElement {
  let node: HTMLElement | null = el;
  for (let i = 0; i < 8 && node; i += 1) {
    const rect = node.getBoundingClientRect();
    if (rect.width >= 24 && rect.height >= 24) return node;
    node = node.parentElement;
  }
  return el;
}

export function elementE2e(el: Element): string {
  const self = el.getAttribute("data-e2e") ?? "";
  if (self) return self;
  const closest = el.closest("[data-e2e]") as HTMLElement | null;
  return closest?.getAttribute("data-e2e") ?? "";
}

/** 仅允许评论入口，排除收藏/点赞等相邻图标 */
export function isCommentActionElement(el: Element): boolean {
  const e2e = elementE2e(el);
  if (!e2e) return false;
  if (EXCLUDED_ACTION_E2E.test(e2e)) return false;
  return /comment/i.test(e2e);
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

export function findAllCommentsHeader(): HTMLElement | null {
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

export function pushIconTarget(
  out: IconTarget[],
  el: HTMLElement,
  selector: string,
  priority: number,
) {
  if (!isCommentActionElement(el)) return;
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

function isCommentTabSelector(selector: string): boolean {
  return selector.startsWith("tab:评论");
}

export function clickTargetAt(primary: IconTarget): boolean {
  const el = document.elementFromPoint(primary.center.x, primary.center.y) as HTMLElement | null;
  if (!el || !isVisible(el)) return false;
  if (isCommentTabSelector(primary.selector)) {
    const target = resolveClickTarget(el);
    target.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
    humanClick(target);
    return true;
  }
  if (primary.selector.startsWith("lottie:")) {
    humanClick(resolveClickTarget(el));
    return true;
  }
  if (!isCommentActionElement(el)) return false;
  humanClick(resolveClickTarget(el));
  return true;
}

export function isCollectOverlayOpen(): boolean {
  const markers = ["加入收藏", "收藏夹", "已收藏", "取消收藏"];
  const nodes = document.querySelectorAll("div, span, p, button");
  for (let i = 0; i < nodes.length && i < 200; i += 1) {
    const el = nodes[i] as HTMLElement;
    if (!isVisible(el)) continue;
    const text = (el.textContent ?? "").replace(/\s+/g, "");
    if (!markers.some((m) => text.includes(m.replace(/\s+/g, "")))) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 40 || rect.height < 20) continue;
    return true;
  }
  return false;
}

export function dismissTransientOverlay(): void {
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
  );
}

export function findVideoPlayerCenter(): DomPoint | null {
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
