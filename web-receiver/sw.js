/**
 * ChirpDrop Service Worker
 * ------------------------
 * Caches all application shell assets, the GGWave WebAssembly decoder,
 * and packet framing scripts to provide 100% offline air-gapped operation.
 * Compatible with root hosting and GitHub Pages subdirectories.
 */

const CACHE_NAME = 'chirpdrop-v3';
const ASSETS_TO_CACHE = [
    './',
    './index.html',
    './styles.css',
    './app.js',
    './packet.js',
    './ggwave.js',
    './manifest.json',
    './icon.svg',
    './icon-192.png',
    './icon-512.png'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(async (cache) => {
            console.log('[ServiceWorker] Caching app shell assets');
            // Cache items individually to ensure partial success doesn't fail install
            for (const asset of ASSETS_TO_CACHE) {
                try {
                    await cache.add(asset);
                } catch (err) {
                    console.warn('[ServiceWorker] Failed to cache:', asset, err);
                }
            }
        }).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keyList) => {
            return Promise.all(
                keyList.map((key) => {
                    if (key !== CACHE_NAME) {
                        console.log('[ServiceWorker] Removing old cache', key);
                        return caches.delete(key);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    // Only handle GET requests
    if (event.request.method !== 'GET') return;

    // Cache-first strategy for offline resilience
    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                return cachedResponse;
            }
            return fetch(event.request).then((response) => {
                if (!response || response.status !== 200 || response.type !== 'basic') {
                    return response;
                }
                const responseToCache = response.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, responseToCache);
                });
                return response;
            }).catch(async () => {
                // Offline fallback to index.html for navigation requests
                if (event.request.mode === 'navigate') {
                    const fallback = await caches.match('./index.html');
                    if (fallback) return fallback;
                    return caches.match('./');
                }
            });
        })
    );
});
