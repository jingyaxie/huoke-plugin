import { CONTENT_MESSAGE, INJECTED_MESSAGE, NETWORK_HOOK_FILE } from "../shared/constants";
import { createMessage } from "../shared/protocol";
import { log } from "../shared/logger";
import { extensionVersion } from "../shared/runtime";
import { dispatchCommand, getPageInfo } from "./platforms/registry";
import { detectPlatformFromUrl } from "../plugin-lab/platform-hosts";
import { dispatchPluginLabCommand, isPluginLabContentAction } from "../plugin-lab/content";
import { enableSearchNetworkHook, initSearchApiCaptureBridge, ingestNetworkPayload } from "../plugin-lab/search-api";
import {
  initProfileApiCaptureBridge,
  ingestProfileNetworkPayload,
} from "../plugin-lab/profile-api";
import {
  enableCommentNetworkHook,
  initCommentApiCaptureBridge,
  ingestCommentNetworkPayload,
} from "../plugin-lab/comment-api";
import {
  enableXhsCommentNetworkHook,
  initXhsCommentApiBridge,
} from "../plugin-lab/platforms/xiaohongshu/comment-api";
import {
  enableXhsSearchNetworkHook,
  initXhsSearchApiBridge,
  ingestXhsNetworkPayload,
} from "../plugin-lab/platforms/xiaohongshu/search-api";
import {
  enableKsCommentNetworkHook,
  initKsCommentApiBridge,
} from "../plugin-lab/platforms/kuaishou/comment-api";
import {
  enableKsSearchNetworkHook,
  initKsSearchApiBridge,
  ingestKsNetworkPayload,
} from "../plugin-lab/platforms/kuaishou/search-api";

let injected = false;
let captureBootstrapped = false;

/** 页面加载后立即初始化截获桥，避免等第一次 plugin_lab 命令才监听 postMessage */
function bootstrapNetworkCapture(): void {
  if (captureBootstrapped) return;
  captureBootstrapped = true;

  initSearchApiCaptureBridge();
  initProfileApiCaptureBridge();
  initCommentApiCaptureBridge();
  initXhsSearchApiBridge();
  initXhsCommentApiBridge();
  initKsSearchApiBridge();
  initKsCommentApiBridge();

  const platform = detectPlatformFromUrl(location.href);
  if (platform === "douyin") {
    enableSearchNetworkHook();
    enableCommentNetworkHook();
  } else if (platform === "xiaohongshu") {
    enableXhsSearchNetworkHook();
    enableXhsCommentNetworkHook();
  } else if (platform === "kuaishou") {
    enableKsSearchNetworkHook();
    enableKsCommentNetworkHook();
  }

  log("network capture bootstrapped", platform || "unknown", location.href);
}

function hookAlreadyInstalled(): boolean {
  return Boolean((window as Window & { __huokeNetworkHookInstalled?: boolean }).__huokeNetworkHookInstalled);
}

async function ensureInjected() {
  bootstrapNetworkCapture();

  if (injected || hookAlreadyInstalled()) {
    injected = true;
    return;
  }

  await chrome.runtime.sendMessage({ type: "huoke:noop" }).catch(() => undefined);
  const src = chrome.runtime.getURL(NETWORK_HOOK_FILE);
  const script = document.createElement("script");
  script.src = src;
  script.type = "text/javascript";
  script.dataset.huokeInjected = "1";
  (document.head || document.documentElement).appendChild(script);
  injected = true;
  log("injected network hook fallback", src);

  bootstrapNetworkCapture();
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "huoke:ping") {
    sendResponse({ ok: true, url: location.href, version: extensionVersion() });
    return true;
  }
  if (message?.type !== "huoke:command") {
    return false;
  }

  const command = message.command;
  (async () => {
    try {
      await ensureInjected();
      if (isPluginLabContentAction(command.action)) {
        const data = await dispatchPluginLabCommand(command.action, command.payload);
        sendResponse({ ok: true, data });
        return;
      }
      if (command.action.startsWith("network.hook")) {
        // ensure hook script is present before enabling
      }
      const data = await dispatchCommand(command.action, command.payload, location.href);
      sendResponse({ ok: true, data });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      sendResponse({ ok: false, error: errorMessage });
    }
  })();

  return true;
});

window.addEventListener("message", (event) => {
  if (event.source !== window || event.data?.channel !== INJECTED_MESSAGE) {
    return;
  }
  const payload = event.data.payload;
  const platform = detectPlatformFromUrl(location.href);
  ingestNetworkPayload(payload ?? {});
  ingestProfileNetworkPayload(payload ?? {});
  ingestCommentNetworkPayload(payload ?? {});
  if (platform === "xiaohongshu") {
    ingestXhsNetworkPayload(payload ?? {});
  } else if (platform === "kuaishou") {
    ingestKsNetworkPayload(payload ?? {});
  }
  chrome.runtime.sendMessage({
    type: CONTENT_MESSAGE,
    event: createMessage({
      type: "event",
      action: "network.captured",
      platform: getPageInfo(location.href, document.title).platform,
      payload,
    }),
  });
});

bootstrapNetworkCapture();
log("content script ready", location.href);

export function onExecute() {
  log("content script onExecute", location.href);
}
