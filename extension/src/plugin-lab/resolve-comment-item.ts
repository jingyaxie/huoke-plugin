import { randDelay, sleep } from "./search-input";

const COMMENT_ITEM_SELECTOR = '[data-e2e="comment-item"]';

export interface ResolveCommentPayload {
  comment_index?: number;
  index?: number;
  comment_id?: string;
  comment_text?: string;
  scroll_rounds?: number;
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function getCommentItems() {
  return Array.from(document.querySelectorAll<HTMLElement>(COMMENT_ITEM_SELECTOR));
}

function matchCommentNode(node: HTMLElement, commentId?: string, commentText?: string) {
  if (commentId) {
    const idAttr =
      node.getAttribute("data-comment-id") ||
      node.dataset.commentId ||
      node.querySelector("[data-comment-id]")?.getAttribute("data-comment-id") ||
      "";
    if (idAttr && idAttr === commentId) return true;
    if (node.outerHTML.includes(commentId)) return true;
  }
  if (commentText) {
    const text = normalizeText(commentText);
    if (text && normalizeText(node.textContent || "").includes(text)) return true;
  }
  return false;
}

async function scrollCommentPanels(rounds: number) {
  for (let i = 0; i < rounds; i += 1) {
    const panels = Array.from(
      document.querySelectorAll<HTMLElement>(
        '[class*="comment"], [data-e2e="comment-list"], [class*="CommentList"]',
      ),
    );
    for (const panel of panels) {
      if (panel.scrollHeight > panel.clientHeight + 40) {
        panel.scrollTop += 700;
      }
    }
    window.scrollBy({ top: 500, behavior: "smooth" });
    await sleep(randDelay(500, 800));
  }
}

/** 按 index 或 comment_id / comment_text 定位评论项（与任务编排字段对齐） */
export async function resolveCommentItem(payload: ResolveCommentPayload = {}) {
  const commentId = String(payload.comment_id ?? "").trim();
  const commentText = String(payload.comment_text ?? "").trim();
  const scrollRounds = Math.max(0, Math.min(Number(payload.scroll_rounds ?? 12), 24));

  if (commentId || commentText) {
    for (let round = 0; round <= scrollRounds; round += 1) {
      const items = getCommentItems();
      const foundIndex = items.findIndex((node) => matchCommentNode(node, commentId, commentText));
      if (foundIndex >= 0) {
        const item = items[foundIndex];
        item.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
        await sleep(randDelay(200, 400));
        return { ok: true as const, item, index: foundIndex + 1, comment_count: items.length };
      }
      if (round < scrollRounds) {
        await scrollCommentPanels(1);
      }
    }
    return {
      ok: false as const,
      index: 0,
      comment_count: getCommentItems().length,
      message: "target comment not found",
    };
  }

  const index = Math.max(1, Number(payload.comment_index ?? payload.index ?? 1));
  const items = getCommentItems();
  if (items.length === 0) {
    return { ok: false as const, index, comment_count: 0, message: "未找到评论项" };
  }

  const item = items[Math.min(index, items.length) - 1];
  item.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
  await sleep(randDelay(120, 220));
  return {
    ok: true as const,
    item,
    index: Math.min(index, items.length),
    comment_count: items.length,
  };
}
