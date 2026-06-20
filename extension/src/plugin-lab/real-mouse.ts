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
  await sleep(60);
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
}

export function randDelay(min: number, max: number) {
  return min + Math.floor(Math.random() * (max - min + 1));
}
