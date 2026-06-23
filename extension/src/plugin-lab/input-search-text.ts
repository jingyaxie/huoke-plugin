import {
  activateSearchInput,
  detectPlatformFromUrl,
  findSearchInputMatch,
  fillSearchInputFast,
  sleep,
  typeIntoSearchInput,
  waitForSearchInput,
} from "./search-input";
import { findSearchBox } from "./find-search-box";
import { isSearchResultsPage } from "./search-results-dom";

function normalizeKeyword(raw: string): string {
  return raw.replace(/\s+/g, " ").trim();
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

export interface InputSearchTextPayload {
  platform?: string;
  search_text?: string;
  keyword?: string;
  char_delay_ms?: { min: number; max: number };
  /** 为 true 时逐字慢速输入；默认 false 使用快速一次性填入 */
  simulate_human?: boolean;
  focus_first?: boolean;
}

export async function inputSearchText(payload: InputSearchTextPayload = {}) {
  const text = String(payload.search_text ?? payload.keyword ?? "").trim();
  if (!text) {
    throw new Error("input_search_text: missing search_text");
  }

  const platform =
    payload.platform && payload.platform !== "unknown"
      ? (payload.platform as ReturnType<typeof detectPlatformFromUrl>)
      : detectPlatformFromUrl();

  let match = (await waitForSearchInput(platform, 12, 500)) ?? findSearchInputMatch(platform);
  if (!match) {
    const probe = await findSearchBox({ platform });
    if (!probe.found) {
      throw new Error(`search input not found on ${platform} page`);
    }
    match = findSearchInputMatch(platform);
  }
  if (!match) {
    throw new Error(`search input not found on ${platform} page`);
  }

  const input = match.input;

  if (payload.focus_first !== false) {
    await activateSearchInput(input);
  }

  const current = (input.value ?? "").trim();
  const urlKeyword = extractSearchKeywordFromUrl();
  const staleSearchPage =
    isSearchResultsPage() && Boolean(urlKeyword) && normalizeKeyword(text) !== urlKeyword;
  if (current === text && !staleSearchPage) {
    return {
      ok: true,
      typed: false,
      skipped: true,
      platform,
      selector: match.selector,
      keyword: text,
      chars: text.length,
      value: current,
      method: "already_filled",
      url: location.href,
      message: "搜索框已是目标文本，跳过输入",
    };
  }

  let typedChars: string[];
  let method: string;
  if (payload.simulate_human) {
    typedChars = await typeIntoSearchInput(input, text, payload.char_delay_ms);
    method = "char_by_char";
  } else {
    typedChars = await fillSearchInputFast(input, text);
    method = "fast_fill";
  }

  let finalValue = (input.value ?? "").trim();
  if (finalValue !== text) {
    // React 受控输入偶发丢字，用一次性赋值兜底
    const proto =
      input instanceof HTMLTextAreaElement
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(input, text);
    else input.value = text;
    input.dispatchEvent(new InputEvent("input", { bubbles: true, cancelable: true, data: text }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await sleep(120);
    finalValue = (input.value ?? "").trim();
  }
  if (finalValue !== text) {
    throw new Error(`input_search_text: value mismatch "${finalValue}" != "${text}"`);
  }

  return {
    ok: true,
    typed: true,
    skipped: false,
    platform,
    selector: match.selector,
    keyword: text,
    chars: typedChars.length,
    value: finalValue,
    method,
    url: location.href,
    message:
      method === "char_by_char"
        ? `已逐字输入搜索文本（${typedChars.length} 字）`
        : `已快速填入搜索文本（${typedChars.length} 字）`,
  };
}
