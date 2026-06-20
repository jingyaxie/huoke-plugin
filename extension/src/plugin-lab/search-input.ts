import type { PlatformId } from "../shared/protocol";

/** 抖音顶栏搜索框（用户确认 DOM） */
export const DOUYIN_SEARCH_SELECTORS = [
  'input[data-e2e="searchbar-input"]',
  'div.e87TTjIw input[data-e2e="searchbar-input"]',
  'input.st2xnJtZ[data-e2e="searchbar-input"]',
  'input[placeholder="搜索你感兴趣的内容"]',
] as const;

export function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function randDelay(min: number, max: number) {
  return min + Math.floor(Math.random() * (max - min + 1));
}

export function clickElement(el: HTMLElement) {
  el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
  humanClick(el);
}

export function humanClick(el: HTMLElement) {
  const rect = el.getBoundingClientRect();
  const clientX = rect.left + rect.width / 2;
  const clientY = rect.top + rect.height / 2;
  const base: MouseEventInit = {
    bubbles: true,
    cancelable: true,
    view: window,
    clientX,
    clientY,
  };

  el.dispatchEvent(new PointerEvent("pointerdown", { ...base, pointerId: 1, pointerType: "mouse" }));
  el.dispatchEvent(new MouseEvent("mousedown", base));
  el.dispatchEvent(new PointerEvent("pointerup", { ...base, pointerId: 1, pointerType: "mouse" }));
  el.dispatchEvent(new MouseEvent("mouseup", base));
  el.dispatchEvent(new MouseEvent("click", base));
  if (typeof el.click === "function") {
    el.click();
  }
}

export function detectPlatformFromUrl(url = location.href): PlatformId {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes("douyin.com")) return "douyin";
    if (host.includes("xiaohongshu.com")) return "xiaohongshu";
    if (host.includes("kuaishou.com")) return "kuaishou";
  } catch {
    // ignore
  }
  if (/douyin\.com/i.test(url)) return "douyin";
  if (/xiaohongshu\.com/i.test(url)) return "xiaohongshu";
  if (/kuaishou\.com/i.test(url)) return "kuaishou";
  return "unknown";
}

export type SearchField = HTMLInputElement | HTMLTextAreaElement;

export interface SearchInputMatch {
  input: SearchField;
  selector: string;
  matchMethod: string;
}

export function isVisible(el: Element): boolean {
  const rect = el.getBoundingClientRect();
  if (rect.width < 8 || rect.height < 8) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden") return false;
  if (Number(style.opacity || 1) < 0.05) return false;
  return true;
}

function placeholderMatchesSearch(text: string): boolean {
  const value = text.trim();
  return value.includes("搜索") || /search/i.test(value);
}

function scoreSearchCandidate(el: SearchField): number {
  const rect = el.getBoundingClientRect();
  let score = rect.width * rect.height;
  const placeholder = el.getAttribute("placeholder") ?? "";
  const e2e = el.getAttribute("data-e2e") ?? "";
  if (e2e === "searchbar-input") score += 50_000;
  if (placeholder === "搜索你感兴趣的内容") score += 10_000;
  if (placeholderMatchesSearch(placeholder)) score += 5_000;
  if (el.classList.contains("st2xnJtZ")) score += 3_000;
  if (el.id.includes("search")) score += 2_000;
  if (rect.top >= 0 && rect.top <= 260) score += 1_000;
  return score;
}

function queryFirstVisibleInput(selectors: readonly string[]): SearchInputMatch | null {
  for (const selector of selectors) {
    const node = document.querySelector(selector);
    if (!node) continue;
    const input = (node.matches("input, textarea")
      ? node
      : node.querySelector("input, textarea")) as SearchField | null;
    if (input && isVisible(input)) {
      return { input, selector, matchMethod: `selector:${selector}` };
    }
  }
  return null;
}

function findDouyinSearchInput(): SearchInputMatch | null {
  const matched = queryFirstVisibleInput(DOUYIN_SEARCH_SELECTORS);
  if (matched) return matched;

  const inputs = Array.from(document.querySelectorAll("input, textarea")) as SearchField[];
  const candidates = inputs.filter((node) => {
    const ph = node.getAttribute("placeholder") ?? "";
    const e2e = node.getAttribute("data-e2e") ?? "";
    return (e2e === "searchbar-input" || placeholderMatchesSearch(ph)) && isVisible(node);
  });
  candidates.sort((a, b) => scoreSearchCandidate(b) - scoreSearchCandidate(a));
  const input = candidates[0];
  if (!input) return null;
  return {
    input,
    selector: buildSelector(input),
    matchMethod: "fallback:placeholder_or_e2e",
  };
}

function findXhsSearchInput(): SearchInputMatch | null {
  const matched = queryFirstVisibleInput([
    "#search-input-in-feeds textarea",
    "#search-input-in-feeds input",
    "#search-input textarea",
    "#search-input input",
  ]);
  if (matched) return matched;

  const inputs = Array.from(document.querySelectorAll("input, textarea")) as SearchField[];
  const candidates = inputs.filter((node) => {
    const ph = node.getAttribute("placeholder") ?? "";
    const aria = node.getAttribute("aria-label") ?? "";
    return (placeholderMatchesSearch(ph) || placeholderMatchesSearch(aria)) && isVisible(node);
  });
  candidates.sort((a, b) => scoreSearchCandidate(b) - scoreSearchCandidate(a));
  const input = candidates[0];
  if (!input) return null;
  return { input, selector: buildSelector(input), matchMethod: "fallback:placeholder" };
}

