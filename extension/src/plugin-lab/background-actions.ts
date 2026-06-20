const BACKGROUND_ACTIONS = new Set([
  "plugin_lab.open_browser",
  "plugin_lab.click_filter_btn",
  "plugin_lab.click_filter_overlay",
  "plugin_lab.click_search_video",
  "plugin_lab.click_comment_btn",
  "plugin_lab.reply_comment",
  "plugin_lab.click_dm_btn",
  "plugin_lab.input_dm_text",
  "plugin_lab.send_dm",
]);

export function isPluginLabBackgroundAction(action: string): boolean {
  return BACKGROUND_ACTIONS.has(action);
}
