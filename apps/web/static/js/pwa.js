/**
 * AGRIQ AI — PWA registration.
 * Registers the service worker when supported; the manifest is linked
 * from the base template.
 */
(function (global) {
  "use strict";

  if (!("serviceWorker" in navigator)) return;

  global.addEventListener("load", function () {
    navigator.serviceWorker.register("/static/sw.js").catch(function () {
      /* Registration is best-effort; the app works without it. */
    });
  });
})(window);
