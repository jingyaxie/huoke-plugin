(function () {
  'use strict';
  (async () => {
    await import(chrome.runtime.getURL("assets/index.ts-CdYASeNo.js"));
  })().catch((error) => console.error('[huoke-ext] content import failed', error));
})();
