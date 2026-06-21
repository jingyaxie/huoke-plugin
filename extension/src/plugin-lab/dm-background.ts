import { resolveLabTabForAction } from "./resolve-lab-tab";
import { detectPlatformFromUrl, isDmSupportedPlatform } from "./platform-hosts";
import { dmUnsupportedMessage } from "./platform-lab-helpers";
import { dmInputMatchesExpected } from "./dm-dom";
import {
  attachDebugger,
  clickMouse,
  detachDebugger,
  insertTextCdp,
  moveMouse,
  pressBackspace,
  pressEnter,
  randDelay,
  selectAllInFocusedField,
  typeText,
} from "./real-mouse";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface DmButtonProbe {
  ok?: boolean;
  panel_open?: boolean;
  center?: { x: number; y: number };
  message?: string;
  url?: string;
}

interface DmInputProbe {
  found?: boolean;
  panel_open?: boolean;
  center?: { x: number; y: number };
  draft_text?: string;
  message?: string;
  url?: string;
}

interface DmSendProbe {
  found?: boolean;
  center?: { x: number; y: number };
  message?: string;
  url?: string;
}

interface DmVerifyProbe {
  ok?: boolean;
  in_chat?: boolean;
  input_cleared?: boolean;
  draft_text?: string;
  chat_preview?: string;
  message?: string;
  url?: string;
}

async function probeButton(tabId: number): Promise<DmButtonProbe> {
  return (await sendContentPluginLabCommand(tabId, "plugin_lab.dm_button_probe", {})) as DmButtonProbe;
}

async function probeInput(tabId: number): Promise<DmInputProbe> {
  return (await sendContentPluginLabCommand(tabId, "plugin_lab.dm_input_probe", {})) as DmInputProbe;
}

async function probeSendButton(tabId: number): Promise<DmSendProbe> {
  return (await sendContentPluginLabCommand(tabId, "plugin_lab.dm_send_probe", {})) as DmSendProbe;
}

async function probeSendVerify(tabId: number, text: string): Promise<DmVerifyProbe> {
  return (await sendContentPluginLabCommand(tabId, "plugin_lab.dm_send_verify", {
    dm_text: text,
  })) as DmVerifyProbe;
}

async function pollSendVerify(tabId: number, text: string, rounds = 6): Promise<DmVerifyProbe> {
  let last: DmVerifyProbe = { ok: false };
  for (let i = 0; i < rounds; i += 1) {
    last = await probeSendVerify(tabId, text);
    if (last.ok) return last;
    await sleep(550);
  }
  return last;
}

async function cdpFocusInput(tabId: number, inputProbe: DmInputProbe) {
  if (!inputProbe.center) return;
  await clickMouse(tabId, inputProbe.center.x, inputProbe.center.y);
  await sleep(randDelay(250, 400));
}

async function cdpSendViaEnter(tabId: number, inputProbe: DmInputProbe): Promise<string> {
  await cdpFocusInput(tabId, inputProbe);
  await pressEnter(tabId);
  return "cdp_enter";
}

async function cdpSendViaClick(tabId: number, sendProbe: DmSendProbe): Promise<string> {
  if (!sendProbe.center) return "cdp_enter";
  await moveMouse(tabId, sendProbe.center.x, sendProbe.center.y);
  await sleep(randDelay(160, 280));
  await clickMouse(tabId, sendProbe.center.x, sendProbe.center.y);
  return "cdp_click_send";
}

/** CDP 发送：优先真实鼠标点发送按钮，否则 CDP Enter（禁止 content JS） */
async function cdpSendAttempt(
  tabId: number,
  inputProbe: DmInputProbe,
  sendProbe: DmSendProbe,
  prefer: "click" | "enter" = "click",
): Promise<string> {
  if (prefer === "click" && sendProbe.found && sendProbe.center) {
    await cdpFocusInput(tabId, inputProbe);
    return cdpSendViaClick(tabId, sendProbe);
  }
  return cdpSendViaEnter(tabId, inputProbe);
}

async function waitForDmInput(tabId: number, timeoutMs = 6000): Promise<DmInputProbe | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const probe = await probeInput(tabId);
    if (probe.found && probe.center) return probe;
    await sleep(350);
  }
  return null;
}

/** 步骤 16：CDP 真实鼠标点击私信按钮 */
export async function clickDmButtonBackground() {
  const tab = await resolveLabTabForAction("plugin_lab.click_dm_btn");
  const platform = detectPlatformFromUrl(tab.url);
  if (!isDmSupportedPlatform(platform)) {
    return {
      ok: false,
      unsupported: true,
      platform,
      message: dmUnsupportedMessage(platform),
    };
  }
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  let status = await probeButton(tabId);
  if (status.panel_open) {
    return {
      ok: true,
      already_open: true,
      mode: "cdp_real_mouse",
      url: status.url ?? tab.url,
      message: "私信输入面板已打开",
    };
  }

  if (!status.ok || !status.center) {
    return {
      ok: false,
      mode: "cdp_real_mouse",
      url: status.url ?? tab.url,
      message: status.message ?? "未找到私信按钮",
    };
  }

  await attachDebugger(tabId);
  try {
    await moveMouse(tabId, status.center.x, status.center.y);
    await sleep(randDelay(220, 380));
    await clickMouse(tabId, status.center.x, status.center.y);
    await sleep(randDelay(900, 1400));
  } finally {
    await detachDebugger(tabId);
  }

  const inputStatus = await waitForDmInput(tabId, 6000);
  const ok = Boolean(inputStatus?.found);
  return {
    ok,
    clicked: true,
    already_open: false,
    mode: "cdp_real_mouse",
    url: inputStatus?.url ?? status.url ?? tab.url,
    message: ok
      ? "已通过 CDP 点击私信按钮并打开输入面板"
      : "已点击私信按钮，但未检测到可见输入框",
  };
}

