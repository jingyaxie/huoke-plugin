import { humanClick, humanPace, sleep } from "./search-input";
import { isSearchFeedOverlay, isStandaloneVideoPage } from "./search-feed-open";

const FEED_SCOPED_ICON_SELECTORS = [
  '[data-e2e="feed-active-video"] [data-e2e="feed-comment-icon"]',
  '[data-e2e="feed-active-video"] [data-e2e="comment-icon"]',
  '[data-e2e="feed-active-video"] [data-e2e="detail-tab-comment"]',
] as const;

const COMMENT_ICON_SELECTORS = [
  '[data-e2e="feed-comment-icon"]',
  '[data-e2e="comment-icon"]',
  '[data-e2e="detail-tab-comment"]',
] as const;

/** 禁止误点的互动按钮（收藏/点赞/分享等） */
const EXCLUDED_ACTION_E2E =
  /collect|favorite|favourite|digg|like|share|star|forward|转发|收藏/i;

function elementE2e(el: Element): string {
  const self = el.getAttribute("data-e2e") ?? "";
  if (self) return self;
  const closest = el.closest("[data-e2e]") as HTMLElement | null;
  return closest?.getAttribute("data-e2e") ?? "";
}

/** 仅允许评论入口，排除收藏/点赞等相邻图标 */
function isCommentActionElement(el: Element): boolean {
  const e2e = elementE2e(el);
  if (!e2e) return false;
  if (EXCLUDED_ACTION_E2E.test(e2e)) return false;
  return /comment/i.test(e2e);
}

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

/** 对齐 Python：搜索 Feed 须可见评论项才算已展开；独立页/详情页「全部评论」标题也算打开 */
export function isCommentSidebarReadyForCollect(): boolean {
  const itemCount = countVisibleCommentItems();
  if (itemCount > 0) return true;
  const searchFeed = isSearchFeedOverlay();
  if (searchFeed) return false;
  return findAllCommentsHeader() !== null;
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

function pushIconTarget(
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

function clickTargetAt(primary: IconTarget): boolean {
  const el = document.elementFromPoint(primary.center.x, primary.center.y) as HTMLElement | null;
  if (!el || !isVisible(el)) return false;
  if (isCommentTabSelector(primary.selector)) {
    const target = resolveClickTarget(el);
    target.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
    humanClick(target);
    return true;
  }
  if (!isCommentActionElement(el)) return false;
  humanClick(resolveClickTarget(el));
  return true;
}

export function collectCommentIconTargets(): IconTarget[] {
  const out: IconTarget[] = [];
  const seen = new Set<string>();
  const standalone = isStandaloneVideoPage();
  const tabPriority = standalone ? 0 : 20;
  const iconPriority = standalone ? 10 : 10;
  const feedScopedPriority = standalone ? 15 : 0;

  for (const selector of FEED_SCOPED_ICON_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i] as HTMLElement;
      const key = `${selector}:${Math.round(el.getBoundingClientRect().top)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      pushIconTarget(out, el, selector, feedScopedPriority);
    }
  }

  for (const selector of COMMENT_ICON_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i] as HTMLElement;
      const key = `${selector}:${Math.round(el.getBoundingClientRect().top)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      pushIconTarget(out, el, selector, iconPriority);
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
    pushIconTarget(out, el, "tab:评论", tabPriority);
  }

  out.sort((a, b) => a.priority - b.priority || a.center.y - b.center.y);
  return out;
}

/** 每轮只点一个最可信的评论入口，避免连点误触收藏/点赞 */
export function pickPrimaryCommentTarget(): IconTarget | null {
  const targets = collectCommentIconTargets();
  return targets[0] ?? null;
}

function isCollectOverlayOpen(): boolean {
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

/** 对齐 Python `_CLICK_COMMENT_ICON_JS` */
export function clickCommentIconViaDom(): string {
  for (const selector of COMMENT_ICON_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i] as HTMLElement;
      if (!isVisible(el) || !isCommentActionElement(el)) continue;
      humanClick(resolveClickTarget(el));
      return selector;
    }
  }

  const tabs = document.querySelectorAll('div[role="tab"], span, div, button');
  for (let i = 0; i < tabs.length && i < 120; i += 1) {
    const el = tabs[i] as HTMLElement;
    const text = (el.textContent ?? "").replace(/\s+/g, "");
    if (text !== "评论" && !text.startsWith("评论(")) continue;
    if (!isVisible(el)) continue;
    humanClick(resolveClickTarget(el));
    return "tab:评论";
  }

  return "";
}

/** 内容脚本内尝试展开评论区（CDP 失败后的兜底） */
export async function activateCommentSidebar(maxAttempts = 5): Promise<{
  ok: boolean;
  method: string;
  comment_item_count: number;
  message: string;
}> {
  if (isCommentSidebarReadyForCollect()) {
    return {
      ok: true,
      method: "already_open",
      comment_item_count: countVisibleCommentItems(),
      message: "评论区已展开",
    };
  }

  const searchFeed = isSearchFeedOverlay();
  const standalone = isStandaloneVideoPage();
  let lastMethod = "";

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (isCommentSidebarReadyForCollect()) {
      return {
        ok: true,
        method: lastMethod || "probe",
        comment_item_count: countVisibleCommentItems(),
        message: "评论区已展开",
      };
    }

    const primary = pickPrimaryCommentTarget();
    if (primary && clickTargetAt(primary)) {
      lastMethod = primary.selector;
      await sleep(humanPace.afterCommentClick());
      if (isCommentSidebarReadyForCollect()) {
        return {
          ok: true,
          method: lastMethod,
          comment_item_count: countVisibleCommentItems(),
          message: `已通过 ${lastMethod} 打开评论区`,
        };
      }
      if (isCollectOverlayOpen()) {
        dismissTransientOverlay();
        await sleep(300);
      }
    }

    const domHit = clickCommentIconViaDom();
    if (domHit) {
      lastMethod = domHit;
      await sleep(humanPace.afterCommentClick());
      if (isCommentSidebarReadyForCollect()) {
        return {
          ok: true,
          method: domHit,
          comment_item_count: countVisibleCommentItems(),
          message: `已通过 DOM 点击 ${domHit} 打开评论区`,
        };
      }
      if (isCollectOverlayOpen()) {
        dismissTransientOverlay();
        await sleep(300);
      }
    }

    if (!searchFeed && !standalone) {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
      );
      await sleep(300);
    }

    if (standalone && attempt === 0) {
      window.scrollBy({ top: 320, behavior: "instant" });
      await sleep(humanPace.beforeCommentAction());
    }

    await sleep(humanPace.beforeCommentAction());
  }

  return {
    ok: false,
    method: lastMethod || "none",
    comment_item_count: countVisibleCommentItems(),
    message: standalone
      ? "独立视频页未能展开评论区，请确认已登录且「评论」Tab 可见"
      : searchFeed
        ? "搜索 Feed 浮层已打开，但未能展开右侧评论区"
        : "未能打开评论区，请确认视频 Feed 已打开",
  };
}

