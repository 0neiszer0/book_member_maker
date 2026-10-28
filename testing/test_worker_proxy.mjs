import test from 'node:test';
import assert from 'node:assert/strict';
import proxy from '../infra/worker/proxy.mjs';
const env={UPSTREAM_ORIGIN:'https://origin.example.ts.net',ORIGIN_AUTH_SECRET:'s'.repeat(32)};
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

test('bundled public assets skip Funnel and never forward credentials', async()=>{
  const original=globalThis.fetch;
  let seen;
  globalThis.fetch=async()=>{throw new Error('Funnel should not be called');};
  const assets={fetch:async request=>{
    seen=request;
    return new Response('body{}',{headers:{'Content-Type':'text/css',ETag:'"asset-v1"'}});
  }};
  try {
    const result=await proxy.fetch(new Request('https://public.workers.dev/static/theme.css?v=2',{
      headers:{Cookie:'session=private',Authorization:'Bearer private','X-App-Origin-Auth':'spoof','If-None-Match':'"old"'},
    }),{...env,ASSETS:assets});
    assert.equal(seen.headers.get('Cookie'),null);
    assert.equal(seen.headers.get('Authorization'),null);
    assert.equal(seen.headers.get('X-App-Origin-Auth'),null);
    assert.equal(seen.headers.get('If-None-Match'),'"old"');
    assert.equal(new URL(seen.url).search,'?v=2');
    assert.equal(result.headers.get('Cache-Control'),'public, max-age=0, must-revalidate');
    assert.equal(result.headers.get('ETag'),'"asset-v1"');
    assert.equal(result.headers.get('Set-Cookie'),null);
    assert.equal(await result.text(),'body{}');
  } finally {globalThis.fetch=original;}
});

test('conditional and HEAD asset responses retain their status and empty body', async()=>{
  for (const [method,status] of [['GET',304],['HEAD',200]]) {
    const result=await proxy.fetch(new Request('https://public.workers.dev/static/app_ui.js',{method}),{
      ...env,ASSETS:{fetch:async request=>{
        assert.equal(request.method,method);
        return new Response(null,{status,headers:{ETag:'"unchanged"'}});
      }},
    });
    assert.equal(result.status,status);
    assert.equal(await result.text(),'');
    assert.equal(result.headers.get('ETag'),'"unchanged"');
  }
});

test('HTML, API, shared tokens, uploads and writes remain uncached proxy traffic', async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async()=>new Response('dynamic',{headers:{'Set-Cookie':'session=synthetic'}});
  try {
    for (const [path,method] of [['/','GET'],['/admin/dashboard','GET'],['/shared_topics?token=synthetic','GET'],
      ['/api/notifications','GET'],['/static/private.html','GET'],['/uploads/photo.png','GET'],['/static/theme.css','POST']]) {
      const result=await proxy.fetch(new Request('https://public.workers.dev'+path,{method}),{
        ...env,ASSETS:{fetch:async()=>{throw new Error('Private routes must not call ASSETS');}},
      });
      assert.equal(result.headers.get('Cache-Control'),'no-store');
      assert.equal(result.headers.get('Set-Cookie'),'session=synthetic');
    }
  } finally {globalThis.fetch=original;}
});

test('missing bundled asset falls back to origin, and invalid origin config still fails closed', async()=>{
  const original=globalThis.fetch;
  let calls=0;
  globalThis.fetch=async()=>{calls++;return new Response('newly deployed asset');};
  const assets={fetch:async()=>new Response('missing',{status:404})};
  try {
    const result=await proxy.fetch(new Request('https://public.workers.dev/static/new.css'),{...env,ASSETS:assets});
    assert.equal(calls,1);
    assert.equal(result.headers.get('Cache-Control'),'no-store');
    assert.equal(await result.text(),'newly deployed asset');
    const denied=await proxy.fetch(new Request('https://public.workers.dev/static/theme.css'),{
      ...env,ORIGIN_AUTH_SECRET:'',ASSETS:{fetch:async()=>{throw new Error('Must validate first');}},
    });
    assert.equal(denied.status,503);
  } finally {globalThis.fetch=original;}
});
