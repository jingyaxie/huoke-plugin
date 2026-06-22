import { humanClick, sleep } from "./search-input";
import { collectSearchResultCards, isFeedOverlayOpen, isSearchResultsPage } from "./search-results-dom";

type SearchLayoutMode = "multi" | "single" | "unknown";

function normalizeLabel(text: string): string {
  return text.replace(/\s+/g, "").trim();
}

function nodeLabel(node: HTMLElement): string {
  return normalizeLabel(node.innerText || node.textContent || "");
}

function findLayoutToggle(label: "多列" | "单列"): HTMLElement | null {
  const nodes = document.querySelectorAll("span, div, button, label, li, p, a");
  let best: HTMLElement | null = null;
  let bestArea = Number.POSITIVE_INFINITY;

  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i];
    if (!(node instanceof HTMLElement)) continue;
    if (nodeLabel(node) !== label) continue;

    const rect = node.getBoundingClientRect();
    if (rect.width < 14 || rect.height < 10 || rect.top > 520 || rect.top < 16) continue;

    const area = rect.width * rect.height;
    if (area < bestArea) {
      best = node;
      bestArea = area;
    }
  }
  return best;
}

function clickTarget(el: HTMLElement): HTMLElement {
  let node: HTMLElement | null = el;
  for (let depth = 0; depth < 6 && node; depth += 1) {
    const tag = node.tagName.toLowerCase();
    if (tag === "button" || node.getAttribute("role") === "tab" || node.getAttribute("role") === "button") {
      return node;
    }
    const style = getComputedStyle(node);
    if (style.cursor === "pointer") return node;
    node = node.parentElement;
  }
  return el;
}

function toggleLooksSelected(el: HTMLElement): boolean {
  let node: HTMLElement | null = el;
  for (let depth = 0; depth < 5 && node; depth += 1) {
    const cls = String(node.className ?? "");
    if (/active|selected|current|checked|highlight/i.test(cls)) return true;
    if (node.getAttribute("aria-selected") === "true") return true;
    if (node.getAttribute("aria-checked") === "true") return true;
    const bg = getComputedStyle(node).backgroundColor;
    const match = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (match) {
      const r = Number(match[1]);
      const g = Number(match[2]);
      const b = Number(match[3]);
      if (r > 235 && g > 235 && b > 235) return true;
    }
    node = node.parentElement;
  }
  return false;
}

async function dismissFeedOverlay(): Promise<void> {
  for (let i = 0; i < 3; i += 1) {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
    );
    await sleep(220);
  }
}

export function detectSearchLayoutMode(): SearchLayoutMode {
  if (!isSearchResultsPage()) return "unknown";
  const multi = findLayoutToggle("多列");
  const single = findLayoutToggle("单列");
  if (!multi && !single) {
    return isFeedOverlayOpen() ? "single" : "multi";
  }
  const multiSelected = multi ? toggleLooksSelected(multi) : false;
  const singleSelected = single ? toggleLooksSelected(single) : false;
  if (singleSelected && !multiSelected) return "single";
  if (multiSelected && !singleSelected) return "multi";
  if (single && !multi) return "single";
  if (multi && !single) return "multi";
  return isFeedOverlayOpen() ? "single" : "unknown";
}

async function waitForMultiColumnGrid(maxMs = 6000): Promise<boolean> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    const mode = detectSearchLayoutMode();
    const cards = collectSearchResultCards().length;
    if (mode !== "single" && !isFeedOverlayOpen() && cards > 0) return true;
    if (mode === "multi" && cards > 0) return true;
    if (mode === "multi" && !isFeedOverlayOpen()) return true;
    await sleep(350);
  }
  return detectSearchLayoutMode() !== "single" && !isFeedOverlayOpen();
}

/** 抖音搜索页：单列会直接进入 Feed 浮层，自动化需切到多列网格 */
export async function ensureSearchMultiColumnLayout(): Promise<{
  ok: boolean;
  switched: boolean;
  layout: SearchLayoutMode;
  message: string;
}> {
  if (!isSearchResultsPage()) {
    return { ok: false, switched: false, layout: "unknown", message: "不在搜索结果页" };
  }

  const before = detectSearchLayoutMode();
  if (before !== "single" && !isFeedOverlayOpen() && collectSearchResultCards().length > 0) {
    return {
      ok: true,
      switched: false,
      layout: before === "unknown" ? "multi" : before,
      message: "已是多列/网格布局",
    };
  }

  if (isFeedOverlayOpen() || before === "single") {
    await dismissFeedOverlay();
    await sleep(400);
  }

  const multiBtn = findLayoutToggle("多列");
  if (!multiBtn) {
    return {
      ok: false,
      switched: false,
      layout: before,
      message: "未找到「多列」切换按钮，请手动切换到多列后重试",
    };
  }

  humanClick(clickTarget(multiBtn));
  await sleep(900);

  if (isFeedOverlayOpen()) {
    await dismissFeedOverlay();
    await sleep(400);
    humanClick(clickTarget(multiBtn));
    await sleep(700);
  }

  const ready = await waitForMultiColumnGrid();
  const after = detectSearchLayoutMode();
  if (ready || (after !== "single" && !isFeedOverlayOpen())) {
    return {
      ok: true,
      switched: true,
      layout: after === "unknown" ? "multi" : after,
      message: "已切换到多列布局",
    };
  }

  return {
    ok: false,
    switched: true,
    layout: after,
    message: "已点击多列，但页面仍为单列/Feed 浮层",
  };
}
