import {
  clickCommentIconViaDom,
  isCommentSidebarReadyForCollect,
  probeCommentSidebar,
} from "./comment-sidebar-dom";
import { recoverProfileFeedFromAweme } from "./profile-video-dom";
import {
  isDouyinFeedOverlay,
  isProfileFeedOverlay,
  isSearchFeedOverlay,
  openFeedViaModalId,
  readStoredSearchResultsUrl,
} from "./search-feed-open";
import { humanClick, isVisible, randDelay, sleep } from "./search-input";

/** 搜索 Feed 右侧「下一个」下箭头 SVG path 特征（viewBox 0 0 26 26） */
const FEED_NEXT_ARROW_PATH_MARKERS = [
  "M7.26904 9.29059",
  "17.3808 9.29053",
  "13.3098 13.3616",
] as const;

function isFeedNextArrowSvg(svg: SVGElement): boolean {
  const viewBox = svg.getAttribute("viewBox")?.replace(/\s+/g, " ") ?? "";
  if (viewBox && viewBox !== "0 0 26 26") return false;
  const path = svg.querySelector("path");
  const d = path?.getAttribute("d") ?? "";
  if (!d) return false;
  return FEED_NEXT_ARROW_PATH_MARKERS.some((mark) => d.includes(mark));
}

function resolveClickableAncestor(el: Element, maxDepth = 8): HTMLElement | null {
  let node: Element | null = el;
  for (let depth = 0; node && depth < maxDepth; depth += 1) {
    if (node instanceof HTMLElement && isVisible(node)) {
      const tag = node.tagName.toLowerCase();
      const role = node.getAttribute("role") ?? "";
      if (
        tag === "button" ||
        role === "button" ||
        node.hasAttribute("tabindex") ||
        getComputedStyle(node).cursor === "pointer"
      ) {
        return node;
      }
    }
    node = node.parentElement;
  }
  return el instanceof HTMLElement && isVisible(el) ? el : null;
}

/** 搜索 Feed 浮层内「下一个视频」下箭头按钮 */
export function findFeedNextVideoButton(): HTMLElement | null {
  const feedRoot =
    (document.querySelector('[data-e2e="feed-active-video"]') as HTMLElement | null)?.closest(
      '[class*="Player"], [class*="player"], [class*="Feed"], section, div',
    ) ?? document.body;

  const scope = feedRoot instanceof HTMLElement ? feedRoot : document.body;
  const svgs = scope.querySelectorAll("svg");
  for (let i = 0; i < svgs.length; i += 1) {
    const svg = svgs[i];
    if (!(svg instanceof SVGElement) || !isFeedNextArrowSvg(svg)) continue;
    const rect = svg.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) continue;
    const clickable = resolveClickableAncestor(svg);
    if (clickable) return clickable;
  }

  // 兜底：整页扫描（浮层层级可能不在 feed-active-video 子树内）
  const allSvgs = document.querySelectorAll("svg");
  for (let i = 0; i < allSvgs.length; i += 1) {
    const svg = allSvgs[i];
    if (!(svg instanceof SVGElement) || !isFeedNextArrowSvg(svg)) continue;
    const rect = svg.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8 || rect.top < 40) continue;
    const clickable = resolveClickableAncestor(svg);
    if (clickable) return clickable;
  }
  return null;
}

async function clickFeedNextVideoButton(): Promise<boolean> {
  const btn = findFeedNextVideoButton();
  if (!btn) return false;
  humanClick(btn);
  await sleep(randDelay(320, 520));
  return true;
}

export function readFeedAwemeId(url = location.href): string | null {
  try {
    const modal = new URL(url).searchParams.get("modal_id");
    if (modal && /^\d{8,22}$/.test(modal)) return modal;
  } catch {
    // ignore
  }

  const feed = document.querySelector('[data-e2e="feed-active-video"]');
  if (feed) {
    const link = feed.querySelector('a[href*="/video/"]') as HTMLAnchorElement | null;
    const match = link?.href.match(/\/video\/(\d{8,22})/i);
    if (match?.[1]) return match[1];
  }
  return null;
}

function dispatchKey(target: EventTarget, key: string, code: string) {
  const init = { key, code, bubbles: true, cancelable: true };
  target.dispatchEvent(new KeyboardEvent("keydown", init));
  target.dispatchEvent(new KeyboardEvent("keyup", init));
}

function resolveFeedSwipeTarget(): HTMLElement {
  return (
    (document.querySelector('[data-e2e="feed-active-video"]') as HTMLElement | null) ??
    (document.querySelector('[data-e2e="video-player-container"]') as HTMLElement | null) ??
    document.body
  );
}

