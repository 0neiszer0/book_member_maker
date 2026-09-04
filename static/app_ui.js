/* 책 먹는 호반우 — 공통 사용성 보강
 * 기존 Flask/Jinja 라우트와 데이터 계약을 유지한 채 화면만 점진적으로 개선한다.
 */
(function () {
  'use strict';

  const q = (selector, root = document) => root?.querySelector?.(selector) || null;
  const qa = (selector, root = document) => root?.querySelectorAll ? Array.from(root.querySelectorAll(selector)) : [];
  const cleanText = element => (element?.textContent || '').replace(/\s+/g, ' ').trim();
  const userRole = q('meta[name="app-user-role"]')?.content || '';
  const selectorEscape = value => {
    const text = String(value ?? '');
    if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(text);
    return text.replace(/["\\]/g, '\\$&');
  };

  function ensureToastRegion() {
    let region = q('#wd-toast-region');
    if (region) return region;
    region = document.createElement('div');
    region.id = 'wd-toast-region';
    region.className = 'wd-toast-region';
    region.setAttribute('role', 'status');
    region.setAttribute('aria-live', 'polite');
    region.setAttribute('aria-atomic', 'true');
    document.body.appendChild(region);
    return region;
  }

  function makeRoomForToast(region, incomingAction = false) {
    const mobile = window.matchMedia('(max-width: 767px)').matches;
    const maxVisible = mobile ? 1 : 3;
    const current = qa(':scope > .wd-toast', region);
    while (current.length >= maxVisible) {
      const removableIndex = current.findIndex(item => !item.classList.contains('wd-toast-action'));
      const index = removableIndex >= 0 ? removableIndex : (incomingAction ? 0 : -1);
      if (index < 0) break;
      current.splice(index, 1)[0]?.remove();
    }
  }

  function fallbackToast(message, kind = 'success', duration = 2800) {
    if (!message) return;
    const region = ensureToastRegion();
    makeRoomForToast(region);
    const toast = document.createElement('div');
    toast.className = `wd-toast ${kind}`;
    toast.textContent = String(message);
    region.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    window.setTimeout(() => {
      toast.classList.remove('show');
      window.setTimeout(() => toast.remove(), 180);
    }, duration);
  }

  if (typeof window.wdToast !== 'function') window.wdToast = fallbackToast;

  if (typeof window.wdToastUndo !== 'function') {
    window.wdToastUndo = function (message, undo, duration = 6000) {
      if (!message || typeof undo !== 'function') return;
      const region = ensureToastRegion();
      makeRoomForToast(region, true);
      const toast = document.createElement('div');
      toast.className = 'wd-toast wd-toast-action success';

      const copy = document.createElement('span');
      copy.textContent = String(message);
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = '되돌리기';
      button.addEventListener('click', async () => {
        button.disabled = true;
        button.textContent = '처리 중…';
        try {
          await undo();
          toast.remove();
        } catch (error) {
          button.disabled = false;
          button.textContent = '되돌리기';
          window.wdToast(error?.message || '되돌리지 못했습니다.', 'error');
        }
      });
      toast.append(copy, button);
      region.appendChild(toast);
      requestAnimationFrame(() => toast.classList.add('show'));
      window.setTimeout(() => {
        if (!toast.isConnected) return;
        toast.classList.remove('show');
        window.setTimeout(() => toast.remove(), 180);
      }, duration);
    };
  }

  function announce(message, kind = 'success', duration) {
    window.wdToast?.(message, kind, duration);
  }

  function makeLink(href, text, className = '') {
    const link = document.createElement('a');
    link.href = href;
    link.textContent = text;
    if (className) link.className = className;
    return link;
  }

  function addStandaloneToolbar(items) {
    if (q('.wd-topbar, .wd-standalone-toolbar')) return;
    const toolbar = document.createElement('nav');
    toolbar.className = 'wd-standalone-toolbar';
    toolbar.setAttribute('aria-label', '페이지 이동');
    const brand = makeLink('/', '책 먹는 호반우', 'wd-standalone-brand');
    const actions = document.createElement('div');
    actions.className = 'wd-standalone-actions';
    items.forEach(item => actions.appendChild(makeLink(item.href, item.label)));
    toolbar.append(brand, actions);
    document.body.insertBefore(toolbar, document.body.firstChild);
  }

  function alignRoleNavigation() {
    const more = q('#mobile-more-btn');
    const moreIcon = q('svg', more);
    if (moreIcon) {
      moreIcon.setAttribute('viewBox', '0 0 24 24');
      moreIcon.innerHTML = '<circle cx="5" cy="12" r="1.7" fill="currentColor" stroke="none"></circle><circle cx="12" cy="12" r="1.7" fill="currentColor" stroke="none"></circle><circle cx="19" cy="12" r="1.7" fill="currentColor" stroke="none"></circle>';
    }

    const pathname = window.location.pathname || '/';
    const matchesCurrentSection = path => {
      if (path === '/') return pathname === '/';
      if (path === '/seminars') return pathname === '/seminars' || pathname === '/seminar_vote';
      if (path === '/now') {
        return pathname === '/now' || pathname === '/shared_topics' || pathname.startsWith('/books/') ||
          pathname.startsWith('/review/') || pathname.startsWith('/brick/');
      }
      if (path === '/mypage') return pathname === '/mypage';
      if (path.startsWith('/admin/')) return pathname.startsWith('/admin/') || pathname === '/making_team' || pathname.startsWith('/records');
      return pathname === path;
    };
    qa('.wd-top-nav a, .wd-tabbar a').forEach(link => {
      let path = '';
      try { path = new URL(link.getAttribute('href') || link.href, document.baseURI).pathname; } catch (_) { return; }
      const current = matchesCurrentSection(path);
      link.classList.toggle('wd-link-current', current);
      link.classList.toggle('wd-tb-on', current && link.closest('.wd-tabbar'));
      if (current) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });

    if (userRole === 'admin') {
      qa('.wd-link-staff').forEach(link => { link.href = '/admin/dashboard'; });
    }
    if (userRole !== 'officer') return;

    qa('.wd-link-staff').forEach(link => link.remove());
    const profile = q('#profile-list');
    if (!profile) return;

    qa('a', profile).forEach(link => {
      let path = '';
      try { path = new URL(link.getAttribute('href') || link.href, document.baseURI).pathname; } catch (_) { return; }
      if (path.startsWith('/admin/') || path === '/records' || path.startsWith('/records/') || path === '/making_team' || path === '/help/admin') link.remove();
    });
    qa('.wd-menu-label', profile).forEach(label => {
      if (cleanText(label) === '관리') label.remove();
    });
    qa('.wd-menu-divider', profile).forEach(divider => {
      const previous = divider.previousElementSibling;
      const next = divider.nextElementSibling;
      if (!previous || !next || previous.classList.contains('wd-menu-divider') || next.classList.contains('wd-menu-divider')) divider.remove();
    });

    if (!qa('a', profile).some(link => cleanText(link) === '이용 안내')) {
      const logout = qa('a', profile).find(link => cleanText(link) === '로그아웃');
      const help = makeLink('/help/member', '이용 안내', 'wd-menu-item');
      const icon = document.createElement('span');
      icon.className = 'wd-menu-ico';
      icon.textContent = 'i';
      help.prepend(icon);
      profile.insertBefore(help, logout || null);
    }
  }

  function enhanceAdminSidebar() {
    const sidebar = q('.wd-admin-sidebar');
    const nav = q('.wd-admin-sidebar-nav', sidebar);
    if (!sidebar || !nav || q('.wd-admin-menu-trigger', sidebar)) return;

    const groups = [
      { before: '개요', label: '오늘' },
      { before: '세미나 운영', label: '주간 운영' },
      { before: '회원 관리', label: '사람' },
      { before: '활동·행사', label: '활동' },
      { before: '기록·통계', label: '기록' },
      { before: '버그 제보', label: '시스템' }
    ];
    groups.forEach(group => {
      const target = qa('a', nav).find(link => cleanText(link) === group.before);
      if (!target) return;
      const label = document.createElement('span');
      label.className = 'wd-admin-nav-label';
      label.textContent = group.label;
      nav.insertBefore(label, target);
    });

    const active = q('a.active', nav);
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'wd-admin-menu-trigger';
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', 'wd-admin-menu-list');
    trigger.innerHTML = '<span><small>운영 메뉴</small><strong></strong></span><span class="wd-admin-menu-chevron" aria-hidden="true">⌄</span>';
    q('strong', trigger).textContent = cleanText(active) || '메뉴 선택';
    nav.id = nav.id || 'wd-admin-menu-list';
    sidebar.insertBefore(trigger, nav);

    const setOpen = open => {
      sidebar.classList.toggle('wd-admin-menu-open', open);
      trigger.setAttribute('aria-expanded', String(open));
    };
    trigger.addEventListener('click', () => setOpen(!sidebar.classList.contains('wd-admin-menu-open')));
    nav.addEventListener('click', event => {
      if (event.target.closest('a')) setOpen(false);
    });
    document.addEventListener('click', event => {
      if (window.matchMedia('(max-width: 1100px)').matches && !sidebar.contains(event.target)) setOpen(false);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && sidebar.classList.contains('wd-admin-menu-open')) {
        setOpen(false);
        trigger.focus();
      }
    });
    window.addEventListener('resize', () => {
      if (!window.matchMedia('(max-width: 1100px)').matches) setOpen(false);
    }, { passive: true });
  }

  function enhanceAdminSeminars() {
    const heading = qa('h1').find(element => cleanText(element) === '세미나 운영');
    const main = heading?.closest('main');
    const weeks = main ? qa('section[data-week]', main) : [];
    if (!main || !weeks.length || q('.wd-admin-seminar-summary', main)) return;

    const metadata = weeks.map(week => {
      const chips = qa('.chip', week).map(cleanText);
      return {
        week,
        past: chips.some(text => text.includes('지난 세미나')),
        needsReview: chips.some(text => text.includes('도서 확인 필요')),
        topicOpen: qa('.toggle-topic', week).some(button => cleanText(button).includes('접수 마감'))
      };
    });
    const upcomingCount = metadata.filter(item => !item.past).length;
    const reviewCount = metadata.filter(item => item.needsReview).length;
    const openTopicCount = metadata.filter(item => item.topicOpen).length;

    const summary = document.createElement('section');
    summary.className = 'wd-admin-seminar-summary';
    summary.setAttribute('aria-label', '세미나 운영 현황');
    summary.innerHTML = '<div class="wd-admin-seminar-stats"></div><div class="wd-admin-seminar-filter-row"><div class="wd-admin-seminar-filters" role="group" aria-label="주차 필터"></div><span class="wd-admin-seminar-visible-count" aria-live="polite"></span></div>';
    const stats = q('.wd-admin-seminar-stats', summary);
    [
      ['전체 주차', weeks.length],
      ['예정', upcomingCount],
      ['도서 확인 필요', reviewCount],
      ['발제문 접수 중', openTopicCount]
    ].forEach(([label, value]) => {
      const item = document.createElement('div');
      const strong = document.createElement('strong');
      strong.textContent = String(value);
      if (label === '도서 확인 필요') strong.dataset.scheduleReviewCount = '';
      const span = document.createElement('span');
      span.textContent = label;
      item.append(strong, span);
      stats.appendChild(item);
    });

    const filters = [
      ['upcoming', '예정만'],
      ['review', '확인 필요'],
      ['past', '지난 세미나'],
      ['all', '전체']
    ];
    const filterWrap = q('.wd-admin-seminar-filters', summary);
    const visibleCount = q('.wd-admin-seminar-visible-count', summary);
    let currentFilter = upcomingCount ? 'upcoming' : 'all';

    function matches(item, filter) {
      if (filter === 'upcoming') return !item.past;
      if (filter === 'past') return item.past;
      if (filter === 'review') return item.needsReview;
      return true;
    }

    function applyFilter(filter, options = {}) {
      currentFilter = filter;
      let visible = 0;
      metadata.forEach(item => {
        const show = matches(item, filter);
        item.week.hidden = !show;
        item.week.dataset.wdSeminarState = item.past ? 'past' : item.needsReview ? 'review' : 'upcoming';
        if (show) visible += 1;
      });
      qa('button', filterWrap).forEach(button => {
        const active = button.dataset.filter === filter;
        button.setAttribute('aria-pressed', String(active));
      });
      if (visibleCount) visibleCount.textContent = `${visible}개 주차 표시`;
      if (options.scroll) summary.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    filters.forEach(([value, label]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.filter = value;
      button.textContent = label;
      button.addEventListener('click', () => applyFilter(value));
      filterWrap.appendChild(button);
    });

    document.addEventListener('seminar:schedule-saved', event => {
      const item = metadata.find(row => row.week.dataset.week === event.detail.weekId);
      if (!item) return;
      item.needsReview = false;
      q('[data-schedule-review-count]', stats).textContent = String(metadata.filter(row => row.needsReview).length);
      applyFilter(currentFilter);
    });

    const list = weeks[0].parentElement;
    const tools = list?.previousElementSibling;
    if (tools && tools.tagName === 'DETAILS') tools.insertAdjacentElement('afterend', summary);
    else list?.parentElement?.insertBefore(summary, list || null);
    applyFilter(currentFilter);
  }

  function enhanceGroupingInput() {
    const form = q('#group-form');
    if (!form || q('.wd-group-stepper')) return;

    const stepper = document.createElement('nav');
    stepper.className = 'wd-group-stepper';
    stepper.setAttribute('aria-label', '조 편성 진행 단계');
    stepper.innerHTML = '<ol><li class="is-done"><span class="wd-step-dot">1</span><span>회차 확인</span></li><li class="is-current" aria-current="step"><span class="wd-step-dot">2</span><span>참석자·발제자</span></li><li><span class="wd-step-dot">3</span><span>편성 설정</span></li><li><span class="wd-step-dot">4</span><span>추천안 확인</span></li></ol>';
    form.parentNode.insertBefore(stepper, form);

    const quickVoted = q('#quick-voted');
    if (quickVoted) {
      quickVoted.textContent = '투표 반영 명단 적용';
      quickVoted.title = '현재 참석 선택을 이 회차에 반영된 카카오톡 투표 명단으로 되돌립니다.';
      quickVoted.setAttribute('aria-label', '이 회차의 투표 반영 명단을 참석자 선택에 적용');
    }

    const actionWrap = quickVoted?.parentElement;
    if (actionWrap && !q('.wd-bulk-selection', actionWrap)) {
      const bulkButtons = qa('button', actionWrap).filter(button => button !== quickVoted);
      if (bulkButtons.length) {
        const details = document.createElement('details');
        details.className = 'wd-bulk-selection';
        const summary = document.createElement('summary');
        summary.textContent = '일괄 선택';
        const panel = document.createElement('div');
        panel.className = 'wd-bulk-selection-panel';
        bulkButtons.forEach(button => panel.appendChild(button));
        details.append(summary, panel);
        actionWrap.appendChild(details);
        details.addEventListener('toggle', () => {
          if (!details.open) return;
          window.setTimeout(() => {
            document.addEventListener('click', event => {
              if (!details.contains(event.target)) details.open = false;
            }, { once: true });
          }, 0);
        });
      }
    }

    const settings = q('.settings-panel');
    const settingsTitle = settings && q('h2', settings);
    if (settings && settingsTitle) {
      const preflight = document.createElement('section');
      preflight.className = 'wd-preflight';
      preflight.setAttribute('aria-label', '생성 전 요약');
      preflight.innerHTML = '<div class="wd-preflight-title">생성 전 확인</div><div class="wd-preflight-grid"><div class="wd-preflight-item"><strong id="wd-pf-present">0</strong><span>참석자</span></div><div class="wd-preflight-item"><strong id="wd-pf-facilitator">0</strong><span>발제자</span></div><div class="wd-preflight-item"><strong id="wd-pf-groups">-</strong><span>예상 조</span></div></div><p class="wd-preflight-note" id="wd-pf-note" aria-live="polite">참석자를 확인하면 예상 조 구성이 표시됩니다.</p>';
      settings.insertBefore(preflight, settingsTitle.nextSibling);
    }

    const presentInputs = () => qa('input[name="present"]');
    const facilitatorInputs = () => qa('input[name="facilitators"]');
    const groupCountInput = q('input[name="group_count"]');
    const groupNamesSource = q('input[name="group_names"]');
    let groupNameCount = -1;

    function calculateGroupCount(presentCount) {
      if (!presentCount) return 0;
      const requested = Number(groupCountInput?.value) || Math.ceil(presentCount / 4);
      const sensibleMax = Math.max(1, Math.floor(presentCount / 4));
      return Math.max(1, Math.min(requested, sensibleMax));
    }

    function renderGroupNameEditor(groupCount) {
      if (!groupNamesSource) return;
      const label = groupNamesSource.closest('label');
      if (!label) return;
      let editor = q('.wd-group-name-editor', label.parentElement);
      if (!editor) {
        editor = document.createElement('section');
        editor.className = 'wd-group-name-editor';
        const head = document.createElement('div');
        head.className = 'wd-group-name-editor-head';
        const heading = document.createElement('strong');
        heading.textContent = '그룹 이름';
        const help = document.createElement('small');
        help.className = 'wd-group-name-help';
        help.textContent = '비워두면 그룹 1, 그룹 2처럼 자동 표시됩니다.';
        head.append(heading, help);
        const fields = document.createElement('div');
        fields.className = 'wd-group-name-fields';
        editor.append(head, fields);
        label.classList.add('wd-group-name-source-label');
        groupNamesSource.setAttribute('tabindex', '-1');
        groupNamesSource.setAttribute('aria-hidden', 'true');
        label.insertAdjacentElement('afterend', editor);
      }
      const fields = q('.wd-group-name-fields', editor);
      if (!fields || groupNameCount === groupCount) return;
      const existingFields = qa('input', fields).map(input => input.value);
      const sourceValues = groupNamesSource.value.split(',').map(value => value.trim());
      const values = existingFields.length ? existingFields : sourceValues;
      fields.replaceChildren();
      groupNameCount = groupCount;
      if (!groupCount) {
        const empty = document.createElement('span');
        empty.className = 'wd-group-name-empty';
        empty.textContent = '참석자를 선택하면 조 이름 입력칸이 만들어집니다.';
        fields.appendChild(empty);
        return;
      }
      for (let index = 0; index < groupCount; index += 1) {
        const field = document.createElement('div');
        field.className = 'wd-group-name-field';
        const title = document.createElement('span');
        title.textContent = `${index + 1}조 이름`;
        const input = document.createElement('input');
        input.type = 'text';
        input.value = values[index] || '';
        input.placeholder = `그룹 ${index + 1}`;
        input.autocomplete = 'off';
        input.setAttribute('aria-label', `${index + 1}조 이름`);
        input.addEventListener('input', () => {
          groupNamesSource.value = qa('input', fields).map(item => item.value.trim()).join(', ');
        });
        field.append(title, input);
        fields.appendChild(field);
      }
      groupNamesSource.value = qa('input', fields).map(item => item.value.trim()).join(', ');
    }

    function reconcileFacilitators(mode = 'remove-orphans') {
      let changed = 0;
      facilitatorInputs().forEach(input => {
        if (!input.checked) return;
        const present = q(`input[name="present"][value="${selectorEscape(input.value)}"]`);
        if (!present) return;
        if (mode === 'include-present' && !present.checked) {
          present.checked = true;
          changed += 1;
        } else if (mode === 'remove-orphans' && !present.checked) {
          input.checked = false;
          changed += 1;
        }
      });
      return changed;
    }

    function refreshPreflight() {
      const presentCount = presentInputs().filter(input => input.checked).length;
      const facilitatorCount = facilitatorInputs().filter(input => input.checked).length;
      const groupCount = calculateGroupCount(presentCount);
      const minSize = groupCount ? Math.floor(presentCount / groupCount) : 0;
      const maxSize = groupCount ? Math.ceil(presentCount / groupCount) : 0;
      const present = q('#wd-pf-present');
      const facilitator = q('#wd-pf-facilitator');
      const groups = q('#wd-pf-groups');
      const note = q('#wd-pf-note');
      if (present) present.textContent = String(presentCount);
      if (facilitator) facilitator.textContent = String(facilitatorCount);
      if (groups) groups.textContent = groupCount ? String(groupCount) : '-';
      if (note) {
        note.textContent = presentCount
          ? `${groupCount}개 조 · 조당 ${minSize === maxSize ? `${maxSize}명` : `${minSize}~${maxSize}명`}으로 추천안을 만듭니다.`
          : '참석자를 한 명 이상 선택해주세요.';
      }
      renderGroupNameEditor(groupCount);
    }

    form.addEventListener('change', event => {
      const input = event.target;
      if (!(input instanceof HTMLInputElement)) return;
      if (input.name === 'facilitators' && input.checked) {
        const present = q(`input[name="present"][value="${selectorEscape(input.value)}"]`);
        if (present && !present.checked) {
          present.checked = true;
          present.dispatchEvent(new Event('change', { bubbles: true }));
          announce(`${input.value} 님을 발제자로 지정해 참석자에도 포함했습니다.`);
        }
      }
      refreshPreflight();
    });
    groupCountInput?.addEventListener('input', refreshPreflight);

    if (quickVoted) {
      quickVoted.addEventListener('click', () => {
        const presentSnapshot = presentInputs().map(input => input.checked);
        const facilitatorSnapshot = facilitatorInputs().map(input => input.checked);
        window.setTimeout(() => {
          const removedFacilitators = reconcileFacilitators('remove-orphans');
          const selected = presentInputs().filter(input => input.checked).length;
          const suffix = removedFacilitators ? ` · 참석하지 않는 발제자 ${removedFacilitators}명 해제` : '';
          window.wdToastUndo(`신청자 ${selected}명을 참석 명단에 적용했습니다${suffix}.`, () => {
            presentInputs().forEach((input, index) => { input.checked = presentSnapshot[index]; });
            facilitatorInputs().forEach((input, index) => { input.checked = facilitatorSnapshot[index]; });
            presentInputs()[0]?.dispatchEvent(new Event('change', { bubbles: true }));
            refreshPreflight();
            announce('이전 참석·발제 선택으로 되돌렸습니다.');
          });
          refreshPreflight();
        }, 0);
      }, true);
    }

    q('#select-all-facilitators')?.addEventListener('click', () => {
      window.setTimeout(() => {
        const included = reconcileFacilitators('include-present');
        presentInputs()[0]?.dispatchEvent(new Event('change', { bubbles: true }));
        refreshPreflight();
        if (included) announce(`발제자 ${included}명을 참석자에도 포함했습니다.`);
      }, 0);
    });

    q('#bulk-facilitators-apply')?.addEventListener('click', () => {
      window.setTimeout(() => {
        const included = reconcileFacilitators('include-present');
        presentInputs()[0]?.dispatchEvent(new Event('change', { bubbles: true }));
        refreshPreflight();
        if (included) announce(`붙여넣은 발제자 ${included}명을 참석자에도 포함했습니다.`);
      }, 0);
    }, true);

    const generationHeadline = q('#loading-overlay > p.text-xl');
    if (generationHeadline) generationHeadline.textContent = '조 편성 추천안을 만들고 있습니다';
    const generationButton = q('#generate-btn');
    if (generationButton) generationButton.textContent = '조 편성 추천안 만들기';
    refreshPreflight();
  }

  function enhanceGroupingResults() {
    const cards = qa('.result-card-combined');
    const grid = q('.solutions-grid');
    if (!cards.length || !grid || q('.wd-solution-switcher')) return;
    document.body.classList.add('wd-result-page');
    addStandaloneToolbar([
      { href: '/making_team', label: '조건 다시 확인' },
      { href: '/admin/seminars', label: '세미나 운영' }
    ]);

    const mainHeading = q('h1');
    if (mainHeading && /Grouping Result/i.test(cleanText(mainHeading))) mainHeading.textContent = '조 편성 추천안';
    const recommendationHeading = qa('h2').find(element => cleanText(element).includes('최적화된 조 편성'));
    if (recommendationHeading) recommendationHeading.textContent = '추천안을 비교하고 한 가지를 확정하세요';

    const scoreFor = card => {
      const node = qa('span', card).find(element => /^총점\s*:/.test(cleanText(element)));
      const label = cleanText(node).replace(/^총점\s*:\s*/, '') || '-';
      const value = Number.parseFloat(label.replace(/,/g, ''));
      return { label, value: Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY };
    };
    const scores = cards.map(scoreFor);
    const bestScore = Math.max(...scores.map(score => score.value));
    const bestIndex = scores.findIndex(score => score.value === bestScore);

    const switcher = document.createElement('section');
    switcher.className = 'wd-solution-switcher';
    const switcherHead = document.createElement('div');
    switcherHead.className = 'wd-solution-switcher-head';
    const switcherTitle = document.createElement('strong');
    switcherTitle.textContent = '추천안 비교';
    const switcherHelp = document.createElement('span');
    switcherHelp.textContent = '점수뿐 아니라 인원 구성과 반복 만남도 함께 확인하세요.';
    switcherHead.append(switcherTitle, switcherHelp);
    const tabs = document.createElement('div');
    tabs.className = 'wd-solution-tabs';
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', '조 편성 추천안');
    switcher.append(switcherHead, tabs);

    function activate(index, options = {}) {
      cards.forEach((card, cardIndex) => {
        const selected = cardIndex === index;
        card.hidden = !selected;
        card.style.display = selected ? '' : 'none';
        card.setAttribute('aria-hidden', String(!selected));
      });
      qa('.wd-solution-tab', switcher).forEach((tab, tabIndex) => {
        const selected = tabIndex === index;
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
        if (options.focus && selected) tab.focus();
      });
      if (options.scroll) cards[index]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    cards.forEach((card, index) => {
      const panelId = `wd-solution-panel-${index + 1}`;
      const tabId = `wd-solution-tab-${index + 1}`;
      card.id = panelId;
      card.dataset.solutionIndex = String(index);
      card.setAttribute('role', 'tabpanel');
      card.setAttribute('aria-labelledby', tabId);

      const cardTitle = q('h3', card);
      if (cardTitle && index === bestIndex && Number.isFinite(bestScore)) {
        const badge = document.createElement('span');
        badge.className = 'wd-best-score-badge';
        badge.textContent = '최고 점수';
        cardTitle.appendChild(badge);
      }

      const tab = document.createElement('button');
      tab.type = 'button';
      tab.id = tabId;
      tab.className = 'wd-solution-tab';
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', panelId);
      const title = document.createElement('strong');
      title.textContent = `추천안 ${index + 1}${index === bestIndex && Number.isFinite(bestScore) ? ' · 최고 점수' : ''}`;
      const score = document.createElement('small');
      score.textContent = `총점 ${scores[index].label}`;
      tab.append(title, score);
      tab.addEventListener('click', () => activate(index, { scroll: true }));
      tab.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        let next = index;
        if (event.key === 'ArrowLeft') next = (index - 1 + cards.length) % cards.length;
        if (event.key === 'ArrowRight') next = (index + 1) % cards.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = cards.length - 1;
        activate(next, { focus: true, scroll: false });
      });
      tabs.appendChild(tab);

      const save = q('.save-groups-btn', card);
      const capture = q('.capture-groups-btn', card);
      const edit = q('.edit-inline-btn', card);
      if (save) save.textContent = '이 추천안으로 확정';
      if (capture) capture.textContent = '공지 이미지 만들기';
      if (edit) edit.textContent = '인원 이동·수정';
    });

    grid.parentNode.insertBefore(switcher, grid);
    q('#load-more-combined')?.setAttribute('hidden', '');
    activate(bestIndex >= 0 ? bestIndex : 0, { scroll: false });
  }

  function enhanceMemberManagement() {
    const list = q('#member-list');
    if (!list) return;
    const table = list.closest('table');
    table?.classList.add('member-admin-table');

    const search = q('#member-search');
    const searchPanel = search?.closest('.panel');
    if (searchPanel && !q('.wd-member-result-count')) {
      const count = document.createElement('p');
      count.className = 'wd-member-result-count';
      count.setAttribute('aria-live', 'polite');
      searchPanel.insertAdjacentElement('afterend', count);
      const update = () => {
        const rows = qa('.member-row', list);
        const visible = rows.filter(row => !row.hidden).length;
        count.textContent = `현재 ${visible}명 표시 · 전체 ${rows.length}명`;
      };
      ['input', 'change', 'click'].forEach(type => document.addEventListener(type, event => {
        if (event.target.closest('#member-search, .status-filter, #incomplete-filter, #show-all')) requestAnimationFrame(update);
      }));
      update();
    }

    qa('.status-choice').forEach(button => {
      button.addEventListener('click', () => {
        const row = button.closest('tr');
        const oldStatus = row?.dataset.status;
        const nextStatus = button.dataset.status;
        if (!row || !oldStatus || oldStatus === nextStatus) return;
        const memberId = button.dataset.memberId;
        const memberName = cleanText(q('td:first-child .font-extrabold', row));
        let tries = 0;
        const waitForChange = () => {
          tries += 1;
          if (row.dataset.status === nextStatus) {
            q('.status-toast')?.remove();
            window.wdToastUndo(`${memberName} 님을 ${cleanText(button)} 상태로 변경했습니다.`, async () => {
              if (row.dataset.status !== nextStatus) throw new Error('이미 다른 상태로 변경되어 되돌리기를 중단했습니다.');
              const choices = qa('.status-choice', row);
              choices.forEach(choice => { choice.disabled = true; });
              try {
                const response = await fetch(`/api/admin/members/${memberId}/set_status`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ member_status: oldStatus })
                });
                const data = await response.json();
                if (!response.ok || data.status !== 'success') throw new Error(data.message || '되돌리지 못했습니다.');
                row.dataset.status = oldStatus;
                choices.forEach(choice => choice.setAttribute('aria-pressed', String(choice.dataset.status === oldStatus)));
                if (typeof window.updateStatusCounts === 'function') window.updateStatusCounts();
                if (typeof window.filterRows === 'function') window.filterRows();
                announce(`${memberName} 님의 상태를 되돌렸습니다.`);
              } finally {
                choices.forEach(choice => { choice.disabled = false; });
              }
            });
            return;
          }
          if (tries < 30) window.setTimeout(waitForChange, 80);
        };
        window.setTimeout(waitForChange, 80);
      }, true);
    });

    const source = q('#source-member');
    const target = q('#target-member');
    const mergeRun = q('#merge-run');
    const mergePanel = q('#merge-panel');
    if (source && target && mergeRun && mergePanel && !q('.wd-merge-preview', mergePanel)) {
      const preview = document.createElement('div');
      preview.className = 'wd-merge-preview';
      preview.setAttribute('aria-live', 'polite');
      mergeRun.insertAdjacentElement('beforebegin', preview);
      const rowFor = id => qa('.edit-member').find(button => button.dataset.id === id)?.closest('tr');
      const summarize = (label, select) => {
        const row = rowFor(select.value);
        if (!row) return `${label}: 선택하지 않음`;
        const cells = qa('td', row);
        return `${label}: ${cleanText(cells[0])} · 세미나 ${cleanText(cells[3])} · 발제 ${cleanText(cells[4])} · 벽돌책 ${cleanText(cells[5])} · 소모임 ${cleanText(cells[6])}`;
      };
      const update = () => {
        const valid = Boolean(source.value && target.value && source.value !== target.value);
        mergeRun.disabled = !valid;
        preview.replaceChildren();
        const first = document.createElement('p');
        first.textContent = summarize('삭제할 계정', source);
        const second = document.createElement('p');
        second.textContent = summarize('남길 계정', target);
        const warning = document.createElement('strong');
        warning.textContent = valid ? '삭제할 계정의 활동과 로그인 정보가 남길 계정으로 이전됩니다.' : '서로 다른 두 회원을 선택해주세요.';
        preview.append(first, second, warning);
      };
      source.addEventListener('change', update);
      target.addEventListener('change', update);
      update();
    }
  }

  function enhanceRecruitmentTabs() {
    const applicantList = q('#applicantList');
    if (!applicantList || q('.wd-tabs-nav')) return;
    const main = applicantList.closest('main');
    if (!main) return;

    const sections = qa(':scope > section, :scope > div > section', main);
    const byHeading = needle => sections.find(section => cleanText(q('h2', section)).includes(needle));
    const share = byHeading('단톡방 공유 링크');
    const settings = byHeading('공개 상태와 안내문');
    const excel = byHeading('Excel 명단 일괄 등록');
    const addOne = byHeading('지원자 한 명 추가');
    const results = byHeading('지원자 명단');
    const importGrid = excel?.parentElement === addOne?.parentElement ? excel.parentElement : null;
    if (!share || !settings || !importGrid || !results) return;

    const reviewPanel = document.createElement('section');
    reviewPanel.className = 'panel wd-publish-review';
    reviewPanel.innerHTML = '<div class="wd-publish-review-head"><div><h2>발표 전 점검</h2><p>공개 전에 누락된 결과와 링크 상태를 확인하세요.</p></div></div><ul class="wd-publish-checklist" aria-live="polite"></ul><div class="wd-publish-actions"></div>';
    const checklist = q('.wd-publish-checklist', reviewPanel);
    const publishActions = q('.wd-publish-actions', reviewPanel);
    const previewLink = qa('a', share).find(link => cleanText(link).includes('미리 보기'));
    if (previewLink) publishActions.appendChild(makeLink(previewLink.href, '지원자 화면 미리 보기', 'btn paper'));

    function updateReview() {
      const rows = qa('.applicant-row', results);
      const pending = rows.filter(row => (q('select[name="result_status"]', row)?.value || row.dataset.status) === 'pending').length;
      const active = q('input[name="is_active"]', settings)?.checked;
      const published = q('input[name="is_published"]', settings)?.checked;
      const requiredMessages = ['pending_message', 'accepted_message', 'waitlisted_message', 'rejected_message'];
      const messageReady = requiredMessages.every(name => (q(`[name="${name}"]`, settings)?.value || '').trim());
      const checks = [
        { ok: rows.length > 0, text: `지원자 ${rows.length}명 등록` },
        { ok: pending === 0, text: pending ? `결과 미입력 ${pending}명` : '모든 지원자 결과 입력 완료' },
        { ok: messageReady, text: messageReady ? '결과별 공통 안내문 입력 완료' : '비어 있는 결과 안내문 확인 필요' },
        { ok: Boolean(active), text: active ? '공유 링크 열림' : '공유 링크 닫힘' },
        { ok: Boolean(published), text: published ? '결과 발표 상태' : '아직 발표 전' }
      ];
      checklist.replaceChildren();
      checks.forEach(check => {
        const item = document.createElement('li');
        item.className = check.ok ? 'is-ready' : 'needs-review';
        item.textContent = `${check.ok ? '완료' : '확인'} · ${check.text}`;
        checklist.appendChild(item);
      });
    }

    const nav = document.createElement('nav');
    nav.className = 'wd-tabs-nav';
    nav.setAttribute('role', 'tablist');
    nav.setAttribute('aria-label', '면접 지원자 관리 단계');
    const panelSpecs = [
      { id: 'settings', label: '1. 공개 설정', nodes: [share, settings] },
      { id: 'roster', label: '2. 명단 등록', nodes: [importGrid] },
      { id: 'results', label: '3. 결과 입력', nodes: [results] },
      { id: 'review', label: '4. 발표 점검', nodes: [reviewPanel] }
    ];
    const marker = document.createComment('recruitment-tabs');
    main.insertBefore(marker, share);
    const panels = panelSpecs.map((spec, index) => {
      const panel = document.createElement('div');
      panel.id = `wd-recruit-${spec.id}`;
      panel.className = 'wd-tab-panel';
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', `wd-recruit-tab-${spec.id}`);
      panel.hidden = index !== 0;
      spec.nodes.forEach(node => panel.appendChild(node));
      return panel;
    });

    function activate(index, options = {}) {
      const buttons = qa('button[role="tab"]', nav);
      buttons.forEach((button, buttonIndex) => {
        const selected = buttonIndex === index;
        button.setAttribute('aria-selected', String(selected));
        button.tabIndex = selected ? 0 : -1;
        if (options.focus && selected) button.focus();
      });
      panels.forEach((panel, panelIndex) => { panel.hidden = panelIndex !== index; });
      if (panelSpecs[index].id === 'review') updateReview();
      if (options.updateHash !== false) {
        try { history.replaceState(null, '', `#${panelSpecs[index].id}`); } catch (_) { /* sandboxed previews may block history updates */ }
      }
    }

    panelSpecs.forEach((spec, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.id = `wd-recruit-tab-${spec.id}`;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', `wd-recruit-${spec.id}`);
      button.textContent = spec.label;
      button.addEventListener('click', () => activate(index));
      button.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        let next = index;
        if (event.key === 'ArrowLeft') next = (index - 1 + panelSpecs.length) % panelSpecs.length;
        if (event.key === 'ArrowRight') next = (index + 1) % panelSpecs.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = panelSpecs.length - 1;
        activate(next, { focus: true });
      });
      nav.appendChild(button);
    });

    main.insertBefore(nav, marker);
    panels.forEach(panel => main.insertBefore(panel, marker));
    marker.remove();
    main.addEventListener('input', updateReview);
    main.addEventListener('change', updateReview);
    const initial = panelSpecs.findIndex(spec => `#${spec.id}` === location.hash);
    activate(initial >= 0 ? initial : 0, { updateHash: false });
    updateReview();
  }

  function enhanceSeminarVote() {
    const form = q('#voteForm');
    const submitBar = q('.submit-bar');
    if (!form || !submitBar || q('#wd-vote-summary')) return;
    qa('label[for^="skip_"]', form).forEach(label => { label.textContent = '변경 없음'; });
    const summary = document.createElement('p');
    summary.id = 'wd-vote-summary';
    summary.className = 'wd-vote-summary';
    summary.setAttribute('aria-live', 'polite');
    submitBar.insertBefore(summary, submitBar.firstChild);
    const touchedGroups = new Set();

    function update() {
      const changes = Array.from(touchedGroups).map(name => {
        const input = q(`input[name="${selectorEscape(name)}"]:checked`, form);
        if (!input) return null;
        const card = input.closest('.session-card');
        const date = cleanText(q('.font-bold.text-lg, .font-bold', card)).split(' ')[0];
        const action = input.value === 'yes' ? '신청' : input.value === 'no' ? '취소' : '변경 없음';
        return `${date} ${action}`;
      }).filter(Boolean);
      summary.replaceChildren();
      if (!changes.length) {
        summary.textContent = '아직 선택을 변경하지 않았습니다.';
        return;
      }
      const strong = document.createElement('strong');
      strong.textContent = `변경한 회차 ${changes.length}개`;
      summary.append(strong, document.createTextNode(` · ${changes.join(' / ')} · 저장 버튼을 눌러 반영합니다.`));
    }
    form.addEventListener('change', event => {
      const input = event.target;
      if (input instanceof HTMLInputElement && input.type === 'radio' && input.name.startsWith('vote_')) {
        touchedGroups.add(input.name);
      }
      update();
    });
    update();
  }

  function enhanceMyPage() {
    const actionTitle = qa('h2.section-title').find(title => cleanText(title).includes('지금 할 일'));
    const actionSection = actionTitle?.closest('section');
    if (!actionSection || actionSection.dataset.wdPrioritized === '1') return;
    const container = actionSection.parentElement;
    const firstSection = q(':scope > section', container);
    if (firstSection && firstSection !== actionSection) container.insertBefore(actionSection, firstSection);
    actionSection.dataset.wdPrioritized = '1';
    actionSection.classList.add('wd-my-actions');
  }

  function enhanceProfilePages() {
    const title = q('h1');
    if (!title) return;
    const initialTitle = cleanText(title);

    if (initialTitle === 'Member Profiles') {
      title.textContent = '회원 프로필';
      addStandaloneToolbar([
        { href: '/', label: '홈' },
        { href: '/mypage', label: '내 활동' }
      ]);
      const grid = q('.grid.grid-cols-1');
      if (grid && !q('.wd-profile-search')) {
        const tools = document.createElement('section');
        tools.className = 'wd-profile-tools';
        const search = document.createElement('input');
        search.type = 'search';
        search.className = 'wd-profile-search';
        search.placeholder = '이름이나 한 줄 소개로 검색';
        search.setAttribute('aria-label', '회원 프로필 검색');
        const count = document.createElement('span');
        count.setAttribute('aria-live', 'polite');
        tools.append(search, count);
        grid.parentNode.insertBefore(tools, grid);
        const cards = qa(':scope > a', grid);
        const update = () => {
          const keyword = search.value.trim().toLowerCase();
          let visible = 0;
          cards.forEach(card => {
            card.hidden = Boolean(keyword && !cleanText(card).toLowerCase().includes(keyword));
            if (!card.hidden) visible += 1;
          });
          count.textContent = `${visible}명`;
        };
        search.addEventListener('input', update);
        update();
      }
      const home = qa('a').find(link => cleanText(link) === '메인으로');
      if (home) home.textContent = '홈으로';
      return;
    }

    if (/\'s Profile$/.test(initialTitle)) {
      title.textContent = initialTitle.replace("'s Profile", '님의 프로필');
      addStandaloneToolbar([
        { href: '/profiles', label: '회원 목록' },
        { href: '/mypage', label: '내 활동' }
      ]);
      const edit = q('#edit-btn');
      if (edit) edit.textContent = '프로필 편집';
      const introEditor = q('#intro-editor');
      const contentEditor = q('#content-editor');
      const cancel = q('#cancel-btn');
      const initialIntro = introEditor?.value || '';
      const initialContent = contentEditor?.value || '';
      cancel?.addEventListener('click', () => {
        if (introEditor) introEditor.value = initialIntro;
        if (contentEditor) contentEditor.value = initialContent;
      });
      if (contentEditor && !q('.wd-profile-char-count')) {
        const count = document.createElement('p');
        count.className = 'wd-profile-char-count';
        count.setAttribute('aria-live', 'polite');
        contentEditor.insertAdjacentElement('afterend', count);
        const update = () => { count.textContent = `상세 프로필 ${contentEditor.value.length.toLocaleString()}자`; };
        contentEditor.addEventListener('input', update);
        update();
      }
    }
  }

  function enhanceRecordsCopy() {
    qa('p').forEach(paragraph => {
      const text = cleanText(paragraph);
      if (text.includes('날짜·도서·장르·참여명단')) {
        paragraph.textContent = text.replace('날짜·도서·장르·참여명단', '날짜·도서·참여명단');
      }
    });
  }

  function measureStickyNavigation() {
    const header = q('.wd-topbar');
    const sidebar = q('.wd-admin-sidebar');
    const update = () => {
      const headerHeight = header ? Math.ceil(header.getBoundingClientRect().height) : 0;
      const sidebarHeight = sidebar && getComputedStyle(sidebar).position === 'sticky'
        ? Math.ceil(sidebar.getBoundingClientRect().height) : 0;
      document.documentElement.style.setProperty('--app-header-height', `${headerHeight}px`);
      document.documentElement.style.setProperty('--app-sticky-clearance', `${headerHeight + sidebarHeight + 16}px`);
    };
    if (window.ResizeObserver) {
      const observer = new ResizeObserver(update);
      if (header) observer.observe(header);
      if (sidebar) observer.observe(sidebar);
    }
    window.addEventListener('resize', update, { passive: true });
    update();
  }

  function bootstrapEnhancements() {
    document.documentElement.classList.add('wd-ui-enhanced');
    const enhancements = [
      ['role navigation', alignRoleNavigation],
      ['admin navigation', enhanceAdminSidebar],
      ['admin seminars', enhanceAdminSeminars],
      ['grouping input', enhanceGroupingInput],
      ['grouping results', enhanceGroupingResults],
      ['member management', enhanceMemberManagement],
      ['recruitment workflow', enhanceRecruitmentTabs],
      ['seminar vote', enhanceSeminarVote],
      ['my page', enhanceMyPage],
      ['profile pages', enhanceProfilePages],
      ['records copy', enhanceRecordsCopy],
      ['sticky navigation', measureStickyNavigation]
    ];
    enhancements.forEach(([name, enhancement]) => {
      try {
        enhancement();
      } catch (error) {
        console.warn(`[book-member-maker] ${name} UI enhancement failed`, error);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapEnhancements, { once: true });
  } else {
    bootstrapEnhancements();
  }
})();
