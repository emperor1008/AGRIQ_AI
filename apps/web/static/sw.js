/* AGRIQ AI service worker: cache-first for core static shell assets. */
const CACHE_NAME = "agriq-static-v2";
const CORE_ASSETS = [
  "/static/css/tokens.css",
  "/static/css/base.css",
  "/static/css/components.css",
  "/static/css/dashboard.css",
  "/static/css/animations.css",
  "/static/css/responsive.css",
  "/static/js/app.js",
  "/static/js/api-client.js",
  "/static/js/assistant.js",
  "/static/js/dashboard.js",
  "/static/js/map.js",
  "/static/js/weather.js",
  "/static/js/leafscan.js",
  "/static/js/pwa.js",
  "/static/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isStatic = url.origin === self.location.origin && url.pathname.startsWith("/static/");
  if (!isStatic || event.request.method !== "GET") return;

  event.respondWith(
    caches.match(event.request).then(
      (cached) =>
        cached ||
        fetch(event.request).then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          return response;
        })
    )
  );
});
