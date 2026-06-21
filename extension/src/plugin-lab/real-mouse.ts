function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function attachDebugger(tabId: number) {
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (!msg.includes("Already attached")) throw err;
  }
}

export async function detachDebugger(tabId: number) {
  try {
    await chrome.debugger.detach({ tabId });
  } catch {
    // ignore
  }
}

export async function moveMouse(tabId: number, x: number, y: number) {
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: Math.round(x),
    y: Math.round(y),
    modifiers: 0,
  });
}

export async function clickMouse(tabId: number, x: number, y: number) {
  const px = Math.round(x);
  const py = Math.round(y);
  await moveMouse(tabId, px, py);
  await sleep(randDelay(120, 220));
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: px,
    y: py,
    button: "left",
    clickCount: 1,
  });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: px,
    y: py,
    button: "left",
    clickCount: 1,
  });
  await sleep(randDelay(80, 160));
}

export function randDelay(min: number, max: number) {
  return min + Math.floor(Math.random() * (max - min + 1));
}

const MOD_ALT = 1;
const MOD_CTRL = 2;
const MOD_META = 4;
const MOD_SHIFT = 8;

export async function pressKey(
  tabId: number,
  key: string,
  options: { modifiers?: number; code?: string } = {},
) {
  const modifiers = options.modifiers ?? 0;
  const code = options.code ?? key;
  const base = { key, code, modifiers, windowsVirtualKeyCode: 0, nativeVirtualKeyCode: 0 };

  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    ...base,
    type: "keyDown",
  });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    ...base,
    type: "keyUp",
  });
}

export async function typeCharacter(tabId: number, ch: string) {
  const codePoint = ch.codePointAt(0) ?? 0;
  const keyBase = {
    key: ch,
    windowsVirtualKeyCode: codePoint,
    nativeVirtualKeyCode: codePoint,
  };

  // keyDown/keyUp 不要带 text，否则 Draft.js 会与 char 事件重复插入（「同意」→「同同意意」）
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    ...keyBase,
    type: "keyDown",
    text: "",
    unmodifiedText: "",
  });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    ...keyBase,
    type: "char",
    text: ch,
    unmodifiedText: ch,
  });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    ...keyBase,
    type: "keyUp",
    text: "",
    unmodifiedText: "",
  });
}

export async function insertTextCdp(tabId: number, text: string) {
  await chrome.debugger.sendCommand({ tabId }, "Input.insertText", { text });
}

export async function typeText(
  tabId: number,
  text: string,
  charDelayMs: { min: number; max: number } = { min: 70, max: 160 },
) {
  for (const ch of text) {
    await typeCharacter(tabId, ch);
    await sleep(randDelay(charDelayMs.min, charDelayMs.max));
  }
}

export async function selectAllInFocusedField(tabId: number) {
  const info = await chrome.runtime.getPlatformInfo();
  const mod = info.os === "mac" ? MOD_META : MOD_CTRL;
  await pressKey(tabId, "a", { modifiers: mod, code: "KeyA" });
}

export async function pressBackspace(tabId: number) {
  await pressKey(tabId, "Backspace", { code: "Backspace" });
}

export async function pressEnter(tabId: number) {
  const base = {
    key: "Enter",
    code: "Enter",
    text: "\r",
    unmodifiedText: "\r",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
    modifiers: 0,
  };
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    ...base,
    type: "keyDown",
  });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    ...base,
    type: "char",
  });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", {
    ...base,
    type: "keyUp",
  });
}