/** 步骤 17：CDP 输入私信（insertText 优先，避免逐字卡顿） */
export async function inputDmTextBackground(payload: Record<string, unknown> = {}) {
  const text = String(payload.dm_text ?? payload.text ?? "").trim();
  if (!text) throw new Error("input_dm_text: missing dm_text");

  const tab = await resolveLabTabForAction("plugin_lab.input_dm_text");
  const platform = detectPlatformFromUrl(tab.url);
  if (!isDmSupportedPlatform(platform)) {
    return {
      ok: false,
      unsupported: true,
      platform,
      message: dmUnsupportedMessage(platform),
    };
  }
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  const inputProbe = await waitForDmInput(tabId, 5000);
  if (!inputProbe?.found || !inputProbe.center) {
    return {
      ok: false,
      mode: "cdp_real_mouse",
      url: tab.url,
      message: "未找到私信输入框，请先执行步骤 16",
    };
  }

  let method = "cdp_insert_text";

  await attachDebugger(tabId);
  try {
    await clickMouse(tabId, inputProbe.center.x, inputProbe.center.y);
    await sleep(randDelay(300, 450));

    if ((inputProbe.draft_text ?? "").length > 0) {
      await selectAllInFocusedField(tabId);
      await sleep(randDelay(100, 180));
      await pressBackspace(tabId);
      await sleep(randDelay(150, 280));
    }

    try {
      await insertTextCdp(tabId, text);
    } catch {
      method = "cdp_type_char";
      await typeText(tabId, text, { min: 35, max: 70 });
    }
    await sleep(randDelay(350, 500));
  } finally {
    await detachDebugger(tabId);
  }

  const after = await probeInput(tabId);
  const typedPreview = (after.draft_text ?? "").trim();
  const verified = dmInputMatchesExpected(text, typedPreview);

  return {
    ok: verified || method === "cdp_insert_text",
    mode: "cdp_real_mouse",
    method,
    dm_text: text,
    typed_preview: typedPreview.slice(0, 120) || text.slice(0, 120),
    verified,
    url: after.url ?? tab.url,
    message: verified
      ? `已通过 CDP 输入私信（${text.length} 字）`
      : "CDP 已写入私信，若界面可见内容可继续步骤 18",
  };
}

/** 步骤 18：CDP 点击发送或 Enter（对齐 Python _human_dm_on_profile） */
export async function sendDmBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTabForAction("plugin_lab.send_dm");
  const platform = detectPlatformFromUrl(tab.url);
  if (!isDmSupportedPlatform(platform)) {
    return {
      ok: false,
      unsupported: true,
      platform,
      message: dmUnsupportedMessage(platform),
    };
  }
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  const inputProbeInitial = await probeInput(tabId);
  if (!inputProbeInitial.found) {
    return {
      ok: false,
      mode: "cdp_real_mouse",
      url: tab.url,
      message: "私信输入框不可见，请先执行步骤 16–17",
    };
  }

  const expectedText = String(
    payload.dm_text ?? payload.text ?? inputProbeInitial.draft_text ?? "",
  ).trim();
  if (!expectedText) {
    return {
      ok: false,
      mode: "cdp_real_mouse",
      url: tab.url,
      message: "输入框为空，请先执行步骤 17 输入私信文案",
    };
  }

  let sendProbe = await probeSendButton(tabId);
  let method = "cdp_enter";
  let inputProbe = inputProbeInitial;

  await attachDebugger(tabId);
  try {
    method = await cdpSendAttempt(tabId, inputProbe, sendProbe, "click");
    await sleep(randDelay(900, 1300));
  } finally {
    await detachDebugger(tabId);
  }

  let verify = await pollSendVerify(tabId, expectedText, 4);
  if (!verify.ok) {
    sendProbe = await probeSendButton(tabId);
    inputProbe = await probeInput(tabId);

    await attachDebugger(tabId);
    try {
      const retryPrefer = method === "cdp_click_send" ? "enter" : "click";
      const retryMethod = await cdpSendAttempt(tabId, inputProbe, sendProbe, retryPrefer);
      method = `${method}+retry_${retryMethod}`;
      await sleep(randDelay(1200, 1800));
    } finally {
      await detachDebugger(tabId);
    }

    verify = await pollSendVerify(tabId, expectedText, 6);
  }

  return {
      ok: Boolean(verify.ok),
      mode: "cdp_real_mouse",
      method,
      in_chat: verify.in_chat,
      input_cleared: verify.input_cleared,
      draft_text: verify.draft_text,
      chat_preview: verify.chat_preview,
      dm_text: expectedText,
      url: verify.url ?? tab.url,
      message:
        verify.message ??
        (verify.ok ? "私信已发送并在聊天记录中验证" : "发送失败，输入框内容仍在或聊天记录未出现"),
  };
}
