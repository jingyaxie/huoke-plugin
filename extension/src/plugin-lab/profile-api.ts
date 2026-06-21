import {
  parseSearchApiBody,
  resolveCaptureUrl,
  type SearchApiItem,
} from "./search-api";

const INJECTED_CHANNEL = "huoke:injected";

export const PROFILE_API_STORAGE_KEY = "huoke:profile-api-cache";

const PROFILE_API_MARKERS = [
  "aweme/v1/web/aweme/post",
  "/aweme/post/",
] as const;

export type ProfileApiItem = SearchApiItem;

export interface ProfileCaptureCache {
  at: number;
  items: ProfileApiItem[];
  sourceUrl: string;
  eventsSeen: number;
  lastApiUrl?: string;
  lastParseCount?: number;
  lastStatus?: number;
  lastBodyKind?: string;
}

let lastProfileCapture: ProfileCaptureCache | null = null;
let bridgeReady = false;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function isProfilePostApi(url: string): boolean {
  const lower = resolveCaptureUrl(url).toLowerCase();
  return PROFILE_API_MARKERS.some((marker) => lower.includes(marker));
}

export function enableProfileNetworkHook(): void {
  if (typeof window === "undefined") return;
  window.postMessage(
    {
      channel: "huoke:injected:config",
      enabled: true,
      patterns: ["/aweme/", "/comment/"],
    },
    "*",
  );
}

async function readCacheFromStorage(): Promise<ProfileCaptureCache | null> {
  try {
    const stored = await chrome.storage.session.get(PROFILE_API_STORAGE_KEY);
    const cache = stored[PROFILE_API_STORAGE_KEY] as ProfileCaptureCache | undefined;
    return cache ?? null;
  } catch {
    return null;
  }
}

async function writeCacheToStorage(cache: ProfileCaptureCache): Promise<void> {
  lastProfileCapture = cache;
  try {
    await chrome.storage.session.set({ [PROFILE_API_STORAGE_KEY]: cache });
  } catch {
    // ignore
  }
}

async function mergeProfileApiCapture(
  url: string,
  parsed: ProfileApiItem[],
  meta: Partial<ProfileCaptureCache>,
): Promise<void> {
  const previous = lastProfileCapture ?? (await readCacheFromStorage());
  const merged = new Map<string, ProfileApiItem>();
  for (const item of previous?.items ?? []) merged.set(item.aweme_id, item);
  for (const item of parsed) merged.set(item.aweme_id, item);

  const nextItems = Array.from(merged.values()).map((item, index) => ({
    ...item,
    index: index + 1,
  }));

  await writeCacheToStorage({
    at: Date.now(),
    items: nextItems,
    sourceUrl: meta.sourceUrl ?? previous?.sourceUrl ?? (typeof location !== "undefined" ? location.href : ""),
    eventsSeen: (previous?.eventsSeen ?? 0) + 1,
    lastApiUrl: url,
    lastParseCount: parsed.length,
    lastStatus: meta.lastStatus,
    lastBodyKind: meta.lastBodyKind,
  });
}

export async function ingestProfileApiResponse(
  url: string,
  body: unknown | null,
  status = 200,
): Promise<boolean> {
  if (!isProfilePostApi(url)) return false;
  if (status >= 400) return false;

  const parsed = body ? parseSearchApiBody(body) : [];
  await mergeProfileApiCapture(url, parsed, {
    lastStatus: status,
    lastBodyKind: body ? (parsed.length > 0 ? "json" : "json_empty_parse") : "no_body",
  });
  return parsed.length > 0;
}

export function ingestProfileNetworkPayload(payload: {
  url?: string;
  status?: number;
  body?: unknown;
}): boolean {
  const url = resolveCaptureUrl(payload?.url);
  void ingestProfileApiResponse(url, payload?.body ?? null, payload?.status ?? 200);
  return Boolean(payload?.body && isProfilePostApi(url) && parseSearchApiBody(payload.body).length > 0);
}

export async function getLastProfileApiResults(maxAgeMs = 120_000): Promise<ProfileApiItem[] | null> {
  const cache =
    lastProfileCapture && Date.now() - lastProfileCapture.at <= maxAgeMs
      ? lastProfileCapture
      : await readCacheFromStorage();
  if (!cache || Date.now() - cache.at > maxAgeMs) return null;
  lastProfileCapture = cache;
  return cache.items;
}

export function getCachedProfileApiResultsSync(maxAgeMs = 120_000): ProfileApiItem[] | null {
  if (!lastProfileCapture || Date.now() - lastProfileCapture.at > maxAgeMs) return null;
  return lastProfileCapture.items;
}

export async function hydrateProfileApiCache(): Promise<void> {
  const cache = await readCacheFromStorage();
  if (cache) lastProfileCapture = cache;
}

export async function getProfileApiDebug(): Promise<Partial<ProfileCaptureCache>> {
  const cache = lastProfileCapture ?? (await readCacheFromStorage());
  if (!cache) return { eventsSeen: 0 };
  return {
    eventsSeen: cache.eventsSeen,
    lastApiUrl: cache.lastApiUrl,
    lastParseCount: cache.lastParseCount,
    lastStatus: cache.lastStatus,
    lastBodyKind: cache.lastBodyKind,
  };
}

export async function pollProfileApiCache(options: {
  timeoutMs?: number;
  minItems?: number;
} = {}): Promise<ProfileCaptureCache | null> {
  const timeoutMs = options.timeoutMs ?? 15_000;
  const minItems = Math.max(1, options.minItems ?? 1);
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const cache = await readCacheFromStorage();
    if (cache?.items?.length && cache.items.length >= minItems) {
      lastProfileCapture = cache;
      return cache;
    }
    await sleep(300);
  }

  const cache = await readCacheFromStorage();
  if (cache?.items?.length) lastProfileCapture = cache;
  return cache;
}

export async function waitForProfileApiResults(options: {
  timeoutMs?: number;
  minItems?: number;
} = {}): Promise<ProfileApiItem[]> {
  const cache = await pollProfileApiCache(options);
  return cache?.items ?? [];
}

export function initProfileApiCaptureBridge(): void {
  if (bridgeReady || typeof window === "undefined") return;
  bridgeReady = true;
  void hydrateProfileApiCache();
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== INJECTED_CHANNEL) return;
    ingestProfileNetworkPayload(event.data.payload ?? {});
  });
}
