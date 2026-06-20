(async () => {
  try {
    await import(chrome.runtime.getURL("__HUOKE_CONTENT_CHUNK__"));
  } catch (error) {
    console.error("[huoke-ext] content import failed", error);
  }
})();
