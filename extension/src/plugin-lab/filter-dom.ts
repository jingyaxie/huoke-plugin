import { findFilterButton } from "./click-filter-btn";
import {
  findFilterOverlayOption,
  findFilterPanel,
  isFilterPanelOpen,
  listFilterOverlayOptions,
} from "./filter-overlay";

export interface FilterDomRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

function serializeRect(rect: DOMRect): FilterDomRect {
  return {
    top: Math.round(rect.top),
    left: Math.round(rect.left),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
}

/** 供 background 查询：筛选按钮位置、浮层状态、可见选项 */
export function probeFilterDom() {
  const buttonMatch = findFilterButton();
  const button = buttonMatch?.element ?? null;
  const panel = findFilterPanel();

  return {
    ok: true,
    url: location.href,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
    },
    button: button
      ? {
          selector: buttonMatch?.selector ?? "",
          text: (button.textContent ?? "").replace(/\s+/g, "").trim(),
          rect: serializeRect(button.getBoundingClientRect()),
        }
      : null,
    panel_open: isFilterPanelOpen(),
    panel_tag: panel?.tagName.toLowerCase() ?? null,
    options: listFilterOverlayOptions(),
  };
}

/** 供 background 查询：选项中心坐标 */
export function findFilterOptionPoint(label: string) {
  const target = String(label ?? "").trim();
  if (!target) {
    return { ok: false, found: false, message: "missing label" };
  }

  const match = findFilterOverlayOption(target);
  if (!match) {
    return {
      ok: false,
      found: false,
      label: target,
      panel_open: isFilterPanelOpen(),
      options: listFilterOverlayOptions(),
      message: `未找到选项「${target}」`,
    };
  }

  const rect = match.element.getBoundingClientRect();
  return {
    ok: true,
    found: true,
    label: target,
    match_method: match.matchMethod,
    rect: serializeRect(rect),
    center: {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    },
    panel_open: isFilterPanelOpen(),
    options: listFilterOverlayOptions(),
  };
}
