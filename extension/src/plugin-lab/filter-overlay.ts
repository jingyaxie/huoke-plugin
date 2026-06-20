import { sleep } from "./search-input";

/** 与 Python `_FILTER_PANEL_MARKERS` 对齐 */
export const FILTER_PANEL_MARKERS = [
  "发布时间",
  "排序依据",
  "搜索范围",
  "视频时长",
  "内容形式",
] as const;

/** 抖音筛选浮层常见选项（便于测试页选择） */
export const KNOWN_FILTER_OPTIONS = [
  "综合排序",
  "最新发布",
  "最多点赞",
  "不限",
  "一天内",
  "一周内",
  "半年内",
  "1分钟以下",
  "1-5分钟",
  "5分钟以上",
  "关注的人",
  "最近看过",
  "还未看过",
] as const;

const MAX_PANEL_BLOCKS = 100;
const MAX_OPTION_NODES = 160;

export function normalizeText(text: string): string {
  return text.replace(/\s+/g, "").trim();
}

export function publishTimeLabelFromDays(days?: number | null): string | null {
  const value = Number(days ?? 0);
  if (!value || value <= 0) return null;
  if (value <= 1) return "一天内";
  if (value <= 7) return "一周内";
  if (value <= 180) return "半年内";
  return null;
}

function countMarkerHits(text: string): number {
  return FILTER_PANEL_MARKERS.filter((marker) => text.includes(marker)).length;
}

function nodeText(node: HTMLElement): string {
  return (node.textContent ?? "").replace(/\s+/g, " ").trim();
}

function isClickableSize(node: HTMLElement): boolean {
  const rect = node.getBoundingClientRect();
  return rect.width >= 8 && rect.height >= 8 && rect.bottom > 0 && rect.right > 0;
}

/**
 * 找筛选浮层根节点 — 对齐 Python `_FILTER_PANEL_OPEN_JS`。
 * 用索引遍历 NodeList，禁止 Array.from 全量 materialize。
 */
export function findFilterPanel(): HTMLElement | null {
  const openDialog = document.querySelector("dialog[open]") as HTMLDialogElement | null;
  if (openDialog) return openDialog;

  for (const marker of FILTER_PANEL_MARKERS) {
    const hit = findVisibleExactText(marker);
    if (!hit) continue;

    let node: HTMLElement | null = hit;
    for (let depth = 0; depth < 10 && node; depth += 1) {
      const rect = node.getBoundingClientRect();
      const text = (node.textContent ?? "").slice(0, 800);
      if (rect.height >= 72 && rect.width >= 160 && countMarkerHits(text) >= 2) {
        return node;
      }
      node = node.parentElement;
    }
  }

  const blocks = document.querySelectorAll("div, section, aside, ul");
  let checked = 0;

  for (let i = 0; i < blocks.length; i += 1) {
    const el = blocks[i] as HTMLElement;
    const rect = el.getBoundingClientRect();
    if (rect.height < 72 || rect.width < 160) continue;
    if (rect.top < 72 || rect.top > window.innerHeight * 0.72) continue;

    checked += 1;
    if (checked > MAX_PANEL_BLOCKS) break;

    const text = (el.textContent ?? "").slice(0, 600);
    if (countMarkerHits(text) < 1) continue;

    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    if (Number(style.opacity || 1) < 0.05) continue;
    return el;
  }

  return null;
}

function findVisibleExactText(text: string): HTMLElement | null {
  const xpath = `//*[normalize-space(text())="${text.replace(/"/g, '\\"')}"]`;
  const snap = document.evaluate(
    xpath,
    document,
    null,
    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
    null,
  );

  for (let i = 0; i < snap.snapshotLength && i < 20; i += 1) {
    const node = snap.snapshotItem(i) as HTMLElement | null;
    if (!node) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    if (rect.top < 40 || rect.top > window.innerHeight * 0.85) continue;
    return node;
  }

  return null;
}

export function isFilterPanelOpen(): boolean {
  return findFilterPanel() !== null;
}

/** @deprecated 使用 findFilterPanel */
export function findFilterOverlayRoot(): HTMLElement | null {
  return findFilterPanel();
}

function collectOptionNodes(root: HTMLElement): HTMLElement[] {
  const nodes = root.querySelectorAll("span, div, button, label, li, a");
  const out: HTMLElement[] = [];
  for (let i = 0; i < nodes.length && out.length < MAX_OPTION_NODES; i += 1) {
    const node = nodes[i] as HTMLElement;
    if (!isClickableSize(node)) continue;
    out.push(node);
  }
  return out;
}

/** 收集浮层内可见选项文案（有上限） */
export function listFilterOverlayOptions(): string[] {
  const root = findFilterPanel();
  if (!root) return [];

  const seen = new Set<string>();
  const options: string[] = [];

  for (const node of collectOptionNodes(root)) {
    const text = nodeText(node);
    if (!text || text.length > 20) continue;
    if (FILTER_PANEL_MARKERS.some((marker) => text.startsWith(marker))) continue;
    if (seen.has(text)) continue;
    seen.add(text);
    options.push(text);
  }

  return options.sort((a, b) => a.localeCompare(b, "zh-CN"));
}

/** 浮层未识别时的兜底：在上半屏按精确文案找可点击项 */
export function findFilterOptionFallback(label: string): {
  element: HTMLElement;
  matchMethod: string;
} | null {
  const target = String(label ?? "").trim();
  if (!target) return null;

  const targetNorm = normalizeText(target);
  const nodes = document.querySelectorAll("span, div, button, label, li, a");
  let best: HTMLElement | null = null;
  let bestLen = Infinity;
  let checked = 0;

  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i] as HTMLElement;
    const rect = node.getBoundingClientRect();
    if (rect.top < 48 || rect.top > window.innerHeight * 0.58) continue;
    if (!isClickableSize(node)) continue;

    checked += 1;
    if (checked > 240) break;

    const text = nodeText(node);
    if (text !== target && normalizeText(text) !== targetNorm) continue;
    if (text.length >= bestLen) continue;
    best = node;
    bestLen = text.length;
  }

  if (!best) return null;
  return { element: best, matchMethod: "fallback_exact_text_top" };
}

/** 在浮层内按文案精确匹配可点击项 — 对齐 Python `_click_publish_time_option` */
export function findFilterOverlayOption(label: string): {
  element: HTMLElement;
  matchMethod: string;
} | null {
  const target = String(label ?? "").trim();
  if (!target) return null;

  const root = findFilterPanel();
  if (root) {
    const targetNorm = normalizeText(target);
    let best: HTMLElement | null = null;
    let bestLen = Infinity;

    for (const node of collectOptionNodes(root)) {
      const text = nodeText(node);
      if (text !== target && normalizeText(text) !== targetNorm) continue;
      if (text.length >= bestLen) continue;
      best = node;
      bestLen = text.length;
    }

    if (best) {
      return { element: best, matchMethod: "exact_text_in_panel" };
    }
  }

  return findFilterOptionFallback(label);
}

export async function waitForFilterPanel(timeoutMs = 1400): Promise<HTMLElement | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const root = findFilterPanel();
    if (root) return root;
    await sleep(120);
  }
  return null;
}

/** @deprecated 使用 waitForFilterPanel */
export async function waitForFilterOverlayRoot(timeoutMs = 1400): Promise<HTMLElement | null> {
  return waitForFilterPanel(timeoutMs);
}
