import { sleep } from "./search-input";

const CARD_SELECTORS = [
  '[data-e2e="search-card-video"]',
  '[data-e2e="search-video-item"]',
  '[data-e2e="search-result-video"]',
  "div.search-result-card",
  '[class*="search-result-card"]',
  '[class*="SearchVideoCard"]',
  '[class*="discover-video-card"]',
  '[class*="video-card"]',
] as const;

const POSTER_SELECTORS = [
  '[class*="discover-video-card"]',
  "img.discover-video-card-img",
  '[data-e2e="search-card-video"]',
  "div.search-result-card",
  '[class*="search-result-card"]',
  '[class*="SearchVideoCard"]',
  '[class*="videoImage"] img',
] as const;

const LINK_SELECTORS = [
  'a[href*="/video/"]',
  'a[href*="/note/"]',
  'a[href*="modal_id="]',
  'a[href*="aweme_id="]',
  '[data-e2e="search-card-video"] a',
] as const;

const AWEME_ID_ATTRS = [
  "data-aweme-id",
  "data-item-id",
  "data-video-id",
  "data-id",
] as const;

export function isSearchResultsPage(url = location.href): boolean {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.toLowerCase();
    if (/\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(path)) return true;
    if (path.includes("/search")) return true;
    for (const key of ["keyword", "q", "search_key", "searchKey", "search_keyword", "type"]) {
      const value = parsed.searchParams.get(key)?.trim() ?? "";
      if (value && key !== "type") return true;
      if (key === "type" && /general|video|note/i.test(value)) return true;
    }
    return false;
  } catch {
    return /\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(url);
  }
}

export function parseAwemeId(href: string): string | null {
  const trimmed = href.trim();
  if (!trimmed) return null;

  const videoMatch = trimmed.match(/\/(?:video|note)\/(\d{8,22})/);
  if (videoMatch?.[1]) return videoMatch[1];

  try {
    const url = new URL(trimmed, location.href);
    for (const key of ["modal_id", "aweme_id", "item_id"]) {
      const value = url.searchParams.get(key);
      if (value && /^\d{8,22}$/.test(value)) return value;
    }
  } catch {
    // ignore invalid href
  }

  const inlineMatch = trimmed.match(/(?:modal_id|aweme_id|item_id)=(\d{8,22})/i);
  if (inlineMatch?.[1]) return inlineMatch[1];

  return null;
}

function parseAwemeIdFromElement(node: Element): string | null {
  if (node instanceof HTMLAnchorElement || node.matches("a[href]")) {
    const href = (node as HTMLAnchorElement).href ?? node.getAttribute("href") ?? "";
    const fromHref = parseAwemeId(href);
    if (fromHref) return fromHref;
  }

  for (const attr of AWEME_ID_ATTRS) {
    const value = node.getAttribute(attr)?.trim() ?? "";
    if (/^\d{8,22}$/.test(value)) return value;
  }

  const snippet = node.outerHTML.slice(0, 4000);
  const patterns = [
    /\/(?:video|note)\/(\d{8,22})/,
    /(?:aweme[_-]?id|modal[_-]?id|item[_-]?id)["':=\s]+(\d{8,22})/i,
    /"awemeId"\s*:\s*"(\d{8,22})"/,
    /"aweme_id"\s*:\s*"(\d{8,22})"/,
  ];
  for (const pattern of patterns) {
    const match = snippet.match(pattern);
    if (match?.[1]) return match[1];
  }

  return null;
}

function isInViewport(rect: DOMRect, minW = 24, minH = 24): boolean {
  return (
    rect.width >= minW &&
    rect.height >= minH &&
    rect.bottom > 8 &&
    rect.top < window.innerHeight - 8 &&
    rect.right > 8 &&
    rect.left < window.innerWidth - 8
  );
}

function positionKey(rect: DOMRect): string {
  return `${Math.round(rect.top)}:${Math.round(rect.left)}:${Math.round(rect.width)}`;
}

function pickPosterNode(el: Element): HTMLElement | null {
  const chain = [
    el.closest('[class*="discover-video-card"]'),
    el.closest('[data-e2e="search-card-video"]'),
    el.closest('[class*="search-result-card"]'),
    el.closest("div.search-result-card"),
    el.closest('[class*="SearchVideoCard"]'),
    el.closest('a[href*="/video/"]'),
    el.closest('a[href*="modal_id="]'),
    el.tagName === "IMG" ? el.parentElement : null,
    el,
  ];

  for (const node of chain) {
    if (!(node instanceof HTMLElement)) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width >= 24 && rect.height >= 24) return node;
  }
  return null;
}

