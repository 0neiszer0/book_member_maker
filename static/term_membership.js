(function (root) {
  'use strict';
  class TermRosterDraft {
    constructor(data) {
      this.term = data.term;
      this.terms = data.terms;
      this.members = data.members;
      this.history = data.memberships;
      this.sourceTermIds = data.source_term_ids || [];
      this.entries = new Map(this.history.filter(row => row.term_id === this.term.id).map(row => [row.member_id, {member_id: row.member_id, status: row.status, entry_type: row.entry_type}]));
      this.original = this.serialize();
    }
    suggestedType(id) {
      const prior = this.terms.filter(t => t.start_date < this.term.start_date).sort((a, b) => b.start_date.localeCompare(a.start_date));
      const automatic = this.sourceTermIds.length ? this.sourceTermIds : [prior[0]?.id].filter(Boolean);
      const previous = this.history.find(row => row.member_id === id && automatic.includes(row.term_id) && row.status === 'active');
      if (previous) return 'continuing';
      return this.history.some(row => row.member_id === id && prior.some(t => t.id === row.term_id)) ? 'returning' : 'new';
    }
    setStatus(id, status) {
      if (!['active', 'paused', 'left'].includes(status)) throw new Error('잘못된 활동 상태');
      const previous = this.entries.get(id);
      this.entries.set(id, {member_id: id, status, entry_type: previous?.entry_type || this.suggestedType(id)});
    }
    carry(sourceId) {
      const source = this.terms.find(t => t.id === sourceId);
      if (!source?.roster_initialized_at || source.start_date >= this.term.start_date) throw new Error('이전 학기의 명단을 먼저 확정해주세요.');
      let added = 0;
      this.history.filter(row => row.term_id === sourceId && row.status === 'active').forEach(row => {
        // Never overwrite an intentional pause/end in the target draft.
        if (!this.entries.has(row.member_id)) {
          this.entries.set(row.member_id, {member_id: row.member_id, status: 'active', entry_type: this.suggestedType(row.member_id)});
          added++;
        }
      });
      return added;
    }
    payload() { return [...this.entries.values()].sort((a, b) => a.member_id - b.member_id); }
    serialize() { return JSON.stringify(this.payload()); }
    get dirty() { return this.original !== this.serialize(); }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {TermRosterDraft};
  root.TermRosterDraft = TermRosterDraft;
  if (typeof document === 'undefined') return;
  const shell = document.getElementById('term-members');
  if (!shell) return;
  const data = JSON.parse(document.getElementById('term-members-data').textContent);
  data.statuses = {active: data.statuses.active, paused: data.statuses.paused, left: data.statuses.left};
  const draft = data.term ? new TermRosterDraft(data) : null;
  let busy = false, filter = 'assigned';
  const byId = id => document.getElementById(id);
  function ask(message) {
    return new Promise(resolve => {
      const dialog = document.createElement('dialog'); dialog.className = 'term-confirm';
      dialog.setAttribute('aria-label', '명단 변경 확인');
      const title = document.createElement('h2'); title.textContent = '명단 변경 확인';
      const text = document.createElement('p'); text.textContent = message;
      const actions = document.createElement('div'); actions.className = 'attendance-actions';
      const cancel = document.createElement('button'), accept = document.createElement('button');
      cancel.type = accept.type = 'button'; cancel.textContent = '취소'; accept.textContent = '확인 후 진행';
      const finish = answer => { dialog.close(); dialog.remove(); resolve(answer); };
      cancel.addEventListener('click', () => finish(false)); accept.addEventListener('click', () => finish(true));
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false); });
      actions.append(cancel, accept); dialog.append(title, text, actions); document.body.append(dialog);
      dialog.showModal(); cancel.focus();
    });
  }
  async function api(url, body) {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': shell.dataset.csrf}, body: JSON.stringify(body)});
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.status === 'error') throw new Error(result.message || '요청을 완료하지 못했습니다. 로그인 상태를 확인해주세요.');
    return result;
  }
  function lock(value) {
    busy = value;
    shell.querySelectorAll('button,input,select').forEach(el => { el.disabled = value; });
  }
  window.addEventListener('beforeunload', event => {
    if (draft?.dirty || busy) { event.preventDefault(); event.returnValue = ''; }
  });
  byId('term-id').addEventListener('change', async () => {
    if (draft?.dirty && !await ask('저장하지 않은 명단 변경을 버리고 다른 학기로 이동할까요?')) { byId('term-id').value = data.term.id; return; }
    if (draft) draft.original = draft.serialize();
    byId('term-picker').submit();
  });
  const newTerm = byId('new-term');
  newTerm.elements.year.value = new Date().getFullYear();
  newTerm.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    if (draft?.dirty && !await ask('현재 학기의 저장하지 않은 변경을 버리고 새 학기를 만들까요?')) return;
    const form = Object.fromEntries(new FormData(newTerm));
    lock(true);
    try {
      const result = await api('/api/admin/term_members/create_term', {...form, name: `${form.year}-${form.season}`});
      if (draft) draft.original = draft.serialize();
      busy = false;
      location.assign(`/admin/term_members?term_id=${encodeURIComponent(result.term.id)}`);
    } catch (error) { byId('new-term-status').textContent = error.message; lock(false); }
  });
  if (!draft) return;
  const recentMemberIds = new Set(draft.history
    .filter(row => draft.sourceTermIds.includes(row.term_id) && row.status === 'active')
    .map(row => row.member_id));
  function visibleMembers() {
    const search = byId('term-member-search').value.trim().toLocaleLowerCase();
    return draft.members.filter(member => {
      const assigned = draft.entries.has(member.id);
      const inFilter = filter === 'assigned' ? assigned
        : filter === 'recent' ? !assigned && recentMemberIds.has(member.id)
          : !assigned;
      return inFilter &&
        [member.name, member.student_id, member.department].join(' ').toLocaleLowerCase().includes(search);
    });
  }
  function optionSelect(values, value, label, change) {
    const wrapper = document.createElement('label'); wrapper.textContent = label;
    const select = document.createElement('select');
    Object.entries(values).forEach(([key, text]) => { const option = document.createElement('option'); option.value = key; option.textContent = text; select.append(option); });
    select.value = value;
    select.addEventListener('change', () => change(select.value));
    wrapper.append(select); return wrapper;
  }
  function summary() {
    const entries = draft.payload();
    const counts = Object.keys(data.statuses).map(key => `${data.statuses[key]} ${entries.filter(e => e.status === key).length}명`);
    byId('term-count').textContent = `${counts.join(' · ')} / 검색 결과 ${visibleMembers().length}명`;
    byId('term-dirty').textContent = draft.dirty ? '아직 저장하지 않은 변경이 있습니다' : '저장된 명단';
    byId('term-empty').hidden = visibleMembers().length !== 0;
  }
  function render() {
    const list = byId('term-member-list'); list.replaceChildren();
    visibleMembers().forEach(member => {
      const entry = draft.entries.get(member.id);
      const card = document.createElement('article'); card.className = 'term-member-card'; card.dataset.status = entry?.status || '';
      const heading = document.createElement('div'), name = document.createElement('strong'), detail = document.createElement('small');
      name.textContent = member.name; detail.textContent = `${member.student_id || '학번 없음'} · ${member.department || '학과 없음'}`;
      heading.append(name, detail); card.append(heading);
      if (!entry) {
        const add = document.createElement('button'); add.type = 'button'; add.textContent = `이 학기에 추가 (${data.entry_types[draft.suggestedType(member.id)]})`;
        add.addEventListener('click', () => { draft.setStatus(member.id, 'active'); render(); }); card.append(add);
      } else {
        const fields = document.createElement('div'); fields.className = 'term-member-fields';
        fields.append(optionSelect(data.statuses, entry.status, `${member.name} 활동 상태`, status => {
          draft.setStatus(member.id, status); card.dataset.status = status; summary();
        }), optionSelect(data.entry_types, entry.entry_type, `${member.name} 참여 구분`, kind => {
          entry.entry_type = kind; draft.entries.get(member.id).entry_type = kind; summary();
        })); card.append(fields);
      }
      list.append(card);
    });
    summary();
  }
  byId('term-member-search').addEventListener('input', render);
  document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    filter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(el => el.setAttribute('aria-pressed', String(el === button))); render();
  }));
  byId('copy-term').addEventListener('click', () => {
    try { const count = draft.carry(byId('copy-source').value); byId('term-save-status').textContent = `${count}명을 추가했습니다. 명단을 확인하고 저장해주세요.`; render(); }
    catch (error) { byId('term-save-status').textContent = error.message; }
  });
  byId('bulk-apply').addEventListener('click', async () => {
    const visible = visibleMembers(), status = byId('bulk-status').value;
    if (!visible.length || !await ask(`검색된 ${visible.length}명을 '${data.statuses[status]}' 상태로 변경할까요? 명단 저장 전에는 반영되지 않습니다.`)) return;
    visible.forEach(member => draft.setStatus(member.id, status)); render();
  });
  byId('save-term-members').addEventListener('click', async () => {
    if (busy) return;
    const entries = draft.payload(), count = entries.filter(row => row.status === 'active').length;
    if (!await ask(`${data.term.name}의 활동 회원 ${count}명, 전체 명단 ${entries.length}명을 저장할까요? 다른 학기와 기존 출석 기록은 바뀌지 않습니다.`)) return;
    lock(true); byId('term-save-status').textContent = '저장 중…';
    try {
      const result = await api(`/api/admin/term_members/${encodeURIComponent(data.term.id)}`, {entries, revision: data.term.roster_revision || 0});
      data.term.roster_revision = result.revision; draft.original = draft.serialize();
      busy = false; location.reload();
    } catch (error) { byId('term-save-status').textContent = error.message; lock(false); }
  });
  byId('new-term-member').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    const form = event.currentTarget, fields = Object.fromEntries(new FormData(form));
    lock(true);
    try {
      const result = await api('/api/admin/term_members/new_member', fields);
      if (!result.member?.id) throw new Error('회원 등록 결과를 확인하려면 새로고침해주세요. 중복 등록하지 마세요.');
      draft.members.push(result.member); draft.members.sort((a, b) => a.name.localeCompare(b.name, 'ko'));
      draft.setStatus(result.member.id, 'active'); filter = 'assigned'; byId('term-member-search').value = '';
      document.querySelectorAll('[data-filter]').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.filter === filter)));
      form.reset(); byId('new-member-status').textContent = `${result.member.name}님을 등록했습니다. 학기 명단 저장도 눌러주세요.`; render();
    } catch (error) { byId('new-member-status').textContent = error.message; }
    finally { lock(false); }
  });
  render();
})(typeof globalThis !== 'undefined' ? globalThis : this);
