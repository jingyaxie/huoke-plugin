(function earlyInjectNetworkHook() {
  if (document.documentElement?.dataset?.huokeHookEarly === "1") return;
  if (document.documentElement) {
    document.documentElement.dataset.huokeHookEarly = "1";
  }
  try {
    const src = chrome.runtime.getURL("src/injected/network-hook.js");
    const script = document.createElement("script");
    script.src = src;
    script.type = "text/javascript";
    script.dataset.huokeInjected = "early";
    const root = document.documentElement || document.head;
    if (root) root.appendChild(script);
  } catch (err) {
    console.warn("[huoke-ext] early hook inject failed", err);
  }
})();
