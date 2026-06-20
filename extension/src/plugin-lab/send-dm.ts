import { humanClick, randDelay, sleep } from "./search-input";

const SEND_SELECTORS = [
  '[data-e2e="msg-input"] .messageMsgInputinputAction',
  '[data-e2e="msg-input"] button',
  '[data-e2e="im-dialog"] button',
] as const;

function findDmSendButton(): HTMLElement | null {
  for (const selector of SEND_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = nodes.length - 1; i >= 0; i -= 1) {
      const node = nodes[i] as HTMLElement;
      const text = (node.textContent ?? "").replace(/\s+/g, "");
      if (text === "发送" || selector.includes("inputAction")) {
        const rect = node.getBoundingClientRect();
        if (rect.width >= 20 && rect.height >= 14) return node;
      }
    }
  }

  const buttons = document.querySelectorAll("button, span");
  for (let i = 0; i < buttons.length && i < 100; i += 1) {
    const node = buttons[i] as HTMLElement;
    if ((node.textContent ?? "").replace(/\s+/g, "") !== "发送") continue;
    const rect = node.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 14) continue;
    return node;
  }

  return null;
}

/** 步骤 18：点击私信发送按钮 */
export async function sendDm() {
  const button = findDmSendButton();
  if (!button) {
    const input = document.querySelector('[data-e2e="msg-input"] div[contenteditable="true"], [data-e2e="im-dialog"] div[contenteditable="true"]') as
      | HTMLElement
      | null;
    if (input) {
      input.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
      );
      await sleep(randDelay(700, 1100));
      return {
        ok: true,
        method: "enter_key",
        url: location.href,
        message: "已通过 Enter 发送私信",
      };
    }

    return {
      ok: false,
      url: location.href,
      message: "未找到私信发送按钮",
    };
  }

  humanClick(button);
  await sleep(randDelay(900, 1400));

  return {
    ok: true,
    method: "click_send",
    url: location.href,
    message: "已点击私信发送按钮",
  };
}
