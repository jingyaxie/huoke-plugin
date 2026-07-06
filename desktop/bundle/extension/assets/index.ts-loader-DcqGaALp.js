(function () {
  'use strict';
  (async () => {
    await import(chrome.runtime.getURL("assets/index.ts-D_Kq8aG3.js"));
  })().catch((error) => console.error('[huoke-ext] content import failed', error));
})();