function findKuaishouSearchInput(): SearchInputMatch | null {
  const inputs = Array.from(document.querySelectorAll("input, textarea")) as SearchField[];
  const candidates = inputs.filter((node) => {
    const ph = node.getAttribute("placeholder") ?? "";
    return placeholderMatchesSearch(ph) && isVisible(node);
  });
  candidates.sort((a, b) => scoreSearchCandidate(b) - scoreSearchCandidate(a));
  const input = candidates[0];
  if (!input) return null;
  return { input, selector: buildSelector(input), matchMethod: "fallback:placeholder" };
}

function findGenericSearchInput(): SearchInputMatch | null {
  const inputs = Array.from(document.querySelectorAll("input, textarea")) as SearchField[];
  const candidates = inputs.filter((node) => {
    const ph = node.getAttribute("placeholder") ?? "";
    const aria = node.getAttribute("aria-label") ?? "";
    return (placeholderMatchesSearch(ph) || placeholderMatchesSearch(aria)) && isVisible(node);
  });
  candidates.sort((a, b) => scoreSearchCandidate(b) - scoreSearchCandidate(a));
  const input = candidates[0];
  if (!input) return null;
  return { input, selector: buildSelector(input), matchMethod: "fallback:generic" };
}

export function findSearchInputMatch(platform: PlatformId): SearchInputMatch | null {
  switch (platform) {
    case "douyin":
      return findDouyinSearchInput() ?? findGenericSearchInput();
    case "xiaohongshu":
      return findXhsSearchInput() ?? findGenericSearchInput();
    case "kuaishou":
      return findKuaishouSearchInput() ?? findGenericSearchInput();
    default:
      return findGenericSearchInput();
  }
}

export function findSearchInput(platform: PlatformId): SearchField | null {
  return findSearchInputMatch(platform)?.input ?? null;
}

export function buildSelector(el: Element): string {
  const e2e = el.getAttribute("data-e2e");
  if (e2e) return `input[data-e2e="${e2e}"]`;
  if (el.id) return `#${CSS.escape(el.id)}`;
  const placeholder = el.getAttribute("placeholder");
  if (placeholder) {
    return `${el.tagName.toLowerCase()}[placeholder="${placeholder.replace(/"/g, '\\"')}"]`;
  }
  return el.tagName.toLowerCase();
}

export function describeSearchInput(
  match: SearchInputMatch,
  platform: PlatformId,
) {
  const { input, selector, matchMethod } = match;
  const rect = input.getBoundingClientRect();
  const wrapper = input.closest("div.e87TTjIw") as HTMLElement | null;

  return {
    found: true,
    platform,
    match_method: matchMethod,
    tag: input.tagName.toLowerCase(),
    selector,
    class_name: input.className || "",
    wrapper_class: wrapper?.className ?? "",
    placeholder: input.getAttribute("placeholder") ?? "",
    value: input.value ?? "",
    maxlength: input.getAttribute("maxlength") ?? "",
    type: input.getAttribute("type") ?? "",
    id: input.id || "",
    name: input.getAttribute("name") ?? "",
    data_e2e: input.getAttribute("data-e2e") ?? "",
    rect: {
      top: Math.round(rect.top),
      left: Math.round(rect.left),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    },
    visible: isVisible(input),
    url: location.href,
  };
}

function setNativeInputValue(input: SearchField, value: string) {
  const proto =
    input instanceof HTMLTextAreaElement
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) {
    setter.call(input, value);
  } else {
    input.value = value;
  }
}

function dispatchInputChange(input: SearchField, ch?: string) {
  input.dispatchEvent(
    new InputEvent("input", {
      bubbles: true,
      cancelable: true,
      data: ch ?? null,
      inputType: ch ? "insertText" : "deleteContentBackward",
    }),
  );
}

export async function activateSearchInput(input: SearchField) {
  const wrapper = input.closest("div.e87TTjIw") as HTMLElement | null;
  if (wrapper) {
    clickElement(wrapper);
    await sleep(randDelay(180, 360));
  }

  input.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
  input.focus();
  clickElement(input as HTMLElement);
  await sleep(randDelay(350, 750));
}

export async function clearSearchInput(input: SearchField) {
  input.focus();
  setNativeInputValue(input, "");
  dispatchInputChange(input);
  await sleep(randDelay(120, 280));
}

export async function typeIntoSearchInput(
  input: SearchField,
  text: string,
  charDelayMs?: { min: number; max: number },
) {
  const delay = charDelayMs ?? { min: 850, max: 1100 };
  await clearSearchInput(input);

  const typedChars: string[] = [];
  let current = "";

  for (const ch of text) {
    current += ch;
    setNativeInputValue(input, current);
    dispatchInputChange(input, ch);
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: ch, bubbles: true, cancelable: true }),
    );
    input.dispatchEvent(
      new KeyboardEvent("keyup", { key: ch, bubbles: true, cancelable: true }),
    );
    typedChars.push(ch);
    await sleep(randDelay(delay.min, delay.max));
  }

  input.dispatchEvent(new Event("change", { bubbles: true }));
  return typedChars;
}

export async function waitForSearchInput(
  platform: PlatformId,
  rounds = 12,
  intervalMs = 600,
): Promise<SearchInputMatch | null> {
  for (let i = 0; i < rounds; i += 1) {
    const match = findSearchInputMatch(platform);
    if (match) return match;
    await sleep(intervalMs);
  }
  return null;
}
