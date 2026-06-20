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

const DM_BUTTON_SELECTORS = [
  '[data-e2e="user-info-message-btn"]',
  '[data-e2e="user-detail"] button',
  '[data-e2e="user-info"] button',
] as const;

const DM_INPUT_SELECTORS = [
  '[data-e2e="msg-input"] div[contenteditable="true"]',
  '[data-e2e="msg-input"] .editor-kit-container',
  '[data-e2e="im-dialog"] [data-e2e="message-input"]',
  '[data-e2e="im-dialog"] div[contenteditable="true"]',
  '[data-e2e="message-input"]',
] as const;

const DM_SEND_SELECTORS = [
  '[data-e2e="msg-input"] .messageMsgInputinputAction',
  '[data-e2e="msg-input"] button',
  '[data-e2e="im-dialog"] button',
] as const;

function serializeRect(rect: DOMRect): DomRect {
  return {
    top: Math.round(rect.top),
    left: Math.round(rect.left),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
}

function centerOf(rect: DOMRect): DomPoint {
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function isVisible(el: Element): boolean {
  const rect = el.getBoundingClientRect();
  if (rect.width < 8 || rect.height < 8) return false;
  if (rect.bottom < 0 || rect.top > window.innerHeight + 4) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden") return false;
  if (Number(style.opacity || 1) < 0.05) return false;
  return true;
}

function buttonLooksLikeDm(el: HTMLElement): boolean {
  if (el.matches('[data-e2e="user-info-message-btn"]')) return true;
  const text = (el.textContent ?? "").replace(/\s+/g, "");
  return text === "私信" || text.includes("私信");
}

export function findVisibleDmButton(): HTMLElement | null {
  for (const selector of DM_BUTTON_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i] as HTMLElement;
      if (!buttonLooksLikeDm(node)) continue;
      if (!isVisible(node)) continue;
      const rect = node.getBoundingClientRect();
      if (rect.width >= 24 && rect.height >= 16) return node;
    }
  }

  const root = document.querySelector('[data-e2e="user-detail"]');
  if (root) {
    const buttons = root.querySelectorAll("button");
    for (let i = 0; i < buttons.length; i += 1) {
      const btn = buttons[i] as HTMLElement;
      if (!buttonLooksLikeDm(btn) || !isVisible(btn)) continue;
      return btn;
    }
  }

  const allButtons = document.querySelectorAll("button");
  for (let i = 0; i < allButtons.length && i < 100; i += 1) {
    const btn = allButtons[i] as HTMLElement;
    if ((btn.textContent ?? "").replace(/\s+/g, "") !== "私信") continue;
    if (!isVisible(btn)) continue;
    return btn;
  }

  return null;
}

export function findVisibleDmInput(): HTMLElement | null {
  for (const selector of DM_INPUT_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = nodes.length - 1; i >= 0; i -= 1) {
      const node = nodes[i] as HTMLElement;
      const editable = resolveEditable(node);
      if (!isVisible(editable)) continue;
      const rect = editable.getBoundingClientRect();
      if (rect.width >= 40 && rect.height >= 12) return editable;
    }
  }
  return null;
}

function resolveEditable(el: HTMLElement): HTMLElement {
  if (el.matches('[contenteditable="true"]')) return el;
  return (el.querySelector('[contenteditable="true"]') as HTMLElement | null) ?? el;
}

/** 归一化编辑器文本，便于比对 */
export function normalizeDmText(raw: string): string {
  return raw
    .replace(/\u200b/g, "")
    .replace(/\ufeff/g, "")
    .replace(/\s+/g, "")
    .trim();
}

function readTextFromEditable(el: HTMLElement): string {
  return normalizeDmText(el.innerText || el.textContent || "");
}

export function readDmInputText(): string {
  const input = findVisibleDmInput();
  if (!input) return "";
  return readTextFromEditable(input);
}

export function dmInputMatchesExpected(expected: string, actual?: string): boolean {
  const exp = normalizeDmText(expected);
  if (!exp) return false;

  const act = normalizeDmText(actual ?? readDmInputText());
  if (!act) return false;
  return act === exp || act.includes(exp) || exp.includes(act);
}

function sendButtonLooksValid(el: HTMLElement, selector: string): boolean {
  if (selector.includes("inputAction")) return true;
  const text = (el.textContent ?? "").replace(/\s+/g, "");
  return text === "发送";
}

function resolveClickTarget(el: HTMLElement): HTMLElement {
  let node: HTMLElement | null = el;
  for (let i = 0; i < 6 && node; i += 1) {
    const rect = node.getBoundingClientRect();
    if (rect.width >= 28 && rect.height >= 20) return node;
    node = node.parentElement;
  }
  return el;
}

export function findVisibleDmSendButton(): HTMLElement | null {
  for (const selector of DM_SEND_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = nodes.length - 1; i >= 0; i -= 1) {
      const node = nodes[i] as HTMLElement;
      if (!sendButtonLooksValid(node, selector)) continue;
      const clickEl = resolveClickTarget(node);
      if (!isVisible(clickEl)) continue;
      const rect = clickEl.getBoundingClientRect();
      if (rect.width >= 20 && rect.height >= 14) return clickEl;
    }
  }

  const buttons = document.querySelectorAll("button, span");
  for (let i = 0; i < buttons.length && i < 100; i += 1) {
    const node = buttons[i] as HTMLElement;
    if ((node.textContent ?? "").replace(/\s+/g, "") !== "发送") continue;
    if (!isVisible(node)) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width >= 20 && rect.height >= 14) return node;
  }

  return null;
}

