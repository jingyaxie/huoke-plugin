import { humanClick, isVisible, randDelay, sleep } from "./search-input";
import { resolveCommentItem, type ResolveCommentPayload } from "./resolve-comment-item";

export interface DomRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface DomPoint {
  x: number;
  y: number;
}

function serializeRect(rect: DOMRect): DomRect {
  return {
    top: Math.round(rect.top),
    left: Math.round(rect.left),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
}

function centerOf(rect: DOMRect): DomPoint {
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
  };
}

/** 对齐 Python `_hover_comment_item` 坐标（55% 处） */
export function hoverPointForRect(rect: DomRect): DomPoint {
  return {
    x: rect.left + rect.width * 0.55,
    y: rect.top + rect.height * 0.55,
  };
}

function getCommentItems(): HTMLElement[] {
  return Array.from(document.querySelectorAll('[data-e2e="comment-item"]')) as HTMLElement[];
}

const REPLY_BTN_SELECTORS = [
  '[data-e2e="comment-reply"]',
  'span[class*="reply"]',
  'button[class*="reply"]',
  "span",
  "button",
] as const;

function normalizeReplyText(text: string): string {
  return text.replace(/\s+/g, "").trim();
}

/** 对齐 Python `_hover_comment_item`：在评论项 55% 处派发 pointer/mouse 事件 */
export function hoverCommentItem(item: HTMLElement) {
  const rect = item.getBoundingClientRect();
  const clientX = rect.left + rect.width * 0.55;
  const clientY = rect.top + rect.height * 0.55;
  const base: MouseEventInit = {
    bubbles: true,
    cancelable: true,
    view: window,
    clientX,
    clientY,
  };

  item.dispatchEvent(new PointerEvent("pointerover", { ...base, pointerId: 1, pointerType: "mouse" }));
  item.dispatchEvent(
    new PointerEvent("pointerenter", { ...base, pointerId: 1, pointerType: "mouse", bubbles: false }),
  );
  item.dispatchEvent(new MouseEvent("mouseover", base));
  item.dispatchEvent(new MouseEvent("mouseenter", { ...base, bubbles: false }));
  item.dispatchEvent(new MouseEvent("mousemove", base));
}

function findReplyButtonInItem(item: HTMLElement): HTMLElement | null {
  for (const selector of REPLY_BTN_SELECTORS) {
    const nodes = item.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i] as HTMLElement;
      if (selector === '[data-e2e="comment-reply"]') {
        if (isVisible(node)) return node;
        continue;
      }
      if (normalizeReplyText(node.textContent ?? "") !== "回复") continue;
      if (isVisible(node)) return node;
    }
  }
  return null;
}

function replyInputPlaceholder(el: HTMLElement): string {
  return (
    el.getAttribute("data-placeholder") ??
    el.getAttribute("aria-placeholder") ??
    el.closest('[data-e2e="comment-input"]')?.getAttribute("data-placeholder") ??
    ""
  ).trim();
}

export function findReplyInputElement(): HTMLElement | null {
  const selectors = [
    '[data-e2e="comment-input"] div.public-DraftEditor-content[contenteditable="true"]',
    '[data-e2e="comment-input"] [contenteditable="true"]',
    '.comment-input-inner-container [contenteditable="true"]',
  ];

  for (const selector of selectors) {
    const nodes = document.querySelectorAll(selector);
    for (let i = nodes.length - 1; i >= 0; i -= 1) {
      const el = nodes[i] as HTMLElement;
      const rect = el.getBoundingClientRect();
      if (rect.width < 8 || rect.height < 8) continue;
      const ph = replyInputPlaceholder(el);
      const active = document.activeElement === el || el.contains(document.activeElement);
      if (active || ph.includes("回复")) return el;
    }
  }

  return null;
}

/** 供 background 查询：评论项 / 回复按钮坐标 */
export async function probeReplyCommentTargets(payload: ResolveCommentPayload = {}) {
  const resolved = await resolveCommentItem(payload);
  if (!resolved.ok || !resolved.item) {
    return {
      ok: false,
      comment_index: resolved.index || Number(payload.comment_index ?? payload.index ?? 1),
      comment_count: resolved.comment_count ?? 0,
      url: location.href,
      message: resolved.message ?? "未找到评论项",
    };
  }

  const item = resolved.item;
  const itemRect = item.getBoundingClientRect();
  const serializedItemRect = serializeRect(itemRect);
  const replyBtn = findReplyButtonInItem(item);

  return {
    ok: true,
    comment_index: resolved.index,
    comment_count: resolved.comment_count,
    item_rect: serializedItemRect,
    item_center: centerOf(itemRect),
    hover_point: hoverPointForRect(serializedItemRect),
    reply_btn: replyBtn
      ? {
          rect: serializeRect(replyBtn.getBoundingClientRect()),
          center: centerOf(replyBtn.getBoundingClientRect()),
        }
      : null,
    url: location.href,
  };
}

