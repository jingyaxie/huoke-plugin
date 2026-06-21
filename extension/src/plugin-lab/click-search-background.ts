import { resolveLabTabForAction } from "./resolve-lab-tab";
import { sendContentPluginLabCommand } from "./tab-command";
import {
  getSearchApiDebug,
} from "./search-api";
import { buildSearchResultPayload } from "./click-search-btn";
import { withSearchNetworkCapture } from "./search-network-debugger";
import { pollPlatformSearchCache } from "./platform-lab-helpers";

export async function clickSearchButtonBackground() {
  const tab = await resolveLabTabForAction("plugin_lab.click_search_btn");
  if (!tab.id) {
    throw new Error("lab tab has no id");
  }
  const tabId = tab.id;

  return withSearchNetworkCapture(tabId, async () => {
    await sendContentPluginLabCommand(tabId, "plugin_lab.search_prepare", {}, { skipPreflight: true });

    const clickResult = (await sendContentPluginLabCommand(
      tabId,
      "plugin_lab.search_submit",
      {},
      { skipPreflight: true },
    )) as Record<string, unknown>;

    const polled = await pollPlatformSearchCache(tab.url, 15_000, 1);
    let items = polled.items;
    let captureMethod: "api" | "dom" | "none" = polled.captureMethod;

    if (!items.length && clickResult.ok) {
      const domResult = (await sendContentPluginLabCommand(
        tabId,
        "plugin_lab.fetch_search_results",
        { limit: 20 },
        { skipPreflight: true },
      )) as Record<string, unknown>;
      const domItems = domResult.items ?? domResult.results;
      if (Array.isArray(domItems) && domItems.length > 0) {
        items = domItems as typeof items;
        captureMethod = "dom";
      }
    }

    const debug = await getSearchApiDebug().catch(() => null);
    const hasResults = items.length > 0;
    const ok = Boolean(clickResult.ok) || hasResults;

    return {
      ...clickResult,
      ok,
      ...buildSearchResultPayload(items, captureMethod),
      api_events_seen: debug?.eventsSeen ?? 0,
      last_api_url: debug?.lastApiUrl ?? "",
      last_api_status: debug?.lastStatus,
      last_body_kind: debug?.lastBodyKind ?? "",
      message: hasResults
        ? captureMethod === "api"
          ? `已触发搜索，从接口获取 ${items.length} 条结果`
          : `已进入搜索页，接口未解析到数据，已用 DOM 兜底 ${items.length} 条`
        : ok
          ? `已进入搜索页，但接口暂无数据`
          : "已点击搜索，但未进入搜索结果页，也未截获搜索接口",
    };
  });
}
