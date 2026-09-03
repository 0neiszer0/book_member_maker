(() => {
 const root=document.querySelector('.attendance-shell[data-csrf]');if(!root)return;
 const status=document.getElementById('term-status');let filter='all';
 async function api(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':root.dataset.csrf},body:JSON.stringify(body)});const j=await r.json();if(!r.ok||j.status==='error')throw new Error(j.message||'처리하지 못했습니다.');return j;}
 function update(){const query=(document.getElementById('member-search')?.value||'').trim().toLowerCase();let count=0;root.querySelectorAll('[data-member-row]').forEach(row=>{const active=row.dataset.active==='yes',shortage=Number(row.dataset.shortage);row.hidden=!row.dataset.search.toLowerCase().includes(query)||!(filter==='archived'?!active:active&&(filter==='all'||(filter==='below'?shortage>0:shortage===0)));if(!row.hidden)count++;});const out=document.getElementById('visible-count');if(out)out.textContent=count+'명 표시';root.querySelectorAll('[data-show]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.show===filter)));}
 document.getElementById('member-search')?.addEventListener('input',update);update();
 root.addEventListener('click',async e=>{try{
  const filterButton=e.target.closest('[data-show]');if(filterButton){filter=filterButton.dataset.show;update();return;}
  const personal=e.target.closest('[data-personal-notice]');if(personal){await navigator.clipboard.writeText(personal.dataset.personalNotice);status.textContent='개인 안내 문구를 복사했습니다. 자동 발송되지 않습니다.';return;}
  if(e.target.closest('#copy-notice')){await navigator.clipboard.writeText(document.getElementById('notice-text').textContent);status.textContent='공지 문구를 복사했습니다.';return;}
  const save=e.target.closest('#save-minimum');if(save){await api('/api/admin/term_attendance/'+encodeURIComponent(save.dataset.termId)+'/minimum',{minimum:Number(document.getElementById('minimum').value)});location.reload();return;}
  const event=e.target.closest('[data-event-id]');if(event){const enabled=event.dataset.enable==='true';if(!confirm(enabled?'행사 상세에서 실제 참석 명단을 확인했나요? 이 행사를 OT 참석으로 합산합니다.':'이 행사를 학기 참석 합산에서 제외할까요?'))return;await api('/api/admin/term_attendance/events/'+encodeURIComponent(event.dataset.eventId)+'/confirm',{enabled});location.reload();}
 }catch(err){status.textContent=err.message;}});
})();
