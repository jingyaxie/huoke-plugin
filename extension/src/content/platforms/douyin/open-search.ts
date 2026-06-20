import { buildVideoUrl, detectPageKind, sleep } from "./search";

const SEARCH_CARD_SELECTORS = [
  '[data-e2e="search-card-video"]',
  '[class*="discover-video-card"]',
  'div.search-result-card',
  '[class*="search-result-card"]',
  '[class*="SearchVideoCard"]',
  '[class*="videoImage"] img',
  'a[href*="/video/"]',
];

function extractAwemeId(el: Element): string {
  const link = (
    el.closest('a[href*="/video/"]') as HTMLAnchorElement | null
  ) ?? (el.querySelector('a[href*="/video/"]') as HTMLAnchorElement | null);
  const href = link?.href ?? "";
  const fromHref = href.match(/\/video\/(\d{8,22})/)?.[1] ?? "";
  if (fromHref) return fromHref;
  const holder = el.closest("[data-aweme-id]") ?? el;
  return String(holder.getAttribute("data-aweme-id") ?? "").trim();
}

function clickElement(el: HTMLElement) {
  el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
  if (typeof el.click === "function") {
    el.click();
    return;
  }
  el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
}

export async function openSearchVideo(index = 0): Promise<{
  clicked: boolean;
  index: number;
  aweme_id: string;
  video_url: string;
  selector: string;
  method: string;
  pageKind: ReturnType<typeof detectPageKind>;
  url: string;
}> {
  if (detectPageKind(location.href) !== "search") {
    throw new Error("douyin.search.open_video: current page is not search results");
  }

  const safeIndex = Math.max(0, Math.min(index, 20));

  for (const selector of SEARCH_CARD_SELECTORS) {
    const nodes = Array.from(document.querySelectorAll(selector));
    if (nodes.length <= safeIndex) continue;

    let target = nodes[safeIndex] as HTMLElement;
    if (target.tagName === "IMG") {
      target =
        (target.closest(
          '[class*="discover-video-card"], [data-e2e="search-card-video"], [class*="search-result-card"], [class*="SearchVideoCard"]',
        ) as HTMLElement | null) ??
        (target.parentElement as HTMLElement | null) ??
        target;
    }

    const rect = target.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) continue;

    const awemeId = extractAwemeId(target);
    clickElement(target);
    await sleep(1200);

    let pageKind = detectPageKind(location.href);
    let url = location.href;

    if (pageKind !== "video" && awemeId) {
      location.href = buildVideoUrl(awemeId);
      await sleep(1500);
      pageKind = detectPageKind(location.href);
      url = location.href;
      return {
        clicked: true,
        index: safeIndex,
        aweme_id: awemeId,
        video_url: url,
        selector,
        method: "navigate_after_click",
        pageKind,
        url,
      };
    }

    return {
      clicked: true,
      index: safeIndex,
      aweme_id: awemeId,
      video_url: pageKind === "video" ? url : awemeId ? buildVideoUrl(awemeId) : "",
      selector,
      method: "dom_click",
      pageKind,
      url,
    };
  }

  const links = Array.from(document.querySelectorAll('a[href*="/video/"]')) as HTMLAnchorElement[];
  if (links.length > safeIndex) {
    const link = links[safeIndex];
    const awemeId = extractAwemeId(link);
    clickElement(link);
    await sleep(1500);
    const pageKind = detectPageKind(location.href);
    return {
      clicked: true,
      index: safeIndex,
      aweme_id: awemeId,
      video_url: location.href,
      selector: 'a[href*="/video/"]',
      method: "link_click",
      pageKind,
      url: location.href,
    };
  }

  throw new Error(`douyin.search.open_video: no search result video found at index ${safeIndex}`);
}
