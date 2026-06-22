import { humanClick, humanPace, sleep } from "./search-input";
import { isStandaloneVideoPage } from "./search-feed-open";
import {
  centerOf,
  clickTargetAt,
  countVisibleCommentItems,
  dismissTransientOverlay,
  findAllCommentsHeader,
  findVideoPlayerCenter,
  IconTarget,
  isCollectOverlayOpen,
  isCommentActionElement,
  isVisible,
  pushIconTarget,
  resolveClickTarget,
  serializeRect,
} from "./comment-sidebar-shared";

const VIDEO_DETAIL_COMMENT_ICON_SELECTORS = [
  '[data-e2e="feed-comment-icon"]',
  '[data-e2e="comment-icon"]',
  '[data-e2e="detail-tab-comment"]',
  '[data-e2e="browse-comment-icon"]',
] as const;

/** 抖音 /video/ 详情页右侧互动栏（Lottie SVG，viewBox 0 0 99 99） */
const STANDALONE_COMMENT_LOTTIE_MARKERS = [
  "M-5.79,5.98",
  "-13.5,-11.25",
  "-13.34,11.06",
] as const;

function isStandaloneCommentLottieSvg(svg: SVGElement): boolean {
  const path = svg.querySelector("path")?.getAttribute("d") ?? "";
  if (!path || path.length < 40) return false;
  if (STANDALONE_COMMENT_LOTTIE_MARKERS.some((mark) => path.includes(mark))) return true;
  if (path.includes("-4.644") || path.includes("-13.5,-11.25") || path.includes("-13.34,11.06")) {
    return true;
  }
  const viewBox = svg.getAttribute("viewBox")?.replace(/\s+/g, " ") ?? "";
  return viewBox === "0 0 99 99" && path.includes(" C") && path.includes("-13.");
}

function resolveSideActionClickTarget(el: Element, maxDepth = 10): HTMLElement | null {
  let node: Element | null = el;
  for (let depth = 0; node && depth < maxDepth; depth += 1) {
    if (node instanceof HTMLElement && isVisible(node)) {
      const rect = node.getBoundingClientRect();
      if (rect.width >= 28 && rect.height >= 28) return node;
    }
    node = node.parentElement;
  }
  return el instanceof HTMLElement ? el : null;
}

function collectVideoDetailSideCommentTargets(): IconTarget[] {
  if (!isStandaloneVideoPage()) return [];
  const out: IconTarget[] = [];
  const minX = window.innerWidth * 0.42;

  for (const svg of Array.from(document.querySelectorAll("svg"))) {
    if (!(svg instanceof SVGElement) || !isStandaloneCommentLottieSvg(svg)) continue;
    const rect = svg.getBoundingClientRect();
    if (rect.width < 12 || rect.height < 12) continue;
    if (rect.left < minX) continue;
    const clickable = resolveSideActionClickTarget(svg);
    if (!clickable) continue;
    const clickRect = clickable.getBoundingClientRect();
    out.push({
      selector: "lottie:standalone-comment",
      center: centerOf(clickRect),
      rect: serializeRect(clickRect),
      priority: 0,
    });
  }
  return out;
}

/** /video/ 页是否使用右侧互动栏（非下方 Tab） */
export function isDouyinVideoDetailSidePanel(url = location.href): boolean {
  if (!isStandaloneVideoPage(url)) return false;
  if (collectVideoDetailSideCommentTargets().length > 0) return true;
  for (const selector of VIDEO_DETAIL_COMMENT_ICON_SELECTORS) {
    const el = document.querySelector(selector);
    if (el && isVisible(el)) {
      const rect = el.getBoundingClientRect();
      if (rect.left >= window.innerWidth * 0.42) return true;
    }
  }
  return false;
}

export function isVideoDetailCommentSidebarActive(): boolean {
  return countVisibleCommentItems() > 0 || findAllCommentsHeader() !== null;
}

/** /video/ 详情页：可见评论项或「全部评论」标题即算展开 */
export function isVideoDetailCommentSidebarReadyForCollect(): boolean {
  const itemCount = countVisibleCommentItems();
  if (itemCount > 0) return true;
  return findAllCommentsHeader() !== null;
}

