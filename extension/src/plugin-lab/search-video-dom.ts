const CARD_SELECTORS = [
  '[data-e2e="search-card-video"]',
  "div.search-result-card",
  '[class*="search-result-card"]',
  'a[href*="/video/"]',
] as const;

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

function centerOf(rect: DOMRect): DomPoint {
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function serializeRect(rect: DOMRect): DomRect {
  return {
    top: Math.round(rect.top),
    left: Math.round(rect.left),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
}

function collectClickableCards(): HTMLElement[] {
  const seen = new Set<HTMLElement>();
  const out: HTMLElement[] = [];

  for (const selector of CARD_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length && out.length < 50; i += 1) {
      const node = nodes[i] as HTMLElement;
      const rect = node.getBoundingClientRect();
      if (rect.width < 60 || rect.height < 60 || rect.top < 60) continue;
      if (seen.has(node)) continue;
      seen.add(node);
      out.push(node);
    }
  }

  out.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  return out;
}

function isFeedOpen(): boolean {
  const selectors = [
    '[data-e2e="feed-active-video"]',
    '[data-e2e="feed-comment-icon"]',
    '[data-e2e="comment-icon"]',
    '[data-e2e="detail-tab-comment"]',
  ];
  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (!el) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width >= 10 && rect.height >= 10) return true;
  }
  return false;
}

/** 供 background 探测搜索结果视频点击坐标 */
export function probeSearchVideoCard(payload: { video_index?: number; index?: number } = {}) {
  const index = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  const cards = collectClickableCards();

  if (cards.length === 0) {
    return {
      ok: false,
      video_index: index,
      available: 0,
      feed_open: isFeedOpen(),
      url: location.href,
      message: "未找到搜索结果视频卡片",
    };
  }

  const targetIndex = Math.min(index, cards.length);
  const target = cards[targetIndex - 1];
  const clickTarget =
    (target.matches('a[href*="/video/"]')
      ? target
      : (target.querySelector('a[href*="/video/"]') as HTMLElement | null)) ?? target;
  const rect = clickTarget.getBoundingClientRect();

  return {
    ok: true,
    video_index: targetIndex,
    available: cards.length,
    center: centerOf(rect),
    rect: serializeRect(rect),
    feed_open: isFeedOpen(),
    url: location.href,
    message: `找到第 ${targetIndex} 个视频卡片`,
  };
}

export async function clickSearchVideoFallback(payload: { video_index?: number; index?: number } = {}) {
  const { ok: _ignored, ...probe } = probeSearchVideoCard(payload);
  return {
    ...probe,
    ok: false,
    mode: "content_fallback",
    message: "请重新加载扩展以启用 CDP 视频点击",
  };
}
