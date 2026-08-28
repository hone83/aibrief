
const CACHE = 'brief-v1';
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

self.addEventListener('fetch', function(ev){
  if(ev.request.method !== 'GET'){ return; }
  ev.respondWith(
    fetch(ev.request).then(function(res){
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
