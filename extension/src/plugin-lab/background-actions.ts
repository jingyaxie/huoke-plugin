const BACKGROUND_ACTIONS = new Set([
  "plugin_lab.open_browser",
  "plugin_lab.click_filter_btn",
  "plugin_lab.click_filter_overlay",
]);

export function isPluginLabBackgroundAction(action: string): boolean {
  return BACKGROUND_ACTIONS.has(action);
}
