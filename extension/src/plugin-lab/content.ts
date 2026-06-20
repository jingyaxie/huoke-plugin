import { clickFilterButton } from "./click-filter-btn";
import { clickFilterOverlay, type ClickFilterOverlayPayload } from "./click-filter-overlay";
import { isPluginLabBackgroundAction } from "./background-actions";
import { findFilterOptionPoint, probeFilterDom } from "./filter-dom";
import { findAndFocusSearchBox } from "./find-search-box";
import { inputSearchText, type InputSearchTextPayload } from "./input-search-text";
import { swipePage, type SwipePagePayload } from "./swipe-page";

export async function dispatchPluginLabCommand(action: string, payload: unknown): Promise<unknown> {
  switch (action) {
    case "plugin_lab.swipe_page":
      return swipePage((payload ?? {}) as SwipePagePayload);
    case "plugin_lab.find_search_box":
      return findAndFocusSearchBox((payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.input_search_text":
      return inputSearchText((payload ?? {}) as InputSearchTextPayload);
    case "plugin_lab.click_filter_btn":
      return clickFilterButton();
    case "plugin_lab.click_filter_overlay":
      return clickFilterOverlay((payload ?? {}) as ClickFilterOverlayPayload);
    case "plugin_lab.filter_probe":
      return probeFilterDom();
    case "plugin_lab.filter_find_option":
      return findFilterOptionPoint(String((payload as { label?: string })?.label ?? ""));
    default:
      throw new Error(`unsupported plugin_lab content action: ${action}`);
  }
}

export function isPluginLabContentAction(action: string): boolean {
  return action.startsWith("plugin_lab.") && !isPluginLabBackgroundAction(action);
}
