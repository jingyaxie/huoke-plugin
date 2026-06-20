(() => {
  const meta = window.__ANTIBOT_STEALTH_META__ || {};
  const define = (object, key, value) => {
    try {
      Object.defineProperty(object, key, { get: () => value, configurable: true });
    } catch (_) {}
  };

  // navigator.webdriver
  define(navigator, "webdriver", undefined);
  try {
    delete Object.getPrototypeOf(navigator).webdriver;
  } catch (_) {}

  // Playwright / CDP artifacts
  try {
    const cdcProps = Object.getOwnPropertyNames(window).filter((name) => /^cdc_|^__pw/.test(name));
    for (const name of cdcProps) {
      try {
        delete window[name];
      } catch (_) {}
    }
  } catch (_) {}

  // window.chrome
  if (!window.chrome) {
    window.chrome = {};
  }
  if (!window.chrome.runtime) {
    window.chrome.runtime = {
      connect: () => {},
      sendMessage: () => {},
      onMessage: { addListener: () => {}, removeListener: () => {} },
    };
  }
  if (!window.chrome.app) {
    window.chrome.app = {
      isInstalled: false,
      InstallState: { DISABLED: "disabled", INSTALLED: "installed", NOT_INSTALLED: "not_installed" },
      RunningState: { CANNOT_RUN: "cannot_run", READY_TO_RUN: "ready_to_run", RUNNING: "running" },
    };
  }

  const languages = meta.languages || ["zh-CN", "zh", "en-US", "en"];
  const platform = meta.platform || "MacIntel";
  const hardwareConcurrency = meta.hardware_concurrency || 8;
  const deviceMemory = meta.device_memory || 8;
  const maxTouchPoints = meta.max_touch_points ?? 0;

  define(navigator, "languages", languages);
  define(navigator, "language", languages[0] || "zh-CN");
  define(navigator, "platform", platform);
  define(navigator, "hardwareConcurrency", hardwareConcurrency);
  define(navigator, "deviceMemory", deviceMemory);
  define(navigator, "maxTouchPoints", maxTouchPoints);

  // plugins / mimeTypes length (headless often returns 0)
  const pluginData = [
    { name: "Chrome PDF Plugin", filename: "internal-pdf-viewer", description: "Portable Document Format" },
    { name: "Chrome PDF Viewer", filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai", description: "" },
    { name: "Native Client", filename: "internal-nacl-plugin", description: "" },
  ];
  const fakePlugins = Object.assign(pluginData, { item: (i) => pluginData[i], namedItem: (name) => pluginData.find((p) => p.name === name) });
  const mimeTypes = Object.assign([{ type: "application/pdf", suffixes: "pdf", description: "" }], {
    item: (i) => ({ type: "application/pdf" }),
    namedItem: (type) => ({ type }),
  });
  define(navigator, "plugins", fakePlugins);
  define(navigator, "mimeTypes", mimeTypes);

  // navigator.userAgentData — 抖音等用其上报 browser_platform / os_name
  const chromeMajor = String(meta.chrome_major || "131");
  const uaPlatform = meta.ua_data_platform || "macOS";
  const uaPlatformVersion = meta.ua_data_platform_version || "13.0.0";
  const uaBrands = [
    { brand: "Google Chrome", version: chromeMajor },
    { brand: "Chromium", version: chromeMajor },
    { brand: "Not_A Brand", version: "24" },
  ];
  const fakeUaData = {
    brands: uaBrands,
    mobile: false,
    platform: uaPlatform,
    getHighEntropyValues: async () => ({
      architecture: "x86",
      bitness: "64",
      brands: uaBrands,
      fullVersionList: uaBrands.map((item) => ({
        brand: item.brand,
        version: `${chromeMajor}.0.0.0`,
      })),
      mobile: false,
      model: "",
      platform: uaPlatform,
      platformVersion: uaPlatformVersion,
      uaFullVersion: `${chromeMajor}.0.0.0`,
      wow64: false,
    }),
  };
  define(navigator, "userAgentData", fakeUaData);

  // permissions.query for notifications
  if (navigator.permissions && navigator.permissions.query) {
    const originalQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (parameters) => {
      if (parameters && parameters.name === "notifications") {
        return Promise.resolve({ state: Notification.permission, onchange: null });
      }
      return originalQuery(parameters);
    };
  }

  // iframe contentWindow
  try {
    const elementDescriptor = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, "contentWindow");
    if (elementDescriptor && elementDescriptor.get) {
      Object.defineProperty(HTMLIFrameElement.prototype, "contentWindow", {
        get: function () {
          const win = elementDescriptor.get.call(this);
          if (win) {
            try {
              define(win.navigator, "webdriver", undefined);
            } catch (_) {}
          }
          return win;
        },
      });
    }
  } catch (_) {}

  // WebGL vendor / renderer
  const webglVendor = meta.webgl_vendor || "Intel Inc.";
  const webglRenderer = meta.webgl_renderer || "Intel Iris OpenGL Engine";
  const patchWebGL = (contextPrototype) => {
    if (!contextPrototype || !contextPrototype.getParameter) return;
    const getParameter = contextPrototype.getParameter;
    contextPrototype.getParameter = function (parameter) {
      if (parameter === 37445) return webglVendor;
      if (parameter === 37446) return webglRenderer;
      return getParameter.call(this, parameter);
    };
  };
  try {
    patchWebGL(WebGLRenderingContext && WebGLRenderingContext.prototype);
    patchWebGL(WebGL2RenderingContext && WebGL2RenderingContext.prototype);
  } catch (_) {}

  // outer/inner dimensions sanity
  if (window.outerWidth === 0 && window.innerWidth > 0) {
    define(window, "outerWidth", window.innerWidth);
    define(window, "outerHeight", window.innerHeight + (meta.outer_height_offset || 88));
  }
})();
