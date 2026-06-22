import { closeVideoDetail } from "./close-video-detail";
import {
  isDouyinFeedOverlay,
  isProfileFeedOverlay,
  isStandaloneVideoPage,
} from "./search-feed-open";
import { humanClick, humanPace, randDelay, sleep } from "./search-input";

export const PROFILE_URL_STORAGE_KEY = "huoke:douyin-profile-url";

export interface ProfileVideoRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface ProfileVideoCard {
  index: number;
  aweme_id: string;
  rect: ProfileVideoRect;
}

const PROFILE_ITEM_SELECTORS = [
  '[data-e2e="user-post-item"]',
  'ul[data-e2e="user-post-item-list"] > li',
  'div[data-e2e="user-post-item-list"] li',
  '[class*="UserPost"] li',
  '[class*="user-post"] li',
] as const;

function isVisible(el: Element): boolean {
  const rect = el.getBoundingClientRect();
  return rect.width >= 40 && rect.height >= 40 && rect.bottom > 0 && rect.top < window.innerHeight + 80;
}

function extractAwemeFromElement(el: Element): string {
  const link =
    el.closest('a[href*="/video/"], a[href*="modal_id="]') ??
    el.querySelector('a[href*="/video/"], a[href*="modal_id="]') ??
    (el.tagName === "A" ? el : null);
  if (link) {
    const href = link.getAttribute("href") ?? "";
    const videoMatch = href.match(/\/video\/(\d{8,22})/);
    if (videoMatch?.[1]) return videoMatch[1];
    const modalMatch = href.match(/modal_id=(\d{8,22})/);
    if (modalMatch?.[1]) return modalMatch[1];
  }
  const href = el.getAttribute("href") ?? "";
  const videoMatch = href.match(/\/video\/(\d{8,22})/);
  if (videoMatch?.[1]) return videoMatch[1];
  const modalMatch = href.match(/modal_id=(\d{8,22})/);
  return modalMatch?.[1] ?? "";
}

