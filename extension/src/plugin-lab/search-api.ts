const INJECTED_CHANNEL = "huoke:injected";
const CONFIG_CHANNEL = "huoke:injected:config";

export const SEARCH_API_STORAGE_KEY = "huoke:search-api-cache";

const SEARCH_API_MARKERS = [
  "general/search/single",
  "general/search/stream",
  "search/item",
  "search/single",
  "aweme/v1/web/general/search",
] as const;
const SEARCH_API_EXCLUDES = ["search/sug", "suggest_words"] as const;

export interface SearchApiItem {
  index: number;
  title: string;
  author: string;
  url: string;
  aweme_id: string;
  /** API 截获项：含完整 aweme 节点，供下游解析 */
  source: "api";
  click_by: "aweme_id";
  raw_aweme: Record<string, unknown>;
}

export interface SearchCaptureCache {
  at: number;
  items: SearchApiItem[];
  sourceUrl: string;
  eventsSeen: number;
  lastApiUrl?: string;
  lastParseCount?: number;
  lastStatus?: number;
  lastBodyKind?: string;
}

let lastSearchCapture: SearchCaptureCache | null = null;
let bridgeReady = false;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function resolveCaptureUrl(url?: string): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  try {
    return new URL(url, typeof location !== "undefined" ? location.href : "https://www.douyin.com/").href;
  } catch {
    return url.startsWith("/") ? `https://www.douyin.com${url}` : `https://www.douyin.com/${url}`;
  }
}

export function isSearchResultApi(url: string): boolean {
  const lower = resolveCaptureUrl(url).toLowerCase();
  if (SEARCH_API_EXCLUDES.some((marker) => lower.includes(marker))) return false;
  return SEARCH_API_MARKERS.some((marker) => lower.includes(marker));
}

export function enableSearchNetworkHook(): void {
  if (typeof window === "undefined") return;
  window.postMessage(
    {
      channel: CONFIG_CHANNEL,
      enabled: true,
      patterns: ["/aweme/", "/search/"],
    },
    "*",
  );
}

function isValidAwemeId(value: string): boolean {
  return /^\d{8,22}$/.test(value);
}

function normalizeSearchAweme(node: Record<string, unknown>): SearchApiItem | null {
  const awemeRaw = node.aweme_info;
  const aweme =
    awemeRaw && typeof awemeRaw === "object" && !Array.isArray(awemeRaw)
      ? (awemeRaw as Record<string, unknown>)
      : node;

  const awemeId = String(aweme.aweme_id ?? aweme.awemeId ?? "").trim();
  if (!isValidAwemeId(awemeId)) return null;

  const author =
    aweme.author && typeof aweme.author === "object" && !Array.isArray(aweme.author)
      ? (aweme.author as Record<string, unknown>)
      : null;

  return {
    index: 0,
    title: String(aweme.desc ?? aweme.title ?? "").trim(),
    author: String(author?.nickname ?? "").trim() || "—",
    url: `https://www.douyin.com/video/${awemeId}`,
    aweme_id: awemeId,
    source: "api",
    click_by: "aweme_id",
    raw_aweme: aweme,
  };
}

export function parseSearchApiBody(body: unknown): SearchApiItem[] {
  const seen = new Set<string>();
  const items: SearchApiItem[] = [];

  const walk = (node: unknown): void => {
    if (!node || typeof node !== "object") return;

    if (Array.isArray(node)) {
      for (let i = 0; i < node.length; i += 1) walk(node[i]);
      return;
    }

    const record = node as Record<string, unknown>;
    const hasAwemeInfo = "aweme_info" in record;
    const hasAwemeShape =
      ("aweme_id" in record || "awemeId" in record) &&
      ("desc" in record || "author" in record || "title" in record);
    if (hasAwemeInfo || hasAwemeShape) {
      const normalized = normalizeSearchAweme(record);
      if (normalized && !seen.has(normalized.aweme_id)) {
        seen.add(normalized.aweme_id);
        items.push(normalized);
      }
    }

    for (const value of Object.values(record)) {
      walk(value);
    }
  };

  walk(body);
  return items.map((item, index) => ({ ...item, index: index + 1 }));
}

async function readCacheFromStorage(): Promise<SearchCaptureCache | null> {
  try {
    const stored = await chrome.storage.session.get(SEARCH_API_STORAGE_KEY);
    const cache = stored[SEARCH_API_STORAGE_KEY] as SearchCaptureCache | undefined;
    return cache ?? null;
  } catch {
    return null;
  }
}

async function writeCacheToStorage(cache: SearchCaptureCache): Promise<void> {
  lastSearchCapture = cache;
  try {
    await chrome.storage.session.set({ [SEARCH_API_STORAGE_KEY]: cache });
  } catch {
    // ignore storage failures
  }
}

