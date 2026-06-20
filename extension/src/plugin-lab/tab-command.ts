import { createMessage } from "../shared/protocol";
import { ensureContentScript } from "../background/command-router";

export async function sendContentPluginLabCommand(
  tabId: number,
  action: string,
  payload: unknown,
): Promise<unknown> {
  await ensureContentScript(tabId);
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
