import { resolveLabTabForAction } from "./resolve-lab-tab";
import { sendContentPluginLabCommand } from "./tab-command";
import {
  getSearchApiDebug,
  pollSearchApiCache,
} from "./search-api";
import { buildSearchResultPayload } from "./click-search-btn";
import { withSearchNetworkCapture } from "./search-network-debugger";

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

    let cache = await pollSearchApiCache({ timeoutMs: 15_000, minItems: 1 });
    let items = cache?.items ?? [];
    let captureMethod: "api" | "dom" | "none" = items.length > 0 ? "api" : "none";

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

    const debug = await getSearchApiDebug();
    const hasResults = items.length > 0;
    const ok = Boolean(clickResult.ok) || hasResults;

    return {
      ...clickResult,
      ok,
      ...buildSearchResultPayload(items, captureMethod),
      api_events_seen: debug.eventsSeen ?? cache?.eventsSeen ?? 0,
      last_api_url: debug.lastApiUrl ?? cache?.lastApiUrl ?? "",
      last_api_status: debug.lastStatus ?? cache?.lastStatus,
      last_body_kind: debug.lastBodyKind ?? cache?.lastBodyKind ?? "",
      message: hasResults
        ? captureMethod === "api"
          ? `已触发搜索，从 search/single 接口获取 ${items.length} 条结果`
          : `已进入搜索页，接口未解析到数据，已用 DOM 兜底 ${items.length} 条`
        : ok
          ? `已进入搜索页，但接口暂无数据（events=${debug.eventsSeen ?? 0}, body=${debug.lastBodyKind ?? "none"}）`
          : "已点击搜索，但未进入搜索结果页，也未捕获 search/single 接口",
    };
  });
}
