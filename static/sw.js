const CACHE = 'fleetpod-shell-v1';
const SHELL = ['/', '/static/app.css', '/static/app.js', '/static/manifest.json'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request).then(response => {
    if (response.ok && (url.pathname.startsWith('/static/') || url.pathname === '/')) {
      const copy = response.clone();
      caches.open(CACHE).then(cache => cache.put(event.request, copy));
    }
    return response;
  })));
});
