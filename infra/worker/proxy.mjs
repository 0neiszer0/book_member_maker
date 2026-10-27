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