export function isProfileListPage(url = location.href): boolean {
  if (!/\/user\//i.test(url)) return false;
  if (/\/video\/\d{8,22}/i.test(url)) return false;
  return true;
}

export function rememberProfileUrl(url = location.href): void {
  if (!isProfileListPage(url)) return;
  try {
    sessionStorage.setItem(PROFILE_URL_STORAGE_KEY, url.split("#")[0] ?? url);
  } catch {
    // ignore
  }
}

export function readStoredProfileUrl(): string {
  try {
    const stored = sessionStorage.getItem(PROFILE_URL_STORAGE_KEY)?.trim();
    if (stored && isProfileListPage(stored)) return stored;
  } catch {
    // ignore
  }
  if (isProfileListPage()) return location.href.split("#")[0] ?? location.href;
  return "";
}

export function profileFeedOpen(): boolean {
  return isProfileFeedOverlay();
}

export function stripModalFromProfileUrl(url: string): string {
  try {
    const parsed = new URL(url);
    parsed.searchParams.delete("modal_id");
    parsed.hash = "";
    return parsed.toString();
  } catch {
    return url.replace(/([?&])modal_id=[^&]+&?/i, "$1").replace(/[?&]$/, "");
  }
}

export function buildProfileModalUrl(awemeId: string, baseUrl?: string): string | null {
  const aweme = awemeId.trim();
  if (!/^\d{8,22}$/.test(aweme)) return null;

  const candidates = [
    baseUrl?.trim(),
    readStoredProfileUrl(),
    isProfileListPage() ? location.href : "",
  ].filter(Boolean) as string[];

  for (const candidate of candidates) {
    if (!isProfileListPage(candidate)) continue;
    try {
      const url = new URL(candidate);
      url.searchParams.set("modal_id", aweme);
      url.hash = "";
      return url.toString();
    } catch {
      continue;
    }
  }
  return null;
}

export async function waitForProfileFeedOverlay(maxMs = 9000): Promise<boolean> {
  const deadline = Date.now() + maxMs;
  const pollMs = maxMs <= 5000 ? 160 : 280;
  while (Date.now() < deadline) {
    if (isProfileFeedOverlay()) return true;
    await sleep(pollMs);
  }
  return isProfileFeedOverlay();
}

export async function openProfileFeedViaModalId(
  awemeId: string,
  baseUrl?: string,
): Promise<{ ok: boolean; mode: "modal_id"; url: string; message: string }> {
  const target = buildProfileModalUrl(awemeId, baseUrl);
  if (!target) {
    return {
      ok: false,
      mode: "modal_id",
      url: location.href,
      message: "无法构造主页 Feed modal_id URL（缺少用户主页地址）",
    };
  }

  const currentBase = location.href.split("#")[0];
  const targetBase = target.split("#")[0];
  if (currentBase !== targetBase) {
    location.assign(target);
  } else if (!isProfileFeedOverlay()) {
    location.replace(target);
    await sleep(400);
    if (!isProfileFeedOverlay()) {
      location.reload();
      await sleep(500);
    }
  }

  const opened = await waitForProfileFeedOverlay(9000);
  return {
    ok: opened,
    mode: "modal_id",
    url: location.href,
    message: opened
      ? `已通过 modal_id 打开主页 Feed 浮层（aweme=${awemeId.slice(0, 12)}…）`
      : isStandaloneVideoPage()
        ? "modal_id 导航后仍落在独立视频详情页"
        : "modal_id 导航后主页 Feed 浮层未就绪",
  };
}

/** Feed 被误关时，用 modal_id 恢复主页 Feed */
export async function recoverProfileFeedFromAweme(awemeId: string) {
  const id = String(awemeId ?? "").trim();
  if (!/^\d{8,22}$/.test(id)) {
    return {
      ok: false,
      is_search_feed: false,
      message: "缺少有效 aweme_id，无法恢复主页 Feed",
      url: location.href,
    };
  }
  const opened = await openProfileFeedViaModalId(id);
  const phase = isDouyinFeedOverlay();
  return {
    ok: opened.ok && phase,
    is_search_feed: phase,
    aweme_id: readFeedAwemeIdFromUrl() ?? id,
    url: location.href,
    message: opened.message,
  };
}

function readFeedAwemeIdFromUrl(url = location.href): string | null {
  try {
    const modal = new URL(url).searchParams.get("modal_id");
    if (modal && /^\d{8,22}$/.test(modal)) return modal;
  } catch {
    // ignore
  }
  return null;
}

export async function waitForProfileVideoCards(limit = 10, maxAttempts = 12): Promise<ProfileVideoCard[]> {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const cards = collectProfileVideoCards(limit);
    if (cards.length > 0) return cards;
    await sleep(attempt === 0 ? 400 : 600);
  }
  return collectProfileVideoCards(limit);
}

export function collectProfileVideoCards(limit = 50): ProfileVideoCard[] {
  const cards: ProfileVideoCard[] = [];
  const seen = new Set<string>();

  const pushCard = (el: Element, aweme: string) => {
    if (!aweme || seen.has(aweme)) return;
    const rect = el.getBoundingClientRect();
    if (rect.width < 40 || rect.height < 40) return;
    seen.add(aweme);
    cards.push({
      index: cards.length + 1,
      aweme_id: aweme,
      rect: {
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      },
    });
  };

  for (const selector of PROFILE_ITEM_SELECTORS) {
    for (const el of Array.from(document.querySelectorAll(selector))) {
      const aweme = extractAwemeFromElement(el);
      if (aweme && isVisible(el)) pushCard(el, aweme);
      if (cards.length >= limit) break;
    }
    if (cards.length >= limit) break;
  }

  if (cards.length < limit) {
    for (const anchor of Array.from(
      document.querySelectorAll('a[href*="/video/"], a[href*="modal_id="]'),
    )) {
      const href = anchor.getAttribute("href") ?? "";
      const videoMatch = href.match(/\/video\/(\d{8,22})/);
      const modalMatch = href.match(/modal_id=(\d{8,22})/);
      const aweme = videoMatch?.[1] ?? modalMatch?.[1] ?? "";
      if (aweme && isVisible(anchor)) pushCard(anchor, aweme);
      if (cards.length >= limit) break;
    }
  }

  cards.sort((a, b) => a.rect.top - b.rect.top || a.rect.left - b.rect.left);
  return cards.slice(0, limit).map((card, idx) => ({ ...card, index: idx + 1 }));
}

