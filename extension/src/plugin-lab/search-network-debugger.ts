import { attachDebugger, detachDebugger } from "./real-mouse";
import { ingestSearchApiResponse, isSearchResultApi } from "./search-api";

let listenerReady = false;

const pendingResponses = new Map<string, { tabId: number; url: string; status: number }>();

function pendingKey(tabId: number, requestId: string): string {
  return `${tabId}:${requestId}`;
}

function ensureDebuggerListener(): void {
  if (listenerReady) return;
  listenerReady = true;

  chrome.debugger.onEvent.addListener((source, method, params) => {
    const tabId = source.tabId;
    if (!tabId) return;

    const payload = params as {
      requestId?: string;
      response?: { url?: string; status?: number };
    };
    const requestId = payload.requestId;
    if (!requestId) return;

    if (method === "Network.responseReceived") {
      const url = payload.response?.url ?? "";
      if (!isSearchResultApi(url)) return;
      pendingResponses.set(pendingKey(tabId, requestId), {
        tabId,
        url,
        status: payload.response?.status ?? 0,
      });
      return;
    }

    if (method !== "Network.loadingFinished") return;

    const meta = pendingResponses.get(pendingKey(tabId, requestId));
    if (!meta) return;
    pendingResponses.delete(pendingKey(tabId, requestId));

    void (async () => {
      try {
        const bodyResult = (await chrome.debugger.sendCommand(
          { tabId: meta.tabId },
          "Network.getResponseBody",
          { requestId },
        )) as { body?: string; base64Encoded?: boolean };

        let text = bodyResult.body ?? "";
        if (bodyResult.base64Encoded && text) {
          text = atob(text);
        }
        if (!text) {
          await ingestSearchApiResponse(meta.url, null, meta.status);
          return;
        }
        const json = JSON.parse(text) as unknown;
        await ingestSearchApiResponse(meta.url, json, meta.status);
      } catch {
        await ingestSearchApiResponse(meta.url, null, meta.status);
      }
    })();
  });
}

export async function withSearchNetworkCapture<T>(tabId: number, run: () => Promise<T>): Promise<T> {
  ensureDebuggerListener();
  await attachDebugger(tabId);
  try {
    await chrome.debugger.sendCommand({ tabId }, "Network.enable", {
      maxResourceBufferSize: 1024 * 1024 * 8,
      maxTotalBufferSize: 1024 * 1024 * 16,
    });
    return await run();
  } finally {
    try {
      await chrome.debugger.sendCommand({ tabId }, "Network.disable");
    } catch {
      // ignore
    }
    await detachDebugger(tabId);
  }
}
