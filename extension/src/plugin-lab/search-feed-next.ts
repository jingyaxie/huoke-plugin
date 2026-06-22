import {
  dismissTransientOverlay,
  isCommentSidebarReadyForCollect,
  probeCommentSidebar,
} from "./comment-sidebar-dom";
import { isSearchFeedOverlay } from "./search-feed-open";
import { humanClick, randDelay, sleep } from "./search-input";

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
  for (let i = 0; i < 3; i += 1) {
    if (!isCommentSidebarReadyForCollect()) break;
    dismissTransientOverlay();
    await sleep(randDelay(220, 380));
  }
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

async function waitForFeedAwemeChange(before: string | null, maxMs = 1800): Promise<string | null> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    const after = readFeedAwemeId();
    if (after && after !== before) return after;
    await sleep(180);
  }
  return readFeedAwemeId();
}

/** 搜索 Feed 浮层内切换到下一个视频（上滑/ArrowDown），无需返回列表 */
export async function swipeSearchFeedNext() {
  if (!isSearchFeedOverlay()) {
    return {
      ok: false,
      is_search_feed: false,
      url: location.href,
      message: "不在搜索 Feed 浮层，无法 Feed 内切下一个视频",
    };
  }

  const before = readFeedAwemeId();
  await dismissCommentPanelForSwipe();

  const target = resolveFeedSwipeTarget();
  await focusFeedPlayer(target);

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

  for (let attempt = 1; attempt <= methods.length; attempt += 1) {
    await methods[attempt - 1]();
    const after = await waitForFeedAwemeChange(before, 2000);
    if (after && after !== before) {
      return {
        ok: true,
        is_search_feed: true,
        aweme_id: after,
        previous_aweme_id: before,
        attempt,
        method: attempt === 1 ? "wheel_key" : attempt === 2 ? "pointer_wheel" : "pointer_key",
        url: location.href,
        message: "已在搜索 Feed 内切换到下一个视频",
      };
    }
  }

  const sidebar = probeCommentSidebar();
  return {
    ok: false,
    is_search_feed: isSearchFeedOverlay(),
    aweme_id: readFeedAwemeId(),
    previous_aweme_id: before,
    comment_sidebar_open: sidebar.sidebar_ready,
    url: location.href,
    message: sidebar.sidebar_ready
      ? "Feed 内未能切换：评论区可能仍占据焦点，请稍后重试"
      : "Feed 内未能切换到下一个视频",
  };
}
