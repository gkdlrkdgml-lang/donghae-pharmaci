// 동해시 의료기관 운영현황 — 오프라인 대비용 서비스 워커
// 원칙: 항상 인터넷에서 최신 내용을 먼저 받고, 연결이 안 될 때만 마지막으로 받은 내용을 보여 줍니다.
const CACHE = "dh-med-v1";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon-192.png"];
const LIBS = ["cdnjs.cloudflare.com", "cdn.jsdelivr.net"];   // 지도 라이브러리·글꼴

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const same = url.origin === location.origin;
  if (!same && !LIBS.includes(url.hostname)) return;          // 지도 타일 등은 그대로 통과(저장하지 않음)
  const key = same ? url.origin + url.pathname : req.url;     // ?t=시각 같은 캐시 회피 값은 떼고 저장
  if (!same) {                                                // 라이브러리: 저장본 먼저, 뒤에서 새로 받음
    e.respondWith(caches.open(CACHE).then(c => c.match(key).then(hit => {
      const net = fetch(req).then(r => { if (r && (r.ok || r.type === "opaque")) c.put(key, r.clone()); return r; });
      return hit || net;
    })));
    return;
  }
  e.respondWith(fetch(req).then(r => {                        // 페이지·데이터: 인터넷 먼저
    if (r && r.ok) { const cp = r.clone(); caches.open(CACHE).then(c => c.put(key, cp)); }
    return r;
  }).catch(() => caches.open(CACHE).then(c => c.match(key)).then(hit => hit || (req.mode === "navigate" ? caches.match("index.html") : Response.error()))));
});
