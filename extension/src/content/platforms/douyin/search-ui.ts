import { buildSearchUrl, detectPageKind, sleep } from "./search";
import { openSearchVideo } from "./open-search";

const JINGXUAN_HOME = "https://www.douyin.com/jingxuan";
const CHAR_DELAY_MS = { min: 850, max: 1100 };

function randDelay(min: number, max: number) {
  return min + Math.floor(Math.random() * (max - min + 1));
}

function clickElement(el: HTMLElement) {
  el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
  if (typeof el.click === "function") {
    el.click();
    return;
  }
  el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
}

function publishTimeLabel(days?: number): string | null {
  const d = Number(days ?? 0);
  if (!d || d <= 0) return null;
  if (d <= 1) return "一天内";
  if (d <= 7) return "一周内";
  if (d <= 180) return "半年内";
  return null;
}

function findSearchInput(): HTMLInputElement | null {
  const inputs = Array.from(document.querySelectorAll("input")) as HTMLInputElement[];
  return (
    inputs.find((node) => {
      const ph = node.getAttribute("placeholder") ?? "";
      if (!ph.includes("搜索")) return false;
      const rect = node.getBoundingClientRect();
      return rect.width > 80 && rect.height > 10 && rect.top >= 0;
    }) ?? null
  );
}

async function activateSearchInput(input: HTMLInputElement) {
  input.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
  input.focus();
  clickElement(input);
  await sleep(randDelay(450, 950));
}

async function readSearchInputValue(): Promise<string> {
  const input = findSearchInput();
  return (input?.value ?? "").trim();
}

async function clearSearchInput(input: HTMLInputElement) {
  input.focus();
  input.value = "";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await sleep(randDelay(150, 350));
}

export async function typeSearchKeyword(keyword: string, charDelayMs?: { min: number; max: number }) {
  const text = String(keyword ?? "").trim();
  if (!text) throw new Error("douyin.search.type: missing keyword");

  let input = findSearchInput();
  if (!input) {
    if (!location.href.includes("/jingxuan")) {
      location.href = JINGXUAN_HOME;
      await sleep(2500);
    }
    for (let i = 0; i < 10; i += 1) {
      input = findSearchInput();
      if (input) break;
      await sleep(800);
    }
  }
  if (!input) throw new Error("douyin.search.type: search input not found");

  await activateSearchInput(input);
  if ((await readSearchInputValue()) === text) {
    return { typed: true, keyword: text, skipped: true, method: "already_filled" };
  }

  await clearSearchInput(input);
  const delay = charDelayMs ?? CHAR_DELAY_MS;
  for (const ch of text) {
    input.value += ch;
    input.dispatchEvent(
      new InputEvent("input", { bubbles: true, data: ch, inputType: "insertText" }),
    );
    await sleep(randDelay(delay.min, delay.max));
  }
  input.dispatchEvent(new Event("change", { bubbles: true }));

  const finalValue = (input.value ?? "").trim();
  if (finalValue !== text) {
    throw new Error(`douyin.search.type: value mismatch "${finalValue}" != "${text}"`);
  }
  return { typed: true, keyword: text, chars: text.length, method: "char_by_char" };
}

function onSearchResultsUrl(url = location.href): boolean {
  return /\/search\//i.test(url) || /\/jingxuan\/search\//i.test(url);
}

async function waitSearchResults(rounds = 12): Promise<boolean> {
  for (let i = 0; i < rounds; i += 1) {
    if (onSearchResultsUrl() && hasSearchResults()) return true;
    await sleep(i < 2 ? 600 : 900);
    if (i >= 2) window.scrollBy({ top: 500, behavior: "smooth" });
  }
  return onSearchResultsUrl() && hasSearchResults();
}

function hasSearchResults(): boolean {
  const cards = document.querySelectorAll(
    '[data-e2e="search-card-video"], [class*="discover-video-card"], a[href*="/video/"]',
  );
  return cards.length > 0;
}

export async function submitSearch(keyword?: string) {
  const kw = String(keyword ?? "").trim();
  const input = findSearchInput();
  if (kw && input && (input.value ?? "").trim() !== kw) {
    await typeSearchKeyword(kw);
  }

  if (input) {
    input.focus();
    await sleep(120);
  }

  const btn =
    (document.querySelector('[data-e2e="searchbar-button"]') as HTMLElement | null) ??
    Array.from(document.querySelectorAll("button, span, div")).find(
      (n) => (n.textContent ?? "").trim() === "搜索",
    ) ??
    null;

  if (btn) {
    clickElement(btn as HTMLElement);
  } else {
    input?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }),
    );
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }),
    );
  }

  await sleep(500);
  const ok = await waitSearchResults(14);
  return {
    submitted: true,
    keyword: kw || (await readSearchInputValue()),
    navigated: ok,
    url: location.href,
    pageKind: detectPageKind(location.href),
  };
}

