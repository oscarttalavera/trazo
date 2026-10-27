/* Trazo — service worker: guarda la app y el motor en caché para que las
   visitas siguientes carguen al instante y funcione sin conexión. */
"use strict";
const CACHE = "trazo-__CACHE_VERSION__";
const PRECACHE = __PRECACHE__;   // lista generada por tools/build_web.py

// al instalarse guarda la app completa: así funciona sin conexión desde la primera visita
self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(PRECACHE);
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith("trazo-") && k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) return;
  const fresh = req.mode === "navigate" || req.url.endsWith("/py/manifest.json");
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    if (fresh) {   // la página y el manifiesto: primero la red, para recibir actualizaciones
      try {
        const res = await fetch(req);
        if (res.ok) cache.put(req, res.clone());
        return res;
      } catch (_) {
        return (await cache.match(req, { ignoreSearch: true })) || (await cache.match("./")) || Response.error();
      }
    }
    const hit = await cache.match(req, { ignoreSearch: true });   // lo demás (motor, fuentes, ruedas): primero la caché
    if (hit) return hit;
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  })());
});
