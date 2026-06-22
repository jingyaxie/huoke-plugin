import {
  isVideoDetailCommentSidebarReadyForCollect,
  probeVideoDetailCommentSidebar,
} from "./video-detail-comment-sidebar-dom";
import { isStandaloneVideoPage } from "./search-feed-open";
import { humanClick, isVisible, randDelay, sleep } from "./search-input";

/** 详情页 /video/ 右侧「下一个」下箭头 SVG（与 Feed 浮层相同 viewBox 0 0 26 26） */
const DETAIL_NEXT_ARROW_PATH_MARKERS = [
  "M7.26904 9.29059",
  "17.3808 9.29053",
  "13.3098 13.3616",
] as const;

function isDetailNextArrowSvg(svg: SVGElement): boolean {
  const viewBox = svg.getAttribute("viewBox")?.replace(/\s+/g, " ") ?? "";
  if (viewBox && viewBox !== "0 0 26 26") return false;
  const path = svg.querySelector("path");
  const d = path?.getAttribute("d") ?? "";
  if (!d) return false;
  return DETAIL_NEXT_ARROW_PATH_MARKERS.some((mark) => d.includes(mark));
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

/** /video/ 详情页播放器旁「下一个视频」下箭头 */
export function findVideoDetailNextButton(): HTMLElement | null {
  const playerRoot =
    (document.querySelector('[data-e2e="video-player-container"]') as HTMLElement | null)
    ?? (document.querySelector('[class*="PlayerContainer"]') as HTMLElement | null)
    ?? document.body;

  const scope = playerRoot instanceof HTMLElement ? playerRoot : document.body;
  const svgs = scope.querySelectorAll("svg");
  for (let i = 0; i < svgs.length; i += 1) {
    const svg = svgs[i];
    if (!(svg instanceof SVGElement) || !isDetailNextArrowSvg(svg)) continue;
    const rect = svg.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) continue;
    const clickable = resolveClickableAncestor(svg);
    if (clickable) return clickable;
  }

  const allSvgs = document.querySelectorAll("svg");
  for (let i = 0; i < allSvgs.length; i += 1) {
    const svg = allSvgs[i];
    if (!(svg instanceof SVGElement) || !isDetailNextArrowSvg(svg)) continue;
    const rect = svg.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8 || rect.top < 40) continue;
    if (rect.left < window.innerWidth * 0.08) continue;
    const clickable = resolveClickableAncestor(svg);
    if (clickable) return clickable;
  }
  return null;
}

export function readVideoDetailAwemeId(url = location.href): string | null {
  const match = url.match(/\/video\/(\d{8,22})/i) ?? url.match(/\/note\/(\d{8,22})/i);
  return match?.[1] ?? null;
}

function resolveVideoDetailSwipeTarget(): HTMLElement {
  return (
    (document.querySelector('[data-e2e="video-player-container"]') as HTMLElement | null)
    ?? (document.querySelector('[class*="PlayerContainer"]') as HTMLElement | null)
    ?? document.body
  );
}

function resolveVideoFocusPoint(target: HTMLElement): { x: number; y: number } {
  const rect = target.getBoundingClientRect();
  return {
    x: Math.round(rect.left + Math.min(rect.width * 0.35, rect.width - 48)),
    y: Math.round(rect.top + rect.height * 0.52),
  };
}

function dispatchKey(target: EventTarget, key: string, code: string) {
  const init = { key, code, bubbles: true, cancelable: true };
  target.dispatchEvent(new KeyboardEvent("keydown", init));
  target.dispatchEvent(new KeyboardEvent("keyup", init));
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

async function wheelDetailNext(target: HTMLElement) {
  const total = randDelay(520, 860);
  const segments = randDelay(6, 9);
  const perStep = Math.max(48, Math.round(total / segments));
  for (let i = 0; i < segments; i += 1) {
    dispatchWheelAt(target, perStep + randDelay(-8, 12));
    await sleep(randDelay(55, 110));
  }
}

async function focusVideoDetailPlayer(target: HTMLElement) {
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

async function dismissCommentPanelForDetailSwipe() {
  const player = resolveVideoDetailSwipeTarget();
  await focusVideoDetailPlayer(player);
  await sleep(randDelay(180, 300));

  if (!isVideoDetailCommentSidebarReadyForCollect()) return;

  const probe = probeVideoDetailCommentSidebar();
  const primary = probe.icon_targets?.[0];
  if (primary && typeof primary.center?.x === "number") {
    const el = document.elementFromPoint(primary.center.x, primary.center.y);
    if (el instanceof HTMLElement) {
      humanClick(el);
      await sleep(randDelay(280, 420));
    }
  }
  await focusVideoDetailPlayer(player);
  await sleep(randDelay(180, 280));
}

async function waitForVideoDetailAwemeChange(before: string | null, maxMs = 3500): Promise<string | null> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    const after = readVideoDetailAwemeId();
    if (after && after !== before) return after;
    await sleep(180);
  }
  return readVideoDetailAwemeId();
}

