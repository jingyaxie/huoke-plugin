import { createMessage } from "../shared/protocol";
import type { LabReadinessResult } from "./lab-readiness";

const SKIP_PREFLIGHT = new Set([
  "plugin_lab.open_browser",
  "plugin_lab.preflight",
  "plugin_lab.page_snapshot",
  "plugin_lab.search_video_probe",
  "plugin_lab.search_prepare",
  "plugin_lab.search_submit",
  "network.hook.enable",
  "network.hook.disable",
  "network.hook.status",
  "plugin_lab.fetch_profile_videos",
  "plugin_lab.prepare_profile_video",
  "plugin_lab.profile_video_probe",
  "plugin_lab.profile_video_dom_click",
  "plugin_lab.back_to_profile",
]);

export class LabPreflightError extends Error {
  readonly probe: LabReadinessResult;

  constructor(probe: LabReadinessResult) {
    super(probe.message || "当前界面无法执行此命令");
    this.name = "LabPreflightError";
    this.probe = probe;
  }
}

/** 调用方须先 ensureContentScript(tabId) */
export async function probeLabReadinessOnTab(
  tabId: number,
  targetAction: string,
): Promise<LabReadinessResult> {
  const command = createMessage({
    type: "command",
    action: "plugin_lab.preflight",
    platform: "douyin",
    payload: { target_action: targetAction },
  });

  const response = (await chrome.tabs.sendMessage(tabId, {
    type: "huoke:command",
    command,
  })) as { ok?: boolean; data?: LabReadinessResult; error?: string };

  if (!response?.ok || !response.data) {
    return {
      ok: false,
      can_execute: false,
      target_action: targetAction,
      required_context: "platform",
      detected_context: null,
      url: "",
      message: response?.error ?? "预检失败：content script 无响应",
    };
  }
  return response.data;
}

export async function ensureLabCommandReady(tabId: number, action: string): Promise<LabReadinessResult> {
  if (SKIP_PREFLIGHT.has(action)) {
    return {
      ok: true,
      can_execute: true,
      target_action: action,
      required_context: "platform",
      detected_context: null,
      url: "",
      message: "skip preflight",
    };
  }

  const probe = await probeLabReadinessOnTab(tabId, action);
  if (!probe.can_execute) {
    throw new LabPreflightError(probe);
  }
  return probe;
}