export async function clearSearchApiCache(): Promise<void> {
  lastSearchCapture = null;
  try {
    await chrome.storage.session.remove(SEARCH_API_STORAGE_KEY);
  } catch {
    // ignore
  }
}

async function mergeSearchApiCapture(
  url: string,
  parsed: SearchApiItem[],
  meta: Partial<SearchCaptureCache>,
): Promise<void> {
  const previous = lastSearchCapture ?? (await readCacheFromStorage());
  const merged = new Map<string, SearchApiItem>();
  for (const item of previous?.items ?? []) merged.set(item.aweme_id, item);
  for (const item of parsed) merged.set(item.aweme_id, item);

  const nextItems = Array.from(merged.values()).map((item, index) => ({
    ...item,
    index: index + 1,
  }));

  await writeCacheToStorage({
    at: Date.now(),
    items: nextItems,
    sourceUrl: meta.sourceUrl ?? previous?.sourceUrl ?? "",
    eventsSeen: (previous?.eventsSeen ?? 0) + 1,
    lastApiUrl: url,
    lastParseCount: parsed.length,
    lastStatus: meta.lastStatus,
    lastBodyKind: meta.lastBodyKind,
  });
}

export async function ingestSearchApiResponse(
  url: string,
  body: unknown | null,
  status = 200,
): Promise<boolean> {
  if (!isSearchResultApi(url)) return false;
  if (status >= 400) return false;

  const parsed = body ? parseSearchApiBody(body) : [];
  await mergeSearchApiCapture(url, parsed, {
    lastStatus: status,
    lastBodyKind: body ? (parsed.length > 0 ? "json" : "json_empty_parse") : "no_body",
  });
  return parsed.length > 0;
}

export function ingestNetworkPayload(payload: {
  url?: string;
  status?: number;
  body?: unknown;
}): boolean {
  const url = resolveCaptureUrl(payload?.url);
  void ingestSearchApiResponse(url, payload?.body ?? null, payload?.status ?? 200);
  return Boolean(payload?.body && parseSearchApiBody(payload.body).length > 0);
}

export async function getLastSearchApiResults(maxAgeMs = 120_000): Promise<SearchApiItem[] | null> {
  const cache =
    lastSearchCapture && Date.now() - lastSearchCapture.at <= maxAgeMs
      ? lastSearchCapture
      : await readCacheFromStorage();
  if (!cache || Date.now() - cache.at > maxAgeMs) return null;
  lastSearchCapture = cache;
  return cache.items;
}

export function getCachedSearchApiResultsSync(maxAgeMs = 120_000): SearchApiItem[] | null {
  if (!lastSearchCapture || Date.now() - lastSearchCapture.at > maxAgeMs) return null;
  return lastSearchCapture.items;
}

export async function hydrateSearchApiCache(): Promise<void> {
  const cache = await readCacheFromStorage();
  if (cache) {
    lastSearchCapture = cache;
  }
}

export async function getSearchApiDebug(): Promise<Partial<SearchCaptureCache>> {
  const cache = lastSearchCapture ?? (await readCacheFromStorage());
  if (!cache) return { eventsSeen: 0 };
  return {
    eventsSeen: cache.eventsSeen,
    lastApiUrl: cache.lastApiUrl,
    lastParseCount: cache.lastParseCount,
    lastStatus: cache.lastStatus,
    lastBodyKind: cache.lastBodyKind,
  };
}

export function initSearchApiCaptureBridge(): void {
  if (bridgeReady || typeof window === "undefined") return;
  bridgeReady = true;
  void hydrateSearchApiCache();
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== INJECTED_CHANNEL) return;
    ingestNetworkPayload(event.data.payload ?? {});
  });
}

export async function pollSearchApiCache(options: {
  timeoutMs?: number;
  minItems?: number;
} = {}): Promise<SearchCaptureCache | null> {
  const timeoutMs = options.timeoutMs ?? 15_000;
  const minItems = Math.max(1, options.minItems ?? 1);
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const cache = await readCacheFromStorage();
    if (cache?.items?.length && cache.items.length >= minItems) {
      lastSearchCapture = cache;
      return cache;
    }
    await sleep(300);
  }

  const cache = await readCacheFromStorage();
  if (cache?.items?.length) {
    lastSearchCapture = cache;
  }
  return cache;
}

export async function waitForSearchApiResults(options: {
  timeoutMs?: number;
  minItems?: number;
} = {}): Promise<SearchApiItem[]> {
  const cache = await pollSearchApiCache(options);
  return cache?.items ?? [];
}