function resolveVideoFocusPoint(target: HTMLElement): { x: number; y: number } {
  const rect = target.getBoundingClientRect();
  return {
    x: Math.round(rect.left + Math.min(rect.width * 0.35, rect.width - 48)),
    y: Math.round(rect.top + rect.height * 0.52),
  };
}

function dispatchWheelAt(target: HTMLElement, deltaY: number) {
  const point = resolveVideoFocusPoint(target);
  const init: WheelEventInit = {
    deltaX: 0,
    deltaY,
    deltaMode: WheelEvent.DOM_DELTA_PIXEL,
    bubbles: true,
    cancelable: true,
    clientX: point.x,
    clientY: point.y,
    view: window,
  };
  target.dispatchEvent(new WheelEvent("wheel", init));
  window.dispatchEvent(new WheelEvent("wheel", init));
  document.dispatchEvent(new WheelEvent("wheel", init));
}

async function wheelFeedNext(feed: HTMLElement) {
  const total = randDelay(520, 860);
  const segments = randDelay(6, 9);
  const perStep = Math.max(48, Math.round(total / segments));
  for (let i = 0; i < segments; i += 1) {
    dispatchWheelAt(feed, perStep + randDelay(-8, 12));
    await sleep(randDelay(55, 110));
  }
}

async function pointerDragFeedNext(feed: HTMLElement) {
  const start = resolveVideoFocusPoint(feed);
  const endY = start.y - randDelay(220, 340);
  const target = feed === document.body ? document.documentElement : feed;
  const pointerInit: PointerEventInit = {
    bubbles: true,
    cancelable: true,
    clientX: start.x,
    clientY: start.y,
    pointerId: 1,
    pointerType: "touch",
    isPrimary: true,
  };
  target.dispatchEvent(new PointerEvent("pointerdown", pointerInit));
  const steps = randDelay(8, 12);
  for (let i = 1; i <= steps; i += 1) {
    const t = i / steps;
    const y = Math.round(start.y + (endY - start.y) * t);
    target.dispatchEvent(
      new PointerEvent("pointermove", {
        ...pointerInit,
        clientX: start.x,
        clientY: y,
      }),
    );
    await sleep(randDelay(16, 36));
  }
  target.dispatchEvent(
    new PointerEvent("pointerup", {
      ...pointerInit,
      clientX: start.x,
      clientY: endY,
    }),
  );
}

async function dismissCommentPanelForSwipe() {
  const inDouyinFeed = isDouyinFeedOverlay();
  const player = resolveFeedSwipeTarget();

  // 先点视频区收回焦点；Feed 浮层内禁止 Escape（会关掉整个 Feed）
  await focusFeedPlayer(player);
  await sleep(randDelay(180, 300));

  if (!isCommentSidebarReadyForCollect()) return;

  if (inDouyinFeed) {
    clickCommentIconViaDom();
    await sleep(randDelay(280, 420));
    await focusFeedPlayer(player);
    await sleep(randDelay(180, 280));
    return;
  }

  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
  );
  await sleep(randDelay(220, 320));
}

function feedOverlayReady(): boolean {
  return isDouyinFeedOverlay();
}

/** 采完评论后、切下一个视频前：确保仍在 Feed 且评论区不挡操作 */
export async function prepareFeedForSwipe() {
  if (!feedOverlayReady()) {
    const awemeId = readFeedAwemeId();
    return {
      ok: false,
      is_search_feed: false,
      aweme_id: awemeId,
      url: location.href,
      message: "不在 Feed 浮层",
    };
  }

  await dismissCommentPanelForSwipe();
  const stillInFeed = feedOverlayReady();
  return {
    ok: stillInFeed,
    is_search_feed: stillInFeed,
    aweme_id: readFeedAwemeId(),
    url: location.href,
    message: stillInFeed ? "Feed 已就绪，可切换下一个视频" : "Feed 浮层已关闭",
  };
}

/** 用 modal_id 恢复搜索 Feed（Feed 被误关时） */
export async function recoverSearchFeedFromAweme(awemeId: string) {
  const id = String(awemeId ?? "").trim();
  if (!/^\d{8,22}$/.test(id)) {
    return {
      ok: false,
      is_search_feed: false,
      message: "缺少有效 aweme_id，无法恢复 Feed",
      url: location.href,
    };
  }
  const opened = await openFeedViaModalId(id);
  const phase = feedOverlayReady();
  return {
    ok: opened.ok && phase,
    is_search_feed: phase,
    aweme_id: readFeedAwemeId() ?? id,
    url: location.href,
    message: opened.message,
  };
}