const FILTER_MARKERS = ["发布时间", "排序依据", "搜索范围", "内容形式"];

function isFilterPanelOpen(): boolean {
  const blocks = Array.from(document.querySelectorAll("div, section, aside, ul"));
  for (const el of blocks) {
    const r = el.getBoundingClientRect();
    if (r.height < 72 || r.width < 160) continue;
    if (r.top < 72 || r.top > window.innerHeight * 0.72) continue;
    const text = (el as HTMLElement).innerText?.slice(0, 600) ?? "";
    if (!FILTER_MARKERS.some((m) => text.includes(m))) continue;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    if (Number(style.opacity || 1) < 0.05) continue;
    return true;
  }
  return false;
}

function filterButtonText(el: Element): string {
  return (el.textContent ?? "").replace(/\s+/g, "").trim();
}

function isFilterButtonCandidate(el: Element): boolean {
  const text = filterButtonText(el);
  if (!text.startsWith("筛选")) return false;
  const r = el.getBoundingClientRect();
  return (
    r.width >= 20 &&
    r.width <= 140 &&
    r.height >= 14 &&
    r.height <= 56 &&
    r.top >= 48 &&
    r.top <= 220 &&
    r.left > 40
  );
}

function findFilterButton(): HTMLElement | null {
  const byClass = document.querySelector("span.QfeM8ow3") as HTMLElement | null;
  if (byClass && isFilterButtonCandidate(byClass)) return byClass;

  const withArrow = Array.from(document.querySelectorAll("span")).find((span) => {
    if (!filterButtonText(span).startsWith("筛选")) return false;
    return span.querySelector("svg.arrow, svg") !== null;
  }) as HTMLElement | undefined;
  if (withArrow && isFilterButtonCandidate(withArrow)) return withArrow;

  const nodes = Array.from(document.querySelectorAll("span, div, button, a"));
  const candidates = nodes.filter(isFilterButtonCandidate);
  candidates.sort((a, b) => {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    const score = (el: Element) => {
      const r = el.getBoundingClientRect();
      let s = r.width * r.height;
      if (el.tagName === "SPAN" && el.classList.contains("QfeM8ow3")) s += 10_000;
      if (el.querySelector("svg")) s += 1_000;
      if (filterButtonText(el) === "筛选") s += 100;
      return s;
    };
    return score(b) - score(a);
  });
  return (candidates[0] as HTMLElement | undefined) ?? null;
}

async function openFilterPanel(): Promise<string> {
  if (isFilterPanelOpen()) return "already_open";
  const btn = findFilterButton();
  if (!btn) return "failed";
  clickElement(btn);
  await sleep(randDelay(800, 1400));
  if (isFilterPanelOpen()) return "click";
  // 部分页面需 hover 才展开浮层
  btn.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
  btn.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  await sleep(randDelay(1000, 1700));
  if (isFilterPanelOpen()) return "hover";
  clickElement(btn);
  await sleep(randDelay(1200, 2000));
  if (isFilterPanelOpen()) return "click";
  return "failed";
}

async function clickFilterOption(label: string): Promise<boolean> {
  if (!isFilterPanelOpen()) return false;
  await sleep(randDelay(800, 1300));
  const blocks = Array.from(document.querySelectorAll("div, section, aside, ul"));
  let panel: Element | null = null;
  for (const el of blocks) {
    const r = el.getBoundingClientRect();
    if (r.height < 72 || r.width < 160) continue;
    if (r.top < 72 || r.top > window.innerHeight * 0.72) continue;
    const text = (el as HTMLElement).innerText?.slice(0, 600) ?? "";
    if (!FILTER_MARKERS.some((m) => text.includes(m))) continue;
    panel = el;
    break;
  }
  const scope = panel ?? document.body;
  const nodes = Array.from(scope.querySelectorAll("span, div, button, label"));
  const target = nodes.find((n) => (n.textContent ?? "").trim() === label) as HTMLElement | undefined;
  if (!target) return false;
  clickElement(target);
  await sleep(randDelay(1000, 1600));
  return true;
}