export function readDmChatHistoryText(): string {
  const parts: string[] = [];

  const chatSelectors = [
    ".componentsRightPanelnotHeaderArea",
    ".componentsRightPanelwrapper",
  ];
  for (const selector of chatSelectors) {
    const el = document.querySelector(selector) as HTMLElement | null;
    if (el && isVisible(el)) parts.push(el.innerText ?? "");
  }

  const dialog = document.querySelector('[data-e2e="im-dialog"]') as HTMLElement | null;
  if (dialog && isVisible(dialog)) {
    const clone = dialog.cloneNode(true) as HTMLElement;
    clone
      .querySelectorAll(
        '[data-e2e="message-input"], [data-e2e="msg-input"], [contenteditable="true"], textarea',
      )
      .forEach((node) => node.remove());
    parts.push(clone.innerText ?? "");
  }

  return parts.join("\n");
}

/** @deprecated 含输入框文字，勿用于发送校验 */
export function readDmDialogMergedText(): string {
  const parts: string[] = [];
  const panel = document.querySelector('[data-e2e="msg-input"]') as HTMLElement | null;
  if (panel && isVisible(panel)) parts.push(panel.innerText ?? "");
  parts.push(readDmChatHistoryText());
  return parts.join("\n");
}

export function verifyDmSent(expectedText: string): {
  ok: boolean;
  in_chat: boolean;
  input_cleared: boolean;
  draft_text: string;
  chat_preview: string;
} {
  const draftText = readDmInputText();
  const chatText = readDmChatHistoryText();
  const text = expectedText.trim();

  const inputStillHasText = text.length > 0 && draftText.includes(text);
  const inputCleared = text.length === 0 ? draftText.length === 0 : !inputStillHasText;
  const inChat = text.length > 0 && chatText.includes(text);

  return {
    ok: text.length > 0 && inChat && inputCleared,
    in_chat: inChat,
    input_cleared: inputCleared,
    draft_text: draftText.slice(0, 120),
    chat_preview: chatText.slice(0, 200),
  };
}

/** 私信输入面板是否真正可见（不能仅凭 DOM 存在判定） */
export function isDmPanelOpen(): boolean {
  return findVisibleDmInput() !== null;
}

export function probeDmButton() {
  const button = findVisibleDmButton();
  const panelOpen = isDmPanelOpen();

  if (panelOpen) {
    return {
      ok: true,
      panel_open: true,
      url: location.href,
      message: "私信输入面板已打开",
    };
  }

  if (!button) {
    return {
      ok: false,
      panel_open: false,
      url: location.href,
      message: "未找到可见的私信按钮（请确认在用户主页）",
    };
  }

  const rect = button.getBoundingClientRect();
  return {
    ok: true,
    panel_open: false,
    center: centerOf(rect),
    rect: serializeRect(rect),
    button_text: (button.textContent ?? "").replace(/\s+/g, "").slice(0, 20),
    url: location.href,
    message: "找到私信按钮",
  };
}

export function probeDmInput() {
  const input = findVisibleDmInput();
  if (!input) {
    return {
      ok: false,
      found: false,
      panel_open: false,
      url: location.href,
      message: "私信输入框不可见",
    };
  }

  const rect = input.getBoundingClientRect();
  return {
    ok: true,
    found: true,
    panel_open: true,
    rect: serializeRect(rect),
    center: centerOf(rect),
    draft_text: readDmInputText().slice(0, 120),
    url: location.href,
    message: "私信输入框已可见",
  };
}

export function probeDmSendButton() {
  const button = findVisibleDmSendButton();
  if (!button) {
    return {
      ok: false,
      found: false,
      url: location.href,
      message: "未找到可见的发送按钮，将尝试 Enter",
    };
  }

  const rect = button.getBoundingClientRect();
  return {
    ok: true,
    found: true,
    center: centerOf(rect),
    rect: serializeRect(rect),
    url: location.href,
    message: "找到私信发送按钮",
  };
}

export function probeDmSendVerify(payload: { dm_text?: string; text?: string } = {}) {
  const expected = String(payload.dm_text ?? payload.text ?? "").trim();
  const { ok, ...verify } = verifyDmSent(expected);
  return {
    ...verify,
    ok,
    url: location.href,
    message: ok
      ? "已在聊天记录中验证到私信"
      : !verify.input_cleared
        ? "发送失败：输入框仍有未发送内容"
        : verify.in_chat
          ? "发送状态不确定"
          : "发送后未在聊天记录中找到文案",
  };
}

/** content 回退：逐字 insertText，禁止 textContent 赋值 */
export async function typeDmTextFallback(payload: { dm_text?: string; text?: string } = {}) {
  const text = String(payload.dm_text ?? payload.text ?? "").trim();
  if (!text) return { ok: false, message: "missing dm_text" };

  const input = findVisibleDmInput();
  if (!input) {
    return {
      ok: false,
      url: location.href,
      message: "未找到私信输入框，请先执行步骤 16",
    };
  }

  input.focus();
  for (const ch of text) {
    try {
      document.execCommand("insertText", false, ch);
    } catch {
      // ignore
    }
    input.dispatchEvent(
      new InputEvent("input", { bubbles: true, data: ch, inputType: "insertText" }),
    );
    await new Promise((r) => setTimeout(r, 70 + Math.floor(Math.random() * 90)));
  }

  const value = readDmInputText();
  const ok = dmInputMatchesExpected(text, value);
  return {
    ok,
    dm_text: text,
    value: value.slice(0, 120),
    mode: "content_fallback",
    url: location.href,
    message: ok ? `已逐字输入私信（${value.length || text.length} 字）` : "输入后未能读取到私信内容",
  };
}
