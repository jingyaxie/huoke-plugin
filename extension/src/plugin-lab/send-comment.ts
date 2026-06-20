import { findReplyInputElement } from "./reply-comment-dom";
import { humanClick, randDelay, sleep } from "./search-input";

function dispatchEnterKey(target: HTMLElement) {
  target.focus();
  humanClick(target);

  const base: KeyboardEventInit = {
    key: "Enter",
    code: "Enter",
    keyCode: 13,
    which: 13,
    bubbles: true,
    cancelable: true,
    view: window,
  };

  target.dispatchEvent(new KeyboardEvent("keydown", base));
  target.dispatchEvent(new KeyboardEvent("keypress", base));
  target.dispatchEvent(new KeyboardEvent("keyup", base));
}

function inputHasText(el: HTMLElement): boolean {
  return Boolean((el.textContent ?? "").trim());
}

/** 步骤 13：Enter 发送评论（Douyin 回复框通常无「发送」按钮） */
export async function sendComment() {
  const input = findReplyInputElement();
  if (!input) {
    const fallback = document.querySelector(
      '[data-e2e="comment-input"] div[contenteditable="true"], .comment-input-inner-container [contenteditable="true"]',
    ) as HTMLElement | null;
    if (!fallback) {
      return {
        ok: false,
        url: location.href,
        message: "未找到评论输入框",
      };
    }
    dispatchEnterKey(fallback);
    await sleep(randDelay(700, 1100));
    return {
      ok: true,
      method: "enter_key",
      input_cleared: !inputHasText(fallback),
      url: location.href,
      message: "已通过 Enter 发送评论",
    };
  }

  const hadText = inputHasText(input);
  dispatchEnterKey(input);
  await sleep(randDelay(700, 1100));

  return {
    ok: true,
    method: "enter_key",
    had_text: hadText,
    input_cleared: !inputHasText(input),
    url: location.href,
    message: "已通过 Enter 发送评论",
  };
}