async function waitFilterPanelClosed(timeoutMs = 8000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isFilterPanelOpen()) return true;
    await sleep(380);
  }
  return !isFilterPanelOpen();
}

export async function applyPublishTimeFilter(days = 7) {
  if (!onSearchResultsUrl()) {
    throw new Error("douyin.search.filter_time: not on search results page");
  }
  const label = publishTimeLabel(days);
  if (!label) throw new Error("douyin.search.filter_time: invalid days");

  const steps: string[] = [];
  await sleep(randDelay(1000, 1800));

  const openMode = await openFilterPanel();
  steps.push(openMode);
  if (openMode === "failed") {
    return { applied: false, label, steps, reason: "filter_button_not_found" };
  }
  await sleep(randDelay(800, 1300));

  if (!(await clickFilterOption(label))) {
    steps.push("option_miss");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    return { applied: false, label, steps, reason: `option_not_found:${label}` };
  }
  steps.push(`option=${label}`);
  await waitFilterPanelClosed();
  steps.push("panel_closed");

  return { applied: true, label, days, steps, url: location.href };
}

export function listSearchVideos(max = 20) {
  const seen = new Set<string>();
  const items: Array<{ index: number; aweme_id: string; href: string }> = [];
  const links = Array.from(document.querySelectorAll('a[href*="/video/"]')) as HTMLAnchorElement[];
  for (const link of links) {
    const href = link.href ?? "";
    const awemeId = href.match(/\/video\/(\d{8,22})/)?.[1] ?? "";
    if (!awemeId || seen.has(awemeId)) continue;
    seen.add(awemeId);
    items.push({ index: items.length, aweme_id: awemeId, href });
    if (items.length >= max) break;
  }
  return { count: items.length, items, url: location.href };
}

export async function browseSearchVideos(options: {
  max?: number;
  pause_ms?: number;
  search_url?: string;
}) {
  const max = Math.max(1, Math.min(Number(options.max ?? 5), 20));
  const pauseMs = Number(options.pause_ms ?? 2000);
  const searchUrl = String(options.search_url ?? location.href);

  if (detectPageKind(location.href) !== "search") {
    throw new Error("douyin.search.browse_videos: not on search page");
  }

  const opened: Array<{
    index: number;
    aweme_id: string;
    video_url: string;
    method: string;
  }> = [];

  for (let i = 0; i < max; i += 1) {
    const result = await openSearchVideo(i);
    opened.push({
      index: i,
      aweme_id: result.aweme_id,
      video_url: result.video_url || result.url,
      method: result.method,
    });
    await sleep(pauseMs);

    if (detectPageKind(location.href) === "video") {
      history.back();
      await sleep(2000);
      for (let retry = 0; retry < 10; retry += 1) {
        if (detectPageKind(location.href) === "search") break;
        await sleep(600);
      }
      if (detectPageKind(location.href) !== "search") {
        location.href = searchUrl;
        await sleep(2500);
      }
    }
  }

  return { browsed: opened.length, videos: opened, url: location.href };
}

export async function runSearchUiFlow(payload: {
  keyword: string;
  days?: number;
  max_videos?: number;
  char_delay_ms?: { min: number; max: number };
  video_pause_ms?: number;
}) {
  const keyword = String(payload.keyword ?? "").trim();
  if (!keyword) throw new Error("douyin.search.ui_flow: missing keyword");
  const days = Number(payload.days ?? 7);
  const maxVideos = Math.max(1, Math.min(Number(payload.max_videos ?? 3), 20));

  const steps: Record<string, unknown> = {};

  if (!findSearchInput() && !location.href.includes("/jingxuan")) {
    location.href = JINGXUAN_HOME;
    await sleep(2500);
  }
  steps.type = await typeSearchKeyword(keyword, payload.char_delay_ms);
  await sleep(randDelay(300, 600));
  steps.submit = await submitSearch(keyword);
  if (!steps.submit || !(steps.submit as { navigated?: boolean }).navigated) {
    return { ok: false, step: "submit", steps, url: location.href };
  }

  const searchUrl = location.href;
  steps.filter = await applyPublishTimeFilter(days);
  await sleep(randDelay(1500, 2500));
  steps.list = listSearchVideos(maxVideos + 5);
  steps.browse = await browseSearchVideos({
    max: maxVideos,
    pause_ms: payload.video_pause_ms ?? 2000,
    search_url: searchUrl,
  });

  return {
    ok: true,
    keyword,
    days,
    max_videos: maxVideos,
    steps,
    url: location.href,
    pageKind: detectPageKind(location.href),
  };
}
