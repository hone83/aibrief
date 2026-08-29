
const CACHE = 'brief-v2';
const CORE = ['./', './index.html', './manifest.json',
              './dates.json', './models.json', './search-index.json'];

self.addEventListener('install', function(ev){
  self.skipWaiting();
  ev.waitUntil(caches.open(CACHE).then(function(c){
    return Promise.all(CORE.map(function(u){
      return c.add(u).catch(function(){ /* 아직 없는 파일은 넘어간다 */ });
    }));
  }));
});

self.addEventListener('activate', function(ev){
  ev.waitUntil(caches.keys().then(function(keys){
    return Promise.all(keys.filter(function(k){ return k !== CACHE; })
                           .map(function(k){ return caches.delete(k); }));
  }).then(function(){ return self.clients.claim(); }));
});

// 브리핑 본문과 색인은 매일 바뀐다. 그런데 그냥 fetch를 하면 브라우저의 HTTP 캐시가
// 먼저 답해버려서, 서비스 워커가 "네트워크 먼저"를 해도 어제 것이 온다.
// (깃허브 Pages가 HTML에 10분짜리 캐시를 걸어 두기 때문이다.)
// 그래서 이 파일들만 cache:'reload'로 요청해 HTTP 캐시를 건너뛴다.
function isFresh(url){
  return /\.(html|json)$/.test(url) || url.endsWith('/') ||
         url.indexOf('/index') !== -1;
}

self.addEventListener('fetch', function(ev){
  if(ev.request.method !== 'GET'){ return; }
  var req = ev.request;
  if(req.mode === 'navigate' || isFresh(req.url)){
    try { req = new Request(req.url, {cache: 'reload', credentials: 'same-origin'}); }
    catch(e){ req = ev.request; }
  }
  ev.respondWith(
    fetch(req).then(function(res){
      var copy = res.clone();
      caches.open(CACHE).then(function(c){ c.put(ev.request, copy); });
      return res;
    }).catch(function(){
      return caches.match(ev.request).then(function(hit){
        return hit || caches.match('./index.html');
      });
    })
  );
});
