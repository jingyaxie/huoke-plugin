import { resolveLabTargetTab } from "./resolve-lab-tab";
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
}

async function probeVideo(tabId: number, payload: Record<string, unknown>): Promise<VideoProbe> {
  return (await sendContentPluginLabCommand(tabId, "plugin_lab.search_video_probe", payload)) as VideoProbe;
}

/** 步骤 9：CDP 真实鼠标点击搜索结果视频 */
export async function clickSearchVideoBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTargetTab();
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  let probe = await probeVideo(tabId, payload);
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
      video_index: probe.video_index,
      url: probe.url ?? tab.url,
      message: "视频 Feed 已打开",
    };
  }

  await attachDebugger(tabId);
  try {
    await moveMouse(tabId, probe.center.x, probe.center.y);
    await sleep(randDelay(200, 350));
    await clickMouse(tabId, probe.center.x, probe.center.y);

    for (let i = 0; i < 12; i += 1) {
      await sleep(randDelay(400, 550));
      probe = await probeVideo(tabId, payload);
      if (probe.feed_open) break;
    }
  } finally {
    await detachDebugger(tabId);
  }

  probe = await probeVideo(tabId, payload);
  const feedOpen = Boolean(probe.feed_open);

  return {
    ok: feedOpen,
    clicked: true,
    mode: "cdp_real_mouse",
    video_index: probe.video_index,
    available: probe.available,
    url: probe.url ?? tab.url,
    message: feedOpen
      ? `已点击第 ${probe.video_index} 个搜索结果视频并打开 Feed`
      : `已点击视频，但 Feed 未检测到（URL 应有 modal_id）`,
  };
}