async function clickVideoDetailNextButton(): Promise<boolean> {
  const btn = findVideoDetailNextButton();
  if (!btn) return false;
  humanClick(btn);
  await sleep(randDelay(320, 520));
  return true;
}

/** 采完评论后、切下一个视频前：确保仍在 /video/ 页且评论区不挡操作 */
export async function prepareVideoDetailForSwipe() {
  if (!isStandaloneVideoPage()) {
    return {
      ok: false,
      is_standalone_video: false,
      aweme_id: readVideoDetailAwemeId(),
      url: location.href,
      message: "不在 /video/ 详情页",
    };
  }

  await dismissCommentPanelForDetailSwipe();
  const stillDetail = isStandaloneVideoPage();
  return {
    ok: stillDetail,
    is_standalone_video: stillDetail,
    aweme_id: readVideoDetailAwemeId(),
    url: location.href,
    message: stillDetail ? "详情页已就绪，可切换下一个视频" : "已离开视频详情页",
  };
}

export function probeVideoDetailPlayback() {
  const onDetail = isStandaloneVideoPage();
  return {
    ok: onDetail,
    is_standalone_video: onDetail,
    is_search_feed: false,
    aweme_id: readVideoDetailAwemeId(),
    url: location.href,
    message: onDetail ? "视频详情页播放中" : "不在 /video/ 详情页",
  };
}

/** /video/ 详情页内切换到下一个视频，不返回搜索列表 */
export async function swipeVideoDetailNext() {
  if (!isStandaloneVideoPage()) {
    return {
      ok: false,
      is_standalone_video: false,
      url: location.href,
      message: "不在 /video/ 详情页，无法详情页内切下一个视频",
    };
  }

  const before = readVideoDetailAwemeId();
  await dismissCommentPanelForDetailSwipe();

  if (!isStandaloneVideoPage()) {
    return {
      ok: false,
      is_standalone_video: false,
      aweme_id: before,
      previous_aweme_id: before,
      url: location.href,
      message: "详情页已关闭",
    };
  }

  const target = resolveVideoDetailSwipeTarget();
  await focusVideoDetailPlayer(target);

  if (await clickVideoDetailNextButton()) {
    const afterArrow = await waitForVideoDetailAwemeChange(before, 3500);
    if (afterArrow && afterArrow !== before) {
      return {
        ok: true,
        is_standalone_video: true,
        aweme_id: afterArrow,
        previous_aweme_id: before,
        attempt: 1,
        method: "next_arrow_click",
        url: location.href,
        message: "已通过下箭头按钮切换到下一个视频",
      };
    }
  }

  dispatchKey(target, "ArrowDown", "ArrowDown");
  dispatchKey(document, "PageDown", "PageDown");
  await wheelDetailNext(target);

  const after = await waitForVideoDetailAwemeChange(before, 3500);
  if (after && after !== before) {
    return {
      ok: true,
      is_standalone_video: true,
      aweme_id: after,
      previous_aweme_id: before,
      attempt: 2,
      method: "wheel_key",
      url: location.href,
      message: "已在详情页内切换到下一个视频",
    };
  }

  const sidebar = probeVideoDetailCommentSidebar();
  return {
    ok: false,
    is_standalone_video: isStandaloneVideoPage(),
    aweme_id: readVideoDetailAwemeId(),
    previous_aweme_id: before,
    comment_sidebar_open: sidebar.sidebar_ready,
    url: location.href,
    message: sidebar.sidebar_ready
      ? "详情页内未能切换：评论区可能仍占据焦点"
      : "详情页内未能切换到下一个视频",
  };
}
