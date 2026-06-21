import { resolveLabTabForAction } from "./resolve-lab-tab";
import { sendContentPluginLabCommand } from "./tab-command";
import {
  getSearchApiDebug,
  pollSearchApiCache,
} from "./search-api";
import { buildSearchResultPayload } from "./click-search-btn";

export async function clickSearchButtonBackground() {
  const tab = await resolveLabTabForAction("plugin_lab.click_search_btn");
  if (!tab.id) {
    throw new Error("lab tab has no id");
  }

  await sendContentPluginLabCommand(tab.id, "plugin_lab.search_prepare", {}, { skipPreflight: true });

  const clickResult = (await sendContentPluginLabCommand(
    tab.id,
    "plugin_lab.search_submit",
    {},
    { skipPreflight: true },
  )) as Record<string, unknown>;

  const cache = await pollSearchApiCache({ timeoutMs: 15_000, minItems: 1 });
  const items = cache?.items ?? [];
  const debug = await getSearchApiDebug();
  const hasApiResults = items.length > 0;

  const ok = Boolean(clickResult.ok) || hasApiResults;
  return {
    ...clickResult,
    ok,
    ...buildSearchResultPayload(items, hasApiResults ? "api" : "none"),
    api_events_seen: debug.eventsSeen ?? cache?.eventsSeen ?? 0,
    last_api_url: debug.lastApiUrl ?? cache?.lastApiUrl ?? "",
    message: hasApiResults
      ? `已触发搜索，从 search/single 接口获取 ${items.length} 条结果`
      : ok
        ? `已进入搜索页，但接口暂无数据（events=${debug.eventsSeen ?? 0}；可执行步骤 8 DOM 兜底）`
        : "已点击搜索，但未进入搜索结果页，也未捕获 search/single 接口",
  };
}
