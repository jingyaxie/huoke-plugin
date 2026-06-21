import { readLabSearchUrl } from "./lab-context";
import { mergeSearchContextProbe } from "./search-context-probe";
import { resolveLabTabForAction } from "./resolve-lab-tab";
import { sendContentPluginLabCommand } from "./tab-command";

export async function probeSearchContextBackground(payload: Record<string, unknown> = {}) {
  const platform = String(payload.platform ?? "douyin");
  const tab = await resolveLabTabForAction("plugin_lab.search_context_probe", platform);
  if (!tab?.id) {
    throw new Error("no platform tab open for search_context_probe");
  }
  const dom = (await sendContentPluginLabCommand(
    tab.id,
    "plugin_lab.search_context_dom_probe",
    payload,
    { skipPreflight: true },
  )) as ReturnType<typeof import("./search-context-probe").probeSearchContextDom>;
  const labUrl = await readLabSearchUrl(platform);
  return mergeSearchContextProbe(dom, labUrl);
}
