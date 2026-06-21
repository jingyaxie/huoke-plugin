import { humanPace } from "./search-input";
import { resolveLabTabForAction } from "./resolve-lab-tab";
import {
  attachDebugger,
  clickMouse,
  detachDebugger,
  moveMouse,
} from "./real-mouse";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface ProfileProbe {
  ok?: boolean;
  center?: { x: number; y: number };
  video_index?: number;
  available?: number;
  feed_open?: boolean;
  is_profile_feed?: boolean;
  aweme_id?: string;
  url?: string;
  message?: string;
}

interface ClickResult {
  ok?: boolean;
  feed_open?: boolean;
  mode?: string;
  video_index?: number;
  aweme_id?: string;
  url?: string;
  message?: string;
  attempt?: number;
}

async function probeProfileVideo(
  tabId: number,
  payload: Record<string, unknown>,
): Promise<ProfileProbe> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.profile_video_probe",
    payload,
    { skipPreflight: true },
  )) as ProfileProbe;
}

async function prepareProfilePage(tabId: number) {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.prepare_profile_video",
    {},
    { skipPreflight: true },
  )) as { ok?: boolean; card_count?: number; message?: string };
}

async function domClickProfile(
  tabId: number,
  payload: Record<string, unknown>,
): Promise<ClickResult> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.profile_video_dom_click",
    payload,
    { skipPreflight: true },
  )) as ClickResult;
}

async function waitProfileFeedOpen(tabId: number, videoIndex: number, maxPolls = 30): Promise<boolean> {
  for (let i = 0; i < maxPolls; i += 1) {
    await sleep(220 + i * 45);
    const status = await probeProfileVideo(tabId, { video_index: videoIndex, status_only: true });
    if (status.is_profile_feed || status.feed_open) return true;
  }
  const status = await probeProfileVideo(tabId, { video_index: videoIndex, status_only: true });
  return Boolean(status.is_profile_feed || status.feed_open);
}

async function cdpClickAt(tabId: number, x: number, y: number): Promise<void> {
  await attachDebugger(tabId);
  try {
    await moveMouse(tabId, x, y);
    await sleep(humanPace.mouseHover());
    await clickMouse(tabId, x, y);
    await sleep(humanPace.posterClick());
  } finally {
    await detachDebugger(tabId);
  }
}

/** 主页作品列表：点击第 N 个视频进入 Feed 浮层 */
export async function clickProfileVideoBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTabForAction("plugin_lab.click_profile_video");
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;
  const videoIndex = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  let awemeHint = String(payload.aweme_id ?? payload.aweme_hint ?? "").trim();
  let lastMessage = "未打开主页视频浮层";
  let lastUrl = tab.url ?? "";

  for (let attempt = 1; attempt <= 4; attempt += 1) {
    const prep = await prepareProfilePage(tabId);
    if (!prep.ok) {
      lastMessage = prep.message ?? "主页作品列表未就绪";
      await sleep(800 + attempt * 350);
      continue;
    }

    const probe = await probeProfileVideo(tabId, {
      ...payload,
      video_index: videoIndex,
      aweme_id: awemeHint,
    });
    lastUrl = probe.url ?? lastUrl;
    if (!awemeHint && probe.aweme_id) awemeHint = probe.aweme_id;

    if (probe.feed_open) {
      return {
        ok: true,
        feed_open: true,
        mode: "already_open",
        video_index: videoIndex,
        aweme_id: awemeHint || probe.aweme_id,
        url: lastUrl,
        attempt,
        message: "主页视频浮层已打开",
      };
    }

    if (probe.ok && probe.center) {
      await cdpClickAt(tabId, probe.center.x, probe.center.y);
      if (await waitProfileFeedOpen(tabId, videoIndex)) {
        return {
          ok: true,
          clicked: true,
          feed_open: true,
          mode: "cdp_real_mouse",
          video_index: probe.video_index ?? videoIndex,
          aweme_id: awemeHint || probe.aweme_id,
          url: lastUrl,
          attempt,
          message: `已点击主页第 ${probe.video_index ?? videoIndex} 个视频（CDP）`,
        };
      }
      lastMessage = "CDP 点击后未进入视频浮层";
    } else {
      lastMessage = probe.message ?? "未找到主页视频卡片";
    }

    const domFallback = await domClickProfile(tabId, {
      ...payload,
      video_index: videoIndex,
      aweme_id: awemeHint,
    });
    lastUrl = domFallback.url ?? lastUrl;
    if (domFallback.ok && domFallback.feed_open) {
      return { ...domFallback, attempt, aweme_id: awemeHint || domFallback.aweme_id };
    }

    lastMessage = domFallback.message ?? lastMessage;
    await sleep(1000 + attempt * 400);
  }

  return {
    ok: false,
    feed_open: false,
    video_index: videoIndex,
    aweme_id: awemeHint,
    url: lastUrl,
    message: lastMessage,
  };
}
