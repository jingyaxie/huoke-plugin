import { randDelay, sleep } from "./search-input";

const INPUT_SELECTORS = [
  '[data-e2e="msg-input"] div[contenteditable="true"]',
  '[data-e2e="im-dialog"] [data-e2e="message-input"]',
  '[data-e2e="im-dialog"] div[contenteditable="true"]',
  ".editor-kit-container[contenteditable='true']",
  'div[contenteditable="true"]',
] as const;

function findDmInput(): HTMLElement | null {
  for (const selector of INPUT_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = nodes.length - 1; i >= 0; i -= 1) {
      const node = nodes[i] as HTMLElement;
      const rect = node.getBoundingClientRect();
      if (rect.width > 40 && rect.height > 12) return node;
    }
  }
  return null;
}

function typeIntoContentEditable(el: HTMLElement, text: string) {
  el.focus();
  el.textContent = text;
  el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
}

export interface InputDmTextPayload {
  dm_text?: string;
  text?: string;
}

/** 步骤 17：在私信输入框输入文本 */
export async function inputDmText(payload: InputDmTextPayload = {}) {
  const text = String(payload.dm_text ?? payload.text ?? "").trim();
  if (!text) {
    throw new Error("input_dm_text: missing dm_text");
  }

  const input = findDmInput();
  if (!input) {
    return {
      ok: false,
      url: location.href,
      message: "未找到私信输入框，请先点击私信按钮",
    };
  }

  typeIntoContentEditable(input, text);
  await sleep(randDelay(300, 500));

  const value = (input.textContent ?? "").trim();
  return {
    ok: value === text,
    dm_text: text,
    value,
    input_tag: input.tagName.toLowerCase(),
    url: location.href,
    message: value === text ? `已输入私信文本（${text.length} 字）` : "私信输入框内容不匹配",
  };
}
