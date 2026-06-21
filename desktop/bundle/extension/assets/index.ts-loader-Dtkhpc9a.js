(function () {
  'use strict';
  (async () => {
    await import(chrome.runtime.getURL("assets/index.ts-DjkE4qN4.js"));
  })().catch((error) => console.error('[huoke-ext] content import failed', error));
})();
