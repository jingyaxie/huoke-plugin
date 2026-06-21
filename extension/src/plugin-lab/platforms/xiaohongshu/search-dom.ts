import { humanClick, humanPace, isVisible, randDelay, sleep } from "../../search-input";
import { NOTE_DETAIL_MARKERS, NOTE_ID_RE, NOTE_LINK_SELECTORS } from "./constants";
import type { PlatformSearchItem } from "../shared/content-item";

export function isXhsSearchResultsPage(url = location.href): boolean {
  if (/search_result/i.test(url)) return true;
  try {
    const path = new URL(url).pathname.replace(/\/+$/, "") || "/";
    if (path === "/explore" && collectXhsNoteCards().length >= 2) return true;
  } catch {
    // ignore
  }
  return false;
}

export function isXhsNotePage(url = location.href): boolean {
  return /\/explore\//i.test(url) || /\/discovery\/item\//i.test(url) || /\/note\//i.test(url);
}

export function isXhsProfilePage(url = location.href): boolean {
  return /\/user\/profile\//i.test(url);
}

export function extractNoteIdFromHref(href: string): string {
  const match = href.match(/\/explore\/([0-9a-fA-F]{16,32})/i)
    || href.match(/\/discovery\/item\/([0-9a-fA-F]{16,32})/i)
    || href.match(/\/note\/([0-9a-fA-F]{16,32})/i);
  return match?.[1] ?? "";
}

export function collectXhsNoteCards(): HTMLElement[] {
  const out: HTMLElement[] = [];
  const seen = new Set<string>();
  for (const selector of NOTE_LINK_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const el = nodes[i] as HTMLElement;
      const href = el.getAttribute("href") ?? "";
      const noteId = extractNoteIdFromHref(href);
      if (!NOTE_ID_RE.test(noteId) || !isVisible(el)) continue;
      const key = `${noteId}:${Math.round(el.getBoundingClientRect().top)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(el);
    }
  }
  out.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  return out;
}

export function noteDetailReady(): boolean {
  for (const selector of NOTE_DETAIL_MARKERS) {
    const el = document.querySelector(selector);
    if (el && isVisible(el)) return true;
  }
  return document.body.innerText.includes("条评论") || document.body.innerText.includes("全部评论");
}

export function countVisibleXhsComments(): number {
  let count = 0;
  const selectors = ['[class*="comment-item"]', '[class*="CommentItem"]', ".note-comment-item", "li"];
  for (const selector of selectors) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length && i < 80; i += 1) {
      const el = nodes[i] as HTMLElement;
      if (!isVisible(el)) continue;
      const text = (el.textContent ?? "").replace(/\s+/g, "");
      if (text.length < 4) continue;
      count += 1;
    }
  }
  return count;
}

export function isXhsCommentReady(): boolean {
  if (countVisibleXhsComments() > 0) return true;
  return /全部评论|条评论/.test(document.body.innerText) && noteDetailReady();
}

export async function clickXhsCommentTab(): Promise<boolean> {
  const tabs = document.querySelectorAll('div[role="tab"], span, button, div');
  for (let i = 0; i < tabs.length && i < 120; i += 1) {
    const el = tabs[i] as HTMLElement;
    const text = (el.textContent ?? "").replace(/\s+/g, "");
    if (!/^评论(\(\d+\))?$/.test(text) && !text.startsWith("条评论") && !text.startsWith("全部评论")) continue;
    if (!isVisible(el)) continue;
    el.scrollIntoView({ block: "center", behavior: "instant" });
    humanClick(el);
    await sleep(humanPace.afterCommentClick());
    return isXhsCommentReady();
  }
  return false;
}

export function buildDomSearchItems(limit: number): PlatformSearchItem[] {
  const cards = collectXhsNoteCards();
  const items: PlatformSearchItem[] = [];
  for (let i = 0; i < cards.length && items.length < limit; i += 1) {
    const el = cards[i];
    const href = el.getAttribute("href") ?? "";
    const noteId = extractNoteIdFromHref(href);
    if (!NOTE_ID_RE.test(noteId)) continue;
    const rect = el.getBoundingClientRect();
    items.push({
      index: items.length + 1,
      title: (el.textContent ?? "").trim().slice(0, 80) || `笔记 ${noteId.slice(0, 8)}`,
      author: "—",
      url: href.startsWith("http") ? href : `https://www.xiaohongshu.com${href}`,
      aweme_id: noteId,
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

export async function clickXhsNoteAtIndex(index: number): Promise<{ ok: boolean; aweme_id: string; message: string }> {
  const cards = collectXhsNoteCards();
  if (cards.length === 0) {
    return { ok: false, aweme_id: "", message: "未找到小红书笔记卡片" };
  }
  const targetIndex = Math.min(Math.max(1, index), cards.length);
  const el = cards[targetIndex - 1];
  const noteId = extractNoteIdFromHref(el.getAttribute("href") ?? "");
  el.scrollIntoView({ block: "center", behavior: "instant" });
  await sleep(randDelay(300, 600));
  humanClick(el);
  await sleep(humanPace.videoFeedSettle());
  return {
    ok: noteDetailReady() || isXhsNotePage(),
    aweme_id: noteId,
    message: noteDetailReady() ? `已打开第 ${targetIndex} 条笔记` : "已点击笔记，等待详情页加载",
  };
}

export function scrollXhsComments(): boolean {
  const selectors = ['[class*="comment"]', ".comments-el", ".note-scroller", "#noteContainer"];
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
