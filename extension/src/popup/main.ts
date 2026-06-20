const stateEl = document.getElementById("state")!;
const wsEl = document.getElementById("ws")!;
const hintEl = document.getElementById("hint")!;
const reconnectBtn = document.getElementById("reconnect")!;

function hintForState(state: string, lastError?: string) {
  if (state === "connected") {
    return "扩展管理页显示 Service Worker（无效）为 MV3 正常休眠，不影响使用。";
  }
  if (lastError?.includes("ERR_CONNECTION_REFUSED") || lastError?.includes("18766")) {
    return "本地服务未启动。请在项目目录运行 npm run dev（端口 18766），然后点「重新连接」。";
  }
  if (lastError) {
    return lastError;
  }
  return "请确认 local-service 已启动（npm run dev，端口 18766）。若刚 build 过，请先在 chrome://extensions 重新加载插件。";
}

async function refresh() {
  try {
    const res = await chrome.runtime.sendMessage({ type: "huoke:get-state" });
    const state = res?.state ?? "disconnected";
    stateEl.textContent =
      state === "connected" ? "已连接本地服务" : state === "connecting" ? "连接中…" : "未连接";
    stateEl.className = `state ${state === "connected" ? "ok" : "bad"}`;
    wsEl.textContent = res?.wsUrl ?? "";
    hintEl.textContent = hintForState(state, res?.lastError);
  } catch {
    stateEl.textContent = "插件后台未响应";
    stateEl.className = "state bad";
    wsEl.textContent = "";
    hintEl.textContent =
      "请先到 chrome://extensions 重新加载 Huoke 插件（加载 extension/dist），再点「重新连接」。";
  }
}

reconnectBtn.addEventListener("click", async () => {
  stateEl.textContent = "连接中…";
  stateEl.className = "state bad";
  hintEl.textContent = "正在尝试连接 local-service…";
  try {
    await chrome.runtime.sendMessage({ type: "huoke:reconnect" });
  } catch {
    /* wake attempt */
  }
  await refresh();
});

refresh();
