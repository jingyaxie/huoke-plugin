const CARD_SELECTORS = [
  '[data-e2e="search-card-video"]',
  "div.search-result-card",
  '[class*="search-result-card"]',
  '[class*="discover-video-card"]',
] as const;

const LINK_SELECTORS = [
  'a[href*="/video/"]',
  '[data-e2e="search-card-video"] a',
] as const;

function parseAwemeId(href: string): string | null {
  const match = href.match(/\/video\/(\d+)/);
  return match?.[1] ?? null;
}

function nodeText(node: Element): string {
  return (node.textContent ?? "").replace(/\s+/g, " ").trim();
}

function collectCards(): HTMLElement[] {
  const seen = new Set<HTMLElement>();
  const cards: HTMLElement[] = [];

  for (const selector of CARD_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length && cards.length < 40; i += 1) {
      const node = nodes[i] as HTMLElement;
      const rect = node.getBoundingClientRect();
      if (rect.width < 80 || rect.height < 80) continue;
      if (seen.has(node)) continue;
      seen.add(node);
      cards.push(node);
    }
  }

  if (cards.length > 0) return cards;

  for (const selector of LINK_SELECTORS) {
    const links = document.querySelectorAll(selector);
    for (let i = 0; i < links.length && cards.length < 40; i += 1) {
      const link = links[i] as HTMLElement;
      const rect = link.getBoundingClientRect();
      if (rect.width < 40 || rect.height < 40) continue;
      if (seen.has(link)) continue;
      seen.add(link);
      cards.push(link);
    }
  }

  return cards;
}

export interface FetchSearchResultsPayload {
  limit?: number;
}

/** 步骤 8：从 DOM 抓取当前可见搜索结果 */
export async function fetchSearchResults(payload: FetchSearchResultsPayload = {}) {
  const limit = Math.max(1, Math.min(Number(payload.limit ?? 20), 50));
  const cards = collectCards();
  const items: Array<{
    index: number;
    title: string;
    author: string;
    url: string;
    aweme_id: string | null;
  }> = [];

  for (let i = 0; i < cards.length && items.length < limit; i += 1) {
    const card = cards[i];
    const link =
      (card.matches('a[href*="/video/"]') ? card : card.querySelector('a[href*="/video/"]')) as
        | HTMLAnchorElement
        | null;
    const href = link?.href ?? "";
    const awemeId = parseAwemeId(href);
    const titleNode =
      card.querySelector('[class*="title"], [class*="desc"], span, p') ?? card;
    const authorNode = card.querySelector('[class*="author"], [class*="name"], a[href*="/user/"]');

    items.push({
      index: items.length + 1,
      title: nodeText(titleNode).slice(0, 120) || `视频 ${items.length + 1}`,
      author: authorNode ? nodeText(authorNode).slice(0, 40) : "—",
      url: href,
      aweme_id: awemeId,
    });
  }

  return {
    ok: items.length > 0,
    count: items.length,
    items,
    results: items,
    url: location.href,
    message:
      items.length > 0
        ? `已抓取 ${items.length} 条搜索结果`
        : "未找到搜索结果卡片，请先完成搜索",
  };
}
