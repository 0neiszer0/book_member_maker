(function () {
  'use strict';
  const hourMs = 3600000;
  const pad = value => String(value).padStart(2, '0');
  const kst = value => new Date(new Date(value).getTime() + 9 * hourMs).toISOString().slice(0, 16);
  const shiftDate = (day, delta) => new Date(Date.parse(day + 'T00:00:00Z') + delta * 24 * hourMs).toISOString().slice(0, 10);
  const weekStart = day => shiftDate(day, -(new Date(day + 'T00:00:00Z').getUTCDay() + 6) % 7);
  const overlaps = (booking, start, end) => Date.parse(booking.starts_at) < end && Date.parse(booking.ends_at) > start;
  function slotState(bookings, day, hour, now) {
    const start = Date.parse(day + 'T' + pad(hour) + ':00:00+09:00');
    const rows = bookings.filter(b => overlaps(b, start, start + hourMs));
    const blocked = rows.some(b => b.kind === 'blocked');
    return {rows, blocked, past: start + hourMs <= now, start};
  }
  function freeRanges(bookings, day, now) {
    const ranges = [];
    for (let h = 0; h < 24; h++) {
      const slot = slotState(bookings, day, h, now);
      if (slot.rows.length || slot.past) continue;
      const last = ranges[ranges.length - 1];
      if (last && last[1] === h) last[1] = h + 1;
      else ranges.push([h, h + 1]);
    }
    return ranges;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {kst, shiftDate, weekStart, slotState, freeRanges}; return;
  }
  const root = document.getElementById('club-room');
  const homeStatus = document.getElementById('cr-home-status');
  if (homeStatus) {
    fetch('/api/club-room/schedule?date=' + kst(new Date()).slice(0,10), {cache:'no-store'})
      .then(response => { if (!response.ok) throw new Error(); return response.json(); })
      .then(data => {
        const ranges = freeRanges(data.bookings, kst(data.now).slice(0,10), Date.parse(data.now));
        homeStatus.textContent = ranges.length
          ? '오늘 예약 없는 시간 · ' + ranges.map(([a,b]) => pad(a) + ':00–' + pad(b) + ':00').join(', ')
          : '오늘 예약 없는 시간은 없어요 · 함께 사용 가능한 시간 확인';
      }).catch(() => { homeStatus.textContent = '시간표를 열어 최신 예약을 확인해주세요'; });
  }
  if (!root) return;
  const $ = id => document.getElementById(id);
  const staff = root.dataset.staff === 'true';
  const dialog = $('cr-dialog'), form = $('cr-form');
  const localKey = 'club-room:receipts:v1';
  let selected = root.dataset.today, bookings = [], now = Date.now(), current = null;
  let busy = false, dirty = false, ready = false, requestNumber = 0, staffRequest = 0;
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function message(id, text) { $(id).textContent = text; $(id).hidden = !text; }
  function dateText(day) { return new Intl.DateTimeFormat('ko-KR', {month:'long', day:'numeric', weekday:'short', timeZone:'Asia/Seoul'}).format(new Date(day + 'T00:00:00+09:00')); }
  function timeText(booking) { return kst(booking.starts_at).replace('T', ' ') + ' → ' + kst(booking.ends_at).replace('T', ' '); }
  function savedReceipts() {
    try { const rows = JSON.parse(localStorage.getItem(localKey) || '[]'); return Array.isArray(rows) ? rows.filter(r => typeof r?.code === 'string' && typeof r?.id === 'string') : []; }
    catch (_) { return []; }
  }
  function remember(receipt) {
    if (!receipt.code) return;
    try {
      const rows = savedReceipts().filter(r => r.id !== receipt.id);
      rows.push({id:receipt.id, code:receipt.code, start:receipt.start || ''});
      localStorage.setItem(localKey, JSON.stringify(rows));
      $('cr-storage-note').textContent = '이 브라우저에 관리 코드가 저장됐어요. 다른 기기에서는 코드를 입력해주세요. 타인에게 공유하지 마세요.';
    } catch (_) {
      $('cr-code-details').open = true;
      $('cr-storage-note').textContent = '브라우저에 저장할 수 없어요. 창을 닫기 전에 관리 코드를 꼭 복사해주세요.';
    }
    renderSaved();
  }
  function renderSaved() {
    $('cr-saved').replaceChildren();
    savedReceipts().reverse().forEach(row => {
      const button = node('button', row.start ? row.start.replace('T', ' ') + ' 예약 확인' : '신청 결과 확인 (' + row.id.slice(0, 8) + ')');
      button.type = 'button'; button.addEventListener('click', () => loadBooking(row.id, row.code)); $('cr-saved').append(button);
    });
  }
  async function api(url, body) {
    const response = await fetch(url, body ? {method:'POST', headers:{'Content-Type':'application/json', 'X-Room-CSRF':root.dataset.csrf}, body:JSON.stringify(body)} : {cache:'no-store'});
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('응답을 확인하지 못했어요. 새로고침 후 다시 시도해주세요.'); }
    if (!response.ok && data.status !== 'overlap') throw new Error(data.error || '정보를 확인하지 못했어요.');
    return data;
  }
  function render() {
    const focusedLabel = document.activeElement.closest('#cr-days, #cr-grid') ? document.activeElement.getAttribute('aria-label') : null;
    $('cr-date').value = selected;
    $('cr-summary-date').textContent = dateText(selected);
    $('cr-days').replaceChildren(); $('cr-grid').replaceChildren(); $('cr-free').replaceChildren();
    const start = weekStart(selected);
    for (let i = 0; i < 7; i++) {
      const day = shiftDate(start, i), isSelected = day === selected;
      const tab = node('button', undefined, isSelected ? 'is-selected' : '');
      tab.type = 'button'; tab.setAttribute('aria-pressed', String(isSelected)); tab.setAttribute('aria-label', dateText(day));
      tab.append(node('span', '일월화수목금토'[new Date(day + 'T00:00:00Z').getUTCDay()]), node('strong', String(Number(day.slice(8)))));
      tab.addEventListener('click', () => { selected = day; render(); scrollToDay(); if (staff) refreshStaff(); }); $('cr-days').append(tab);
      const column = node('section', undefined, 'cr-day' + (isSelected ? ' is-selected' : ''));
      column.setAttribute('aria-label', dateText(day)); const list = node('ol');
      for (let h = 0; h < 24; h++) {
        const slot = slotState(bookings, day, h, now);
        const item = node('li', undefined, 'cr-slot' + (slot.blocked ? ' is-blocked' : slot.rows.length ? ' is-shared' : '') + (slot.past ? ' is-past' : ''));
        const button = node('button'); button.type = 'button'; button.disabled = !ready || slot.past || slot.blocked;
        const names = slot.rows.filter(r => r.kind === 'regular').map(r => r.representative);
        const label = !ready ? '확인 필요' : slot.blocked ? '이용 불가' : names.length ? names.join(', ') : slot.past ? '지난 시간' : '예약 없음';
        button.append(node('span', pad(h) + ':00', 'cr-time'), node('strong', label), node('small', slot.blocked ? '동아리 일정' : names.length ? '함께 사용 가능' : slot.past ? '' : '선택해서 신청'));
        button.setAttribute('aria-label', dateText(day) + ' ' + pad(h) + '시 · ' + label);
        button.title = label;
        button.addEventListener('click', () => openNew(day, h)); item.append(button); list.append(item);
      }
      column.append(list); $('cr-grid').append(column);
    }
    if (!ready) $('cr-free').textContent = '시간표를 다시 불러온 뒤 확인해주세요.';
    else {
      const ranges = freeRanges(bookings, selected, now);
      ranges.forEach(([startHour, endHour]) => {
        const button = node('button', pad(startHour) + ':00–' + pad(endHour) + ':00'); button.type = 'button';
        button.addEventListener('click', () => openNew(selected, startHour)); $('cr-free').append(button);
      });
      if (!ranges.length) $('cr-free').textContent = '예약 없는 시간이 없어요. 함께 사용 가능한 칸은 선택할 수 있어요.';
    }
    $('cr-new').disabled = !ready;
    if (staff) $('cr-meeting').disabled = !ready;
    if (focusedLabel) [...root.querySelectorAll('button[aria-label]')].find(button => button.getAttribute('aria-label') === focusedLabel)?.focus({preventScroll:true});
  }
  function scrollToDay() {
    $('cr-grid-scroll').scrollTop = (window.matchMedia('(max-width:767px)').matches ? 72 : 88) * Math.max(0, (selected === kst(now).slice(0,10) ? Number(kst(now).slice(11,13)) - 1 : 8));
  }
  async function refresh(scroll = false) {
    const seq = ++requestNumber, start = weekStart(selected);
    try {
      const data = await api('/api/club-room/schedule?date=' + start);
      if (seq !== requestNumber) return;
      bookings = data.bookings; now = Date.parse(data.now); ready = true; message('cr-error', '');
      $('cr-updated').textContent = '방금 확인 · 화면이 열려 있으면 30초마다 갱신'; render();
      if (scroll) scrollToDay();
      if (staff) refreshStaff();
    } catch (error) {
      if (seq !== requestNumber) return;
      ready = false; render(); message('cr-error', error.message); $('cr-updated').textContent = '최신 상태 확인 필요';
    }
  }
  async function refreshStaff() {
    const seq = ++staffRequest;
    if (!$('cr-staff-panel').open) return;
    try {
      const data = await api('/api/club-room/staff?date=' + weekStart(selected));
      if (seq !== staffRequest) return;
      $('cr-staff-list').replaceChildren();
      data.bookings.forEach(row => {
        const item = node('div', undefined, 'cr-staff-row'), info = node('div');
        info.append(node('strong', (row.kind === 'meeting' ? '임원진 회의 · ' : '') + row.representative), node('p', timeText(row)), node('p', '참여자: ' + row.participants.join(', ')));
        if (row.purpose) info.append(node('p', row.purpose));
        const shared = data.bookings.filter(other => other.id !== row.id && overlaps(other, Date.parse(row.starts_at), Date.parse(row.ends_at)));
        if (row.kind === 'meeting' && shared.length) info.append(node('p', '직접 조율 필요: ' + shared.map(other => other.representative).join(', '), 'cr-error'));
        const button = node('button', '확인·수정'); button.type = 'button'; button.addEventListener('click', () => loadBooking(row.id, ''));
        item.append(info, button); $('cr-staff-list').append(item);
      });
      if (!data.bookings.length) $('cr-staff-list').textContent = '이 주에는 등록된 예약이 없어요.';
    } catch (error) { if (seq === staffRequest) $('cr-staff-list').textContent = error.message; }
  }
  function setTime(prefix, value) { const local = kst(value); $('cr-' + prefix + '-date').value = local.slice(0,10); $('cr-' + prefix + '-hour').value = local.slice(11,13); }
  function times() { return {starts_at:$('cr-start-date').value + 'T' + $('cr-start-hour').value + ':00', ends_at:$('cr-end-date').value + 'T' + $('cr-end-hour').value + ':00'}; }
  function duration() {
    const t = times(), hours = (Date.parse(t.ends_at + ':00+09:00') - Date.parse(t.starts_at + ':00+09:00')) / hourMs;
    $('cr-duration').textContent = hours > 0 ? '총 ' + hours + '시간 · 한국시간 기준' : '종료 시간을 시작 시간보다 뒤로 선택해주세요.';
  }
  function showForm(booking) {
    dirty = false; form.reset(); $('cr-fields').hidden = false; $('cr-fields').disabled = false; $('cr-save').hidden = false;
    $('cr-copy').textContent = '코드 복사';
    $('cr-receipt').hidden = true; message('cr-form-error', ''); $('cr-kind').value = booking.kind;
    $('cr-representative').value = booking.representative || ''; $('cr-participants').value = (booking.participants || []).join(', '); $('cr-purpose').value = booking.purpose || '';
    setTime('start', booking.starts_at); setTime('end', booking.ends_at); duration();
    $('cr-dialog-title').textContent = current.version ? '예약 확인·수정' : booking.kind === 'meeting' ? '임원진 회의 등록' : '동아리방 사용 신청';
    $('cr-save').textContent = current.version ? '변경 내용 저장' : booking.kind === 'meeting' ? '회의 등록 완료' : '사용 신청 완료';
    $('cr-cancel').hidden = !current.version || !!booking.cancelled_at;
    $('cr-meeting-note').hidden = booking.kind !== 'meeting'; $('cr-code-details').hidden = !current.code; $('cr-code-details').open = false;
    $('cr-issued-code').value = current.code ? current.id + '.' + current.code : '';
    if (booking.cancelled_at) { $('cr-save').hidden = true; $('cr-fields').disabled = true; message('cr-form-error', '취소된 예약이에요. 다시 사용하려면 새로 신청해주세요.'); }
    if (!dialog.open) dialog.showModal();
  }
  function openNew(day, hour, kind = 'regular') {
    if (!ready || busy) return;
    const start = Date.parse(day + 'T' + pad(hour) + ':00:00+09:00');
    const code = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
    current = {id:crypto.randomUUID(), code, version:null};
    showForm({kind, starts_at:new Date(start).toISOString(), ends_at:new Date(start + hourMs).toISOString(), participants:[]});
  }
  async function loadBooking(id, code) {
    if (busy) return;
    try {
      const data = await api('/api/club-room/bookings/' + encodeURIComponent(id), {action:'read', edit_code:code});
      current = {id:data.booking.id, code, version:data.booking.version}; showForm(data.booking); message('cr-lookup-error', '');
    } catch (error) { message('cr-lookup-error', error.message); $('cr-lookup-error').scrollIntoView({block:'center'}); }
  }
  function setBusy(value) { busy = value; $('cr-fields').disabled = value; $('cr-save').disabled = value; $('cr-cancel').disabled = value; $('cr-close').disabled = value; }
  async function save(action) {
    if (!current || busy) return;
    const body = {action, edit_code:current.code, version:current.version, ...times(), kind:$('cr-kind').value, representative:$('cr-representative').value, participants:$('cr-participants').value, purpose:$('cr-purpose').value};
    if (action === 'create') { current.start = body.starts_at; remember(current); }
    setBusy(true); message('cr-form-error', '');
    try {
      const url = '/api/club-room/bookings/' + current.id;
      let data = await api(url, body);
      if (data.status === 'overlap') {
        const rows = data.conflicts.map(row => timeText(row) + ' · ' + (row.representative || '동아리 일정')).join('\n');
        const prompt = body.kind === 'meeting' ? '아래 예약은 그대로 유지됩니다. 대표자와 직접 조율한 뒤 이용해주세요. 회의를 등록할까요?' : '다른 팀도 이 시간에 사용해요. 함께 사용하는 데 동의하고 신청할까요?';
        if (!window.confirm(prompt + '\n\n' + rows)) return;
        data = await api(url, {...body, acknowledge_overlap:true});
      }
      if (data.status !== 'success') throw new Error('예약 상태가 바뀌었어요. 다시 확인해주세요.');
      dirty = false; current.version = data.booking.version;
      if (current.code) { current.start = kst(data.booking.starts_at); remember(current); }
      $('cr-fields').hidden = true; $('cr-save').hidden = true; $('cr-cancel').hidden = true; $('cr-receipt').hidden = false;
      $('cr-receipt-title').textContent = data.booking.cancelled_at ? '예약이 취소됐어요' : '예약이 완료됐어요';
      $('cr-receipt-detail').textContent = timeText(data.booking) + '\n대표자 ' + data.booking.representative + (body.kind === 'meeting' ? '\n기존 예약은 유지됩니다. 필요한 경우 직접 조율해주세요.' : ' · 참여 ' + data.booking.participants.length + '명');
      $('cr-dialog-title').textContent = '처리 완료'; $('cr-code-details').open = !!current.code;
      refresh();
    } catch (error) { message('cr-form-error', error.message); }
    finally { setBusy(false); }
  }
  $('cr-form').addEventListener('submit', event => { event.preventDefault(); if (current && !$('cr-save').hidden) save(current.version ? 'update' : 'create'); });
  form.addEventListener('input', () => { dirty = true; duration(); });
  $('cr-cancel').addEventListener('click', () => { if (window.confirm('이 예약을 취소할까요? 취소 이력은 운영진에게 남습니다.')) save('cancel'); });
  function close() { if (!busy && (!dirty || window.confirm('저장하지 않은 입력을 닫을까요?'))) { dirty = false; dialog.close(); } }
  $('cr-close').addEventListener('click', close); dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  window.addEventListener('beforeunload', event => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } });
  $('cr-copy').addEventListener('click', async () => { try { await navigator.clipboard.writeText($('cr-issued-code').value); $('cr-copy').textContent = '복사했어요'; } catch (_) { $('cr-issued-code').select(); $('cr-storage-note').textContent = '선택된 코드를 직접 복사해주세요.'; } });
  $('cr-lookup').addEventListener('submit', event => { event.preventDefault(); const parts = $('cr-code').value.trim().split('.'); if (parts.length !== 2) { message('cr-lookup-error', '받은 관리 코드 전체를 붙여넣어주세요.'); return; } loadBooking(parts[0], parts[1]); });
  $('cr-forget').addEventListener('click', () => { if (window.confirm('이 브라우저에 저장한 관리 코드만 지울까요? 예약은 취소되지 않습니다.')) { try { localStorage.removeItem(localKey); renderSaved(); } catch (_) { message('cr-lookup-error', '브라우저 저장 설정을 확인해주세요.'); } } });
  $('cr-new').addEventListener('click', () => openNew(selected, selected === kst(now).slice(0,10) ? Number(kst(now).slice(11,13)) : 9));
  if (staff) { $('cr-meeting').addEventListener('click', () => openNew(selected, selected === kst(now).slice(0,10) ? Number(kst(now).slice(11,13)) : 9, 'meeting')); $('cr-staff-panel').addEventListener('toggle', refreshStaff); }
  $('cr-date').addEventListener('change', () => { if (/^\d{4}-\d{2}-\d{2}$/.test($('cr-date').value)) { selected = $('cr-date').value; ready = false; render(); refresh(true); } });
  for (const [id, offset] of [['cr-prev',-7],['cr-next',7]]) $(id).addEventListener('click', () => { selected = shiftDate(selected,offset); ready = false; render(); refresh(true); });
  $('cr-today').addEventListener('click', () => { selected = kst(new Date()).slice(0,10); ready = false; render(); refresh(true); });
  $('cr-refresh').addEventListener('click', () => refresh());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  setInterval(() => { if (!document.hidden) refresh(); }, 30000);
  renderSaved(); render(); refresh(true);
})();
