import { buildVideoUrl, sleep } from "./search";

const REPLY_BTN_SELECTORS = [
  '[data-e2e="comment-reply"]',
  'button',
  'span',
];

const INPUT_SELECTORS = [
  '[data-e2e="comment-input"] div[contenteditable="true"]',
  '[data-e2e="comment-input"] textarea',
  'div.public-DraftEditor-content[contenteditable="true"]',
  'div[contenteditable="true"]',
];

const SEND_SELECTORS = [
  '[data-e2e="comment-post"]',
  'button',
  'span',
];

const COMMENT_ITEM_SELECTOR = '[data-e2e="comment-item"]';
const PUBLISH_PATH = "/aweme/v1/web/comment/publish";

export interface ReplyCommentPayload {
  video_url?: string;
  aweme_id?: string;
  comment_id?: string;
  comment_text?: string;
  parent_comment_id?: string;
  reply_text: string;
  scroll_rounds?: number;
  dry_run?: boolean;
}

export interface ReplyCommentResult {
  ok: boolean;
  dry_run?: boolean;
  capture_method: string;
  comment_id?: string;
  parent_comment_id?: string;
  video_url?: string;
  error?: string;
  publish?: {
    status_code?: number;
    comment?: unknown;
  };
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function isVisible(el: Element | null) {
  if (!el || !(el instanceof HTMLElement)) return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function clickElement(el: HTMLElement) {
  el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  el.click();
}

async function setEditableText(el: HTMLElement, text: string) {
  el.focus();
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
    el.value = text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return;
  }
  el.textContent = text;
  el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text }));
}

function findByText(nodes: HTMLElement[], text: string) {
  const target = normalizeText(text);
  if (!target) return null;
  return (
    nodes.find((node) => normalizeText(node.textContent || "").includes(target)) ?? null
  );
}

function getCommentNodes() {
  return Array.from(document.querySelectorAll<HTMLElement>(COMMENT_ITEM_SELECTOR));
}

function matchCommentNode(
  node: HTMLElement,
  commentId?: string,
  commentText?: string,
) {
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
    await sleep(700);
  }
}

async function waitForCommentItems(timeoutMs = 12000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (getCommentNodes().length > 0) return true;
    await sleep(400);
  }
  return false;
}

async function findTargetComment(
  commentId?: string,
  commentText?: string,
  scrollRounds = 12,
) {
  for (let round = 0; round <= scrollRounds; round += 1) {
    const nodes = getCommentNodes();
    const direct = nodes.find((node) => matchCommentNode(node, commentId, commentText));
    if (direct) {
      direct.scrollIntoView({ block: "center", behavior: "smooth" });
      await sleep(500);
      return direct;
    }
    if (commentText) {
      const fuzzy = findByText(nodes, commentText);
      if (fuzzy) {
        fuzzy.scrollIntoView({ block: "center", behavior: "smooth" });
        await sleep(500);
        return fuzzy;
      }
    }
    if (round < scrollRounds) {
      await scrollCommentPanels(1);
    }
  }
  return null;
}

function findReplyButton(item: HTMLElement) {
  const scoped = Array.from(item.querySelectorAll<HTMLElement>('[data-e2e="comment-reply"], button, span'));
  for (const node of scoped) {
    if (normalizeText(node.textContent || "") === "回复" && isVisible(node)) {
      return node;
    }
  }
  for (const selector of REPLY_BTN_SELECTORS) {
    const candidate = item.querySelector<HTMLElement>(selector);
    if (candidate && normalizeText(candidate.textContent || "") === "回复" && isVisible(candidate)) {
      return candidate;
    }
  }
  return null;
}

function findReplyInput() {
  for (const selector of INPUT_SELECTORS) {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>(selector));
    for (const node of nodes.reverse()) {
      if (isVisible(node)) return node;
    }
  }
  return null;
}

function findSendButton() {
  for (const selector of SEND_SELECTORS) {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>(selector));
    for (const node of nodes.reverse()) {
      if (normalizeText(node.textContent || "") === "发送" && isVisible(node)) {
        return node;
      }
    }
  }
  return null;
}

