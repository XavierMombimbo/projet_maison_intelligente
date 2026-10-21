{% load static %}
const CACHE = 'sentinelle-public-v2-brand';
const LOGO = '{% static "icons/sentinelle.svg" %}';
const OFFLINE = '/hors-ligne/';
self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll([OFFLINE, LOGO])));
});
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys
    .filter((key) => key.startsWith('sentinelle-public-') && key !== CACHE)
    .map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});
// Never cache authenticated pages, API responses, captures or POST requests.
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  if (new URL(event.request.url).origin !== self.location.origin) return;
  if (event.request.url === new URL(LOGO, self.location.origin).href) {
    event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
    return;
  }
  if (event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
