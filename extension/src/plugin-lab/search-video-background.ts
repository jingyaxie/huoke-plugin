import { resolveLabTabForAction } from "./resolve-lab-tab";
import {
  attachDebugger,
  clickMouse,
  detachDebugger,
  moveMouse,
  randDelay,
} from "./real-mouse";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface VideoProbe {
  ok?: boolean;
  center?: { x: number; y: number };
  video_index?: number;
  available?: number;
  feed_open?: boolean;
  url?: string;
  message?: string;
  already_open?: boolean;
}

async function probeVideo(
  tabId: number,
  payload: Record<string, unknown>,
  options?: { skipPreflight?: boolean },
): Promise<VideoProbe> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.search_video_probe",
    payload,
    options,
  )) as VideoProbe;
}

/** 步骤 9：CDP 真实鼠标点击搜索结果视频 */
export async function clickSearchVideoBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTabForAction("plugin_lab.click_search_video");
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;
  const videoIndex = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));

  let probe = await probeVideo(tabId, payload, { skipPreflight: true });
  if (!probe.ok || !probe.center) {
    return {
      ok: false,
      mode: "cdp_real_mouse",
      url: probe.url ?? tab.url,
      message: probe.message ?? "未找到搜索结果视频",
    };
  }

  if (probe.feed_open) {
    return {
      ok: true,
      already_open: true,
      mode: "cdp_real_mouse",
      video_index: probe.video_index ?? videoIndex,
      url: probe.url ?? tab.url,
      message: "视频 Feed 已打开",
    };
  }

  await attachDebugger(tabId);
  try {
    await moveMouse(tabId, probe.center.x, probe.center.y);
    await sleep(randDelay(120, 200));
    await clickMouse(tabId, probe.center.x, probe.center.y);

    for (let i = 0; i < 5; i += 1) {
      await sleep(180 + i * 40);
      const status = await probeVideo(
        tabId,
        { video_index: videoIndex, status_only: true },
        { skipPreflight: true },
      );
      if (status.feed_open) {
        probe = { ...probe, ...status, feed_open: true };
        break;
      }
    }
  } finally {
    await detachDebugger(tabId);
  }

  const feedOpen = Boolean(probe.feed_open);
  return {
    ok: true,
    clicked: true,
    feed_open: feedOpen,
    mode: "cdp_real_mouse",
    video_index: probe.video_index ?? videoIndex,
    available: probe.available,
    url: probe.url ?? tab.url,
    message: feedOpen
      ? `已点击第 ${probe.video_index ?? videoIndex} 个搜索结果视频并打开 Feed`
      : `已点击第 ${probe.video_index ?? videoIndex} 个视频卡片`,
  };
}
