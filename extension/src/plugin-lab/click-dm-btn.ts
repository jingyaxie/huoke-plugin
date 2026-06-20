import { findVisibleDmButton, isDmPanelOpen } from "./dm-dom";
import { humanClick, randDelay, sleep } from "./search-input";

/** content 回退（无 CDP 时） */
export async function clickDmButton() {
  if (isDmPanelOpen()) {
    return {
      ok: true,
      already_open: true,
      mode: "content_fallback",
      url: location.href,
      message: "私信输入面板已打开",
    };
  }

  const button = findVisibleDmButton();
  if (!button) {
    return {
      ok: false,
      mode: "content_fallback",
      url: location.href,
      message: "未找到私信按钮，请重新加载扩展以启用 CDP 点击",
    };
  }

  humanClick(button);
  await sleep(randDelay(1200, 1800));

  const ok = isDmPanelOpen();
  return {
    ok,
    clicked: true,
    mode: "content_fallback",
    url: location.href,
    message: ok ? "已点击私信按钮" : "已点击私信，但未检测到可见输入框",
  };
}
