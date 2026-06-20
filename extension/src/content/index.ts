import { CONTENT_MESSAGE, INJECTED_MESSAGE, NETWORK_HOOK_FILE } from "../shared/constants";
import { createMessage } from "../shared/protocol";
import { log } from "../shared/logger";
import { extensionVersion } from "../shared/runtime";
import { dispatchCommand, getPageInfo } from "./platforms/registry";
import { dispatchPluginLabCommand, isPluginLabContentAction } from "../plugin-lab/content";

let injected = false;

async function ensureInjected() {
  if (injected) return;
  await chrome.runtime.sendMessage({ type: "huoke:noop" }).catch(() => undefined);
  const src = chrome.runtime.getURL(NETWORK_HOOK_FILE);
  const script = document.createElement("script");
  script.src = src;
  script.type = "text/javascript";
  script.dataset.huokeInjected = "1";
  (document.head || document.documentElement).appendChild(script);
  injected = true;
  log("injected network hook", src);
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

log("content script ready", location.href);

export function onExecute() {
  log("content script onExecute", location.href);
}
