/* Public room responses only. Never infer availability from a failed request. */
(() => {
  'use strict';
  const root = document.querySelector('#integrated-calendar');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const names = {seminar: '세미나', deadline: '발제문 마감', room: '예약', blocked: '이용 불가'};
  const day = value => new Date(value.slice(0, 10) + 'T00:00:00Z');
  const iso = value => value.toISOString().slice(0, 10);
  const shift = (value, amount) => {const d = day(value); d.setUTCDate(d.getUTCDate() + amount); return iso(d);};
  const kstDate = value => new Date(new Date(value).getTime() + 9 * 3600000).toISOString().slice(0, 10);
  const clock = value => new Intl.DateTimeFormat('ko-KR', {timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).format(new Date(value));
  let events = [], revision = 0;
  const filterRoot = $('ic-filters') || root;
  const tabs = [...root.querySelectorAll('[data-calendar-view]')];
  $('ic-view').value = 'month';
  function syncControls() {
    const chosen = $('ic-date').value || root.dataset.today, d = day(chosen);
    const title = d.getUTCFullYear() + '년 ' + (d.getUTCMonth() + 1) + '월';
    if ($('ic-title')) $('ic-title').textContent = title;
    tabs.forEach(tab => {const selected = tab.dataset.calendarView === $('ic-view').value; tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;});
    if (!$('ic-mini-calendar')) return;
    $('ic-mini-title').textContent = title;
    const grid = document.createElement('div'); grid.className = 'ic-mini-grid';
    for (const text of '일월화수목금토') {const header = document.createElement('span'); header.textContent = text; grid.append(header);}
    d.setUTCDate(1); const start = shift(iso(d), -d.getUTCDay());
    const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
    const end = shift(iso(last), 7 - last.getUTCDay());
    for (let i = 0; shift(start, i) < end; i++) {
      const date = shift(start, i), button = document.createElement('button'); button.type = 'button';
      button.className = 'ic-mini-day' + (date.slice(0,7) !== chosen.slice(0,7) ? ' ic-mini-other' : '');
      button.textContent = String(day(date).getUTCDate()); button.setAttribute('aria-label', date + ' 일정 보기'); button.setAttribute('aria-pressed', String(date === chosen));
      button.addEventListener('click', () => {$('ic-date').value = date; load();}); grid.append(button);
    }
    $('ic-mini-calendar').replaceChildren(grid);
  }
  function range() {
    const chosen = $('ic-date').value || root.dataset.today, d = day(chosen);
    if ($('ic-view').value === 'month') {
      d.setUTCDate(1); const start = shift(iso(d), -d.getUTCDay());
      const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
      return [start, shift(iso(last), 7 - last.getUTCDay())];
    }
    if ($('ic-view').value === 'week') {const start = shift(chosen, -d.getUTCDay()); return [start, shift(start, 7)];}
    return [chosen, shift(chosen, 30)];
  }
  function eventDay(event) {return event.allDay ? event.start : kstDate(event.start);}
  function onDate(event, date) {
    if (!event.end) return eventDay(event) === date;
    const first = Date.parse(date + 'T00:00:00+09:00'), last = first + 86400000;
    return Date.parse(event.start) < last && Date.parse(event.end) > first;
  }
  function link(event) {
    const a = document.createElement('a'); a.className = 'ic-event ic-' + event.type; a.href = event.url;
    const timing = event.allDay ? '날짜 일정' : clock(event.start) + (event.end ? '–' + clock(event.end) : '');
    a.textContent = '[' + names[event.type] + '] ' + timing + ' ' + event.title + (event.status ? ' · ' + event.status : '');
    a.title = a.textContent;
    return a;
  }
  function render() {
    const [start, end] = range(), content = $('ic-content'), view = $('ic-view').value;
    content.replaceChildren(); $('ic-range').textContent = start + ' ~ ' + shift(end, -1);
    const enabled = new Set([...filterRoot.querySelectorAll('[data-filter]:checked')].map(x => x.dataset.filter));
    const visible = events.filter(e => enabled.has(e.type)).sort((a,b) => a.start.localeCompare(b.start));
    const outer = document.createElement('div'); outer.className = view === 'agenda' ? 'ic-agenda' : 'ic-scroll';
    const grid = document.createElement('div'); grid.className = view === 'agenda' ? '' : 'ic-' + view;
    if (view === 'month') for (const text of '일월화수목금토') {const heading = document.createElement('div'); heading.className = 'ic-weekday'; heading.textContent = text; grid.append(heading);}
    let count = 0;
    for (let date = start; date < end; date = shift(date, 1)) {
      const items = visible.filter(e => onDate(e, date));
      if (view === 'agenda' && !items.length) continue;
      const cell = document.createElement('section'); cell.className = view === 'agenda' ? '' : 'ic-cell';
      if (date === root.dataset.today) cell.classList.add('ic-today');
      if (view === 'month' && date.slice(0,7) !== $('ic-date').value.slice(0,7)) cell.classList.add('ic-other');
      const h = document.createElement('h3'); h.textContent = view === 'month' ? String(day(date).getUTCDate()) : date + ' (' + '일월화수목금토'[day(date).getUTCDay()] + ')'; h.setAttribute('aria-label', date); cell.append(h);
      if (view === 'week') {
        items.filter(e => !e.end).forEach(e => cell.append(link(e)));
        for (let hour = 0; hour < 24; hour++) {
          if (hour > 0 && hour < 9) continue;
          const slot = document.createElement('div'); slot.className = 'ic-hour'; slot.textContent = String(hour).padStart(2, '0') + ':00';
          const first = Date.parse(date + 'T' + String(hour).padStart(2, '0') + ':00:00+09:00');
          items.filter(e => e.end && Date.parse(e.start) < first + 3600000 && Date.parse(e.end) > first).forEach(e => slot.append(link(e)));
          cell.append(slot);
        }
      } else items.forEach(e => cell.append(link(e)));
      count += items.length; grid.append(cell);
    }
    outer.append(grid); content.append(outer);
    if (!count) {const p = document.createElement('p'); p.textContent = '표시할 일정이 없습니다. 필터와 조회 상태를 확인해주세요.'; content.append(p);}
  }
  async function json(url) {const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}}); if (!response.ok) throw new Error(String(response.status)); return response.json();}
  async function load() {
    syncControls();
    const ticket = ++revision, [start, end] = range();
    $('ic-status').textContent = '일정을 불러오는 중이에요.'; $('ic-error').hidden = true; $('ic-content').replaceChildren(); $('ic-content').setAttribute('aria-busy', 'true');
    const urls = []; for (let date = start; date < end; date = shift(date, 7)) urls.push('/api/club-room/schedule?date=' + date);
    const results = await Promise.allSettled(urls.map(json));
    const seminar = root.dataset.member === 'true' ? await Promise.allSettled([json('/api/calendar/seminars?' + new URLSearchParams({term_id: root.dataset.term}))]) : [];
    if (ticket !== revision) return;
    const unique = new Map(); let failed = results.some(x => x.status === 'rejected');
    for (const result of results) if (result.status === 'fulfilled') {
      if (!Array.isArray(result.value.bookings)) {failed = true; continue;}
      for (const row of result.value.bookings) {
        // Anonymous blocked intervals have no public ID; identical intervals represent one public block.
        if (!['regular','blocked'].includes(row.kind) || !Number.isFinite(Date.parse(row.starts_at)) || !Number.isFinite(Date.parse(row.ends_at))) {failed = true; continue;}
        const type = row.kind === 'blocked' ? 'blocked' : 'room';
        const key = type === 'room' ? 'room:' + row.id : 'blocked:' + Date.parse(row.starts_at) + ':' + Date.parse(row.ends_at);
        const target = new URLSearchParams({date: kstDate(row.starts_at)});
        if (type === 'room' && row.id) target.set('booking', row.id);
        else target.set('at', new Date(Date.parse(row.starts_at) + 9 * 3600000).toISOString().slice(11,16));
        unique.set(key, {type, start: row.starts_at, end: row.ends_at, title: type === 'blocked' ? '동아리방 이용 불가' : row.representative || '동아리방 예약', url: '/club-room?' + target, allDay: false});
      }
    }
    events = [...unique.values()];
    if (seminar.length && seminar[0].status === 'fulfilled' && Array.isArray(seminar[0].value.events)) events.push(...seminar[0].value.events);
    else if (seminar.length) failed = true;
    $('ic-status').textContent = failed ? '일부 일정을 확인하지 못했어요.' : '전체 조회 완료 · 한국시간';
    $('ic-error').hidden = !failed; $('ic-error').textContent = '조회 실패한 일정이 있어요. 표시되지 않은 시간을 빈 시간으로 판단하지 말고 새로고침해주세요. 예약은 동아리방 화면에서 다시 확인합니다.';
    $('ic-content').setAttribute('aria-busy', 'false'); render();
  }
  $('ic-view').addEventListener('change', load); $('ic-date').addEventListener('change', load); $('ic-refresh').addEventListener('click', load);
  $('ic-today').addEventListener('click', () => {$('ic-date').value = root.dataset.today; load();});
  for (const [id, direction] of [['ic-prev',-1],['ic-next',1]]) $(id).addEventListener('click', () => {
    const d = day($('ic-date').value || root.dataset.today);
    if ($('ic-view').value === 'month') {d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + direction); $('ic-date').value = iso(d);}
    else $('ic-date').value = shift(iso(d), direction * ($('ic-view').value === 'week' ? 7 : 30));
    load();
  });
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => {$('ic-view').value = tab.dataset.calendarView; load();});
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus(); $('ic-view').value = tabs[next].dataset.calendarView; load();
    });
  });
  filterRoot.querySelectorAll('[data-filter]').forEach(input => input.addEventListener('change', render));
  load();
})();