/** 滚动到评论项并派发 hover，再探测回复按钮（CDP 鼠标 alone 无法触发 React hover） */
export async function hoverReplyCommentTarget(payload: ResolveCommentPayload = {}) {
  const resolved = await resolveCommentItem(payload);
  if (!resolved.ok || !resolved.item) {
    return {
      ok: false,
      comment_index: resolved.index || Number(payload.comment_index ?? payload.index ?? 1),
      comment_count: resolved.comment_count ?? 0,
      url: location.href,
      message: resolved.message ?? "未找到评论项",
    };
  }

  const item = resolved.item;
  hoverCommentItem(item);

  const actionRow = item.querySelector('[class*="action"], [class*="Action"], [class*="footer"]') as HTMLElement | null;
  if (actionRow) hoverCommentItem(actionRow);

  await sleep(randDelay(280, 480));
  return probeReplyCommentTargets(payload);
}

/** 供 background 查询：回复输入框坐标 */
export function probeReplyInput() {
  const input = findReplyInputElement();
  if (!input) {
    return {
      ok: false,
      found: false,
      url: location.href,
      message: "回复输入框未出现",
    };
  }

  const rect = input.getBoundingClientRect();
  const editable = resolveEditable(input);
  return {
    ok: true,
    found: true,
    rect: serializeRect(rect),
    center: centerOf(rect),
    placeholder: replyInputPlaceholder(input),
    draft_text: readDraftText(editable).slice(0, 120),
    placeholder_visible: isDraftPlaceholderVisible(editable),
    url: location.href,
  };
}

function resolveEditable(el: HTMLElement): HTMLElement {
  if (el.matches('[contenteditable="true"]')) return el;
  return (el.querySelector('[contenteditable="true"]') as HTMLElement | null) ?? el;
}

function readDraftText(editable: HTMLElement): string {
  return (editable.textContent ?? "").replace(/\u200b/g, "").trim();
}

function isDraftPlaceholderVisible(editable: HTMLElement): boolean {
  const root = editable.closest(".public-DraftEditor-root");
  const ph = root?.querySelector(".public-DraftEditorPlaceholder-root") as HTMLElement | null;
  if (!ph) return false;
  const style = window.getComputedStyle(ph);
  return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || 1) > 0.05;
}

/** Draft.js：逐字 insertText，禁止改 textContent */
async function typeIntoDraftEditor(editable: HTMLElement, text: string) {
  editable.focus();
  humanClick(editable);
  await sleep(randDelay(300, 500));

  for (const ch of text) {
    try {
      document.execCommand("insertText", false, ch);
    } catch {
      // ignore
    }
    editable.dispatchEvent(
      new InputEvent("beforeinput", {
        bubbles: true,
        cancelable: true,
        data: ch,
        inputType: "insertText",
      }),
    );
    editable.dispatchEvent(
      new InputEvent("input", {
        bubbles: true,
        cancelable: true,
        data: ch,
        inputType: "insertText",
      }),
    );
    await sleep(randDelay(70, 160));
  }
}

/** 安全写入 Draft 编辑器 — 禁止 selectAll / textContent 赋值 */
export async function typeReplyCommentText(payload: { reply_text?: string; text?: string } = {}) {
  const text = String(payload.reply_text ?? payload.text ?? "").trim();
  if (!text) {
    return { ok: false, message: "missing reply_text" };
  }

  const input = findReplyInputElement();
  if (!input) {
    return {
      ok: false,
      message: "未找到回复输入框",
      url: location.href,
    };
  }

  const editable = resolveEditable(input);
  await typeIntoDraftEditor(editable, text);

  const value = readDraftText(editable);
  const placeholderVisible = isDraftPlaceholderVisible(editable);
  const ok = value.length > 0 && !placeholderVisible;

  return {
    ok,
    reply_text: text,
    value: value.slice(0, 120),
    placeholder_visible: placeholderVisible,
    placeholder: replyInputPlaceholder(input),
    url: location.href,
    message: ok
      ? "已逐字写入回复文案"
      : placeholderVisible
        ? "placeholder 未消失，请用 CDP 模式（重新加载扩展）"
        : "写入回复文案失败",
  };
}

/** content 回退（无 CDP 时） */
export async function replyComment(payload: {
  reply_text?: string;
  comment_index?: number;
  index?: number;
}) {
  const replyText = String(payload.reply_text ?? "").trim();
  if (!replyText) throw new Error("reply_comment: missing reply_text");

  const probe = await hoverReplyCommentTarget(payload);
  if (!probe.ok || !probe.reply_btn?.center) {
    return {
      ok: false,
      message: probe.message ?? "未找到回复按钮，请用 background CDP 模式",
      url: location.href,
    };
  }

  const btn = document.elementFromPoint(probe.reply_btn.center.x, probe.reply_btn.center.y);
  if (btn instanceof HTMLElement) humanClick(btn);
  await sleep(randDelay(600, 900));

  const typed = await typeReplyCommentText({ reply_text: replyText });
  return {
    ...typed,
    comment_index: probe.comment_index,
    mode: "content_fallback",
  };
}
