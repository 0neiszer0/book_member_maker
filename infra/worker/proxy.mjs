export default {
  async fetch(request, env) {
    let upstream;
    try {
      upstream = new URL(env.UPSTREAM_ORIGIN);
      if (upstream.protocol !== 'https:' || upstream.username || upstream.password ||
          upstream.pathname !== '/' || upstream.search || upstream.hash ||
          !env.ORIGIN_AUTH_SECRET || env.ORIGIN_AUTH_SECRET.length < 32) throw new Error();
    } catch {
      return new Response('Proxy configuration unavailable', {status: 503});
    }
    const incoming = new URL(request.url);
    // Only bundled public CSS/JS and the existing club preview bypass Funnel.
    // Authenticated HTML, APIs, uploads and unknown paths always use the origin.
    if (env.ASSETS && ['GET', 'HEAD'].includes(request.method) &&
        /^\/static\/(?:[\w-]+\.(?:css|js)|og\/club-preview\.png)$/.test(incoming.pathname)) {
      const assetHeaders = new Headers();
      for (const name of ['Accept-Encoding', 'If-None-Match', 'If-Modified-Since', 'Range', 'If-Range']) {
        const value = request.headers.get(name);
        if (value) assetHeaders.set(name, value);
      }
      const asset = await env.ASSETS.fetch(new Request(incoming, {
        method: request.method, headers: assetHeaders,
      }));
      if ([200, 206, 304].includes(asset.status)) {
        const result = new Response(asset.body, asset);
        // Revalidate against the CDN so a UI deployment cannot leave stale CSS/JS.
        result.headers.set('Cache-Control', 'public, max-age=0, must-revalidate');
        result.headers.set('X-Content-Type-Options', 'nosniff');
        result.headers.set('X-Frame-Options', 'DENY');
        result.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
        result.headers.set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
        result.headers.delete('Set-Cookie');
        result.headers.delete('X-App-Origin-Auth');
        return result;
      }
    }
    const target = new URL(upstream);
    target.pathname = incoming.pathname;
    target.search = incoming.search;
    const headers = new Headers(request.headers);
    for (const name of [...headers.keys()]) {
      if (/^(x-app-|x-forwarded-|x-real-ip$|forwarded$|host$|cf-connecting-ip$|true-client-ip$)/i.test(name)) headers.delete(name);
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
