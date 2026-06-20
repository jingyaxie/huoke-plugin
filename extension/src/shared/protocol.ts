/** Huoke Bridge Protocol v1 — keep in sync with local-service/src/protocol.rs */

export const PROTOCOL_VERSION = 1;

export type PlatformId = "douyin" | "xiaohongshu" | "kuaishou" | "unknown";

export type MessageType = "command" | "result" | "event" | "error" | "ping" | "pong";

export interface BridgeMessage<T = unknown> {
  v: number;
  type: MessageType;
  id: string;
  ts: number;
  platform: PlatformId | null;
  action: string;
  payload: T;
}

export interface PageInfo {
  url: string;
  title: string;
  platform: PlatformId;
}

export interface NetworkCapturedPayload {
  url: string;
  method: string;
  status?: number;
  body?: unknown;
}

export const DEFAULT_WS_URL = "ws://127.0.0.1:18766/ws";

export function createMessage<T>(
  partial: Pick<BridgeMessage<T>, "type" | "action" | "payload"> &
    Partial<Pick<BridgeMessage<T>, "id" | "platform">>,
): BridgeMessage<T> {
  return {
    v: PROTOCOL_VERSION,
    id: partial.id ?? crypto.randomUUID(),
    ts: Date.now(),
    platform: partial.platform ?? null,
    type: partial.type,
    action: partial.action,
    payload: partial.payload,
  };
}
