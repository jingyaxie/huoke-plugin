import { createMessage } from "../shared/protocol";
import { ensureContentScript } from "../background/command-router";
import { ensureLabCommandReady } from "./lab-preflight";

export async function sendContentPluginLabCommand(
  tabId: number,
  action: string,
  payload: unknown,
  options?: { skipPreflight?: boolean },
): Promise<unknown> {
  await ensureContentScript(tabId);
  if (!options?.skipPreflight) {
    await ensureLabCommandReady(tabId, action);
  }
  const command = createMessage({
    type: "command",
    action,
    platform: "douyin",
    payload,
  });

  const response = await chrome.tabs.sendMessage(tabId, {
    type: "huoke:command",
    command,
  });

  if (!response?.ok) {
    throw new Error(response?.error ?? `content script failed: ${action}`);
  }
  return response.data;
}
