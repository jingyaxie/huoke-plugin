(function () {
  const CHANNEL = "huoke:injected";
  const CONFIG_CHANNEL = "huoke:injected:config";
  const seen = new Set();

  let enabled = true;
  let patterns = [];

  const DEFAULT_PATTERNS = [/\/aweme\//i, /\/comment\//i, /\/search\//i];

  function absoluteUrl(url) {
    try {
      return new URL(String(url || ""), window.location.href).href;
    } catch (_err) {
      return String(url || "");
    }
  }

  function shouldCapture(url) {
    if (!enabled || !url) return false;
    const active = patterns.length ? patterns : DEFAULT_PATTERNS;
    const target = absoluteUrl(url);
    return active.some((pattern) => {
      if (pattern instanceof RegExp) return pattern.test(target);
      if (typeof pattern === "string") return target.includes(pattern);
      return false;
    });
  }

  function emit(payload) {
    window.postMessage({ channel: CHANNEL, payload: { ...payload, url: absoluteUrl(payload.url) } }, "*");
  }

  async function readResponseClone(response) {
    try {
      const clone = response.clone();
      const text = await clone.text();
      if (!text) return undefined;
      try {
        return JSON.parse(text);
      } catch (_err) {
        return undefined;
      }
    } catch (_err) {
      return undefined;
    }
  }

  function captureOnce(meta) {
    const url = absoluteUrl(meta.url);
    if (!shouldCapture(url)) return;
    const isSearchApi =
      /general\/search\/single|general\/search\/stream|search\/item|search\/single/i.test(url);
    const key = `${meta.method || "GET"}:${url}`;
    if (!isSearchApi && seen.has(key)) return;
    if (!isSearchApi) seen.add(key);
    emit({ ...meta, url });
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== CONFIG_CHANNEL) return;
    enabled = event.data.enabled !== false;
    patterns = Array.isArray(event.data.patterns) ? event.data.patterns : [];
    seen.clear();
  });

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    try {
      const request = args[0];
      const url = typeof request === "string" ? request : request.url;
      const body = await readResponseClone(response);
      captureOnce({
        kind: "fetch",
        url,
        method: (typeof request === "object" && request.method) || "GET",
        status: response.status,
        body,
      });
    } catch (_err) {
      // ignore hook errors
    }
    return response;
  };

  const XHR = XMLHttpRequest.prototype;
  const open = XHR.open;
  const send = XHR.send;

  XHR.open = function (method, url, ...rest) {
    this.__huokeMethod = method;
    this.__huokeUrl = absoluteUrl(String(url));
    return open.call(this, method, url, ...rest);
  };

  XHR.send = function (...args) {
    this.addEventListener("load", function () {
      try {
        const url = this.__huokeUrl || absoluteUrl(this.responseURL || "");
        let body;
        try {
          body = JSON.parse(this.responseText);
        } catch (_err) {
          body = undefined;
        }
        captureOnce({
          kind: "xhr",
          url,
          method: this.__huokeMethod || "GET",
          status: this.status,
          body,
        });
      } catch (_err) {
        // ignore
      }
    });
    return send.apply(this, args);
  };
})();
