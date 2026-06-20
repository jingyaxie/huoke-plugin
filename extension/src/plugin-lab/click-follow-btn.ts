import { humanClick, randDelay, sleep } from "./search-input";

const FOLLOW_SELECTORS = [
  '[data-e2e="user-info-follow-btn"]',
  '[data-e2e="user-info-follow"]',
  '[data-e2e="follow-button"]',
  'button[class*="follow"]',
] as const;

function findFollowButton(): HTMLElement | null {
  for (const selector of FOLLOW_SELECTORS) {
    const node = document.querySelector(selector) as HTMLElement | null;
    if (!node) continue;
    const text = (node.textContent ?? "").replace(/\s+/g, "");
    if (text.includes("已关注") || text.includes("互相关注")) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width >= 40 && rect.height >= 20) return node;
  }

  const buttons = document.querySelectorAll("button, span, div");
  for (let i = 0; i < buttons.length && i < 120; i += 1) {
    const node = buttons[i] as HTMLElement;
    const text = (node.textContent ?? "").replace(/\s+/g, "");
    if (text !== "关注") continue;
    const rect = node.getBoundingClientRect();
    if (rect.width < 40 || rect.height < 18) continue;
    return node;
  }

  return null;
}

/** 步骤 15：在用户主页点击关注 */
export async function clickFollowButton() {
  const button = findFollowButton();
  if (!button) {
    return {
      ok: false,
      url: location.href,
      message: "未找到关注按钮（或已关注）",
    };
  }

  const beforeText = (button.textContent ?? "").replace(/\s+/g, "");
  humanClick(button);
  await sleep(randDelay(800, 1200));

  const afterText = (button.textContent ?? "").replace(/\s+/g, "");
  const followed = afterText.includes("已关注") || afterText.includes("互相关注") || afterText !== beforeText;

  return {
    ok: followed,
    clicked: true,
    before_text: beforeText,
    after_text: afterText,
    url: location.href,
    message: followed ? "已点击关注按钮" : "已点击关注，但状态未变化",
  };
}
