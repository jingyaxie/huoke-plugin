import { findSearchInputMatch, humanClick, randDelay, sleep } from "./search-input";
import { clearStoredSearchResultsUrl, rememberSearchResultsUrl } from "./search-feed-open";
import { collectSearchResultCards, isSearchResultsPage } from "./search-results-dom";
import {
  clearSearchApiCache,
  enableSearchNetworkHook,
  getCachedSearchApiResultsSync,
} from "./search-api";
import { ensureSearchMultiColumnLayout } from "./search-layout";

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

function normalizeKeyword(raw: string): string {
  return raw.replace(/\s+/g, " ").trim();
}

function searchResultsReady(): boolean {
  if (getCachedSearchApiResultsSync(120_000)?.length) return true;
  return collectSearchResultCards().length > 0;
}

function dismissSearchSuggestions(input?: HTMLInputElement | HTMLTextAreaElement | null): void {
  if (input) {
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
    );
    input.blur();
  }
}

function extractSearchKeywordFromUrl(url = location.href): string {
  try {
    const parsed = new URL(url);
    const pathMatch = decodeURIComponent(parsed.pathname).match(/\/search\/([^/?#]+)/i);
    if (pathMatch?.[1]) return normalizeKeyword(pathMatch[1]);
    for (const key of ["keyword", "q", "search_key", "searchKey", "search_keyword"]) {
      const value = parsed.searchParams.get(key);
      if (value?.trim()) return normalizeKeyword(decodeURIComponent(value));
    }
  } catch {
    // ignore malformed URL
  }
  return "";
}

export function buildSearchResultPayload(
  items: ReadonlyArray<{ aweme_id?: string | null; index?: number }>,
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
  clearStoredSearchResultsUrl();
  await clearSearchApiCache();
  enableSearchNetworkHook();
  await sleep(150);
  return { ok: true, message: "search hook ready" };
}

export interface SubmitSearchClickPayload {
  keyword?: string;
  search_text?: string;
}

/** 步骤 7 提交：点击搜索；若已在搜索结果页且关键词未变则跳过 */
export async function submitSearchClick(payload: SubmitSearchClickPayload = {}) {
  const beforeUrl = location.href;
  const inputMatch = findSearchInputMatch("douyin");
  const button = findSearchButton();
  const inputValue = normalizeKeyword(inputMatch?.input?.value ?? "");
  const expectedKeyword = normalizeKeyword(String(payload.search_text ?? payload.keyword ?? inputValue));
  const urlKeyword = extractSearchKeywordFromUrl(beforeUrl);

  const sameKeywordAsUrl =
    Boolean(expectedKeyword) &&
    expectedKeyword === urlKeyword &&
    inputValue === expectedKeyword;

  if (isSearchResultsPage(location.href) && sameKeywordAsUrl && searchResultsReady()) {
    rememberSearchResultsUrl(location.href);
    const layout = await ensureSearchMultiColumnLayout();
    return {
      ok: true,
      method: "skip_already_on_results",
      selector: inputMatch?.selector ?? "",
      url: location.href,
      on_search_page: true,
      keyword: inputValue || expectedKeyword || undefined,
      message: layout.message
        ? `已在搜索结果页且关键词一致；${layout.message}`
        : "已在搜索结果页且关键词一致，跳过重复搜索",
    };
  }

  dismissSearchSuggestions(inputMatch?.input ?? null);
  await sleep(randDelay(120, 220));

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

  if (isSearchResultsPage(location.href)) {
    rememberSearchResultsUrl(location.href);
  }

  let layoutMessage = "";
  if (isSearchResultsPage(location.href)) {
    const layout = await ensureSearchMultiColumnLayout();
    layoutMessage = layout.message;
  }

  return {
    ok: isSearchResultsPage(location.href),
    method: button ? "click_button" : "enter_key",
    selector: button ? SEARCH_BTN_SELECTORS[0] : inputMatch?.selector ?? "",
    url: location.href,
    on_search_page: isSearchResultsPage(location.href),
    message: isSearchResultsPage(location.href)
      ? layoutMessage
        ? `已触发搜索；${layoutMessage}`
        : "已触发搜索并进入搜索结果页"
      : "已点击搜索，等待接口返回",
  };
}

/** Step 7：仅触发搜索；结果采集见 Step 8 fetch_search_results（hook + DOM，无 CDP） */
export async function clickSearchButton(payload: SubmitSearchClickPayload = {}) {
  await prepareSearchCapture();
  const clickResult = await submitSearchClick(payload);
  return {
    ...clickResult,
    ok: Boolean(clickResult.ok),
    on_search_page: isSearchResultsPage(),
    message: clickResult.message ?? (clickResult.ok ? "已触发搜索" : "未能触发搜索"),
  };
}
