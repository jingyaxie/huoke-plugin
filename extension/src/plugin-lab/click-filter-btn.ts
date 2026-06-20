import { findFilterPanel, isFilterPanelOpen, waitForFilterPanel } from "./filter-overlay";
import { humanClick, randDelay, sleep } from "./search-input";

/** 抖音筛选按钮（用户确认 DOM） */
const FILTER_BTN_SELECTOR = "span.P1BREWal";
const FILTER_BTN_FALLBACK = "span.QfeM8ow3";

function pickFilterButton(): HTMLElement | null {
  return (
    (document.querySelector(FILTER_BTN_SELECTOR) as HTMLElement | null) ??
    (document.querySelector(FILTER_BTN_FALLBACK) as HTMLElement | null)
  );
}

function hoverFilterButton(element: HTMLElement) {
  const rect = element.getBoundingClientRect();
  const base: MouseEventInit = {
    bubbles: true,
    cancelable: true,
    view: window,
    clientX: rect.left + rect.width / 2,
    clientY: rect.top + rect.height / 2,
  };
  element.dispatchEvent(new MouseEvent("mouseover", base));
  element.dispatchEvent(new MouseEvent("mouseenter", { ...base, bubbles: false }));
  element.dispatchEvent(new MouseEvent("mousemove", base));
}

/**
 * 打开筛选浮层 — 对齐 Python `_open_search_filter_panel`：
 * 已打开则跳过；先 hover 再 click，避免重复触发导致开关切换。
 */
export async function clickFilterButton() {
  const element = pickFilterButton();
  if (!element) {
    return {
      ok: false,
      clicked: false,
      selector: FILTER_BTN_SELECTOR,
      url: location.href,
      message: "未找到筛选按钮 span.P1BREWal",
    };
  }

  const rect = element.getBoundingClientRect();
  const baseInfo = {
    selector: FILTER_BTN_SELECTOR,
    class_name: element.className,
    text: (element.textContent ?? "").replace(/\s+/g, "").trim(),
    rect: {
      top: Math.round(rect.top),
      left: Math.round(rect.left),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    },
    url: location.href,
  };

  if (isFilterPanelOpen()) {
    return {
      ok: true,
      clicked: false,
      already_open: true,
      open_method: "already_open",
      ...baseInfo,
      message: "筛选浮层已打开",
    };
  }

  hoverFilterButton(element);
  await sleep(randDelay(900, 1400));

  if (isFilterPanelOpen()) {
    return {
      ok: true,
      clicked: false,
      already_open: true,
      open_method: "hover",
      ...baseInfo,
      message: "hover 后筛选浮层已打开",
    };
  }

  humanClick(element);
  await waitForFilterPanel(1600);

  const opened = isFilterPanelOpen();
  return {
    ok: opened,
    clicked: true,
    already_open: false,
    open_method: opened ? "click" : "click_failed",
    ...baseInfo,
    message: opened ? "已点击筛选按钮并打开浮层" : "已点击筛选按钮，但浮层未检测到",
  };
}

export function findFilterButton() {
  const element = pickFilterButton();
  if (!element) return null;
  return { element, selector: FILTER_BTN_SELECTOR, matchMethod: "selector" };
}
