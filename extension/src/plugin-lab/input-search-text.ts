import {
  activateSearchInput,
  detectPlatformFromUrl,
  findSearchInputMatch,
  sleep,
  typeIntoSearchInput,
  waitForSearchInput,
} from "./search-input";
import { findSearchBox } from "./find-search-box";

export interface InputSearchTextPayload {
  platform?: string;
  search_text?: string;
  keyword?: string;
  char_delay_ms?: { min: number; max: number };
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
  if (current === text) {
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

  const typedChars = await typeIntoSearchInput(input, text, payload.char_delay_ms);
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
    method: "char_by_char",
    url: location.href,
    message: `已逐字输入搜索文本（${typedChars.length} 字）`,
  };
}
