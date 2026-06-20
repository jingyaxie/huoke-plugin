export interface SwipePagePayload {
  direction?: "down" | "up" | string;
  distance?: number;
  segments?: number;
  selector?: string;
}

export interface SwipePageResult {
  ok: boolean;
  direction: "down" | "up";
  distance_requested: number;
  scroll_before: number;
  scroll_after: number;
  scroll_delta: number;
  segments: number;
  target_tag: string;
  target_selector: string;
  url: string;
  message: string;
}

const SEARCH_ANCHOR_SELECTORS = [
  '[data-e2e="search-card-video"]',
  "div.search-result-card",
  '[class*="SearchVideoCard"]',
  '[class*="search-result-card"]',
  '[class*="search-result"]',
] as const;

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomInt(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function blurActiveInput() {
  const active = document.activeElement as HTMLElement | null;
  if (
    active &&
    (active.tagName === "INPUT" ||
      active.tagName === "TEXTAREA" ||
      active.getAttribute("contenteditable") === "true")
  ) {
    active.blur();
  }
  try {
    document.body?.focus({ preventScroll: true });
  } catch {
    // ignore
  }
}

function tryDismissOverlay() {
  if (!location.href.includes("modal_id=")) return;
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
  );
}

function pickScrollParent(anchor: Element): HTMLElement | null {
  let node: HTMLElement | null = anchor as HTMLElement;
  for (let i = 0; i < 14 && node; i += 1) {
    const sh = node.scrollHeight || 0;
    const ch = node.clientHeight || 0;
    if (sh > ch + 40) return node;
    node = node.parentElement;
  }
  return null;
}

function isScrollable(el: HTMLElement): boolean {
  if (el.scrollHeight <= el.clientHeight + 8) return false;
  const style = window.getComputedStyle(el);
  const overflowY = style.overflowY;
  return overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay";
}

/** 对齐 Python search_ui._SEARCH_RESULTS_SCROLL_JS */
function resolveScrollTarget(selector?: string): { el: HTMLElement; selector: string } {
  blurActiveInput();
  tryDismissOverlay();

  const trimmed = String(selector ?? "").trim();
  if (trimmed) {
    const matched = document.querySelector(trimmed);
    if (!matched) throw new Error(`scroll target not found: ${trimmed}`);
    const parent = pickScrollParent(matched) ?? (matched as HTMLElement);
    return { el: parent, selector: trimmed };
  }

  for (const sel of SEARCH_ANCHOR_SELECTORS) {
    const anchor = document.querySelector(sel);
    if (!anchor) continue;
    const parent = pickScrollParent(anchor);
    if (parent) return { el: parent, selector: sel };
  }

  const main = document.querySelector('main, [role="main"]') as HTMLElement | null;
  if (main && isScrollable(main)) {
    return { el: main, selector: "main" };
  }

  const doc = (document.scrollingElement ?? document.documentElement) as HTMLElement;
  return { el: doc, selector: "document" };
}

function getScrollTop(target: HTMLElement): number {
  if (target === document.documentElement || target === document.body) {
    return window.scrollY || document.documentElement.scrollTop || 0;
  }
  return target.scrollTop || 0;
}

function wheelPoint(target: HTMLElement): { x: number; y: number } {
  if (target === document.documentElement || target === document.body) {
    return {
      x: Math.round(window.innerWidth * 0.5),
      y: Math.round(window.innerHeight * 0.65),
    };
  }

  const rect = target.getBoundingClientRect();
  if (rect.width < 8 || rect.height < 8) {
    return { x: Math.round(window.innerWidth * 0.5), y: Math.round(window.innerHeight * 0.65) };
  }

  return {
    x: Math.round(rect.left + Math.min(48, rect.width * 0.12)),
    y: Math.round(rect.top + rect.height * 0.55),
  };
}

/** 直接改 scrollTop（抖音内层列表有效） */
function scrollByPixels(target: HTMLElement, deltaY: number): boolean {
  const before = getScrollTop(target);
  if (target === document.documentElement || target === document.body) {
    window.scrollBy({ top: deltaY, left: 0, behavior: "auto" });
  } else {
    const maxTop = Math.max(0, target.scrollHeight - target.clientHeight);
    const step = Math.max(24, Math.min(120, Math.abs(deltaY)));
    const signed = deltaY >= 0 ? step : -step;
    target.scrollTop = Math.max(0, Math.min(before + signed, maxTop));
  }
  const after = getScrollTop(target);
  return after !== before;
}

function dispatchWheel(target: HTMLElement, deltaY: number, clientX: number, clientY: number) {
  const init: WheelEventInit = {
    deltaX: 0,
    deltaY,
    deltaZ: 0,
    deltaMode: WheelEvent.DOM_DELTA_PIXEL,
    bubbles: true,
    cancelable: true,
    clientX,
    clientY,
    view: window,
  };
  target.dispatchEvent(new WheelEvent("wheel", init));
}

export async function swipePage(payload: SwipePagePayload = {}): Promise<SwipePageResult> {
  const direction = String(payload.direction ?? "down").toLowerCase() === "up" ? "up" : "down";
  const sign = direction === "up" ? -1 : 1;
  const totalDistance = Math.max(180, Math.min(payload.distance ?? randomInt(260, 420), 4000));
  const segmentCount = Math.max(5, Math.min(payload.segments ?? randomInt(5, 9), 12));

  const { el: target, selector: targetSelector } = resolveScrollTarget(payload.selector);
  const point = wheelPoint(target);
  const beforeScroll = getScrollTop(target);

  let moved = 0;
  let scrolledAny = false;

  for (let i = 0; i < segmentCount; i += 1) {
    const remaining = totalDistance - moved;
    if (remaining <= 0) break;

    const perStep = Math.max(28, Math.round(totalDistance / segmentCount));
    const step = Math.max(24, Math.min(remaining, perStep + randomInt(-10, 10)));
    const deltaY = sign * step;

    dispatchWheel(target, deltaY, point.x, point.y);
    if (scrollByPixels(target, deltaY)) scrolledAny = true;

    moved += Math.abs(step);
    await sleep(randomInt(140, 380));
  }

  if (direction === "down" && Math.random() < 0.25) {
    await sleep(randomInt(120, 220));
    const bounce = -randomInt(18, 48);
    dispatchWheel(target, bounce, point.x, point.y);
    scrollByPixels(target, bounce);
  }

  const afterScroll = getScrollTop(target);
  const scrollDelta = afterScroll - beforeScroll;
  const ok = Math.abs(scrollDelta) >= 8 || scrolledAny;

  return {
    ok,
    direction,
    distance_requested: totalDistance,
    scroll_before: beforeScroll,
    scroll_after: afterScroll,
    scroll_delta: scrollDelta,
    segments: segmentCount,
    target_tag: target.tagName.toLowerCase(),
    target_selector: payload.selector?.trim() || targetSelector,
    url: location.href,
    message: ok
      ? `已${direction === "down" ? "向下" : "向上"}滚动 ${Math.abs(scrollDelta)}px（容器: ${targetSelector}）`
      : `未能滚动页面，请确认在搜索结果/Feed 列表页，或 Feed 浮层已关闭（modal_id）`,
  };
}
