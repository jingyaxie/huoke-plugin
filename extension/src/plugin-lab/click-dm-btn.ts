import { humanClick, randDelay, sleep } from "./search-input";

const DM_SELECTORS = [
  '[data-e2e="user-info-message-btn"]',
  '[data-e2e="user-detail"] button',
  '[data-e2e="user-info"] button',
] as const;

function findDmButton(): HTMLElement | null {
  for (const selector of DM_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i] as HTMLElement;
      if (!(node.textContent ?? "").includes("私信")) continue;
      const rect = node.getBoundingClientRect();
      if (rect.width >= 30 && rect.height >= 16) return node;
    }
  }

  const root = document.querySelector('[data-e2e="user-detail"]');
  if (root) {
    const buttons = root.querySelectorAll("button");
    for (let i = 0; i < buttons.length; i += 1) {
      const btn = buttons[i] as HTMLElement;
      if ((btn.textContent ?? "").includes("私信")) return btn;
    }
  }

  const allButtons = document.querySelectorAll("button");
  for (let i = 0; i < allButtons.length && i < 80; i += 1) {
    const btn = allButtons[i] as HTMLElement;
    if ((btn.textContent ?? "").trim() === "私信") return btn;
  }

  return null;
}

function dmSurfaceOpen(): boolean {
  return (
    Boolean(document.querySelector('[data-e2e="im-dialog"]')) ||
    Boolean(document.querySelector('[data-e2e="msg-input"]')) ||
    Boolean(document.querySelector('[data-e2e="message-input"]'))
  );
}

/** 步骤 16：点击私信按钮 */
export async function clickDmButton() {
  if (dmSurfaceOpen()) {
    return {
      ok: true,
      already_open: true,
      url: location.href,
      message: "私信面板已打开",
    };
  }

  const button = findDmButton();
  if (!button) {
    return {
      ok: false,
      url: location.href,
      message: "未找到私信按钮",
    };
  }

  humanClick(button);
  await sleep(randDelay(1200, 1800));

  const ok = dmSurfaceOpen();
  return {
    ok,
    clicked: true,
    url: location.href,
    message: ok ? "已点击私信按钮并打开输入面板" : "已点击私信，但未检测到输入面板",
  };
}
