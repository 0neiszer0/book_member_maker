(() => {
  const csrf=document.querySelector('meta[name="lms-csrf"]')?.content;if(!csrf)return;
  async function api(path,data) {
    const response=await fetch(path,{method:data?'POST':'GET',cache:'no-store',headers:data?{'Content-Type':'application/json','X-App-CSRF':csrf}:{},body:data?JSON.stringify(data):undefined});
    if(!response.ok)throw Error('요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.');return response.json();
  }
  async function loadInbox() {
    const lists=[document.getElementById('member-inbox'),document.getElementById('lms-notification-list')].filter(Boolean);
    try {
      const data=await api('/api/member-notifications');
      document.querySelectorAll('[data-notification-badge]').forEach(b=>{b.textContent=data.unread>99?'99+':data.unread;b.hidden=!data.unread;});
      lists.forEach(list=>{list.replaceChildren();if(!data.items.length)list.textContent='새 알림이 없습니다.';
        data.items.forEach(item=>{const row=document.createElement('article');row.className='lms-notification';
          const link=document.createElement('a');link.textContent=(!item.read_at?'● ':'')+item.title;
          const url=new URL(item.url,location.origin);link.href=url.origin===location.origin?url.href:'/notifications';
          link.onclick=()=>{fetch('/api/member-notifications/'+encodeURIComponent(item.id)+'/read',{method:'POST',keepalive:true,headers:{'X-App-CSRF':csrf}}).catch(()=>{});};
          const body=document.createElement('p');body.className='lms-small';body.textContent=item.body;row.append(link,body);
          for(const [action,label] of [['read',item.read_at?'읽음':'읽음 처리'],['dismiss','삭제']]){const button=document.createElement('button');button.type='button';button.className='lms-button';button.textContent=label;button.disabled=action==='read'&&!!item.read_at;button.setAttribute('aria-label',item.title+' '+label);button.onclick=async()=>{button.disabled=true;try{await api('/api/member-notifications/'+encodeURIComponent(item.id)+'/'+action,{});await loadInbox();}catch(error){body.textContent=error.message;button.disabled=false;}};row.append(button);}list.append(row);});});
    }catch(error){lists.forEach(list=>list.textContent=error.message);}
  }
  window.bookmembersLoadInbox=loadInbox;
  // One lightweight inbox request, no per-page attendance/task recalculation or polling.
  loadInbox();
  document.getElementById('read-all-notifications')?.addEventListener('click',async event=>{event.target.disabled=true;try{await api('/api/member-notifications/read-all',{});await loadInbox();}catch(error){document.getElementById("member-inbox").textContent=error.message;}finally{event.target.disabled=false;}});
  const enable=document.getElementById('push-enable'),disable=document.getElementById('push-disable'),status=document.getElementById('push-status');
  if(!enable)return;
  let config;
  const supported='serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  const keyBytes=key=>Uint8Array.from(atob(key.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-key.length%4)%4)),c=>c.charCodeAt(0));
  async function refresh() {
    if(!supported){enable.hidden=true;status.textContent='이 브라우저는 푸시 알림을 지원하지 않습니다. Chrome·Edge·Firefox 또는 홈 화면에 추가한 Safari 앱을 이용해주세요.';return;}
    config=await api('/api/push/config');
    if(!config.available){enable.disabled=true;status.textContent='현재 브라우저 알림을 사용할 수 없습니다. 사이트 알림함을 이용해주세요.';return;}
    const reg=await navigator.serviceWorker.getRegistration('/');const subscription=await reg?.pushManager.getSubscription();
    const hash=subscription?Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(subscription.endpoint))),v=>v.toString(16).padStart(2,'0')).join(''):'';
    const owned=subscription&&config.subscription_hashes.includes(hash);
    enable.hidden=!!owned;disable.hidden=!subscription;
    status.textContent=owned?'이 계정의 알림이 이 브라우저에 켜져 있습니다.':Notification.permission==='denied'?'브라우저 사이트 설정에서 알림 차단을 해제해주세요.':'알림 켜기를 누르면 브라우저에서 권한을 묻습니다.';
  }
  enable.onclick=async()=>{enable.disabled=true;try{
    if(!config?.available)return;
    // Permission request is directly attached to the user's click.
    const permission=await Notification.requestPermission();if(permission!=='granted')throw Error('알림 권한이 허용되지 않았습니다.');
    await navigator.serviceWorker.register('/push-worker.js',{scope:'/',updateViaCache:'none'});
    const reg=await navigator.serviceWorker.ready;
    const subscription=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:keyBytes(config.public_key)});
    try{await api('/api/push/subscription',subscription.toJSON());}catch(error){await subscription.unsubscribe();throw error;}
    await refresh();
  }catch(error){status.textContent=error.message;}finally{enable.disabled=false;}};
  disable.onclick=async()=>{disable.disabled=true;try{const reg=await navigator.serviceWorker.getRegistration('/');const sub=await reg?.pushManager.getSubscription();if(sub){await api('/api/push/unsubscribe',{endpoint:sub.endpoint});await sub.unsubscribe();}await refresh();}catch(error){status.textContent=error.message;}finally{disable.disabled=false;}};
  refresh().catch(error=>status.textContent=error.message);
})();
