import { findSearchInputMatch, humanClick, randDelay, sleep } from "./search-input";

const SEARCH_BTN_SELECTORS = [
  '[data-e2e="searchbar-button"]',
  'button[data-e2e="searchbar-button"]',
] as const;

function findSearchButton(): HTMLElement | null {
  for (const selector of SEARCH_BTN_SELECTORS) {
    const node = document.querySelector(selector);
    if (node instanceof HTMLElement && node.getBoundingClientRect().width > 8) {
      return node;
    }
  }

  const buttons = document.querySelectorAll("button, span, div");
  for (let i = 0; i < buttons.length && i < 120; i += 1) {
    const node = buttons[i] as HTMLElement;
    const text = (node.textContent ?? "").replace(/\s+/g, "");
    if (text !== "搜索") continue;
    const rect = node.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 14 || rect.top > 220) continue;
    return node;
  }

  return null;
}

function isSearchResultsPage(url = location.href): boolean {
  return /\/search\/|\/jingxuan\/search\//i.test(url);
}

/** 步骤 7：点击搜索按钮或 Enter 提交搜索 */
export async function clickSearchButton() {
  const beforeUrl = location.href;
  const inputMatch = findSearchInputMatch("douyin");
  const button = findSearchButton();

  if (button) {
    humanClick(button);
    await sleep(randDelay(600, 1000));
  } else if (inputMatch?.input) {
    inputMatch.input.focus();
    inputMatch.input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
    );
    inputMatch.input.dispatchEvent(
      new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }),
    );
    await sleep(randDelay(700, 1100));
  } else {
    return {
      ok: false,
      method: "none",
      url: location.href,
      message: "未找到搜索按钮或搜索框",
    };
  }

  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    if (isSearchResultsPage(location.href) && location.href !== beforeUrl) break;
    if (isSearchResultsPage(location.href)) break;
    await sleep(250);
  }

  if (inputMatch?.input) {
    inputMatch.input.blur();
  }

  const ok = isSearchResultsPage(location.href);
  return {
    ok,
    method: button ? "click_button" : "enter_key",
    selector: button ? SEARCH_BTN_SELECTORS[0] : inputMatch?.selector ?? "",
    url: location.href,
    message: ok ? "已触发搜索并进入搜索结果页" : "已点击搜索，但未检测到搜索结果页 URL",
  };
}
