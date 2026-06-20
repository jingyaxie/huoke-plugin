import { resolveLabTargetTab } from "./resolve-lab-tab";
import {
  attachDebugger,
  clickMouse,
  detachDebugger,
  moveMouse,
  pressBackspace,
  randDelay,
  selectAllInFocusedField,
  typeText,
} from "./real-mouse";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface ReplyProbe {
  ok?: boolean;
  comment_index?: number;
  comment_count?: number;
  item_center?: { x: number; y: number };
  reply_btn?: { center: { x: number; y: number } } | null;
  message?: string;
  url?: string;
}

interface InputProbe {
  found?: boolean;
  center?: { x: number; y: number };
  placeholder?: string;
  placeholder_visible?: boolean;
  draft_text?: string;
  message?: string;
  url?: string;
}

export async function replyCommentBackground(payload: Record<string, unknown> = {}) {
  const replyText = String(payload.reply_text ?? "").trim();
  if (!replyText) throw new Error("reply_comment: missing reply_text");

  const commentIndex = Math.max(1, Number(payload.comment_index ?? payload.index ?? 1));
  const tab = await resolveLabTargetTab();
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  let probe = (await sendContentPluginLabCommand(tabId, "plugin_lab.reply_comment_probe", {
    comment_index: commentIndex,
  })) as ReplyProbe;

  if (!probe.ok || !probe.item_center) {
    return {
      ok: false,
      comment_index: commentIndex,
      url: probe.url ?? tab.url,
      message: probe.message ?? "未找到目标评论",
    };
  }

  let inputProbe: InputProbe | null = null;

  await attachDebugger(tabId);
  try {
    await moveMouse(tabId, probe.item_center.x, probe.item_center.y);
    await sleep(randDelay(700, 1100));

    probe = (await sendContentPluginLabCommand(tabId, "plugin_lab.reply_comment_probe", {
      comment_index: commentIndex,
    })) as ReplyProbe;

    if (!probe.reply_btn?.center) {
      return {
        ok: false,
        comment_index: commentIndex,
        url: probe.url ?? tab.url,
        message: "hover 后仍未找到回复按钮",
      };
    }

    await moveMouse(tabId, probe.reply_btn.center.x, probe.reply_btn.center.y);
    await sleep(randDelay(200, 350));
    await clickMouse(tabId, probe.reply_btn.center.x, probe.reply_btn.center.y);
    await sleep(randDelay(500, 800));

    const deadline = Date.now() + 5000;
    while (Date.now() < deadline) {
      inputProbe = (await sendContentPluginLabCommand(tabId, "plugin_lab.reply_comment_input_probe", {})) as InputProbe;
      if (inputProbe.found && inputProbe.center) break;
      await sleep(280);
    }

    if (!inputProbe?.found || !inputProbe.center) {
      return {
        ok: false,
        comment_index: commentIndex,
        url: probe.url ?? tab.url,
        message: "回复输入框未出现",
      };
    }

    await clickMouse(tabId, inputProbe.center.x, inputProbe.center.y);
    await sleep(randDelay(350, 550));

    if ((inputProbe.draft_text ?? "").length > 0) {
      await selectAllInFocusedField(tabId);
      await sleep(randDelay(120, 220));
      await pressBackspace(tabId);
      await sleep(randDelay(200, 350));
    }

    await typeText(tabId, replyText, { min: 70, max: 160 });
    await sleep(randDelay(400, 650));
  } finally {
    await detachDebugger(tabId);
  }

  inputProbe = (await sendContentPluginLabCommand(tabId, "plugin_lab.reply_comment_input_probe", {})) as InputProbe;
  const draftText = (inputProbe?.draft_text ?? "").trim();
  const placeholderVisible = Boolean(inputProbe?.placeholder_visible);
  const ok = draftText.length > 0 && !placeholderVisible;

  return {
    ok,
    comment_index: commentIndex,
    mode: "cdp_real_mouse",
    reply_text: replyText,
    draft_text: draftText.slice(0, 120),
    placeholder_visible: placeholderVisible,
    url: inputProbe?.url ?? probe.url ?? tab.url,
    message: ok
      ? `已通过 CDP 逐字输入回复（${draftText.length} 字）`
      : placeholderVisible
        ? "输入框 placeholder 未消失，Draft 状态未同步，请关闭回复框后重试"
        : "输入后未检测到回复文案",
  };
}
