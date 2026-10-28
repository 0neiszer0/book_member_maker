import test from 'node:test';
import assert from 'node:assert/strict';
import proxy from '../infra/worker/proxy.mjs';
const env={UPSTREAM_ORIGIN:'https://origin.example.ts.net',ORIGIN_AUTH_SECRET:'s'.repeat(32)};
test('legacy links and OAuth start redirect before creating a cookie on the wrong host',async()=>{
  const original=globalThis.fetch;
  const migrating={...env,PUBLIC_BASE_URL:'https://knu-read.xyz',LEGACY_PUBLIC_ORIGIN:'https://www.knu-read.workers.dev'};
  globalThis.fetch=async()=>{throw new Error('Legacy requests must never reach the origin');};
  try {
    for (const path of ['/login/kakao?next=%2Fdashboard','/shared_topics?token=synthetic']) {
      const response=await proxy.fetch(new Request(migrating.LEGACY_PUBLIC_ORIGIN+path),migrating);
      assert.equal(response.status,302);
      assert.equal(response.headers.get('Location'),migrating.PUBLIC_BASE_URL+path);
      assert.equal(response.headers.get('Cache-Control'),'no-store');
      assert.equal(response.headers.get('Set-Cookie'),null);
    }
    const write=await proxy.fetch(new Request(migrating.LEGACY_PUBLIC_ORIGIN+'/api/member',{method:'POST',body:'synthetic'}),migrating);
    assert.equal(write.status,409);
    assert.equal(write.headers.get('Location'),null);
    for (const [url,status] of [['http://knu-read.xyz/login?next=%2F',308],['http://www.knu-read.workers.dev/login?next=%2F',302]]) {
      const response=await proxy.fetch(new Request(url),migrating);
      assert.equal(response.status,status);
      assert.equal(response.headers.get('Location'),'https://knu-read.xyz/login?next=%2F');
    }
  } finally {globalThis.fetch=original;}
});
test('canonical requests still proxy, and incomplete migration configuration fails closed',async()=>{
  const original=globalThis.fetch;
  const migrating={...env,PUBLIC_BASE_URL:'https://knu-read.xyz',LEGACY_PUBLIC_ORIGIN:'https://www.knu-read.workers.dev'};
  let seen;
  globalThis.fetch=async(url,init)=>{seen={url,init};return new Response('ok');};
  try {
    const response=await proxy.fetch(new Request('https://knu-read.xyz/login/kakao'),migrating);
    assert.equal(response.status,200);
    assert.equal(seen.url.href,env.UPSTREAM_ORIGIN+'/login/kakao');
    assert.equal(seen.init.headers.get('X-App-Origin-Auth'),env.ORIGIN_AUTH_SECRET);
    for (const bad of [{...migrating,PUBLIC_BASE_URL:'https://knu-read.xyz/path'},
      {...migrating,LEGACY_PUBLIC_ORIGIN:''},{...migrating,LEGACY_PUBLIC_ORIGIN:migrating.PUBLIC_BASE_URL}]) {
      assert.equal((await proxy.fetch(new Request('https://www.knu-read.workers.dev/'),bad)).status,503);
    }
  } finally {globalThis.fetch=original;}
});
test('preserves request stream and cookies, strips spoofed headers, preserves SSE and multiple cookies',async()=>{
  const original=globalThis.fetch;
  let seen;
  globalThis.fetch=async(url,init)=>{
    seen={url,init};
    const headers=new Headers({'Content-Type':'text/event-stream'});
    headers.append('Set-Cookie','session=synthetic; Secure; HttpOnly; SameSite=Lax');
    headers.append('Set-Cookie','second=synthetic; Secure');
    return new Response('data: ok\n\n',{headers});
  };
  try {
    const request=new Request('https://public.workers.dev/path?q=1',{method:'POST',body:'payload',headers:{Cookie:'session=fake','X-App-Origin-Auth':'spoof','X-Forwarded-Host':'evil','CF-Connecting-IP':'192.0.2.1'}});
    const result=await proxy.fetch(request,env);
    assert.equal(seen.url.href,'https://origin.example.ts.net/path?q=1');
    assert.equal(seen.init.body,request.body);
    assert.equal(seen.init.headers.get('Cookie'),'session=fake');
    assert.equal(seen.init.headers.get('X-Forwarded-Host'),null);
    assert.equal(seen.init.headers.get('X-App-Origin-Auth'),env.ORIGIN_AUTH_SECRET);
    assert.equal(result.headers.getSetCookie().length,2);
    assert.equal(result.headers.get('Content-Type'),'text/event-stream');
    assert.equal(result.headers.get('Cache-Control'),'no-store');
    assert.equal(await result.text(),'data: ok\n\n');
  } finally {globalThis.fetch=original;}
});
test('rewrites only upstream redirects and fails closed',async()=>{
  const original=globalThis.fetch;
  try {
    for (const [location,expected] of [['https://origin.example.ts.net/x?a=1','https://public.workers.dev/x?a=1'],['https://kauth.kakao.com/oauth/authorize','https://kauth.kakao.com/oauth/authorize']]) {
      globalThis.fetch=async()=>new Response(null,{status:302,headers:{Location:location}});
      const result=await proxy.fetch(new Request('https://public.workers.dev/start'),env);
      assert.equal(result.headers.get('Location'),expected);
    }
    assert.equal((await proxy.fetch(new Request('https://public.workers.dev'),{...env,ORIGIN_AUTH_SECRET:''})).status,503);
  } finally {globalThis.fetch=original;}
});

test('asset misses, private routes and writes keep exact paths and remain uncached', async()=>{
  const original=globalThis.fetch;
  let seen;
  globalThis.fetch=async(url,init)=>{seen={url,init};return new Response('origin',{headers:{'Set-Cookie':'session=synthetic'}});};
  try {
    for (const [path,method] of [['/','GET'],['/admin/dashboard','GET'],['/shared_topics?token=synthetic','GET'],
      ['/api/notifications','GET'],['/uploads/photo.png','GET'],['/static/theme.css','GET'],
      ['/static/_v/'+'0'.repeat(64)+'/lms.css','GET'],['/static/_v/'+'a'.repeat(64)+'/lms.css','POST']]) {
      const result=await proxy.fetch(new Request('https://public.workers.dev'+path,{method}),env);
      assert.equal(seen.url.href,'https://origin.example.ts.net'+path);
      assert.deepEqual(seen.init.cf,{cacheTtl:0,cacheEverything:false});
      assert.equal(result.headers.get('Cache-Control'),'no-store');
      assert.equal(result.headers.get('Set-Cookie'),'session=synthetic');
    }
  } finally {globalThis.fetch=original;}
});

test('origin errors and missing versioned files cannot become immutable cache entries', async()=>{
  const original=globalThis.fetch;
  try {
    for (const status of [404,500]) {
      globalThis.fetch=async()=>new Response('missing',{status,headers:{'Cache-Control':'public,max-age=31536000'}});
      const result=await proxy.fetch(new Request('https://public.workers.dev/static/_v/missing/lms.css'),env);
      assert.equal(result.status,status);
      assert.equal(result.headers.get('Cache-Control'),'no-store');
    }
    globalThis.fetch=async()=>{throw new Error('offline');};
    const result=await proxy.fetch(new Request('https://public.workers.dev/'),env);
    assert.equal(result.status,502);
    assert.equal(result.headers.get('Cache-Control'),'no-store');
  } finally {globalThis.fetch=original;}
});