/** 搜索/主页 Feed 被误关时恢复（优先搜索页，其次主页） */
export async function recoverDouyinFeedFromAweme(awemeId: string) {
  const id = String(awemeId ?? "").trim();
  if (!/^\d{8,22}$/.test(id)) {
    return {
      ok: false,
      is_search_feed: false,
      message: "缺少有效 aweme_id，无法恢复 Feed",
      url: location.href,
    };
  }

  const hasSearchContext = Boolean(readStoredSearchResultsUrl()) || isSearchFeedOverlay();
  if (hasSearchContext) {
    const search = await recoverSearchFeedFromAweme(id);
    if (search.ok) return search;
  }

  const profile = await recoverProfileFeedFromAweme(id);
  if (profile.ok) return profile;

  if (!hasSearchContext) {
    return await recoverSearchFeedFromAweme(id);
  }
  return profile;
}

export function probeDouyinFeed() {
  const inFeed = feedOverlayReady();
  return {
    ok: inFeed,
    is_search_feed: inFeed,
    is_profile_feed: isProfileFeedOverlay(),
    aweme_id: readFeedAwemeId(),
    url: location.href,
    message: inFeed ? "Feed 浮层已打开" : "不在 Feed 浮层",
  };
}

async function focusFeedPlayer(target: HTMLElement) {
  const point = resolveVideoFocusPoint(target);
  const el = document.elementFromPoint(point.x, point.y);
  if (el instanceof HTMLElement) {
    humanClick(el);
  } else {
    humanClick(target);
  }
  try {
    target.focus({ preventScroll: true });
  } catch {
    // ignore
  }
  await sleep(randDelay(280, 480));
}

async function waitForFeedAwemeChange(before: string | null, maxMs = 3200): Promise<string | null> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    const after = readFeedAwemeId();
    if (after && after !== before) return after;
    await sleep(180);
  }
  return readFeedAwemeId();
}

/** 搜索/主页 Feed 浮层内切换到下一个视频（上滑/ArrowDown），无需返回列表 */
export async function swipeSearchFeedNext() {
  if (!feedOverlayReady()) {
    return {
      ok: false,
      is_search_feed: false,
      url: location.href,
      message: "不在 Feed 浮层，无法 Feed 内切下一个视频",
    };
  }

  const before = readFeedAwemeId();
  await dismissCommentPanelForSwipe();

  if (!feedOverlayReady()) {
    return {
      ok: false,
      is_search_feed: false,
      aweme_id: before,
      previous_aweme_id: before,
      url: location.href,
      message: "Feed 浮层已关闭（请勿用 Escape 关评论）",
    };
  }

  const target = resolveFeedSwipeTarget();
  await focusFeedPlayer(target);

  if (await clickFeedNextVideoButton()) {
    const afterArrow = await waitForFeedAwemeChange(before, 3500);
    if (afterArrow && afterArrow !== before) {
      return {
        ok: true,
        is_search_feed: true,
        aweme_id: afterArrow,
        previous_aweme_id: before,
        attempt: 1,
        method: "next_arrow_click",
        url: location.href,
        message: "已通过下箭头按钮切换到下一个视频",
      };
    }
  }

  const methods: Array<() => Promise<void>> = [
    async () => {
      dispatchKey(target, "ArrowDown", "ArrowDown");
      dispatchKey(document, "PageDown", "PageDown");
      await wheelFeedNext(target);
    },
    async () => {
      await pointerDragFeedNext(target);
      await wheelFeedNext(target);
    },
    async () => {
      dispatchKey(document, "ArrowDown", "ArrowDown");
      await sleep(randDelay(120, 220));
      await pointerDragFeedNext(target);
    },
  ];

  const methodNames = ["wheel_key", "pointer_wheel", "pointer_key"] as const;

  for (let attempt = 1; attempt <= methods.length; attempt += 1) {
    await methods[attempt - 1]();
    const after = await waitForFeedAwemeChange(before, 3500);
    if (after && after !== before) {
      return {
        ok: true,
        is_search_feed: true,
        aweme_id: after,
        previous_aweme_id: before,
        attempt: attempt + 1,
        method: methodNames[attempt - 1] ?? "unknown",
        url: location.href,
        message: "已在 Feed 内切换到下一个视频",
      };
    }
  }

  const sidebar = probeCommentSidebar();
  return {
    ok: false,
    is_search_feed: feedOverlayReady(),
    aweme_id: readFeedAwemeId(),
    previous_aweme_id: before,
    comment_sidebar_open: sidebar.sidebar_ready,
    url: location.href,
    message: sidebar.sidebar_ready
      ? "Feed 内未能切换：评论区可能仍占据焦点，请稍后重试"
      : "Feed 内未能切换到下一个视频",
  };
}