export function profileListVisible(): boolean {
  if (!isProfileListPage()) return false;
  if (profileFeedOpen()) return false;
  return collectProfileVideoCards(1).length > 0;
}

async function scrollProfileList(): Promise<void> {
  window.scrollBy({ top: Math.min(window.innerHeight, 720), behavior: "auto" });
  await sleep(randDelay(500, 900));
}

export async function backToProfileList(profileUrl?: string): Promise<{ ok: boolean; message: string; url: string }> {
  if (profileListVisible()) {
    return { ok: true, message: "已在主页作品列表", url: location.href };
  }

  if (profileFeedOpen()) {
    await closeVideoDetail();
    await sleep(randDelay(450, 700));
  }

  if (profileListVisible()) {
    return { ok: true, message: "已回到主页作品列表", url: location.href };
  }

  const target = profileUrl?.trim() || readStoredProfileUrl();
  if (target && !isProfileListPage()) {
    location.assign(target);
    await sleep(randDelay(900, 1300));
  }

  for (let i = 0; i < 10; i += 1) {
    if (profileListVisible()) {
      return { ok: true, message: "已导航回主页作品列表", url: location.href };
    }
    await sleep(200);
  }

  return {
    ok: profileListVisible(),
    message: profileListVisible() ? "已在主页作品列表" : "未能回到主页作品列表",
    url: location.href,
  };
}

/** 打开下一个主页视频前：关闭浮层并确保作品列表可见 */
export async function prepareProfileForVideoClick(options: { fresh_profile?: boolean } = {}) {
  const freshProfile = Boolean(options.fresh_profile);
  rememberProfileUrl();

  if (!freshProfile) {
    const profileUrl = readStoredProfileUrl();
    const back = await backToProfileList(profileUrl);
    if (!back.ok && !isProfileListPage()) {
      return {
        ok: false,
        card_count: 0,
        on_profile_page: false,
        url: location.href,
        message: back.message,
      };
    }
  } else if (profileFeedOpen()) {
    await closeVideoDetail();
    await sleep(randDelay(350, 550));
  }

  if (!isProfileListPage()) {
    return {
      ok: false,
      card_count: 0,
      on_profile_page: false,
      url: location.href,
      message: `不在用户主页（${location.href}）`,
    };
  }

  window.scrollTo({ top: 0, behavior: "auto" });
  await sleep(freshProfile ? randDelay(350, 550) : humanPace.listPrepare());

  let cards = collectProfileVideoCards(50);
  if (cards.length === 0 && !freshProfile) {
    await scrollProfileList();
    cards = collectProfileVideoCards(50);
  } else if (cards.length === 0 && freshProfile) {
    await scrollProfileList();
    cards = collectProfileVideoCards(50);
  }

  return {
    ok: cards.length > 0,
    card_count: cards.length,
    on_profile_page: true,
    url: location.href,
    message:
      cards.length > 0
        ? `主页作品列表就绪（${cards.length} 个视频）`
        : "主页作品列表无可见视频卡片",
  };
}

async function ensureProfileItemIndex(index: number): Promise<boolean> {
  let cards = collectProfileVideoCards(index + 1);
  if (cards.length > index) return true;
  for (let round = 0; round < 4; round += 1) {
    await scrollProfileList();
    cards = collectProfileVideoCards(index + 1);
    if (cards.length > index) return true;
  }
  return cards.length > index;
}