/** 供 background CDP 探测 */
export function probeCommentSidebar() {
  const icons = collectCommentIconTargets();
  const commentCount = countVisibleCommentItems();
  const searchFeed = isSearchFeedOverlay();
  const feedOpen = isFeedOverlayOpen() || searchFeed;
  const standalone = isStandaloneVideoPage();
  const sidebarActive = isCommentSidebarActive();
  const sidebarReady = isCommentSidebarReadyForCollect();
  const hasHeader = findAllCommentsHeader() !== null;

  return {
    ok: true,
    active: sidebarActive,
    sidebar_active: sidebarActive,
    sidebar_ready: sidebarReady,
    feed_open: feedOpen,
    is_search_feed: searchFeed,
    is_standalone_video: standalone,
    comment_item_count: commentCount,
    has_visible_comments: commentCount > 0,
    has_comments_header: hasHeader,
    icon_targets: icons,
    video_player_center: findVideoPlayerCenter(),
    url: location.href,
    message: standalone
      ? sidebarReady
        ? hasHeader && commentCount === 0
          ? "独立视频页评论区已打开（可见「全部评论」标题）"
          : `独立视频页评论区已打开（${commentCount} 条可见评论）`
        : icons.length
          ? `独立视频页，找到 ${icons.length} 个评论入口（评论在视频下方）`
          : "独立视频页，等待点击「评论」Tab 展开下方评论区"
      : sidebarActive
        ? hasHeader && commentCount === 0
          ? "评论区已打开（可见「全部评论」标题）"
          : `评论区已打开（${commentCount} 条可见评论）`
        : searchFeed
          ? icons.length
            ? `搜索 Feed 已打开，找到 ${icons.length} 个评论入口`
            : searchFeed && commentCount > 0
              ? "搜索 Feed 右侧评论栏已可见"
              : "搜索 Feed 已打开，但未找到评论入口"
          : "搜索 Feed 浮层未打开，请先执行步骤 9",
  };
}

export async function clickCommentButtonFallback() {
  const probe = probeCommentSidebar();
  const activated = await activateCommentSidebar();
  return {
    ...probe,
    ok: activated.ok,
    mode: "content_dom",
    method: activated.method,
    comment_item_count: activated.comment_item_count,
    message: activated.message,
  };
}
