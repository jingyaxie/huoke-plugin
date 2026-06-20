import { resolveLabTargetTab } from "./resolve-lab-tab";
import {
  attachDebugger,
  clickMouse,
  detachDebugger,
  insertTextCdp,
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
  item_rect?: { top: number; left: number; width: number; height: number };
  item_center?: { x: number; y: number };
  hover_point?: { x: number; y: number };
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
  const commentId = String(payload.comment_id ?? "").trim();
  const commentText = String(payload.comment_text ?? "").trim();
  const scrollRounds = Math.max(1, Math.min(Number(payload.scroll_rounds ?? 12), 24));
  const tab = await resolveLabTargetTab();
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  const probePayload = {
    comment_index: commentIndex,
    comment_id: commentId || undefined,
    comment_text: commentText || undefined,
    scroll_rounds: scrollRounds,
  };

  let probe = (await sendContentPluginLabCommand(tabId, "plugin_lab.reply_comment_probe", probePayload)) as ReplyProbe;

  if (!probe.ok || !probe.item_center) {
    return {
      ok: false,
      comment_index: commentIndex,
      url: probe.url ?? tab.url,
      message: probe.message ?? "未找到目标评论",
    };
  }

  let inputProbe: InputProbe | null = null;
  let typedMethod = "cdp_insert_text";

  // 先用 content hover 触发 React 显示「回复」按钮（不依赖 debugger）
  for (let attempt = 0; attempt < 3 && !probe.reply_btn?.center; attempt += 1) {
    probe = (await sendContentPluginLabCommand(tabId, "plugin_lab.reply_comment_hover", probePayload)) as ReplyProbe;
    if (probe.reply_btn?.center) break;
    await sleep(randDelay(350, 550));
  }

  await attachDebugger(tabId);
  try {
    const hoverPoint =
      probe.hover_point ??
      (probe.item_rect
        ? {
            x: probe.item_rect.left + probe.item_rect.width * 0.55,
            y: probe.item_rect.top + probe.item_rect.height * 0.55,
          }
        : probe.item_center);

    for (let attempt = 0; attempt < 6 && !probe.reply_btn?.center; attempt += 1) {
      if (hoverPoint) {
        await moveMouse(tabId, hoverPoint.x, hoverPoint.y);
        await sleep(randDelay(280, 450));
      }

      probe = (await sendContentPluginLabCommand(tabId, "plugin_lab.reply_comment_hover", probePayload)) as ReplyProbe;

      if (probe.reply_btn?.center) break;
      await sleep(randDelay(400, 650));
    }

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

    try {
      await insertTextCdp(tabId, replyText);
    } catch {
      typedMethod = "cdp_type_char";
      await typeText(tabId, replyText, { min: 70, max: 160 });
    }
    await sleep(randDelay(400, 650));
  } finally {
    await detachDebugger(tabId);
  }

  inputProbe = (await sendContentPluginLabCommand(tabId, "plugin_lab.reply_comment_input_probe", {})) as InputProbe;
  const draftText = (inputProbe?.draft_text ?? "").trim();
  const placeholderVisible = Boolean(inputProbe?.placeholder_visible);
  const normalizedDraft = draftText.replace(/\s+/g, "");
  const normalizedExpected = replyText.replace(/\s+/g, "");
  const textOk =
    normalizedDraft === normalizedExpected ||
    (normalizedDraft.includes(normalizedExpected) && normalizedDraft.length <= normalizedExpected.length + 2);
  const ok = textOk && !placeholderVisible;

  return {
    ok,
    comment_index: commentIndex,
    mode: "cdp_real_mouse",
    method: typedMethod,
    reply_text: replyText,
    draft_text: draftText.slice(0, 120),
    placeholder_visible: placeholderVisible,
    url: inputProbe?.url ?? probe.url ?? tab.url,
    message: ok
      ? `已通过 CDP 输入回复（${replyText.length} 字）`
      : draftText.length > normalizedExpected.length + 1
        ? "检测到重复字符，请关闭回复框后重试"
        : placeholderVisible
          ? "输入框 placeholder 未消失，请关闭回复框后重试"
          : "输入后未检测到回复文案",
  };
}
