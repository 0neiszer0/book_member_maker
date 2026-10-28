'use strict';
// Push only. No fetch handler or offline cache of member pages.
self.addEventListener('push', event => {
  let data = {}; try { data = event.data.json(); } catch (_) {}
  const url = new URL(typeof data.url === 'string' ? data.url : '/notifications', self.location.origin);
  const safe = url.origin === self.location.origin ? url.pathname + url.search + url.hash : '/notifications';
  event.waitUntil(self.registration.showNotification('책반우', {
    body: '새 알림이 있습니다. 눌러서 확인해주세요.', tag: String(data.id || 'bookmembers'),
    data: {url:safe}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const url = new URL(event.notification.data?.url || '/notifications', self.location.origin);
    if (url.origin !== self.location.origin) return;
    const windows = await clients.matchAll({type:'window',includeUncontrolled:true});
    const target=windows.find(w=>new URL(w.url).origin===self.location.origin);
    if(target){await target.navigate(url.href);await target.focus();}else await clients.openWindow(url.href);
  })());
});