export function collectVideoDetailCommentIconTargets(): IconTarget[] {
  const out: IconTarget[] = [];
  const seen = new Set<string>();
  const sidePanel = isDouyinVideoDetailSidePanel();
  const tabPriority = sidePanel ? 20 : 0;
  const iconPriority = sidePanel ? 4 : 10;

  for (const target of collectVideoDetailSideCommentTargets()) {
    const key = `lottie:${target.center.x}:${target.center.y}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(target);
  }

  for (const selector of VIDEO_DETAIL_COMMENT_ICON_SELECTORS) {
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

function clickVideoDetailCommentIconViaDom(): string {
  for (const selector of VIDEO_DETAIL_COMMENT_ICON_SELECTORS) {
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

/** /video/ 详情页：展开评论区 */
export async function activateVideoDetailCommentSidebar(maxAttempts = 5): Promise<{
  ok: boolean;
  method: string;
  comment_item_count: number;
  message: string;
}> {
  if (isVideoDetailCommentSidebarReadyForCollect()) {
    return {
      ok: true,
      method: "already_open",
      comment_item_count: countVisibleCommentItems(),
      message: "视频详情页评论区已展开",
    };
  }

  const sidePanel = isDouyinVideoDetailSidePanel();
  let lastMethod = "";

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (isVideoDetailCommentSidebarReadyForCollect()) {
      return {
        ok: true,
        method: lastMethod || "probe",
        comment_item_count: countVisibleCommentItems(),
        message: "视频详情页评论区已展开",
      };
    }

    if (sidePanel && attempt === 0) {
      const side = collectVideoDetailSideCommentTargets()[0]
        ?? collectVideoDetailCommentIconTargets()[0];
      if (side && clickTargetAt(side)) {
        lastMethod = side.selector;
        await sleep(humanPace.afterCommentClick());
        if (isVideoDetailCommentSidebarReadyForCollect()) {
          return {
            ok: true,
            method: lastMethod,
            comment_item_count: countVisibleCommentItems(),
            message: "已通过右侧评论图标打开评论区",
          };
        }
      }
    }

    const targets = collectVideoDetailCommentIconTargets();
    const primary = targets[0];
    if (primary && clickTargetAt(primary)) {
      lastMethod = primary.selector;
      await sleep(humanPace.afterCommentClick());
      if (isVideoDetailCommentSidebarReadyForCollect()) {
        return {
          ok: true,
          method: lastMethod,
          comment_item_count: countVisibleCommentItems(),
          message: `已通过 ${lastMethod} 打开视频详情页评论区`,
        };
      }
      if (isCollectOverlayOpen()) {
        dismissTransientOverlay();
        await sleep(300);
      }
    }

    const domHit = clickVideoDetailCommentIconViaDom();
    if (domHit) {
      lastMethod = domHit;
      await sleep(humanPace.afterCommentClick());
      if (isVideoDetailCommentSidebarReadyForCollect()) {
        return {
          ok: true,
          method: domHit,
          comment_item_count: countVisibleCommentItems(),
          message: `已通过 DOM 点击 ${domHit} 打开视频详情页评论区`,
        };
      }
      if (isCollectOverlayOpen()) {
        dismissTransientOverlay();
        await sleep(300);
      }
    }

    if (!sidePanel) {
      window.scrollBy({ top: 320, behavior: "instant" });
      await sleep(humanPace.beforeCommentAction());
    }

    await sleep(humanPace.beforeCommentAction());
  }

  return {
    ok: false,
    method: lastMethod || "none",
    comment_item_count: countVisibleCommentItems(),
    message: sidePanel
      ? "视频详情页未能展开右侧评论区，请确认评论图标可见"
      : "视频详情页未能展开评论区，请确认「评论」Tab 可见",
  };
}

export function probeVideoDetailCommentSidebar() {
  const icons = collectVideoDetailCommentIconTargets();
  const commentCount = countVisibleCommentItems();
  const sidePanel = isDouyinVideoDetailSidePanel();
  const sidebarActive = isVideoDetailCommentSidebarActive();
  const sidebarReady = isVideoDetailCommentSidebarReadyForCollect();
  const hasHeader = findAllCommentsHeader() !== null;

  return {
    ok: true,
    playback_mode: "video_detail" as const,
    active: sidebarActive,
    sidebar_active: sidebarActive,
    sidebar_ready: sidebarReady,
    feed_open: false,
    is_search_feed: false,
    is_standalone_video: true,
    is_video_detail_side_panel: sidePanel,
    comment_item_count: commentCount,
    has_visible_comments: commentCount > 0,
    has_comments_header: hasHeader,
    icon_targets: icons,
    video_player_center: findVideoPlayerCenter(),
    url: location.href,
    message: sidebarReady
      ? hasHeader && commentCount === 0
        ? "视频详情页评论区已打开（可见「全部评论」标题）"
        : `视频详情页评论区已打开（${commentCount} 条可见评论）`
      : sidePanel
        ? icons.length
          ? `视频详情页，找到 ${icons.length} 个右侧评论入口`
          : "视频详情页，等待点击右侧评论图标"
        : icons.length
          ? `视频详情页，找到 ${icons.length} 个评论入口（下方 Tab）`
          : "视频详情页，等待点击「评论」Tab",
  };
}

export async function clickVideoDetailCommentButtonFallback() {
  const probe = probeVideoDetailCommentSidebar();
  const activated = await activateVideoDetailCommentSidebar();
  return {
    ...probe,
    ok: activated.ok,
    mode: "content_dom",
    method: activated.method,
    comment_item_count: activated.comment_item_count,
    message: activated.message,
  };
}

/** /video/ 详情页：整页滚动加载评论 */
export function scrollVideoDetailCommentSidebar(): boolean {
  window.scrollBy({ top: 280 + Math.floor(Math.random() * 120), behavior: "instant" });
  return true;
}
