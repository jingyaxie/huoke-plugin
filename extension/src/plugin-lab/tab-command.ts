import { createMessage } from "../shared/protocol";
import { ensureContentScript } from "../background/command-router";
import { ensureLabCommandReady } from "./lab-preflight";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRetryableMessageError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return (
    msg.includes("message channel closed")
    || msg.includes("Receiving end does not exist")
    || msg.includes("Could not establish connection")
  );
}

async function sendTabMessageWithRetry(
  tabId: number,
  message: unknown,
  maxAttempts = 4,
): Promise<{ ok?: boolean; data?: unknown; error?: string }> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      return await chrome.tabs.sendMessage(tabId, message);
    } catch (err) {
      lastErr = err;
      if (!isRetryableMessageError(err) || attempt >= maxAttempts - 1) {
        throw err;
      }
      await sleep(350 + attempt * 650);
      await ensureContentScript(tabId);
    }
  }
  throw lastErr;
}

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

  const response = await sendTabMessageWithRetry(tabId, {
    type: "huoke:command",
    command,
  });

  if (!response?.ok) {
    throw new Error(response?.error ?? `content script failed: ${action}`);
  }
  return response.data;
}
