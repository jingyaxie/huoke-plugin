import { findSearchInputMatch, humanClick, randDelay, sleep } from "./search-input";
import {
  clearSearchApiCache,
  enableSearchNetworkHook,
  type SearchApiItem,
} from "./search-api";

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
  return /\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(url);
}

export function buildSearchResultPayload(
  items: Array<{ aweme_id?: string | null; index?: number } & Record<string, unknown>>,
  captureMethod: "api" | "dom" | "none",
) {
  return {
    count: items.length,
    items,
    results: items,
    capture_method: captureMethod,
    search_aweme_ids: items
      .map((item) => item.aweme_id)
      .filter((id): id is string => typeof id === "string" && id.length > 0),
  };
}

/** 步骤 7 前置：清空缓存并开启 search API hook */
export async function prepareSearchCapture() {
  await clearSearchApiCache();
  enableSearchNetworkHook();
  await sleep(150);
  return { ok: true, message: "search hook ready" };
}

/** 步骤 7 提交：仅点击搜索，不在 content 内等待接口（避免跳转打断） */
export async function submitSearchClick() {
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
      on_search_page: false,
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

  return {
    ok: isSearchResultsPage(location.href),
    method: button ? "click_button" : "enter_key",
    selector: button ? SEARCH_BTN_SELECTORS[0] : inputMatch?.selector ?? "",
    url: location.href,
    on_search_page: isSearchResultsPage(location.href),
    message: isSearchResultsPage(location.href) ? "已触发搜索并进入搜索结果页" : "已点击搜索，等待接口返回",
  };
}
