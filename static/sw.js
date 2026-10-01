// Recruit service worker — enables Web Push + basic offline shell.
self.addEventListener('install', (e) => {
  e.waitUntil(self.skipWaiting());
});
self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener('push', (e) => {
  let data = { title: 'Recruit', body: '' };
  try { data = e.data ? e.data.json() : data; } catch (_) {}
  e.waitUntil(
    self.registration.showNotification(data.title || 'Recruit', {
      body: data.body || '',
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
    })
  );
});
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(self.clients.openWindow('/dashboard'));
});

// Network-first: always fetch live data so the PWA never shows stale feed/hits.
// Falls back to cache only when offline. API/data requests are never cached.
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return; // cross-origin (APIs/CDN) untouched
  if (e.request.method !== 'GET') return;          // GET-only, let everything else through

  e.respondWith(
    fetch(e.request)
      .then((res) => res)
      .catch(() => caches.match(e.request))
  );
});