function cardRoot(node: Element): HTMLElement {
  let current: Element | null = node;
  for (let depth = 0; depth < 6 && current; depth += 1) {
    if (current instanceof HTMLElement) {
      const rect = current.getBoundingClientRect();
      if (rect.width >= 80 && rect.height >= 80) return current;
    }
    current = current.parentElement;
  }
  return node as HTMLElement;
}

function tryAddCard(
  seen: Set<string>,
  cards: HTMLElement[],
  node: HTMLElement,
  minW: number,
  minH: number,
  requireAweme: boolean,
) {
  const target = cardRoot(node);
  const rect = target.getBoundingClientRect();
  if (rect.width < minW || rect.height < minH) return;
  if (!isInViewport(rect, minW, minH)) return;
  if (requireAweme && !parseAwemeIdFromElement(target) && !extractAwemeFromCard(target)) return;

  const key = positionKey(rect);
  if (seen.has(key)) return;
  seen.add(key);
  cards.push(target);
}

function collectPosterCards(seen: Set<string>, cards: HTMLElement[]): void {
  for (const selector of POSTER_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length && cards.length < 60; i += 1) {
      const picked = pickPosterNode(nodes[i]);
      if (!picked) continue;
      tryAddCard(seen, cards, picked, 24, 24, false);
    }
  }
}

export function extractAwemeFromCard(card: HTMLElement): string | null {
  const direct = parseAwemeIdFromElement(card);
  if (direct) return direct;

  const link = findVideoLink(card);
  if (link) {
    const fromLink = parseAwemeIdFromElement(link);
    if (fromLink) return fromLink;
  }

  const nodes = card.querySelectorAll("a[href], [data-aweme-id], [data-item-id], [data-video-id]");
  for (let i = 0; i < nodes.length; i += 1) {
    const id = parseAwemeIdFromElement(nodes[i]);
    if (id) return id;
  }

  let current: Element | null = card;
  for (let depth = 0; depth < 8 && current; depth += 1) {
    for (const attr of AWEME_ID_ATTRS) {
      const value = current.getAttribute(attr)?.trim() ?? "";
      if (/^\d{8,22}$/.test(value)) return value;
    }
    current = current.parentElement;
  }

  return parseAwemeIdFromElement(card);
}

export function collectSearchResultCards(): HTMLElement[] {
  const seen = new Set<string>();
  const cards: HTMLElement[] = [];

  if (isSearchResultsPage()) {
    collectPosterCards(seen, cards);
  }

  for (const selector of LINK_SELECTORS) {
    const links = document.querySelectorAll(selector);
    for (let i = 0; i < links.length && cards.length < 60; i += 1) {
      const link = links[i] as HTMLElement;
      if (!parseAwemeIdFromElement(link)) continue;
      tryAddCard(seen, cards, link, 40, 40, false);
    }
  }

  for (const selector of CARD_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length && cards.length < 60; i += 1) {
      const node = nodes[i] as HTMLElement;
      const link =
        node.matches('a[href*="/video/"], a[href*="/note/"], a[href*="modal_id="], a[href*="aweme_id="]')
          ? node
          : (node.querySelector(
              'a[href*="/video/"], a[href*="/note/"], a[href*="modal_id="], a[href*="aweme_id="]',
            ) as HTMLElement | null);
      const idSource = link ?? node;
      if (!parseAwemeIdFromElement(idSource) && !extractAwemeFromCard(node)) continue;
      tryAddCard(seen, cards, node, 60, 60, false);
    }
  }

  if (isSearchResultsPage() && cards.length === 0) {
    collectPosterCards(seen, cards);
  }

  cards.sort((a, b) => {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    return ra.top - rb.top || ra.left - rb.left;
  });
  return cards;
}

export function findVideoLink(card: HTMLElement): HTMLAnchorElement | null {
  if (card.matches('a[href*="/video/"], a[href*="/note/"], a[href*="modal_id="], a[href*="aweme_id="]')) {
    return card as HTMLAnchorElement;
  }
  return card.querySelector(
    'a[href*="/video/"], a[href*="/note/"], a[href*="modal_id="], a[href*="aweme_id="]',
  ) as HTMLAnchorElement | null;
}

