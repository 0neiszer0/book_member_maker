export default {
  async fetch(request, env) {
    let upstream;
    let publicOrigin;
    let legacyOrigin;
    try {
      upstream = new URL(env.UPSTREAM_ORIGIN);
      if (upstream.protocol !== 'https:' || upstream.username || upstream.password ||
          upstream.pathname !== '/' || upstream.search || upstream.hash ||
          !env.ORIGIN_AUTH_SECRET || env.ORIGIN_AUTH_SECRET.length < 32) throw new Error();
      if (env.PUBLIC_BASE_URL || env.LEGACY_PUBLIC_ORIGIN) {
        const origins = [env.PUBLIC_BASE_URL, env.LEGACY_PUBLIC_ORIGIN].map(value => {
          const url = new URL(value);
          if (url.protocol !== 'https:' || url.username || url.password ||
              url.pathname !== '/' || url.search || url.hash) throw new Error();
          return url.origin;
        });
        [publicOrigin, legacyOrigin] = origins;
        if (publicOrigin === legacyOrigin) throw new Error();
      }
    } catch {
      return new Response('Proxy configuration unavailable', {status: 503, headers: {'Cache-Control': 'no-store'}});
    }
    const incoming = new URL(request.url);
    if (publicOrigin && incoming.protocol === 'http:' && incoming.host === new URL(publicOrigin).host) {
      return new Response(null, {status: 308, headers: {
        Location: publicOrigin + incoming.pathname + incoming.search, 'Cache-Control': 'no-store'}});
    }
    // Start OAuth on the canonical host so its callback receives the same cookie.
    // Do not replay an old open form's write across hosts with different sessions.
    if (legacyOrigin && incoming.host === new URL(legacyOrigin).host) {
      const destination = publicOrigin + incoming.pathname + incoming.search;
      if (['GET', 'HEAD'].includes(request.method)) {
        return new Response(null, {status: 302, headers: {Location: destination, 'Cache-Control': 'no-store'}});
      }
      return new Response('사이트 주소가 변경되었습니다. https://' + new URL(publicOrigin).host +
        ' 에서 다시 로그인한 뒤 작성해 주세요.',
        {status: 409, headers: {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store'}});
    }
    // Exact public versioned files are served by asset-first routing before this
    // script. A miss (including an older release) uses real origin files below;
    // never alias a missing version to current bytes or cache an origin error.
    const target = new URL(upstream);
    target.pathname = incoming.pathname;
    target.search = incoming.search;
    const headers = new Headers(request.headers);
    for (const name of [...headers.keys()]) {
      if (name.toLowerCase() !== 'x-app-csrf' && /^(x-app-|x-forwarded-|x-real-ip$|forwarded$|host$|cf-connecting-ip$|true-client-ip$)/i.test(name)) headers.delete(name);
    }
    headers.set('X-App-Origin-Auth', env.ORIGIN_AUTH_SECRET);
    const clientIP = request.headers.get('CF-Connecting-IP');
    if (clientIP) headers.set('X-App-Client-IP', clientIP);
    const init = {
      method: request.method, headers, redirect: 'manual',
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
      cf: {cacheTtl: 0, cacheEverything: false},
    };
    try {
      const response = await fetch(target, init);
      const result = new Response(response.body, response);
      const location = result.headers.get('Location');
      if (location) {
        const destination = new URL(location, target);
        if (destination.origin === upstream.origin) {
          result.headers.set('Location', incoming.origin + destination.pathname + destination.search + destination.hash);
        }
      }
      result.headers.set('Cache-Control', 'no-store');
      result.headers.delete('X-App-Origin-Auth');
      return result;
    } catch {
      return new Response('Upstream unavailable', {status: 502, headers: {'Cache-Control': 'no-store'}});
    }
  },
};
