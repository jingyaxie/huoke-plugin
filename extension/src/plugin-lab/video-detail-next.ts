import {
  isVideoDetailCommentSidebarReadyForCollect,
  probeVideoDetailCommentSidebar,
} from "./video-detail-comment-sidebar-dom";
import { isStandaloneVideoPage } from "./search-feed-open";
import { humanClick, isVisible, randDelay, sleep } from "./search-input";

/** 临时关闭右侧翻页按钮，仅用手势/键盘测试滑动稳定性 */
const USE_DETAIL_PAGER_BUTTON = false;

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
  const downOnly = findVideoDetailDownArrowButton();
  if (downOnly) return downOnly;
  return findVideoDetailVerticalPagerNextTarget();
}

/** 是否存在详情页「下一个视频」翻页控件 */
export function hasVideoDetailNextButton(): boolean {
  return Boolean(findVideoDetailNextButton());
}

function findVideoDetailDownArrowButton(): HTMLElement | null {
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

/** 详情页右侧上下翻页条 — 点击下半区切下一个 */
function findVideoDetailVerticalPagerNextTarget(): HTMLElement | null {
  const minRight = window.innerWidth * 0.68;
  const hosts = document.querySelectorAll("div, button, span");
  for (let i = 0; i < hosts.length; i += 1) {
    const host = hosts[i];
    if (!(host instanceof HTMLElement) || !isVisible(host)) continue;
    const rect = host.getBoundingClientRect();
    if (rect.left < minRight || rect.width < 18 || rect.width > 64) continue;
    if (rect.height < 36 || rect.height > 120) continue;

    const svgs = host.querySelectorAll("svg");
    if (svgs.length < 1 || svgs.length > 4) continue;

    let downSvg: SVGElement | null = null;
    for (let j = 0; j < svgs.length; j += 1) {
      const svg = svgs[j];
      if (svg instanceof SVGElement && isDetailNextArrowSvg(svg)) {
        downSvg = svg;
        break;
      }
    }
    if (!downSvg) continue;

    const downClickable = resolveClickableAncestor(downSvg);
    if (downClickable) return downClickable;

    if (svgs.length >= 2) {
      return host;
    }
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
    dispatchWheelAt(target, perStep);
    await sleep(randDelay(55, 110));
  }
}

async function pointerDragDetailNext(target: HTMLElement) {
  const start = resolveVideoFocusPoint(target);
  const endY = start.y - randDelay(220, 340);
  const el = target === document.body ? document.documentElement : target;
  const pointerInit: PointerEventInit = {
    bubbles: true,
    cancelable: true,
    clientX: start.x,
    clientY: start.y,
    pointerId: 1,
    pointerType: "touch",
    isPrimary: true,
  };
  el.dispatchEvent(new PointerEvent("pointerdown", pointerInit));
  const steps = randDelay(8, 12);
  for (let i = 1; i <= steps; i += 1) {
    const t = i / steps;
    const y = Math.round(start.y + (endY - start.y) * t);
    el.dispatchEvent(
      new PointerEvent("pointermove", {
        ...pointerInit,
        clientX: start.x,
        clientY: y,
      }),
    );
    await sleep(randDelay(16, 36));
  }
  el.dispatchEvent(
    new PointerEvent("pointerup", {
      ...pointerInit,
      clientX: start.x,
      clientY: endY,
    }),
  );
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

/** 详情页下箭头：多次尝试，间隔放宽，避免连点误触 */
const DETAIL_NEXT_ARROW_MAX_ATTEMPTS = 3;
const DETAIL_NEXT_ARROW_WAIT_PER_ATTEMPT_MS = 2800;
const DETAIL_NEXT_ARROW_RETRY_GAP_MIN_MS = 900;
const DETAIL_NEXT_ARROW_RETRY_GAP_MAX_MS = 1500;

async function tryVideoDetailNextViaArrowButton(
  before: string | null,
  target: HTMLElement,
): Promise<{ ok: boolean; after: string | null; attempt: number }> {
  for (let attempt = 1; attempt <= DETAIL_NEXT_ARROW_MAX_ATTEMPTS; attempt += 1) {
    if (!isStandaloneVideoPage()) break;

    const current = readVideoDetailAwemeId();
    if (current && current !== before) {
      return { ok: true, after: current, attempt };
    }

    if (attempt > 1) {
      await dismissCommentPanelForDetailSwipe();
      if (!isStandaloneVideoPage()) break;
      await focusVideoDetailPlayer(target);
      await sleep(randDelay(DETAIL_NEXT_ARROW_RETRY_GAP_MIN_MS, DETAIL_NEXT_ARROW_RETRY_GAP_MAX_MS));
    }

    const btn = findVideoDetailNextButton();
    if (!btn) {
      return { ok: false, after: readVideoDetailAwemeId(), attempt: 0 };
    }

    humanClick(btn);
    await sleep(randDelay(400, 620));

    const after = await waitForVideoDetailAwemeChange(before, DETAIL_NEXT_ARROW_WAIT_PER_ATTEMPT_MS);
    if (after && after !== before) {
      return { ok: true, after, attempt };
    }

    if (attempt < DETAIL_NEXT_ARROW_MAX_ATTEMPTS) {
      await sleep(randDelay(DETAIL_NEXT_ARROW_RETRY_GAP_MIN_MS, DETAIL_NEXT_ARROW_RETRY_GAP_MAX_MS));
    }
  }

  return { ok: false, after: readVideoDetailAwemeId(), attempt: DETAIL_NEXT_ARROW_MAX_ATTEMPTS };
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

  const hasNextButton = USE_DETAIL_PAGER_BUTTON && hasVideoDetailNextButton();
  if (hasNextButton) {
    const arrow = await tryVideoDetailNextViaArrowButton(before, target);
    if (arrow.ok && arrow.after && arrow.after !== before) {
      return {
        ok: true,
        is_standalone_video: true,
        aweme_id: arrow.after,
        previous_aweme_id: before,
        attempt: arrow.attempt,
        method: "next_arrow_click",
        has_next_button: true,
        url: location.href,
        message:
          arrow.attempt > 1
            ? `已通过下箭头按钮切换到下一个视频（第 ${arrow.attempt} 次点击）`
            : "已通过下箭头按钮切换到下一个视频",
      };
    }
  }

  const methods: Array<{ run: () => Promise<void>; name: string }> = [
    { run: async () => pointerDragDetailNext(target), name: "pointer_up" },
    { run: async () => dispatchKey(target, "ArrowDown", "ArrowDown"), name: "arrow_down" },
    { run: async () => wheelDetailNext(target), name: "wheel_down" },
  ];

  for (let attempt = 1; attempt <= methods.length; attempt += 1) {
    await methods[attempt - 1].run();
    await sleep(randDelay(280, 420));
    const after = await waitForVideoDetailAwemeChange(before, 3500);
    if (after && after !== before) {
      return {
        ok: true,
        is_standalone_video: true,
        aweme_id: after,
        previous_aweme_id: before,
        attempt,
        method: methods[attempt - 1].name,
        has_next_button: false,
        pager_button_disabled: true,
        url: location.href,
        message: `已通过滑动切换到下一个视频（${methods[attempt - 1].name}）`,
      };
    }
  }

  const sidebar = probeVideoDetailCommentSidebar();
  return {
    ok: false,
    is_standalone_video: isStandaloneVideoPage(),
    aweme_id: readVideoDetailAwemeId(),
    previous_aweme_id: before,
    has_next_button: hasVideoDetailNextButton(),
    pager_button_disabled: !USE_DETAIL_PAGER_BUTTON,
    comment_sidebar_open: sidebar.sidebar_ready,
    url: location.href,
    message: sidebar.sidebar_ready
      ? "详情页内未能切换：评论区可能仍占据焦点"
      : "详情页内未能切换到下一个视频",
  };
}
