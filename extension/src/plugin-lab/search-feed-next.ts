import { dismissTransientOverlay, isCommentSidebarReadyForCollect } from "./comment-sidebar-dom";
import { isSearchFeedOverlay } from "./search-feed-open";
import { randDelay, sleep } from "./search-input";

function readFeedAwemeId(url = location.href): string | null {
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

function dispatchArrowDown(target: EventTarget = document) {
  const init = { key: "ArrowDown", code: "ArrowDown", bubbles: true, cancelable: true };
  target.dispatchEvent(new KeyboardEvent("keydown", init));
  target.dispatchEvent(new KeyboardEvent("keyup", init));
}

function wheelFeedNext(feed: HTMLElement) {
  const rect = feed.getBoundingClientRect();
  const clientX = Math.round(rect.left + rect.width * 0.5);
  const clientY = Math.round(rect.top + rect.height * 0.55);
  const deltaY = randDelay(90, 160);
  const init: WheelEventInit = {
    deltaX: 0,
    deltaY,
    deltaMode: WheelEvent.DOM_DELTA_PIXEL,
    bubbles: true,
    cancelable: true,
    clientX,
    clientY,
    view: window,
  };
  feed.dispatchEvent(new WheelEvent("wheel", init));
  document.dispatchEvent(new WheelEvent("wheel", init));
}

async function dismissCommentPanelForSwipe() {
  if (!isCommentSidebarReadyForCollect()) return;
  dismissTransientOverlay();
  await sleep(randDelay(220, 380));
  if (isCommentSidebarReadyForCollect()) {
    dismissTransientOverlay();
    await sleep(randDelay(280, 450));
  }
}

function resolveFeedSwipeTarget(): HTMLElement {
  return (
    (document.querySelector('[data-e2e="feed-active-video"]') as HTMLElement | null) ??
    (document.querySelector('[data-e2e="video-player-container"]') as HTMLElement | null) ??
    document.body
  );
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
  try {
    target.focus({ preventScroll: true });
  } catch {
    // ignore
  }

  for (let attempt = 1; attempt <= 5; attempt += 1) {
    dispatchArrowDown(target);
    wheelFeedNext(target);
    await sleep(randDelay(450, 850));

    const after = readFeedAwemeId();
    if (after && after !== before) {
      return {
        ok: true,
        is_search_feed: true,
        aweme_id: after,
        previous_aweme_id: before,
        attempt,
        method: "feed_swipe",
        url: location.href,
        message: "已在搜索 Feed 内切换到下一个视频",
      };
    }
  }

  return {
    ok: false,
    is_search_feed: isSearchFeedOverlay(),
    aweme_id: readFeedAwemeId(),
    previous_aweme_id: before,
    url: location.href,
    message: "Feed 内未能切换到下一个视频",
  };
}
