import { detectPlatformFromUrl } from "./platform-hosts";
import { isPlatformSearchResultsPage } from "./search-session";
import { SEARCH_URL_STORAGE_KEY } from "./search-feed-open";
import { countPlatformSearchCards } from "./platforms/platform-readiness";
import { detectPageContext } from "./lab-context";
import { normalizePlatformId } from "./platforms/registry";

/** 仅读 DOM + tab sessionStorage（不含 chrome.storage，供 background 合并） */
export function probeSearchContextDom() {
  const platform = normalizePlatformId(detectPlatformFromUrl(location.href) || "douyin");
  let tabStorage = "";
  try {
    tabStorage = sessionStorage.getItem(SEARCH_URL_STORAGE_KEY)?.trim() ?? "";
  } catch {
    // ignore
  }
  return {
    ok: true,
    platform,
    url: location.href,
    detected_context: detectPageContext(location.href, platform),
    on_search_page: isPlatformSearchResultsPage(location.href, platform),
    search_card_count: countPlatformSearchCards(platform),
    tab_session_search_url: tabStorage,
  };
}

export function mergeSearchContextProbe(
  dom: ReturnType<typeof probeSearchContextDom>,
  labUrl: string,
) {
  const platform = dom.platform;
  const platformUrl = labUrl || dom.tab_session_search_url;
  return {
    ...dom,
    lab_search_url: labUrl,
    platform_search_url: platformUrl,
    search_url_preserved: Boolean(
      (labUrl && isPlatformSearchResultsPage(labUrl, platform)) ||
        (platformUrl && isPlatformSearchResultsPage(platformUrl, platform)) ||
        (dom.tab_session_search_url && isPlatformSearchResultsPage(dom.tab_session_search_url, platform)),
    ),
  };
}