function waitForPublish(timeoutMs = 12000): Promise<{ status_code?: number; comment?: unknown } | null> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMessage);
      resolve(null);
    }, timeoutMs);

    function onMessage(event: MessageEvent) {
      if (event.source !== window || event.data?.channel !== "huoke:injected") return;
      const payload = event.data.payload;
      const url = String(payload?.url || "");
      if (!url.includes(PUBLISH_PATH)) return;
      const body = payload?.body;
      window.clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      if (body && typeof body === "object") {
        resolve({
          status_code: (body as { status_code?: number }).status_code,
          comment: (body as { comment?: unknown }).comment,
        });
        return;
      }
      resolve(null);
    }

    window.addEventListener("message", onMessage);
  });
}

export async function replyToComment(payload: ReplyCommentPayload): Promise<ReplyCommentResult> {
  const replyText = String(payload.reply_text || "").trim();
  if (!replyText) {
    return {
      ok: false,
      capture_method: "douyin_comment_ui_extension",
      error: "reply_text is required",
    };
  }

  const commentId = String(payload.comment_id || "").trim();
  const commentText = String(payload.comment_text || "").trim();
  if (!commentId && !commentText) {
    return {
      ok: false,
      capture_method: "douyin_comment_ui_extension",
      error: "comment_id or comment_text is required",
    };
  }

  const awemeId = String(payload.aweme_id || "").trim();
  const videoUrl = String(payload.video_url || "").trim() || (awemeId ? buildVideoUrl(awemeId) : "");
  if (videoUrl && !location.href.includes(videoUrl.replace("https://www.douyin.com", ""))) {
    location.href = videoUrl;
    return {
      ok: false,
      capture_method: "douyin_comment_ui_extension",
      error: "navigating_to_video",
      video_url: videoUrl,
    };
  }

  const hasComments = await waitForCommentItems();
  if (!hasComments) {
    return {
      ok: false,
      capture_method: "douyin_comment_ui_extension",
      error: "comment list not loaded",
      video_url: videoUrl,
    };
  }

  const target = await findTargetComment(
    commentId || undefined,
    commentText || undefined,
    Math.max(1, Math.min(payload.scroll_rounds ?? 12, 24)),
  );
  if (!target) {
    return {
      ok: false,
      capture_method: "douyin_comment_ui_extension",
      error: "target comment not found",
      comment_id: commentId || undefined,
      parent_comment_id: payload.parent_comment_id,
      video_url: videoUrl,
    };
  }

  if (payload.dry_run) {
    return {
      ok: true,
      dry_run: true,
      capture_method: "douyin_comment_ui_extension",
      comment_id: commentId || undefined,
      parent_comment_id: payload.parent_comment_id,
      video_url: videoUrl,
    };
  }

  const replyBtn = findReplyButton(target);
  if (!replyBtn) {
    return {
      ok: false,
      capture_method: "douyin_comment_ui_extension",
      error: "reply button not found",
      comment_id: commentId || undefined,
      video_url: videoUrl,
    };
  }

  clickElement(replyBtn);
  await sleep(800);

  const input = findReplyInput();
  if (!input) {
    return {
      ok: false,
      capture_method: "douyin_comment_ui_extension",
      error: "reply input not found",
      comment_id: commentId || undefined,
      video_url: videoUrl,
    };
  }

  await setEditableText(input, replyText);
  await sleep(500);

  const publishWait = waitForPublish();
  const sendBtn = findSendButton();
  if (!sendBtn) {
    return {
      ok: false,
      capture_method: "douyin_comment_ui_extension",
      error: "send button not found",
      comment_id: commentId || undefined,
      video_url: videoUrl,
    };
  }

  clickElement(sendBtn);
  const publish = await publishWait;
  if (publish?.status_code === 0) {
    return {
      ok: true,
      capture_method: "douyin_comment_ui_extension",
      comment_id: commentId || undefined,
      parent_comment_id: payload.parent_comment_id,
      video_url: videoUrl,
      publish,
    };
  }

  return {
    ok: false,
    capture_method: "douyin_comment_ui_extension",
    error: publish ? `publish status_code=${publish.status_code ?? "unknown"}` : "publish response not captured",
    comment_id: commentId || undefined,
    parent_comment_id: payload.parent_comment_id,
    video_url: videoUrl,
    publish: publish ?? undefined,
  };
}
