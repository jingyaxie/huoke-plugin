import {
  collectSearchResultCards,
  isFeedOverlayOpen,
  pickSearchCardClickTarget,
  scrollCardIntoView,
  serializeCardRect,
} from "./search-results-dom";

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

function centerOf(rect: DomRect): DomPoint {
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function isValidRect(rect?: DomRect | null): rect is DomRect {
  return Boolean(rect && rect.width >= 24 && rect.height >= 24);
}

/** 供 background 探测搜索结果视频点击坐标（按序号，不依赖 aweme_id） */
export function probeSearchVideoCard(payload: {
  video_index?: number;
  index?: number;
  rect?: DomRect;
  status_only?: boolean;
} = {}) {
  const index = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  const url = location.href;
  const feedOpen = isFeedOverlayOpen(url);

  if (payload.status_only) {
    return {
      ok: true,
      video_index: index,
      feed_open: feedOpen,
      url,
      message: feedOpen ? "Feed 已打开" : "等待 Feed",
    };
  }

  if (feedOpen) {
    return {
      ok: true,
      video_index: index,
      available: 0,
      feed_open: true,
      click_by: "already_open",
      url,
      message: "视频 Feed 已打开",
    };
  }

  if (isValidRect(payload.rect)) {
    return {
      ok: true,
      video_index: index,
      available: 0,
      center: centerOf(payload.rect),
      rect: payload.rect,
      feed_open: false,
      click_by: "cached_rect",
      url,
      message: `使用步骤 8 缓存的第 ${index} 个卡片坐标`,
    };
  }

  const cards = collectSearchResultCards();
  if (cards.length > 0) {
    const targetIndex = Math.min(index, cards.length);
    const target = cards[targetIndex - 1];
    scrollCardIntoView(target);
    const clickTarget = pickSearchCardClickTarget(target);
    const rect = serializeCardRect(clickTarget);
    return {
      ok: true,
      video_index: targetIndex,
      available: cards.length,
      center: centerOf(rect),
      rect,
      feed_open: false,
      click_by: "dom_index",
      url,
      message: `找到第 ${targetIndex} 个视频卡片（DOM 坐标点击）`,
    };
  }

  return {
    ok: false,
    video_index: index,
    available: 0,
    feed_open: feedOpen,
    url,
    message: "未找到搜索结果视频卡片",
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
