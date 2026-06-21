import { humanClick, humanPace, isVisible, randDelay, sleep } from "../../search-input";
import { PHOTO_ID_RE, VIDEO_DETAIL_MARKERS, VIDEO_LINK_SELECTORS } from "./constants";
import type { PlatformSearchItem } from "../shared/content-item";

export function isKsSearchResultsPage(url = location.href): boolean {
  return /\/search\//i.test(url) || /searchKey=/i.test(url) || /searchResult/i.test(url);
}

export function isKsVideoPage(url = location.href): boolean {
  return /\/short-video\//i.test(url) || /\/fw\/photo\//i.test(url);
}

export function extractPhotoIdFromHref(href: string): string {
  const match = href.match(/\/short-video\/([0-9a-zA-Z]{8,32})/i)
    || href.match(/\/fw\/photo\/([0-9a-zA-Z]{8,32})/i);
  return match?.[1] ?? "";
}

export function collectKsVideoCards(): HTMLElement[] {
  const out: HTMLElement[] = [];
  const seen = new Set<string>();

  const pushPhotoId = (photoId: string, el: HTMLElement) => {
    if (!PHOTO_ID_RE.test(photoId) || !isVisible(el) || seen.has(photoId)) return;
    seen.add(photoId);
    out.push(el);
  };

  for (const selector of VIDEO_LINK_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i] as HTMLElement;
      const href = el.getAttribute("href") ?? "";
      pushPhotoId(extractPhotoIdFromHref(href), el);
    }
  }

  const attrNodes = document.querySelectorAll("[data-photo-id], [data-photoid], [data-id]");
  for (let i = 0; i < attrNodes.length; i += 1) {
    const el = attrNodes[i] as HTMLElement;
    const photoId = String(
      el.getAttribute("data-photo-id")
      ?? el.getAttribute("data-photoid")
      ?? el.getAttribute("data-id")
      ?? "",
    ).trim();
    pushPhotoId(photoId, el);
  }

  const links = document.querySelectorAll('a[href*="/short-video/"], a[href*="/fw/photo/"], a[href*="/video/"]');
  for (let i = 0; i < links.length; i += 1) {
    const el = links[i] as HTMLElement;
    pushPhotoId(extractPhotoIdFromHref(el.getAttribute("href") ?? ""), el);
  }

  out.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  return out;
}

export function videoDetailReady(): boolean {
  for (const selector of VIDEO_DETAIL_MARKERS) {
    const el = document.querySelector(selector);
    if (el && isVisible(el)) return true;
  }
  return document.body.innerText.includes("评论");
}

export function isKsCommentReady(): boolean {
  const selectors = ['[class*="comment-item"]', '[class*="CommentItem"]', ".comment-list-item"];
  for (const selector of selectors) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length && i < 40; i += 1) {
      if (isVisible(nodes[i] as HTMLElement)) return true;
    }
  }
  return /全部评论|条评论/.test(document.body.innerText) && videoDetailReady();
}

export async function clickKsCommentTab(): Promise<boolean> {
  const tabs = document.querySelectorAll('div[role="tab"], span, button, div');
  for (let i = 0; i < tabs.length && i < 120; i += 1) {
    const el = tabs[i] as HTMLElement;
    const text = (el.textContent ?? "").replace(/\s+/g, "");
    if (!/^评论(\(\d+\))?$/.test(text) && !text.startsWith("全部评论")) continue;
    if (!isVisible(el)) continue;
    el.scrollIntoView({ block: "center", behavior: "instant" });
    humanClick(el);
    await sleep(humanPace.afterCommentClick());
    return isKsCommentReady();
  }
  return false;
}

export function buildDomSearchItems(limit: number): PlatformSearchItem[] {
  const cards = collectKsVideoCards();
  const items: PlatformSearchItem[] = [];
  for (let i = 0; i < cards.length && items.length < limit; i += 1) {
    const el = cards[i];
    const href = el.getAttribute("href") ?? "";
    const photoId = extractPhotoIdFromHref(href);
    if (!PHOTO_ID_RE.test(photoId)) continue;
    const rect = el.getBoundingClientRect();
    items.push({
      index: items.length + 1,
      title: (el.textContent ?? "").trim().slice(0, 80) || `视频 ${photoId.slice(0, 8)}`,
      author: "—",
      url: href.startsWith("http") ? href : `https://www.kuaishou.com${href}`,
      aweme_id: photoId,
      source: "dom",
      click_by: "dom_rect",
      rect: {
        top: Math.round(rect.top),
        left: Math.round(rect.left),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
    });
  }
  return items;
}

export async function clickKsVideoAtIndex(index: number): Promise<{ ok: boolean; aweme_id: string; message: string }> {
  const cards = collectKsVideoCards();
  if (cards.length === 0) {
    return { ok: false, aweme_id: "", message: "未找到快手视频卡片" };
  }
  const targetIndex = Math.min(Math.max(1, index), cards.length);
  const el = cards[targetIndex - 1];
  const photoId = extractPhotoIdFromHref(el.getAttribute("href") ?? "");
  el.scrollIntoView({ block: "center", behavior: "instant" });
  await sleep(randDelay(300, 600));
  humanClick(el);
  await sleep(humanPace.videoFeedSettle());
  return {
    ok: videoDetailReady() || isKsVideoPage(),
    aweme_id: photoId,
    message: videoDetailReady() ? `已打开第 ${targetIndex} 条视频` : "已点击视频，等待详情页加载",
  };
}

export function scrollKsComments(): boolean {
  const selectors = ['[class*="comment"]', ".comment-list", ".video-info"];
  for (const selector of selectors) {
    const el = document.querySelector(selector) as HTMLElement | null;
    if (!el) continue;
    if (el.scrollHeight > el.clientHeight + 40) {
      el.scrollTop = Math.min(el.scrollTop + 420, el.scrollHeight);
      return true;
    }
  }
  window.scrollBy({ top: 360, behavior: "instant" });
  return true;
}
