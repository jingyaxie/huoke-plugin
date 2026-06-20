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

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomInt(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function getScrollTop(target: Element): number {
  if (target === document.documentElement || target === document.body) {
    return window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
  }
  return (target as HTMLElement).scrollTop || 0;
}

function isScrollable(el: Element): boolean {
  const node = el as HTMLElement;
  if (!node || node.scrollHeight <= node.clientHeight + 8) return false;
  const style = window.getComputedStyle(node);
  const overflowY = style.overflowY;
  return overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay";
}

function resolveScrollTarget(selector?: string): Element {
  const trimmed = String(selector ?? "").trim();
  if (trimmed) {
    const matched = document.querySelector(trimmed);
    if (matched) return matched;
    throw new Error(`scroll target not found: ${trimmed}`);
  }

  const candidates: Element[] = [
    document.scrollingElement ?? document.documentElement,
    document.documentElement,
    document.body,
    ...Array.from(
      document.querySelectorAll(
        'main, [role="main"], [class*="feed"], [class*="scroll"], [class*="waterfall"], [class*="search-result"]',
      ),
    ),
  ];

  for (const candidate of candidates) {
    if (!candidate) continue;
    if (candidate === document.documentElement || candidate === document.body) {
      const docHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
      if (docHeight > window.innerHeight + 40) return candidate;
      continue;
    }
    if (isScrollable(candidate)) return candidate;
  }

  return document.scrollingElement ?? document.documentElement;
}

function wheelPoint(target: Element): { x: number; y: number } {
  if (target === document.documentElement || target === document.body) {
    return {
      x: Math.round(window.innerWidth * 0.5),
      y: Math.round(window.innerHeight * 0.65),
    };
  }

  const rect = target.getBoundingClientRect();
  return {
    x: Math.round(rect.left + rect.width * 0.5),
    y: Math.round(rect.top + Math.min(rect.height * 0.65, window.innerHeight * 0.7)),
  };
}

function applyScrollDelta(target: Element, deltaY: number) {
  if (target === document.documentElement || target === document.body) {
    window.scrollBy({ top: deltaY, left: 0, behavior: "auto" });
    return;
  }
  (target as HTMLElement).scrollTop += deltaY;
}

function dispatchWheel(target: Element, deltaY: number, clientX: number, clientY: number) {
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
  window.dispatchEvent(new WheelEvent("wheel", init));
  document.dispatchEvent(new WheelEvent("wheel", init));
}

export async function swipePage(payload: SwipePagePayload = {}): Promise<SwipePageResult> {
  const direction = String(payload.direction ?? "down").toLowerCase() === "up" ? "up" : "down";
  const sign = direction === "up" ? -1 : 1;
  const totalDistance = Math.max(120, Math.min(payload.distance ?? randomInt(600, 1200), 4000));
  const segmentCount = Math.max(2, Math.min(payload.segments ?? randomInt(3, 6), 12));
  const target = resolveScrollTarget(payload.selector);
  const point = wheelPoint(target);

  const beforeScroll = getScrollTop(target);
  let moved = 0;

  for (let i = 0; i < segmentCount; i += 1) {
    const remaining = totalDistance - moved;
    if (remaining <= 0) break;

    const baseStep = Math.round(totalDistance / segmentCount);
    const step = Math.max(40, Math.min(remaining, baseStep + randomInt(-35, 45)));
    const deltaY = sign * step;

    dispatchWheel(target, deltaY, point.x, point.y);
    applyScrollDelta(target, deltaY);

    moved += Math.abs(step);
    await sleep(randomInt(90, 240));
  }

  if (direction === "down" && Math.random() < 0.35) {
    await sleep(randomInt(120, 220));
    const bounce = -randomInt(18, 72);
    dispatchWheel(target, bounce, point.x, point.y);
    applyScrollDelta(target, bounce);
  }

  const afterScroll = getScrollTop(target);
  const scrollDelta = afterScroll - beforeScroll;

  return {
    ok: true,
    direction,
    distance_requested: totalDistance,
    scroll_before: beforeScroll,
    scroll_after: afterScroll,
    scroll_delta: scrollDelta,
    segments: segmentCount,
    target_tag: target.tagName.toLowerCase(),
    target_selector: payload.selector?.trim() || "auto",
    url: location.href,
    message: `已模拟${direction === "down" ? "向下" : "向上"}滚动 ${Math.abs(scrollDelta)}px`,
  };
}
