import type { BridgeMessage } from "../shared/protocol";
import { openBrowser } from "./open-browser";
import {
  clickFilterButtonBackground,
  clickFilterOverlayBackground,
} from "./filter-background";
import { isPluginLabBackgroundAction } from "./background-actions";

export { isPluginLabBackgroundAction } from "./background-actions";

export async function runPluginLabBackgroundCommand(command: BridgeMessage): Promise<unknown> {
  switch (command.action) {
    case "plugin_lab.open_browser":
      return openBrowser((command.payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.click_filter_btn":
      return clickFilterButtonBackground();
    case "plugin_lab.click_filter_overlay":
      return clickFilterOverlayBackground((command.payload ?? {}) as Record<string, unknown>);
    default:
      throw new Error(`unsupported plugin_lab background action: ${command.action}`);
  }
}
