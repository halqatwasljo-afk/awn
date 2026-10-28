self.addEventListener('install', (e) => {
  console.log('[Service Worker] Install');
});

self.addEventListener('fetch', (e) => {
  // نترك الطلبات تمر بشكل طبيعي (لا تخزين مؤقت)
});