export function resolveCardAwemeId(card: HTMLElement): string | null {
  return extractAwemeFromCard(card);
}

export function buildCardUrl(awemeId: string, link?: HTMLAnchorElement | null): string {
  const href = link?.href ?? link?.getAttribute("href") ?? "";
  if (href && parseAwemeId(href)) return href;
  return `https://www.douyin.com/video/${awemeId}`;
}

function nodeText(node: Element): string {
  return (node.textContent ?? "").replace(/\s+/g, " ").trim();
}

function isLikelyStatText(text: string): boolean {
  if (!text) return true;
  if (/^\d+(\.\d+)?万?$/.test(text)) return true;
  if (/^[\d,.]+$/.test(text)) return true;
  if (text.length <= 6 && /万|赞|播|评论|粉丝|收藏/.test(text)) return true;
  return false;
}

/** 从卡片 DOM 提取可读标题（跳过点赞数等统计文案） */
export function pickCardTitle(card: HTMLElement): string {
  const selectors = [
    '[class*="title"]',
    '[class*="desc"]',
    '[class*="Title"]',
    '[class*="Desc"]',
    'a[href*="/video/"]',
    'a[href*="/note/"]',
  ];
  for (const selector of selectors) {
    const nodes = card.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const text = nodeText(nodes[i]);
      if (text.length >= 2 && !isLikelyStatText(text)) return text.slice(0, 120);
    }
  }
  const spans = card.querySelectorAll("span, p");
  let best = "";
  for (let i = 0; i < spans.length; i += 1) {
    const text = nodeText(spans[i]);
    if (text.length < 2 || isLikelyStatText(text)) continue;
    if (text.length > best.length) best = text;
  }
  return best.slice(0, 120);
}

export function pickCardAuthor(card: HTMLElement): string {
  const authorNode = card.querySelector('[class*="author"], [class*="name"], a[href*="/user/"]');
  const text = authorNode ? nodeText(authorNode).slice(0, 40) : "";
  return text && !isLikelyStatText(text) ? text : "—";
}

/** 点击目标：优先封面图/卡片本体，避免点到 a[href=/video/] 误入独立详情页 */
export function pickSearchCardClickTarget(card: HTMLElement): HTMLElement {
  const img = card.querySelector(
    'img[class*="cover"], img[class*="video"], img[class*="poster"], img[class*="card"], img.discover-video-card-img, img',
  ) as HTMLElement | null;
  if (img && img.getBoundingClientRect().width >= 40) return img;

  const poster = card.querySelector(
    '[class*="discover-video-card"], [class*="videoImage"], [class*="cover"]',
  ) as HTMLElement | null;
  if (poster && poster.getBoundingClientRect().width >= 40) return poster;

  return card;
}

export function scrollCardIntoView(card: HTMLElement): void {
  card.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
}

export function serializeCardRect(card: HTMLElement): {
  top: number;
  left: number;
  width: number;
  height: number;
} {
  const rect = card.getBoundingClientRect();
  return {
    top: Math.round(rect.top),
    left: Math.round(rect.left),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
}

export function isFeedOverlayOpen(url = location.href): boolean {
  // 兼容旧调用：搜索 Feed 浮层才算「可采评论的 Feed」
  if (/modal_id=\d{8,22}/i.test(url) && !/\/video\/\d/i.test(url)) {
    return feedOverlayVisibleStrict();
  }
  return feedOverlayVisibleStrict();
}

function feedOverlayVisibleStrict(): boolean {
  const selectors = [
    '[data-e2e="feed-active-video"]',
    '[data-e2e="feed-comment-icon"]',
    '[data-e2e="comment-icon"]',
    '[data-e2e="detail-tab-comment"]',
    '[data-e2e="browse-comment-icon"]',
  ];
  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (!el) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width >= 10 && rect.height >= 10) return true;
  }
  return false;
}

export async function waitForSearchResultCards(
  maxAttempts = 10,
  fast = false,
): Promise<HTMLElement[]> {
  window.scrollTo({ top: 0, behavior: "auto" });
  await sleep(fast ? 120 : 300);

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const cards = collectSearchResultCards();
    if (cards.length > 0) return cards;
    if (attempt < maxAttempts - 1) {
      window.scrollBy({ top: 400 + attempt * 250, behavior: "auto" });
      await sleep(fast ? 220 + attempt * 60 : 450 + attempt * 120);
    }
  }
  return [];
}
