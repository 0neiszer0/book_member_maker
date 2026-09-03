/* Shared, dependency-free group editor. Names remain legacy record keys. */
(function (scope) {
    'use strict';
    const copy = value => JSON.parse(JSON.stringify(value));
    const unique = values => [...new Set(values.filter(Boolean))];
    const escape = value => String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));

    class GroupEditorState {
        constructor(options) {
            this.groups = copy(options.groups || []);
            this.groupNames = this.groups.map((group, index) => (options.groupNames || [])[index] || `조 ${index + 1}`);
            this.participants = unique([...(options.participants || []), ...this.groups.flat()]);
            this.excluded = copy(options.excluded || []);
            this.participants = unique([...this.participants, ...this.excluded.map(item => item.name)]);
            this.facilitators = unique(options.facilitators || []);
            this.undoStack = [];
            this.saved = JSON.stringify(this.snapshot());
        }
        snapshot() { return copy({groups: this.groups, groupNames: this.groupNames, participants: this.participants, excluded: this.excluded, facilitators: this.facilitators}); }
        get unassigned() {
            const assigned = new Set([...this.groups.flat(), ...this.excluded.map(item => item.name)]);
            return this.participants.filter(name => !assigned.has(name));
        }
        get dirty() { return this.saved !== JSON.stringify(this.snapshot()); }
        change(fn) {
            const before = this.snapshot();
            fn();
            if (JSON.stringify(before) !== JSON.stringify(this.snapshot())) this.undoStack.push(before);
            if (this.undoStack.length > 50) this.undoStack.shift();
        }
        move(name, destination) {
            if (!this.participants.includes(name)) return;
            if (destination !== 'unassigned' && (!Number.isInteger(Number(destination)) || !this.groups[Number(destination)])) return;
            this.change(() => {
                this.groups = this.groups.map(group => group.filter(member => member !== name));
                this.excluded = this.excluded.filter(item => item.name !== name);
                if (destination !== 'unassigned') this.groups[Number(destination)].push(name);
            });
        }
        exclude(name, reason) {
            if (!this.participants.includes(name) || !String(reason || '').trim()) return;
            this.change(() => {
                this.groups = this.groups.map(group => group.filter(member => member !== name));
                this.excluded = this.excluded.filter(item => item.name !== name);
                this.excluded.push({name, reason: String(reason).trim().slice(0, 200)});
            });
        }
        addParticipant(name) {
            if (!name || this.participants.includes(name)) return;
            this.change(() => this.participants.push(name));
        }
        addGroup() { this.change(() => { this.groups.push([]); this.groupNames.push(`새 조 ${this.groups.length}`); }); }
        removeGroup(index) { if (this.groups[index]) this.change(() => { this.groups.splice(index, 1); this.groupNames.splice(index, 1); }); }
        toggleFacilitator(name) {
            this.change(() => { this.facilitators = this.facilitators.includes(name) ? this.facilitators.filter(item => item !== name) : [...this.facilitators, name]; });
        }
        undo() { const state = this.undoStack.pop(); if (state) Object.assign(this, state); }
        markSaved() { this.saved = JSON.stringify(this.snapshot()); }
        error() {
            if (this.unassigned.length) return `미배정 ${this.unassigned.length}명을 조에 배정하거나 사유를 입력해 편성에서 제외해주세요.`;
            if (!this.groups.length || !this.groups.flat().length) return '한 명 이상 배정된 조가 필요합니다.';
            if (this.groups.some(group => !group.length)) return '빈 조에 참여자를 배정하거나 빈 조를 삭제해주세요.';
            if (unique(this.groups.flat()).length !== this.groups.flat().length) return '같은 사람이 여러 번 배정되어 있습니다. 중복 배정을 확인해주세요.';
            return '';
        }
        payload() {
            const present = this.groups.flat();
            return copy({groups: this.groups, groupNames: this.groupNames, present, facilitators: this.facilitators.filter(name => present.includes(name)),
                group_editor_state: {participants: this.participants, excluded: this.excluded, group_names: this.groupNames}});
        }
    }

    function pairHistory(group, history) {
        const known = [];
        let fresh = 0;
        for (let i = 0; i < group.length; i++) {
            for (let j = i + 1; j < group.length; j++) {
                const pair = [group[i], group[j]].sort();
                const entry = history[pair.join('-')];
                if (!entry || !entry.count) { fresh++; continue; }
                known.push({pair, count: Number(entry.count), dates: entry.dates || (entry.last_met ? [entry.last_met] : [])});
            }
        }
        known.sort((a, b) => b.count - a.count || String(b.dates[0] || '').localeCompare(String(a.dates[0] || '')));
        return {known, fresh};
    }

    function mount(container, options) {
        const state = new GroupEditorState(options);
        const genders = options.genders || {};
        let selected = null;
        let dragging = null;
        let pointerDrag = null;
        let suppressClickUntil = 0;
        const groupName = index => state.groupNames[index] || `조 ${index + 1}`;
        container.classList.add('ge-editor');
        container._groupEditorState = state;

        function chip(name, removable) {
            const gender = genders[name] === 'M' ? '남' : (genders[name] === 'W' ? '여' : '');
            const genderClass = gender === '남' ? 'ge-male' : (gender === '여' ? 'ge-female' : '');
            return `<span class="ge-chip ${genderClass}"><button type="button" class="ge-member" draggable="true" data-member="${escape(name)}" aria-pressed="${selected === name}" aria-label="${escape(name)} 이동 또는 수정">${escape(name)}${gender ? `<small>${gender}</small>` : ''}${state.facilitators.includes(name) ? '<span aria-label="발제자">★</span>' : ''}</button>${removable ? `<button type="button" class="ge-unassign" data-member="${escape(name)}" aria-label="${escape(name)} 미배정으로 이동">×</button>` : ''}</span>`;
        }
        function historyHtml(group) {
            const {known, fresh} = pairHistory(group, options.meetingHistory || {});
            return `<section class="ge-history" aria-label="이전 만남 기록"><h4>이전 만남 <span>처음 만나는 쌍 ${fresh}쌍</span></h4>${known.length ? `<ul>${known.map(item => `<li><strong>${escape(item.pair.join(' ↔ '))}</strong><span>${item.count}회 · ${item.dates.map(escape).join(', ') || '날짜 미기록'}</span></li>`).join('')}</ul>` : `<p>${group.length < 2 ? '두 명 이상 배정하면 이전 만남을 확인할 수 있습니다.' : '이 조는 모두 처음 만나는 조합입니다.'}</p>`}</section>`;
        }
        function render(focusMove = false) {
            const assigned = state.groups.flat().length;
            const unassigned = state.unassigned;
            const candidates = unique((options.members || []).map(member => typeof member === 'string' ? member : member.name)).filter(name => !state.participants.includes(name));
            container.innerHTML = `<div class="ge-summary" role="status" aria-live="polite"><strong>배정 ${assigned}명 · 미배정 ${unassigned.length}명 · 편성 제외 ${state.excluded.length}명</strong><span>${state.dirty ? '저장하지 않은 변경사항' : '현재 편성'}</span></div>
                <p class="ge-help">사람을 끌어서 이동하거나 이름을 눌러 이동할 조를 선택하세요. ×는 삭제가 아니라 미배정으로 이동합니다. 이전 만남은 즉시 갱신됩니다.</p>
                <div class="ge-tools"><button type="button" data-action="undo" ${state.undoStack.length ? '' : 'disabled'}>이동·수정 되돌리기</button><button type="button" data-action="add-group">+ 조 추가</button>${candidates.length ? `<label>참여자 추가 <select data-add-member><option value="">회원 선택</option>${candidates.map(name => `<option value="${escape(name)}">${escape(name)}</option>`).join('')}</select></label><button type="button" data-action="add-member">추가</button>` : ''}</div>
                <section class="ge-tray" data-destination="unassigned" aria-label="미배정 참여자"><h3>미배정 참여자 <span>${unassigned.length}명</span></h3><div class="ge-chips">${unassigned.map(name => chip(name, false)).join('') || '<p>조에서 뺀 사람은 여기에 남습니다.</p>'}</div></section>
                ${selected ? `<section class="ge-move-panel" aria-label="참여자 이동"><strong>${escape(selected)}</strong><label>이동할 곳 <select data-move-destination><option value="unassigned">미배정 참여자</option>${state.groups.map((group, index) => `<option value="${index}">${escape(groupName(index))} (${group.length}명)</option>`).join('')}</select></label><button type="button" data-action="move">이동</button><button type="button" data-action="facilitator">발제자 ${state.facilitators.includes(selected) ? '해제' : '지정'}</button><button type="button" data-action="close-move">닫기</button><div class="ge-exclude-control"><label>편성 제외 사유 <input data-exclusion-reason maxlength="200" placeholder="예: 이번 회차 참석 취소"></label><button type="button" data-action="exclude">편성에서 제외</button><p>편성에서만 제외합니다. 실제 출석·무단 불참 상태는 변경하지 않습니다.</p></div></section>` : ''}
                ${state.excluded.length ? `<section class="ge-excluded" aria-label="편성 제외 참여자"><h3>편성 제외 <span>${state.excluded.length}명</span></h3><ul>${state.excluded.map(item => `<li><span><strong>${escape(item.name)}</strong> · ${escape(item.reason)}</span><button type="button" data-restore="${escape(item.name)}">미배정으로 복원</button></li>`).join('')}</ul><p>실제 출석·불참 처리와 별개입니다.</p></section>` : ''}
                <div class="ge-groups">${state.groups.map((group, index) => `<section class="ge-group" data-destination="${index}" aria-label="${escape(groupName(index))}"><header><h3>${escape(groupName(index))} <span class="ge-count">${group.length}명</span></h3><button type="button" data-remove-group="${index}">조 삭제</button></header><p class="ge-balance">남 ${group.filter(name => genders[name] === 'M').length}명 · 여 ${group.filter(name => genders[name] === 'W').length}명 · 발제자 ${group.filter(name => state.facilitators.includes(name)).length}명</p><div class="ge-chips">${group.map(name => chip(name, true)).join('') || '<p>여기로 참여자를 옮겨주세요.</p>'}</div>${historyHtml(group)}</section>`).join('')}</div>`;
            if (focusMove) container.querySelector('[data-move-destination]')?.focus();
            if (options.onChange) options.onChange(state);
        }
        container.addEventListener('click', event => {
            if (Date.now() < suppressClickUntil) { event.preventDefault(); return; }
            const target = event.target.closest('button');
            if (!target) return;
            if (target.classList.contains('ge-unassign')) { state.move(target.dataset.member, 'unassigned'); selected = null; }
            else if (target.classList.contains('ge-member')) { selected = target.dataset.member; render(true); return; }
            else if (target.hasAttribute('data-restore')) state.move(target.dataset.restore, 'unassigned');
            else if (target.hasAttribute('data-remove-group')) {
                const index = Number(target.dataset.removeGroup);
                if (state.groups[index].length && !scope.confirm(`${groupName(index)}을 삭제하면 참여자가 미배정으로 이동합니다. 계속할까요?`)) return;
                state.removeGroup(index);
            } else {
                switch (target.dataset.action) {
                    case 'undo': state.undo(); selected = null; break;
                    case 'add-group': state.addGroup(); break;
                    case 'add-member': state.addParticipant(container.querySelector('[data-add-member]')?.value); break;
                    case 'move': state.move(selected, container.querySelector('[data-move-destination]').value); selected = null; break;
                    case 'facilitator': state.toggleFacilitator(selected); break;
                    case 'close-move': selected = null; break;
                    case 'exclude': {
                        const reason = container.querySelector('[data-exclusion-reason]').value.trim();
                        if (!reason) { scope.alert('잊지 않도록 편성 제외 사유를 입력해주세요.'); return; }
                        state.exclude(selected, reason); selected = null; break;
                    }
                    default: return;
                }
            }
            render();
        });
        // Some embedded browsers do not dispatch HTML5 drops for draggable buttons.
        // Mouse pointers use a threshold + hit test; touch remains native scrolling
        // with the same accessible tap-to-move controls.
        container.addEventListener('pointerdown', event => {
            const member = event.target.closest('.ge-member');
            if (!member || event.pointerType !== 'mouse' || event.button !== 0) return;
            pointerDrag = {name: member.dataset.member, x: event.clientX, y: event.clientY, id: event.pointerId, member, active: false};
            member.draggable = false;
            member.setPointerCapture?.(event.pointerId);
        });
        container.addEventListener('pointermove', event => {
            if (!pointerDrag || pointerDrag.id !== event.pointerId) return;
            if (Math.hypot(event.clientX - pointerDrag.x, event.clientY - pointerDrag.y) > 7) pointerDrag.active = true;
            if (!pointerDrag.active) return;
            event.preventDefault();
            container.querySelectorAll('.ge-drop-target').forEach(node => node.classList.remove('ge-drop-target'));
            const destination = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-destination]');
            if (destination && container.contains(destination)) destination.classList.add('ge-drop-target');
        });
        function endPointerDrag(event, cancelled) {
            if (!pointerDrag || pointerDrag.id !== event.pointerId) return;
            const drag = pointerDrag;
            pointerDrag = null;
            drag.member.draggable = true;
            if (drag.member.hasPointerCapture?.(event.pointerId)) drag.member.releasePointerCapture(event.pointerId);
            container.querySelectorAll('.ge-drop-target').forEach(node => node.classList.remove('ge-drop-target'));
            if (!drag.active) return;
            suppressClickUntil = Date.now() + 350;
            event.preventDefault();
            if (cancelled) return;
            const destination = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-destination]');
            if (destination && container.contains(destination)) { state.move(drag.name, destination.dataset.destination); selected = null; render(); }
        }
        container.addEventListener('pointerup', event => endPointerDrag(event, false));
        container.addEventListener('pointercancel', event => endPointerDrag(event, true));
        container.addEventListener('dragstart', event => {
            const member = event.target.closest('.ge-member');
            if (!member) return;
            dragging = member.dataset.member;
            event.dataTransfer.setData('text/plain', dragging);
            event.dataTransfer.effectAllowed = 'move';
        });
        container.addEventListener('dragover', event => {
            if (!dragging) return;
            const destination = event.target.closest('[data-destination]');
            if (destination) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; destination.classList.add('ge-drop-target'); }
        });
        container.addEventListener('dragleave', event => event.target.closest('[data-destination]')?.classList.remove('ge-drop-target'));
        container.addEventListener('drop', event => {
            const destination = event.target.closest('[data-destination]');
            if (!dragging || !destination) return;
            event.preventDefault();
            state.move(dragging, destination.dataset.destination);
            dragging = null; selected = null; render();
        });
        container.addEventListener('dragend', () => { dragging = null; container.querySelectorAll('.ge-drop-target').forEach(node => node.classList.remove('ge-drop-target')); });
        render();
        return {state, render, markSaved() { state.markSaved(); render(); }, ready() { const error = state.error(); if (error) scope.alert(error); return !error; }};
    }

    async function validate(groups) {
        try {
            const response = await fetch('/api/bookclub/validate-groups', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({groups})});
            const result = await response.json();
            if (!response.ok || !result.valid) throw new Error(result.message || '편성 내용을 다시 확인해주세요.');
            return true;
        } catch (error) { scope.alert(error.message || '편성 제한을 확인하지 못했습니다. 잠시 후 다시 시도해주세요.'); return false; }
    }

    async function capture(options) {
        if (typeof scope.html2canvas !== 'function') throw new Error('캡처 기능을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.');
        const container = document.createElement('div');
        const groups = options.groups;
        Object.assign(container.style, {position: 'fixed', top: '0px', left: '0px', zIndex: '-1', width: '900px', padding: '44px', backgroundColor: '#FAF6EC', color: '#2A241B', fontFamily: "'Pretendard', sans-serif", boxSizing: 'border-box', pointerEvents: 'none', lineHeight: '1.5'});
        container.setAttribute('aria-hidden', 'true');
        const meta = [options.date, options.bookTitle, `총 ${groups.flat().length}명 · ${groups.length}개 조`].filter(Boolean).map(escape).join(' · ');
        container.innerHTML = `<header style="border-bottom:2px solid #3D5C2E;padding-bottom:22px;margin-bottom:24px"><p style="font-size:16px;font-weight:800;color:#7A5A3A">책 먹는 호반우</p><h2 style="font-size:30px;font-weight:800;margin:8px 0">세미나 조 편성</h2><p style="font-size:16px">${meta}</p></header><div style="display:grid;grid-template-columns:1fr;gap:12px">${groups.map((group, index) => `<section style="padding:20px;border:1px solid #E5D7B8;border-radius:16px;background:#FFFCF3"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px"><strong style="font-size:20px;color:#3D5C2E">${escape((options.groupNames || [])[index] || `조 ${index + 1}`)}</strong><span style="font-size:16px">${group.length}명</span></div><div data-capture-names style="white-space:nowrap;font-size:19px;line-height:1.7">${group.map(name => {
            const gender = (options.genders || {})[name];
            const color = gender === 'M' ? '#2E6275' : (gender === 'W' ? '#8A4F62' : '#40382E');
            return `<span style="color:${color};white-space:nowrap;font-weight:${(options.facilitators || []).includes(name) ? '850' : '500'}">${escape(name)}</span>`;
        }).join(', ')}</div></section>`).join('')}</div><p style="margin-top:24px;font-size:14px;color:#6B6255">여성은 자주색, 남성은 청록색 · 진한 이름은 발제자</p>`;
        document.body.appendChild(container);
        try {
            if (document.fonts && document.fonts.ready) await document.fonts.ready;
            // Grow the export canvas to the longest comma-separated row: never clip names.
            const extra = Math.max(0, ...[...container.querySelectorAll('[data-capture-names]')].map(node => node.scrollWidth - node.clientWidth));
            const width = Math.ceil(900 + extra);
            container.style.width = `${width}px`;
            const height = container.scrollHeight;
            const scale = Math.min(2, 16000 / Math.max(width, height), Math.sqrt(16000000 / (width * height)));
            const canvas = await scope.html2canvas(container, {scale, backgroundColor: '#FAF6EC', useCORS: true, logging: false, scrollX: 0, scrollY: 0, windowWidth: width, windowHeight: height});
            return canvas.toDataURL('image/png');
        } finally { container.remove(); }
    }
    if (typeof window !== 'undefined') window.addEventListener('beforeunload', event => {
        if ([...document.querySelectorAll('.ge-editor')].some(node => node._groupEditorState?.dirty)) { event.preventDefault(); event.returnValue = ''; }
    });
    const api = {GroupEditorState, pairHistory, mount, validate, capture};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else scope.GroupEditor = api;
})(typeof window !== 'undefined' ? window : globalThis);
