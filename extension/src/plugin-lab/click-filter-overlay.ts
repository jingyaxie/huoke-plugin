import { clickFilterButton } from "./click-filter-btn";
import {
  findFilterOverlayOption,
  findFilterPanel,
  listFilterOverlayOptions,
  publishTimeLabelFromDays,
  waitForFilterPanel,
} from "./filter-overlay";
import { sleep } from "./search-input";

export interface ClickFilterOverlayPayload {
  option_label?: string;
  option_labels?: string[];
  filter_label?: string;
  days?: number;
  open_if_closed?: boolean;
}

function parseLabels(payload: ClickFilterOverlayPayload): string[] {
  if (Array.isArray(payload.option_labels) && payload.option_labels.length > 0) {
    return payload.option_labels.map((item) => String(item).trim()).filter(Boolean);
  }

  const single = String(payload.option_label ?? payload.filter_label ?? "").trim();
  if (single.includes(",")) {
    return single.split(",").map((item) => item.trim()).filter(Boolean);
  }
  if (single) return [single];

  const fromDays = publishTimeLabelFromDays(payload.days);
  return fromDays ? [fromDays] : [];
}

/** 在筛选浮层内按文案点击选项（可多个） */
export async function clickFilterOverlay(payload: ClickFilterOverlayPayload = {}) {
  const labels = parseLabels(payload);
  if (labels.length === 0) {
    throw new Error("click_filter_overlay: missing option_label / option_labels / days");
  }

  let root = findFilterPanel()?.tagName.toLowerCase() ?? null;

  if (!root && payload.open_if_closed !== false) {
    const openResult = await clickFilterButton();
    if (!openResult.ok) {
      return {
        ok: false,
        clicked: false,
        failed_label: labels[0],
        overlay_root: null,
        url: location.href,
        message: openResult.message ?? "打开筛选浮层失败",
      };
    }
    await waitForFilterPanel(800);
    root = findFilterPanel()?.tagName.toLowerCase() ?? null;
  }

  if (!root) {
    // 浮层 DOM 结构可能识别失败，仍尝试在上半屏精确点击选项
    const clicked: Array<{
      label: string;
      match_method: string;
      tag: string;
      class_name: string;
    }> = [];

    for (const label of labels) {
      const match = findFilterOverlayOption(label);
      if (!match) {
        return {
          ok: false,
          clicked: false,
          failed_label: label,
          available_options: listFilterOverlayOptions(),
          overlay_root: null,
          url: location.href,
          message: `筛选浮层未打开，且未找到「${label}」`,
        };
      }
      match.element.click();
      clicked.push({
        label,
        match_method: match.matchMethod,
        tag: match.element.tagName.toLowerCase(),
        class_name: match.element.className || "",
      });
      await sleep(180);
    }

    return {
      ok: true,
      clicked: true,
      clicked_labels: clicked.map((item) => item.label),
      clicks: clicked,
      overlay_root: null,
      open_method: "fallback_without_panel",
      url: location.href,
      message: `已点击筛选选项：${clicked.map((item) => item.label).join("、")}`,
    };
  }

  const clicked: Array<{
    label: string;
    match_method: string;
    tag: string;
    class_name: string;
  }> = [];

  for (const label of labels) {
    const match = findFilterOverlayOption(label);
    if (!match) {
      return {
        ok: false,
        clicked: clicked.length > 0,
        failed_label: label,
        clicked_labels: clicked.map((item) => item.label),
        available_options: listFilterOverlayOptions(),
        overlay_root: root,
        url: location.href,
        message: `浮层内未找到「${label}」`,
      };
    }

    match.element.click();
    clicked.push({
      label,
      match_method: match.matchMethod,
      tag: match.element.tagName.toLowerCase(),
      class_name: match.element.className || "",
    });
    await sleep(180);
  }

  return {
    ok: true,
    clicked: true,
    clicked_labels: clicked.map((item) => item.label),
    clicks: clicked,
    overlay_root: root,
    url: location.href,
    message:
      clicked.length === 1
        ? `已点击筛选选项：${clicked[0].label}`
        : `已点击 ${clicked.length} 个筛选选项：${clicked.map((item) => item.label).join("、")}`,
  };
}

/** 仅列出当前浮层可见选项（调试） */
export async function probeFilterOverlay() {
  const root = findFilterPanel();
  const options = listFilterOverlayOptions();
  return {
    ok: Boolean(root),
    overlay_root: root?.tagName.toLowerCase() ?? null,
    options,
    url: location.href,
    message: root ? `浮层已找到，共 ${options.length} 个选项` : "浮层未打开",
  };
}