function centerOf(rect: ProfileVideoRect): { x: number; y: number } {
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

export async function clickProfileVideoAtIndex(payload: {
  video_index?: number;
  index?: number;
  aweme_id?: string;
  aweme_hint?: string;
} = {}) {
  const index = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  const awemeHint = String(payload.aweme_id ?? payload.aweme_hint ?? "").trim();
  rememberProfileUrl();

  if (profileFeedOpen()) {
    return {
      ok: false,
      feed_open: true,
      video_index: index,
      url: location.href,
      message: "视频浮层已打开，需先关闭再点击下一个",
    };
  }

  if (!await ensureProfileItemIndex(index - 1)) {
    return {
      ok: false,
      feed_open: false,
      video_index: index,
      url: location.href,
      message: `主页列表第 ${index} 个视频不可用（滚动后仍不足）`,
    };
  }

  const cards = collectProfileVideoCards(Math.max(index, 50));
  let target = awemeHint
    ? cards.find((card) => card.aweme_id === awemeHint) ?? null
    : null;
  if (!target && cards.length >= index) {
    target = cards[index - 1];
  }
  if (!target) {
    return {
      ok: false,
      feed_open: false,
      video_index: index,
      aweme_id: awemeHint,
      url: location.href,
      message: `未找到主页第 ${index} 个视频卡片`,
    };
  }

  const clickEl =
    document.elementFromPoint(
      target.rect.left + target.rect.width / 2,
      target.rect.top + target.rect.height / 2,
    ) ?? document.body;

  const link = clickEl.closest('a[href*="/video/"]') as HTMLElement | null;
  humanClick(link ?? (clickEl as HTMLElement));
  await sleep(humanPace.posterClick());

  for (let i = 0; i < 24; i += 1) {
    await sleep(220 + i * 40);
    if (profileFeedOpen()) {
      return {
        ok: true,
        feed_open: true,
        is_search_feed: true,
        clicked: true,
        mode: "dom_click",
        video_index: target.index,
        aweme_id: target.aweme_id,
        center: centerOf(target.rect),
        url: location.href,
        message: `已点击主页第 ${target.index} 个视频（aweme=${target.aweme_id.slice(0, 12)}）`,
      };
    }
  }

  return {
    ok: false,
    feed_open: profileFeedOpen(),
    video_index: target.index,
    aweme_id: target.aweme_id,
    url: location.href,
    message: "点击后未进入视频播放浮层",
  };
}

export function probeProfileVideoCard(payload: {
  video_index?: number;
  index?: number;
  status_only?: boolean;
  aweme_id?: string;
} = {}) {
  const index = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  const feedOpen = profileFeedOpen();

  if (payload.status_only) {
    return {
      ok: true,
      video_index: index,
      feed_open: feedOpen,
      is_profile_feed: feedOpen,
      is_search_feed: feedOpen,
      url: location.href,
      message: feedOpen ? "主页视频浮层已打开" : "等待主页视频浮层",
    };
  }

  if (feedOpen) {
    return {
      ok: false,
      video_index: index,
      feed_open: true,
      is_profile_feed: true,
      click_by: "needs_close",
      url: location.href,
      message: "视频浮层已打开，需先关闭再点击下一个",
    };
  }

  const cards = collectProfileVideoCards(Math.max(index, 50));
  const awemeHint = String(payload.aweme_id ?? "").trim();
  let target = awemeHint ? cards.find((c) => c.aweme_id === awemeHint) ?? null : null;
  if (!target && cards.length >= index) target = cards[index - 1];

  if (!target) {
    return {
      ok: false,
      video_index: index,
      available: cards.length,
      feed_open: false,
      url: location.href,
      message: cards.length > 0 ? `主页仅有 ${cards.length} 个可见视频` : "主页作品列表无可见视频",
    };
  }

  return {
    ok: true,
    video_index: target.index,
    available: cards.length,
    center: centerOf(target.rect),
    rect: target.rect,
    feed_open: false,
    click_by: "dom_index",
    aweme_id: target.aweme_id,
    url: location.href,
    message: `找到主页第 ${target.index} 个视频（DOM 坐标点击）`,
  };
}
