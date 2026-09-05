/* Date-first schedule drafts. No browser access to Supabase credentials. */
(function (scope) {
    'use strict';
    const copy = value => JSON.parse(JSON.stringify(value));
    const fields = ['book_title', 'book_author', 'note'];
    class ScheduleDrafts {
        constructor(rows) {
            this.rows = copy(rows);
            this.saved = new Map(this.rows.map(row => [row.id, JSON.stringify(row)]));
        }
        get(id) { return this.rows.find(row => row.id === id); }
        dirty(id) { return this.saved.get(id) !== JSON.stringify(this.get(id)); }
        get changed() { return this.rows.filter(row => this.dirty(row.id)); }
        markSaved(row) { this.saved.set(row.id, JSON.stringify(row)); }
        payload(row) {
            const original = JSON.parse(this.saved.get(row.id));
            return {...Object.fromEntries(fields.map(key => [key, row[key]])),
                moderators: row.sessions.filter(item => original.sessions.find(old => old.id === item.id)?.moderator_name !== item.moderator_name)
                    .map(item => ({id: item.id, moderator_name: item.moderator_name}))};
        }
        stage(text) {
            const changes = [], seen = new Set(), errors = [];
            text.split(/\r?\n/).forEach((line, index) => {
                if (!line.trim()) return;
                const cells = line.split(line.includes('\t') ? '\t' : '|').map(cell => cell.trim());
                const candidates = this.rows.filter(row => row.sessions.some(item => item.meeting_date === cells[0]));
                if (!/^\d{4}-\d{2}-\d{2}$/.test(cells[0]) || candidates.length !== 1) {
                    errors.push((index + 1) + '행: 이 학기에 없는 날짜입니다 (' + cells[0] + ').'); return;
                }
                const row = candidates[0];
                if (cells.length < 2 || cells.length > 4 || !cells.slice(1).some(Boolean)) {
                    errors.push((index + 1) + '행: 날짜 뒤에 도서명·저자·안내 중 하나 이상 입력해주세요.'); return;
                }
                if (seen.has(row.id)) { errors.push((index + 1) + '행: 같은 목·월 일정이 중복되었습니다.'); return; }
                if (cells.slice(1).some((cell, i) => cell.length > [500, 200, 4000][i])) {
                    errors.push((index + 1) + '행: 입력 내용이 너무 깁니다.'); return;
                }
                seen.add(row.id); changes.push({row, cells});
            });
            if (errors.length) throw new Error(errors.join('\n'));
            if (!changes.length) throw new Error('붙여넣을 일정을 입력해주세요.');
            // Validate the complete paste first; no partial staging on bad rows.
            changes.forEach(({row, cells}) => fields.forEach((key, i) => {
                if (cells[i + 1]) row[key] = cells[i + 1]; // Empty paste cells never erase stored values.
            }));
            return changes.map(item => item.row.id);
        }
    }

    function mount() {
        const dataNode = document.getElementById('schedule-data');
        if (!dataNode) return;
        const data = JSON.parse(dataNode.textContent), drafts = new ScheduleDrafts(data.rows);
        const tool = document.getElementById('schedule-tool');
        const picker = document.getElementById('schedule-week');
        const form = document.getElementById('schedule-form');
        const status = document.getElementById('schedule-status');
        const bulk = document.getElementById('bulk-books');
        let selected = drafts.rows[0]?.id, saving = false, allowLeave = false;
        function message(text, error = false) {
            if (!status) return;
            status.textContent = text; status.dataset.error = String(error);
            status.style.whiteSpace = 'pre-line';
        }
        const dateLabel = row => row.sessions.map(item => item.meeting_date + (item.day_type === 'thu' ? ' (목)' : ' (월)')).join(' · ');
        function refreshOptions() {
            if (!picker) return;
            picker.replaceChildren(...drafts.rows.map(row => {
                const option = document.createElement('option');
                option.value = row.id;
                option.textContent = dateLabel(row) + ' — ' + (row.book_title || '도서 미정') + (drafts.dirty(row.id) ? ' · 미저장' : '');
                return option;
            }));
            picker.value = selected;
            document.getElementById('schedule-dirty').textContent = drafts.changed.length ? '미저장 ' + drafts.changed.length + '개 일정' : '저장된 일정';
            document.getElementById('schedule-save-all').disabled = !drafts.changed.length;
        }
        function render() {
            if (!form || !selected) return;
            const row = drafts.get(selected);
            fields.forEach(key => form.elements.namedItem(key).value = row[key]);
            document.getElementById('schedule-date-detail').textContent = dateLabel(row) + ' · 날짜를 바꿔도 작성 중인 내용은 유지됩니다.';
            const moderators = document.getElementById('schedule-moderators');
            moderators.replaceChildren(...row.sessions.map(item => {
                const label = document.createElement('label'), input = document.createElement('input');
                label.textContent = item.meeting_date + (item.day_type === 'thu' ? ' 목요일 사회자' : ' 월요일 사회자');
                input.className = 'field'; input.dataset.sessionId = item.id;
                input.setAttribute('list', 'schedule-member-names');
                input.maxLength = 100; input.value = item.moderator_name; input.placeholder = '이름 검색 또는 직접 입력';
                label.appendChild(input); return label;
            }));
            refreshOptions();
        }
        form?.addEventListener('input', event => {
            const row = drafts.get(selected), input = event.target;
            if (fields.includes(input.name)) row[input.name] = input.value;
            else if (input.dataset.sessionId) row.sessions.find(item => item.id === input.dataset.sessionId).moderator_name = input.value;
            refreshOptions(); message('');
        });
        picker?.addEventListener('change', () => { selected = picker.value; render(); message(''); });
        function open(id, sessionId) {
            if (saving || !drafts.get(id)) return;
            selected = id; tool.open = true; render();
            const target = sessionId ? [...form.querySelectorAll('[data-session-id]')].find(node => node.dataset.sessionId === sessionId) : form.elements.namedItem('book_title');
            target?.focus({preventScroll: true});
            // A moderator sits below the book fields on mobile. Bring the actual
            // input into view instead of focusing an off-screen control.
            (target || tool).scrollIntoView({block: 'center', behavior: 'smooth'});
            document.querySelectorAll('.schedule-selected').forEach(node => node.classList.remove('schedule-selected'));
            document.querySelectorAll('[data-week]').forEach(node => { if (node.dataset.week === id) node.classList.add('schedule-selected'); });
        }
        document.addEventListener('click', event => {
            const button = event.target.closest('[data-open-schedule]');
            if (button) open(button.dataset.openSchedule, button.dataset.focusSession);
        });
        async function request(url, body) {
            const response = await fetch(url, {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Schedule-CSRF': data.csrf}, body: JSON.stringify(body)});
            let result;
            try { result = await response.json(); } catch (_) { throw new Error('응답을 확인하지 못했습니다. 로그인 상태를 확인하고 다시 저장해주세요.'); }
            if (!response.ok || result.status !== 'success') throw new Error(result.message || '저장하지 못했습니다.');
        }
        function updateSummary(row) {
            const card = [...document.querySelectorAll('[data-week]')].find(node => node.dataset.week === row.id);
            if (!card) return;
            card.querySelector('.schedule-book-display').textContent = row.book_title || '도서 미정';
            card.querySelector('.schedule-author-display').textContent = row.book_author;
            card.querySelector('.schedule-note-display').textContent = row.note;
            row.sessions.forEach(item => [...card.querySelectorAll('[data-moderator-display]')].forEach(node => {
                if (node.dataset.moderatorDisplay === item.id) node.textContent = item.moderator_name || '미입력';
            }));
            card.querySelectorAll('.chip').forEach(node => {
                if (node.textContent.trim() === '도서 확인 필요') node.remove();
            });
            document.dispatchEvent(new CustomEvent('seminar:schedule-saved', {detail: {weekId: row.id}}));
        }
        async function save(rows) {
            if (saving || !rows.length || !form.reportValidity()) return;
            saving = true;
            document.getElementById('schedule-fields').disabled = true;
            let saved = 0;
            try {
                for (const row of rows) {
                    message(dateLabel(row) + ' 저장 중…');
                    const snapshot = copy(row);
                    await request('/api/admin/seminar_weeks/' + encodeURIComponent(row.id), drafts.payload(snapshot));
                    fields.forEach(key => snapshot[key] = snapshot[key].trim());
                    snapshot.sessions.forEach(item => item.moderator_name = item.moderator_name.trim().replace(/\s+/g, ' '));
                    Object.assign(row, snapshot);
                    drafts.markSaved(snapshot); updateSummary(snapshot); saved++;
                }
                message(saved + '개 일정을 저장했습니다. 도서와 회차별 사회자가 반영되었습니다.');
            } catch (error) {
                message((saved ? saved + '개 저장 완료. 나머지 일정은 ' : '') + '입력 내용을 유지했습니다. ' + error.message, true);
            } finally {
                saving = false; document.getElementById('schedule-fields').disabled = false; render();
            }
        }
        form?.addEventListener('submit', event => { event.preventDefault(); save([drafts.get(selected)]); });
        document.getElementById('schedule-save-all')?.addEventListener('click', () => save(drafts.changed));
        document.getElementById('bulk-stage')?.addEventListener('click', () => {
            try {
                const ids = drafts.stage(bulk.value);
                selected = ids[0]; bulk.value = ''; render();
                message(ids.length + '개 일정에 내용을 채웠습니다 (아직 저장 전). 날짜별로 확인 후 저장해주세요.');
            } catch (error) { message(error.message, true); }
        });
        function hasDrafts() { return saving || drafts.changed.length > 0 || Boolean(bulk?.value.trim()); }
        function confirmLeave() { return !hasDrafts() || scope.confirm('저장하지 않은 일정 입력이 있습니다. 저장하지 않고 이동할까요?'); }
        scope.addEventListener('beforeunload', event => {
            if (!allowLeave && hasDrafts()) { event.preventDefault(); event.returnValue = ''; }
        });
        const termSelect = document.getElementById('seminar-term-select'), originalTerm = termSelect?.value;
        termSelect?.addEventListener('change', () => {
            if (saving || !confirmLeave()) { termSelect.value = originalTerm; return; }
            allowLeave = true; scope.location.href = '/admin/seminars?term_id=' + encodeURIComponent(termSelect.value);
        });
        document.getElementById('term-create')?.addEventListener('submit', async event => {
            event.preventDefault();
            if (saving || !confirmLeave()) return;
            const createForm = event.target, resultNode = document.getElementById('term-create-status');
            const values = Object.fromEntries(new FormData(createForm));
            if (values.start_date > values.end_date) { resultNode.textContent = '마지막 세미나 날짜는 첫 세미나 날짜 이후로 선택해주세요.'; return; }
            const button = createForm.querySelector('button');
            button.disabled = true;
            resultNode.textContent = '학기와 세미나 날짜를 생성하고 있습니다…';
            try {
                const response = await fetch('/api/admin/seminar_terms/create', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values)});
                const result = await response.json();
                if (!response.ok || result.status !== 'success') throw new Error(result.message || '학기를 생성하지 못했습니다.');
                allowLeave = true;
                scope.location.href = '/admin/seminars?term_id=' + encodeURIComponent(result.term.id) + '&schedule=1#schedule-tool';
            } catch (error) { resultNode.textContent = error.message; button.disabled = false; }
        });
        render();
        if (new URLSearchParams(scope.location.search).has('schedule') || !drafts.rows.length) tool.open = true;
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = {ScheduleDrafts};
    else mount();
})(typeof window !== 'undefined' ? window : globalThis);
