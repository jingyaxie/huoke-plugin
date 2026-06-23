(async () => {
  try {
    await import(chrome.runtime.getURL("assets/index.ts-DRMdWd2z.js"));
  } catch (error) {
    console.error("[huoke-ext] content import failed", error);
  }
})();
