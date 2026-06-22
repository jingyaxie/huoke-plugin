/** Service Worker / offscreen 命令超时 — 须 ≥ local-service lab_commands action_timeout */
export function backgroundCommandTimeoutMs(action: string): number {
  if (action === "plugin_lab.open_browser") return 120_000;
  if (action === "plugin_lab.find_search_box" ||
    action === "plugin_lab.input_search_text" ||
    action === "plugin_lab.click_search_btn" ||
    action === "plugin_lab.fetch_search_results" ||
    action === "plugin_lab.click_search_video" ||
    action === "plugin_lab.click_profile_video" ||
    action === "plugin_lab.click_comment_btn" ||
    action === "plugin_lab.scroll_and_collect_comments" ||
    action.startsWith("network.hook.")
  ) {
    return 120_000;
  }
  return 55_000;
}
