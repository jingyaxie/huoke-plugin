import { resolveLabTargetTab } from "./resolve-lab-tab";
import type { ClickFilterOverlayPayload } from "./click-filter-overlay";
import { publishTimeLabelFromDays } from "./filter-overlay";
import {
  attachDebugger,
  clickMouse,
  detachDebugger,
  moveMouse,
  randDelay,
} from "./real-mouse";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface FilterProbe {
  button?: {
    rect: { top: number; left: number; width: number; height: number };
    text?: string;
    selector?: string;
  } | null;
  panel_open?: boolean;
  panel_tag?: string | null;
  options?: string[];
  viewport?: { width: number; height: number };
  url?: string;
}

interface OptionPoint {
  found?: boolean;
  center?: { x: number; y: number };
  match_method?: string;
  options?: string[];
  message?: string;
}

async function probeFilter(tabId: number): Promise<FilterProbe> {
  return (await sendContentPluginLabCommand(tabId, "plugin_lab.filter_probe", {})) as FilterProbe;
}

async function findOption(tabId: number, label: string): Promise<OptionPoint> {
  return (await sendContentPluginLabCommand(tabId, "plugin_lab.filter_find_option", {
    label,
  })) as OptionPoint;
}

async function openFilterPanel(tabId: number, probe: FilterProbe) {
  const button = probe.button;
  if (!button?.rect) {
    return {
      ok: false,
      panel_open: false,
      open_method: "no_button",
      message: "未找到筛选按钮",
    };
  }

  if (probe.panel_open) {
    return {
      ok: true,
      panel_open: true,
      open_method: "already_open",
      message: "筛选浮层已打开",
    };
  }

  const viewportH = probe.viewport?.height ?? 900;
  const safeX = 72;
  const safeY = Math.min(viewportH * 0.35, 360);
  const cx = button.rect.left + button.rect.width / 2;
  const cy = button.rect.top + button.rect.height / 2;

  await attachDebugger(tabId);
  try {
    await moveMouse(tabId, safeX, safeY);
    await sleep(randDelay(450, 750));
    await moveMouse(tabId, cx, cy);
    await sleep(randDelay(1000, 1600));

    let afterHover = await probeFilter(tabId);
    if (afterHover.panel_open) {
      return {
        ok: true,
        panel_open: true,
        open_method: "hover",
        message: "hover 后筛选浮层已打开",
      };
    }

    await clickMouse(tabId, cx, cy);
    await sleep(randDelay(1200, 1800));
    afterHover = await probeFilter(tabId);

    return {
      ok: Boolean(afterHover.panel_open),
      panel_open: Boolean(afterHover.panel_open),
      open_method: afterHover.panel_open ? "click" : "click_failed",
      message: afterHover.panel_open
        ? "已点击筛选按钮并打开浮层"
        : "已点击筛选按钮，但浮层未检测到",
      options: afterHover.options ?? [],
      panel_tag: afterHover.panel_tag ?? null,
    };
  } finally {
    await detachDebugger(tabId);
  }
}

/** background：真实鼠标打开筛选浮层 */
export async function clickFilterButtonBackground() {
  const tab = await resolveLabTargetTab();
  if (!tab.id) throw new Error("target tab has no id");

  const tabId = tab.id;
  const probe = await probeFilter(tabId);
  const result = await openFilterPanel(tabId, probe);

  return {
    ...result,
    clicked: result.open_method === "click",
    already_open: result.open_method === "already_open" || result.open_method === "hover",
    selector: probe.button?.selector ?? "span.P1BREWal",
    text: probe.button?.text ?? "筛选",
    rect: probe.button?.rect ?? null,
    url: probe.url ?? tab.url,
  };
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

/** background：真实鼠标点击筛选选项 */
export async function clickFilterOverlayBackground(payload: ClickFilterOverlayPayload = {}) {
  const labels = parseLabels(payload);
  if (labels.length === 0) {
    throw new Error("click_filter_overlay: missing option_label / option_labels / days");
  }

  const tab = await resolveLabTargetTab();
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  let probe = await probeFilter(tabId);

  if (!probe.panel_open && payload.open_if_closed !== false) {
    const opened = await openFilterPanel(tabId, probe);
    if (!opened.panel_open) {
      return {
        ok: false,
        clicked: false,
        failed_label: labels[0],
        overlay_root: null,
        url: probe.url ?? tab.url,
        message: opened.message ?? "打开筛选浮层失败",
        options: opened.options ?? [],
      };
    }
    probe = await probeFilter(tabId);
  }

  const clicked: Array<{
    label: string;
    match_method: string;
    center: { x: number; y: number };
  }> = [];

  await attachDebugger(tabId);
  try {
    for (const label of labels) {
      const point = await findOption(tabId, label);
      if (!point.found || !point.center) {
        return {
          ok: false,
          clicked: clicked.length > 0,
          failed_label: label,
          clicked_labels: clicked.map((item) => item.label),
          available_options: point.options ?? probe.options ?? [],
          overlay_root: probe.panel_tag ?? null,
          url: probe.url ?? tab.url,
          message: point.message ?? `浮层内未找到「${label}」`,
        };
      }

      await clickMouse(tabId, point.center.x, point.center.y);
      clicked.push({
        label,
        match_method: point.match_method ?? "real_mouse",
        center: point.center,
      });
      await sleep(220);
    }
  } finally {
    await detachDebugger(tabId);
  }

  probe = await probeFilter(tabId);

  return {
    ok: true,
    clicked: true,
    clicked_labels: clicked.map((item) => item.label),
    clicks: clicked,
    overlay_root: probe.panel_tag ?? null,
    available_options: probe.options ?? [],
    url: probe.url ?? tab.url,
    message:
      clicked.length === 1
        ? `已点击筛选选项：${clicked[0].label}`
        : `已点击 ${clicked.length} 个筛选选项：${clicked.map((item) => item.label).join("、")}`,
  };
}
