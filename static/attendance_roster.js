(() => {
  const root = document.querySelector('[data-session-id][data-csrf]');
  if (!root) return;
  const base = '/api/admin/seminar_sessions/' + encodeURIComponent(root.dataset.sessionId);
  const status = document.getElementById('attendance-status');
  const preview = document.getElementById('roster-preview');
  const apply = document.getElementById('apply-roster');
  let method = 'text', token = null, busy = false, inputRevision = 0;
  const selected = selector => [...root.querySelectorAll(selector + ':checked')].map(input => Number(input.value));
  function invalidate() { inputRevision++; token = null; apply.hidden = true; preview.hidden = true; }
  async function post(path, data) {
    const isForm = data instanceof FormData;
    const response = await fetch(base + path, {method: 'POST', headers: {'X-CSRF-Token': root.dataset.csrf, ...(isForm ? {} : {'Content-Type':'application/json'})}, body: isForm ? data : JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok || result.status === 'error') throw new Error(result.message || '처리하지 못했습니다. 새로고침 후 다시 확인해주세요.');
    return result;
  }
  async function action(task) {
    if (busy) return;
    busy = true; status.textContent = '처리 중…';
    try { await task(); status.textContent = ''; } catch (error) { status.textContent = error.message; status.scrollIntoView({block:'nearest'}); }
    finally { busy = false; }
  }
  root.querySelectorAll('[data-method]').forEach(button => button.addEventListener('click', () => {
    method = button.dataset.method; invalidate();
    root.querySelectorAll('[data-method]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    root.querySelectorAll('[data-input-panel]').forEach(panel => panel.hidden = panel.dataset.inputPanel !== method);
  }));
  root.querySelectorAll('#roster-text,#roster-file,.roster-choice').forEach(input => input.addEventListener('input', invalidate));
  for (const kind of ['roster','actual']) document.getElementById(kind+'-search').addEventListener('input', event => {
    const query = event.target.value.trim().toLowerCase();
    root.querySelectorAll('[data-'+kind+'-search]').forEach(label => label.hidden = !label.getAttribute('data-'+kind+'-search').toLowerCase().includes(query));
  });
  document.getElementById('preview-roster').addEventListener('click', () => action(async () => {
    invalidate(); const previewRevision = inputRevision; let body = {method};
    if (method === 'file') { body = new FormData(); body.append('method','file'); const file = document.getElementById('roster-file').files[0]; if (!file) throw new Error('엑셀 파일을 선택해주세요.'); body.append('file',file); }
    else if (method === 'selected') body.member_ids = selected('.roster-choice');
    else body.text = document.getElementById('roster-text').value;
    const result = await post('/roster/preview',body);
    // An edited input or a changed input mode must never revive an older token.
    if (previewRevision !== inputRevision) throw new Error('명단이 변경되었습니다. 다시 미리보기해주세요.');
    preview.replaceChildren();
    const line = text => {const p=document.createElement('p');p.textContent=text;preview.append(p);};
    line('반영 후 참석 예정: '+result.expected_count+'명');
    line('입력 명단: '+(result.matched.map(m=>m.name).join(', ') || '없음'));
    line('참석 예정에 추가: '+(result.added.map(m=>m.name).join(', ') || '없음'));
    line('참석 예정에서 제외: '+(result.removed.map(m=>m.name).join(', ') || '없음'));
    result.issues.forEach(issue=>line(issue.line+'행 · '+issue.input+' — '+issue.reason));
    if(result.issues.length) line('오류를 수정한 뒤 다시 미리보기해주세요. 일부만 자동 반영하지 않습니다.');
    token=result.token;apply.hidden=!token;preview.hidden=false;
  }));
  apply.addEventListener('click',()=>action(async()=>{if(!token) return;if(!confirm('미리 본 참석 예정 명단으로 반영할까요? 실제 출석 기록은 바뀌지 않습니다.'))return;await post('/roster/apply',{token});location.reload();}));
  document.getElementById('undo-roster')?.addEventListener('click',()=>action(async()=>{if(!confirm('직전 반영 이전의 참석 예정 명단으로 되돌릴까요?'))return;await post('/roster/undo',{});location.reload();}));
  const absentSummary = document.getElementById('absent-summary');
  const groupCards = () => [...(root.querySelectorAll('[data-group-card]') || [])];
  function syncChoice(input) {
    const row = input.closest?.('[data-group-member]');
    if (!row) return;
    row.classList?.toggle('is-absent', !input.checked);
    const pill = row.querySelector?.('[data-state-pill]');
    if (pill) pill.textContent = input.checked ? '참석' : '불참';
  }
  function renderAbsentSummary(absent) {
    if (!absentSummary) return;
    absentSummary.replaceChildren();
    if (!absent.length) {
      const done = document.createElement('span');
      done.className = 'attendance-all-present';
      done.textContent = '전원 참석';
      absentSummary.append(done);
      return;
    }
    absent.forEach(input => {
      const name = input.closest?.('[data-group-member]')?.dataset?.memberName || input.value;
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'attendance-absent-chip';
      chip.textContent = name + ' 불참';
      chip.setAttribute('aria-label', name + '을(를) 참석으로 되돌리기');
      chip.addEventListener('click', () => { input.checked = true; countActual(); input.focus?.(); });
      absentSummary.append(chip);
    });
  }
  function countActual(){
    const choices = [...root.querySelectorAll('.actual-choice')];
    choices.forEach(syncChoice);
    const cards = groupCards();
    const absent = [];
    cards.forEach(card => {
      const inputs = [...(card.querySelectorAll?.('.actual-choice') || [])];
      const attended = inputs.filter(input => input.checked).length;
      inputs.forEach(input => { if (!input.checked) absent.push(input); });
      const counter = card.querySelector?.('[data-group-count]');
      if (counter) counter.textContent = attended + ' / ' + inputs.length + '명 참석';
    });
    let text = '실제 참석 ' + selected('.actual-choice').length + '명 선택';
    if (cards.length) text += ' · 조 편성 중 불참 ' + absent.length + '명';
    document.getElementById('actual-count').textContent = text;
    if (cards.length) renderAbsentSummary(absent);
  }
  root.querySelectorAll('.actual-choice').forEach(input=>input.addEventListener('change',countActual));countActual();
  document.getElementById('use-grouped')?.addEventListener('click',event=>{const ids=new Set(JSON.parse(event.currentTarget.dataset.ids||'[]'));root.querySelectorAll('.actual-choice').forEach(input=>{input.checked=ids.has(Number(input.value));});countActual();status.textContent='조 편성 명단 '+ids.size+'명을 선택했습니다. 확인한 뒤 실제 출석 확정을 눌러주세요.';});
  const confirmedView = document.getElementById('actual-confirmed-view');
  const editor = document.getElementById('actual-editor');
  document.getElementById('edit-actual-attendance')?.addEventListener('click', () => {
    if (confirmedView) confirmedView.hidden = true;
    if (editor) editor.hidden = false;
    (root.querySelector?.('[data-group-member] .actual-choice') || document.getElementById('actual-search'))?.focus?.();
  });
  document.getElementById('cancel-edit-actual')?.addEventListener('click', () => {
    if (editor) editor.hidden = true;
    if (confirmedView) { confirmedView.hidden = false; document.getElementById('edit-actual-attendance')?.focus?.(); }
  });
  document.getElementById('confirm-attendance').addEventListener('click',()=>action(async()=>{const ids=selected('.actual-choice');await post('/attendance/confirm',{member_ids:ids,confirmation_token:root.dataset.confirmationToken});if(typeof window!=='undefined')window.location.hash='actual-attendance';location.reload();}));
})();
