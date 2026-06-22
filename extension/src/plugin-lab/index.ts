import type { BridgeMessage } from "../shared/protocol";
import { openBrowser } from "./open-browser";
import {
  clickFilterButtonBackground,
  clickFilterOverlayBackground,
} from "./filter-background";
import { clickCommentButtonBackground } from "./comment-sidebar-background";
import { clickDmButtonBackground, inputDmTextBackground, sendDmBackground } from "./dm-background";
import { replyCommentBackground } from "./reply-comment-background";
import { clickSearchVideoBackground } from "./search-video-background";
import { clickProfileVideoBackground } from "./profile-video-background";
import { probeSearchContextBackground } from "./search-context-background";
import { isPluginLabBackgroundAction } from "./background-actions";

export { isPluginLabBackgroundAction } from "./background-actions";
export { resolveLabTabForAction, resolveLabTargetTab, pinLabSession } from "./resolve-lab-tab";
export { contextRequirementForAction, contextLabel, detectPageContext } from "./lab-context";

export async function runPluginLabBackgroundCommand(command: BridgeMessage): Promise<unknown> {
  switch (command.action) {
    case "plugin_lab.open_browser":
      return openBrowser((command.payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.click_filter_btn":
      return clickFilterButtonBackground();
    case "plugin_lab.click_filter_overlay":
      return clickFilterOverlayBackground((command.payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.click_search_video":
      return clickSearchVideoBackground((command.payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.click_profile_video":
      return clickProfileVideoBackground((command.payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.click_comment_btn":
      return clickCommentButtonBackground((command.payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.reply_comment":
      return replyCommentBackground((command.payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.click_dm_btn":
      return clickDmButtonBackground();
    case "plugin_lab.input_dm_text":
      return inputDmTextBackground((command.payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.send_dm":
      return sendDmBackground((command.payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.search_context_probe":
      return probeSearchContextBackground((command.payload ?? {}) as Record<string, unknown>);
    default:
      throw new Error(`unsupported plugin_lab background action: ${command.action}`);
  }
}
