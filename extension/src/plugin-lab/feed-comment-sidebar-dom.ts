import { humanClick, humanPace, sleep } from "./search-input";
import { isSearchFeedOverlay } from "./search-feed-open";
import {
  clickTargetAt,
  COMMENT_SIDEBAR_TIMING,
  countVisibleCommentItems,
  dismissTransientOverlay,
  findAllCommentsHeader,
  findVideoPlayerCenter,
  IconTarget,
  isCollectOverlayOpen,
  isCommentActionElement,
  isCommentSidebarPanelOpen,
  isVisible,
  pollCommentSidebarState,
  pushIconTarget,
  resolveClickTarget,
} from "./comment-sidebar-shared";

const FEED_SCOPED_ICON_SELECTORS = [
  '[data-e2e="feed-active-video"] [data-e2e="feed-comment-icon"]',
  '[data-e2e="feed-active-video"] [data-e2e="comment-icon"]',
  '[data-e2e="feed-active-video"] [data-e2e="detail-tab-comment"]',
] as const;

const FEED_COMMENT_ICON_SELECTORS = [
  '[data-e2e="feed-comment-icon"]',
  '[data-e2e="comment-icon"]',
  '[data-e2e="detail-tab-comment"]',
  '[data-e2e="browse-comment-icon"]',
] as const;

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

export function isFeedCommentSidebarActive(): boolean {
  return isCommentSidebarPanelOpen();
}

/** Feed：可见评论项或「全部评论」标题即视为可采集 */
export function isFeedCommentSidebarReadyForCollect(): boolean {
  if (countVisibleCommentItems() > 0) return true;
  return findAllCommentsHeader() !== null;
}

export function collectFeedCommentIconTargets(): IconTarget[] {
  const out: IconTarget[] = [];
  const seen = new Set<string>();
  const tabPriority = 20;
  const iconPriority = 10;
  const feedScopedPriority = 0;

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

  for (const selector of FEED_COMMENT_ICON_SELECTORS) {
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

/** Feed 内再次点击评论图标以收起侧栏（切换视频前） */
export function clickFeedCommentIconViaDom(): string {
  for (const selector of FEED_COMMENT_ICON_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i] as HTMLElement;
      if (!isVisible(el) || !isCommentActionElement(el)) continue;
      humanClick(resolveClickTarget(el));
      return selector;
    }
  }
  return "";
}

function clickFeedCommentIconOnce(): string {
  const targets = collectFeedCommentIconTargets();
  const primary = targets[0];
  if (primary && clickTargetAt(primary)) return primary.selector;
  return clickFeedCommentIconViaDom();
}

function buildActivateSuccess(method: string, message: string) {
  return {
    ok: true,
    method,
    comment_item_count: countVisibleCommentItems(),
    message,
  };
}

/** Feed 浮层：展开右侧评论区（少点、多等，避免 toggle 误触） */
export async function activateFeedCommentSidebar(maxClicks: number = COMMENT_SIDEBAR_TIMING.maxDomClicks): Promise<{
  ok: boolean;
  method: string;
  comment_item_count: number;
  message: string;
}> {
  if (isFeedCommentSidebarReadyForCollect()) {
    return buildActivateSuccess("already_open", "Feed 评论区已展开");
  }

  if (isFeedCommentSidebarActive()) {
    const waited = await pollCommentSidebarState({
      maxMs: COMMENT_SIDEBAR_TIMING.panelPollMs,
    });
    if (waited.collect_ready) {
      return buildActivateSuccess("wait_load", "Feed 评论区已展开（等待加载完成）");
    }
  }

  const searchFeed = isSearchFeedOverlay();
  let lastMethod = "";

  for (let click = 0; click < maxClicks; click += 1) {
    if (isFeedCommentSidebarActive()) break;

    const hit = clickFeedCommentIconOnce();
    if (!hit) break;
    lastMethod = hit;
    await sleep(humanPace.afterCommentClick());

    if (isCollectOverlayOpen()) {
      dismissTransientOverlay();
      await sleep(300);
    }

    const opened = await pollCommentSidebarState({
      maxMs: COMMENT_SIDEBAR_TIMING.afterClickPollMs,
    });
    if (opened.panel_open) break;

    await sleep(humanPace.beforeCommentAction());
  }

  if (!isFeedCommentSidebarActive()) {
    return {
      ok: false,
      method: lastMethod || "none",
      comment_item_count: countVisibleCommentItems(),
      message: searchFeed
        ? "搜索 Feed 浮层已打开，但未能展开右侧评论区"
        : "未能打开 Feed 评论区，请确认步骤 9 已打开视频 Feed",
    };
  }

  const loaded = await pollCommentSidebarState({
    maxMs: COMMENT_SIDEBAR_TIMING.panelPollMs,
  });

  return {
    ok: loaded.panel_open,
    method: lastMethod || "poll",
    comment_item_count: loaded.comment_item_count,
    message: loaded.collect_ready
      ? lastMethod
        ? `已通过 ${lastMethod} 打开 Feed 评论区`
        : "Feed 评论区已展开"
      : "Feed 评论面板已打开，评论列表仍在加载",
  };
}

export function probeFeedCommentSidebar() {
  const icons = collectFeedCommentIconTargets();
  const commentCount = countVisibleCommentItems();
  const searchFeed = isSearchFeedOverlay();
  const feedOpen = isFeedOverlayOpen() || searchFeed;
  const sidebarActive = isFeedCommentSidebarActive();
  const sidebarReady = isFeedCommentSidebarReadyForCollect();
  const hasHeader = findAllCommentsHeader() !== null;

  return {
    ok: true,
    playback_mode: "feed" as const,
    active: sidebarActive,
    sidebar_active: sidebarActive,
    sidebar_ready: sidebarReady,
    feed_open: feedOpen,
    is_search_feed: searchFeed,
    is_standalone_video: false,
    is_video_detail_side_panel: false,
    comment_item_count: commentCount,
    has_visible_comments: commentCount > 0,
    has_comments_header: hasHeader,
    icon_targets: icons,
    video_player_center: findVideoPlayerCenter(),
    url: location.href,
    message: sidebarReady
      ? hasHeader && commentCount === 0
        ? "Feed 评论区已打开（可见「全部评论」标题）"
        : `Feed 评论区已打开（${commentCount} 条可见评论）`
      : searchFeed
        ? icons.length
          ? `搜索 Feed 已打开，找到 ${icons.length} 个评论入口`
          : "搜索 Feed 已打开，但未找到评论入口"
        : "视频 Feed 浮层未打开，请先执行步骤 9",
  };
}

export async function clickFeedCommentButtonFallback() {
  const probe = probeFeedCommentSidebar();
  const activated = await activateFeedCommentSidebar();
  return {
    ...probe,
    ok: activated.ok,
    mode: "content_dom",
    method: activated.method,
    comment_item_count: activated.comment_item_count,
    message: activated.message,
  };
}

/** Feed 浮层内滚动评论列表 */
export function scrollFeedCommentSidebar(): boolean {
  const items = document.querySelectorAll('[data-e2e="comment-item"]');
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
        const step = 240 + Math.floor(Math.random() * 140);
        node.scrollTop = Math.min(before + step, sh);
        if (node.scrollTop > before || sh > ch + 120) return true;
      }
      node = node.parentElement;
    }
  }

  return false;
}
