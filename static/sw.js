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