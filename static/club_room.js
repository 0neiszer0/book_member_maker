(function () {
  'use strict';
  const hourMs = 3600000;
  const pad = value => String(value).padStart(2, '0');
  const kst = value => new Date(new Date(value).getTime() + 9 * hourMs).toISOString().slice(0, 16);
  const shiftDate = (day, delta) => new Date(Date.parse(day + 'T00:00:00Z') + delta * 24 * hourMs).toISOString().slice(0, 10);
  const weekStart = day => shiftDate(day, -(new Date(day + 'T00:00:00Z').getUTCDay() + 6) % 7);
  function calendarTarget(search, today) {
    const params = new URLSearchParams(search), value = params.get('date') || '';
    const parsed = /^\d{4}-\d{2}-\d{2}$/.test(value) ? Date.parse(value + 'T00:00:00Z') : NaN;
    const valid = Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0,10) === value;
    return {date: valid ? value : today,
      booking: valid && /^[a-zA-Z0-9-]{1,80}$/.test(params.get('booking') || '') ? params.get('booking') : '',
      at: valid && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(params.get('at') || '') ? params.get('at') : ''};
  }
  function targetMatches(target, row, selected) {
    if (target.date !== selected) return false;
    return row.kind === 'blocked' ? !!target.at && kst(row.starts_at).slice(11) === target.at
      : !!target.booking && row.id === target.booking;
  }
  const overlaps = (booking, start, end) => Date.parse(booking.starts_at) < end && Date.parse(booking.ends_at) > start;
  function slotState(bookings, day, hour, now) {
    const start = Date.parse(day + 'T' + pad(hour) + ':00:00+09:00');
    const rows = bookings.filter(b => overlaps(b, start, start + hourMs));
    const blocked = rows.some(b => b.kind === 'blocked');
    return {rows, blocked, past: start + hourMs <= now, start};
  }
  function freeRanges(bookings, day, now) {
    const ranges = [];
    for (let h = 9; h < 24; h++) {
      const slot = slotState(bookings, day, h, now);
      if (slot.rows.length || slot.past) continue;
      const last = ranges[ranges.length - 1];
      if (last && last[1] === h) last[1] = h + 1;
      else ranges.push([h, h + 1]);
    }
    return ranges;
  }
  function nowStatus(bookings, now) {
    const stamp = kst(now), day = stamp.slice(0, 10), hour = Number(stamp.slice(11, 13));
    if (hour < 9) return {tone: 'closed', text: '현재 이용 시간이 아니에요 (09:00~24:00)'};
    const busy = h => slotState(bookings, day, h, now).rows.length > 0;
    if (!busy(hour)) {
      const next = bookings.map(b => Date.parse(b.starts_at)).filter(t => t > now && kst(t).slice(0, 10) === day).sort((a, b) => a - b)[0];
      return {tone: 'free', text: '지금 바로 사용 가능해요 ' + (next ? '(다음 예약 ' + kst(next).slice(11) + ')' : '(오늘 남은 시간 예약 없음)')};
    }
    let end = hour;
    while (end < 24 && busy(end)) end++;
    return {tone: 'busy', text: end >= 24 ? '지금 예약이 있어요 · 오늘은 자정까지 이어져요' : '지금 예약이 있어요 · ' + pad(end) + ':00부터 비어 있어요'};
  }
  const dayOf = value => new Date(value + 'T00:00:00Z').getUTCDay();
  const daysBetween = (from, to) => Math.round((Date.parse(to + 'T00:00:00Z') - Date.parse(from + 'T00:00:00Z')) / (24 * hourMs));
  function monthGridRange(ymd) {
    const year = Number(ymd.slice(0, 4)), month = Number(ymd.slice(5, 7));
    const first = ymd.slice(0, 8) + '01';
    const last = new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
    const start = shiftDate(first, -dayOf(first)), end = shiftDate(last, 6 - dayOf(last));
    const days = daysBetween(start, end) + 1;
    return {year, month, start, end, days, dates: Array.from({length: days}, (_, i) => shiftDate(start, i))};
  }
  function shiftMonth(ymd, delta) {
    const total = Number(ymd.slice(0, 4)) * 12 + Number(ymd.slice(5, 7)) - 1 + delta;
    const year = Math.floor(total / 12), month = total % 12 + 1;
    const day = Math.min(Number(ymd.slice(8, 10)), new Date(Date.UTC(year, month, 0)).getUTCDate());
    return year + '-' + pad(month) + '-' + pad(day);
  }
  // Bucket bookings by every KST date they touch; each bucket is sorted by start time.
  function groupBookingsByDate(rows) {
    const groups = {};
    for (const row of rows || []) {
      const from = Date.parse(row.starts_at || row.start_time), to = Date.parse(row.ends_at || row.end_time);
      if (!Number.isFinite(from)) continue;
      const first = kst(from).slice(0, 10), lastDay = Number.isFinite(to) && to > from ? kst(to - 1).slice(0, 10) : first;
      for (let day = first, guard = 0; day <= lastDay && guard < 60; day = shiftDate(day, 1), guard++) {
        const group = groups[day] || (groups[day] = {regular: [], blocked: [], all: []});
        group.all.push(row);
        (row.kind === 'blocked' || row.kind === 'meeting' ? group.blocked : group.regular).push(row);
      }
    }
    const byStart = (a, b) => Date.parse(a.starts_at || a.start_time) - Date.parse(b.starts_at || b.start_time);
    Object.values(groups).forEach(group => { group.all.sort(byStart); group.regular.sort(byStart); group.blocked.sort(byStart); });
    return groups;
  }
  const shareUrl = origin => origin.replace(/\/+$/, '') + '/club-room';
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {kst, shiftDate, weekStart, slotState, freeRanges, calendarTarget, targetMatches, nowStatus, shareUrl, monthGridRange, shiftMonth, groupBookingsByDate}; return;
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
  const calendarLink = calendarTarget(window.location.search, root.dataset.today);
  let view = 'month', loaded = null, selected = calendarLink.date, bookings = [], now = Date.now(), current = null, calendarFocused = false;
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
  async function api(url, body) {
    const response = await fetch(url, body ? {method:'POST', headers:{'Content-Type':'application/json', 'X-Room-CSRF':root.dataset.csrf}, body:JSON.stringify(body)} : {cache:'no-store'});
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('응답을 확인하지 못했어요. 새로고침 후 다시 시도해주세요.'); }
    if (!response.ok && data.status !== 'overlap') throw new Error(data.error || '정보를 확인하지 못했어요.');
    return data;
  }
  function render() { $('cr-new').disabled = selected < kst(now).slice(0, 10); }
  function refresh() { now = Date.now(); ready = true; render(); if (staff) refreshStaff(); }
  window.addEventListener('calendar:date-selected', event => { selected = event.detail.date; render(); });
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
  function times() {
    const day = $('cr-start-date').value, end = $('cr-end-hour').value;
    return {starts_at:day + 'T' + $('cr-start-hour').value + ':00', ends_at:(end === '24' && day ? shiftDate(day,1) : day) + 'T' + (end === '24' ? '00' : end) + ':00'};
  }
  function duration() {
    for (const option of $('cr-end-hour').options) option.disabled = Number(option.value) <= Number($('cr-start-hour').value);
    const t = times(), hours = (Date.parse(t.ends_at + ':00+09:00') - Date.parse(t.starts_at + ':00+09:00')) / hourMs;
    $('cr-duration').textContent = hours > 0 ? '총 ' + hours + '시간 · ' + ($('cr-end-hour').value === '24' ? '24:00은 자정이에요' : '한국시간 기준') : '종료 시간을 시작 시간보다 뒤로 선택해주세요.';
  }
  function showForm(booking) {
    dirty = false; form.reset(); $('cr-fields').hidden = false; $('cr-fields').disabled = false; $('cr-save').hidden = false;
    $('cr-email').value = root.dataset.email ? root.dataset.email.replace(/@knu\.ac\.kr$/, '') : '';
    const emailNeeded = !current.version && booking.kind !== 'meeting';
    $('cr-email').required = emailNeeded; $('cr-email').setAttribute('aria-required', String(emailNeeded));
    $('cr-email').closest('.knu-email-group').hidden = $('cr-email-label').hidden = !!current.version || booking.kind === 'meeting';
    $('cr-receipt').hidden = true; message('cr-form-error', ''); $('cr-kind').value = booking.kind;
    $('cr-representative').value = booking.representative || ''; $('cr-participants').value = (booking.participants || []).join(', '); $('cr-purpose').value = booking.purpose || '';
    const from = kst(booking.starts_at), to = kst(booking.ends_at);
    const endHour = to === shiftDate(from.slice(0,10),1) + 'T00:00' ? '24' : to.slice(11,13);
    const supported = Number(from.slice(11,13)) >= 9 && (to.slice(0,10) === from.slice(0,10) || endHour === '24');
    $('cr-start-date').value = from.slice(0,10);
    $('cr-start-date').min = kst(now).slice(0,10);
    $('cr-start-hour').value = from.slice(11,13);
    $('cr-end-hour').value = endHour;
    duration();
    $('cr-dialog-title').textContent = current.version ? '예약 확인·수정' : booking.kind === 'meeting' ? '임원진 회의 등록' : '동아리방 사용 신청';
    $('cr-save').textContent = current.version ? '변경 내용 저장' : booking.kind === 'meeting' ? '회의 등록 완료' : '사용 신청 완료';
    $('cr-cancel').hidden = !current.version || !!booking.cancelled_at;
    $('cr-meeting-note').hidden = booking.kind !== 'meeting';
    if (!supported) { $('cr-save').hidden = true; $('cr-fields').disabled = true; message('cr-form-error', '기존 예약은 그대로 유지돼요: ' + timeText(booking) + '. 야간 예약 변경은 운영진에게 문의해주세요. 취소는 가능합니다.'); }
    if (booking.cancelled_at) { $('cr-save').hidden = true; $('cr-fields').disabled = true; message('cr-form-error', '취소된 예약이에요. 다시 사용하려면 새로 신청해주세요.'); }
    document.querySelectorAll('[data-kind]').forEach(button => { button.hidden = !!current.version; button.setAttribute('aria-pressed', String(button.dataset.kind === booking.kind)); });
    if ($('cr-my').open) $('cr-my').close();
    if (!dialog.open) dialog.showModal();
  }
  function openNew(day, hour, kind = 'regular', endHour = hour + 1) {
    if (!ready || busy) return;
    const start = Date.parse(day + 'T' + pad(Math.max(9, hour)) + ':00:00+09:00');
    const code = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
    current = {id:crypto.randomUUID(), code, version:null, hasEmail:false};
    showForm({kind, starts_at:new Date(start).toISOString(), ends_at:new Date(start + Math.max(1, endHour - Math.max(9, hour)) * hourMs).toISOString(), participants:[]});
  }
  async function loadBooking(id, code) {
    if (busy) return;
    try {
      const data = await api('/api/club-room/bookings/' + encodeURIComponent(id), {action:'read', edit_code:code});
      current = {id:data.booking.id, code, version:data.booking.version}; showForm(data.booking); message('cr-mail-error', '');
    } catch (error) { message('cr-mail-error', error.message); }
  }
  function setBusy(value) { busy = value; $('cr-fields').disabled = value; $('cr-save').disabled = value; $('cr-cancel').disabled = value; $('cr-close').disabled = value; }
  async function save(action) {
    if (!current || busy) return;
    const body = {action, edit_code:current.code, version:current.version, ...times(), kind:$('cr-kind').value, representative:$('cr-representative').value, participants:$('cr-participants').value, purpose:$('cr-purpose').value};
    if (action === 'create') body.knu_email = $('cr-email').value.trim();
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
      $('cr-fields').hidden = true; $('cr-save').hidden = true; $('cr-cancel').hidden = true; $('cr-receipt').hidden = false;
      $('cr-receipt-title').textContent = data.booking.cancelled_at ? '예약이 취소됐어요' : '예약이 완료됐어요';
      const mailed = action === 'create' && (data.has_email || !!body.knu_email);
      $('cr-receipt-detail').textContent = (mailed ? '예약이 완료되었어요! 수정·취소가 필요하면 학교 메일 인증으로 언제든 변경할 수 있어요.\n' : '') + timeText(data.booking) + '\n대표자 ' + data.booking.representative + (body.kind === 'meeting' ? '\n기존 예약은 유지됩니다. 필요한 경우 직접 조율해주세요.' : ' · 참여 ' + data.booking.participants.length + '명');
      $('cr-dialog-title').textContent = '처리 완료';
      loadMine();
      refresh(); window.dispatchEvent(new CustomEvent('clubroom:changed'));
    } catch (error) { message('cr-form-error', error.message); }
    finally { setBusy(false); }
  }
  $('cr-form').addEventListener('submit', event => {
    event.preventDefault();
    if (current && !current.version && $('cr-kind').value !== 'meeting' && !$('cr-email').value.trim()) {
      message('cr-form-error', '학교 메일 아이디를 반드시 입력해주세요.'); $('cr-email').focus(); return;
    }
    if (current && !$('cr-save').hidden) save(current.version ? 'update' : 'create');
  });
  form.addEventListener('input', event => {
    dirty = true;
    if (event.target.id === 'cr-start-hour' && Number($('cr-end-hour').value) <= Number(event.target.value)) $('cr-end-hour').value = pad(Number(event.target.value) + 1);
    duration();
  });
  $('cr-cancel').addEventListener('click', () => { if (window.confirm('이 예약을 취소할까요? 취소 이력은 운영진에게 남습니다.')) save('cancel'); });
  function close() { if (!busy && (!dirty || window.confirm('저장하지 않은 입력을 닫을까요?'))) { dirty = false; dialog.close(); } }
  $('cr-close').addEventListener('click', close); dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  window.addEventListener('beforeunload', event => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } });
  $('cr-new').addEventListener('click', () => openNew(selected, selected === kst(now).slice(0,10) ? Number(kst(now).slice(11,13)) : 9));
  if (staff) $('cr-staff-panel').addEventListener('toggle', refreshStaff);
  document.querySelectorAll('[data-kind]').forEach(button => button.addEventListener('click', () => {
    const kind = button.dataset.kind;
    $('cr-kind').value = kind;
    $('cr-email').required = kind === 'regular';
    $('cr-email').setAttribute('aria-required', String(kind === 'regular'));
    $('cr-email').closest('.knu-email-group').hidden = $('cr-email-label').hidden = kind === 'meeting';
    $('cr-meeting-note').hidden = kind !== 'meeting';
    $('cr-dialog-title').textContent = kind === 'meeting' ? '운영진 회의 등록' : '동아리방 사용 신청';
    $('cr-save').textContent = kind === 'meeting' ? '회의 일정 등록' : '사용 신청 완료';
    document.querySelectorAll('[data-kind]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  }));
  $('cr-my-open').addEventListener('click', () => $('cr-my').showModal());
  $('cr-my-close').addEventListener('click', () => $('cr-my').close());
  window.addEventListener('clubroom:show-booking', () => { if (!$('cr-my').open) $('cr-my').showModal(); });
  ['cr-mail-id', 'cr-email'].forEach(id => $(id).addEventListener('input', event => { event.target.value = event.target.value.replace(/@knu\.ac\.kr$/i, ''); }));
  const mine = {email: root.dataset.email || ''};
  function mineMessage(text) { message('cr-mail-error', text); }
  function renderMine(email, rows) {
    mine.email = email || '';
    const state = $('cr-mail-state');
    state.hidden = !mine.email;
    state.textContent = mine.email ? (root.dataset.member === 'true' ? '로그인한 학교 메일 ' : '인증된 학교 메일 ') + mine.email + '의 예약이에요.' : '';
    $('cr-mail-request').hidden = !!mine.email; if (mine.email) $('cr-mail-verify').hidden = true;
    $('cr-my-list').replaceChildren();
    if (!mine.email) return;
    (rows || []).forEach(row => {
      const item = node('div', undefined, 'cr-staff-row'), info = node('div');
      info.append(node('strong', timeText(row)), node('p', '참여 ' + (row.participants || []).length + '명' + (row.purpose ? ' · ' + row.purpose : '')));
      const button = node('button', '확인·수정·취소'); button.type = 'button';
      button.addEventListener('click', () => loadBooking(row.id, ''));
      item.append(info, button); $('cr-my-list').append(item);
    });
    if (!rows || !rows.length) $('cr-my-list').append(node('p', '이 메일로 신청한 예정 예약이 없어요.', 'cr-empty'));
  }
  async function loadMine() {
    try { const data = await api('/api/club-room/my-bookings'); renderMine(data.email, data.bookings); } catch (_) { /* optional */ }
  }
  $('cr-mail-request').addEventListener('submit', async event => {
    event.preventDefault(); mineMessage('');
    try {
      const data = await api('/api/club-room/email/request', {email:$('cr-mail-id').value});
      $('cr-mail-verify').hidden = false; $('cr-otp').focus();
      $('cr-mail-state').hidden = false; $('cr-mail-state').textContent = data.email + '로 6자리 인증번호를 보냈어요. 메일함을 확인해주세요.';
    } catch (error) { mineMessage(error.message); }
  });
  $('cr-mail-verify').addEventListener('submit', async event => {
    event.preventDefault(); mineMessage('');
    try {
      const data = await api('/api/club-room/email/verify', {code:$('cr-otp').value.trim()});
      root.dataset.email = data.email; $('cr-otp').value = ''; renderMine(data.email, data.bookings);
    } catch (error) { mineMessage(error.message); }
  });
  $('cr-share-link').addEventListener('click', async () => {
    const url = shareUrl(window.location.origin), note = $('cr-share-note');
    try { await navigator.clipboard.writeText(url); note.textContent = '링크를 복사했어요'; }
    catch (_) { window.prompt('아래 링크를 복사해주세요', url); note.textContent = ''; }
    setTimeout(() => { note.textContent = ''; }, 3000);
  });
  render(); refresh(true); if (mine.email) loadMine();
})();
