(() => {
  const dataEl = document.getElementById('lms-quick-search-items');
  if (!dataEl) return;

  let allItems = [];
  try {
    const parsed = JSON.parse(dataEl.textContent || '[]');
    if (Array.isArray(parsed)) allItems = parsed;
  } catch {
    allItems = [];
  }

  let dialog = null;
  let input = null;
  let list = null;
  let emptyEl = null;
  let countEl = null;
  let filtered = allItems.slice();
  let activeIndex = 0;
  let lastTrigger = null;

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.className = 'lms-qs-dialog';
    dialog.id = 'lms-quick-search-dialog';
    dialog.setAttribute('aria-labelledby', 'lms-qs-label');
    dialog.setAttribute('aria-modal', 'true');

    const head = document.createElement('div');
    head.className = 'lms-qs-head';

    const label = document.createElement('span');
    label.id = 'lms-qs-label';
    label.className = 'lms-sr';
    label.textContent = '기능 빠른 검색';

    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('width', '20');
    icon.setAttribute('height', '20');
    icon.setAttribute('viewBox', '0 0 28 28');
    icon.setAttribute('fill', 'none');
    icon.setAttribute('stroke', 'currentColor');
    icon.setAttribute('stroke-width', '2');
    icon.setAttribute('aria-hidden', 'true');
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('cx', '12');
    c.setAttribute('cy', '12');
    c.setAttribute('r', '7');
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', 'm17.5 17.5 6 6');
    icon.append(c, p);

    input = document.createElement('input');
    input.type = 'search';
    input.className = 'lms-qs-input';
    input.placeholder = '기능이나 메뉴 검색 (예: 세미나, 출석, 조 편성, 인수인계)';
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('aria-label', '기능 검색어 입력');
    input.setAttribute('aria-controls', 'lms-qs-listbox');

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'lms-qs-close';
    closeBtn.textContent = 'ESC';
    closeBtn.setAttribute('aria-label', '빠른 검색 닫기');
    closeBtn.addEventListener('click', closePalette);

    head.append(label, icon, input, closeBtn);

    list = document.createElement('ul');
    list.className = 'lms-qs-list';
    list.id = 'lms-qs-listbox';
    list.setAttribute('role', 'listbox');

    emptyEl = document.createElement('p');
    emptyEl.className = 'lms-qs-empty';
    emptyEl.textContent = '검색 결과가 없습니다. 다른 키워드를 입력해보세요.';
    emptyEl.hidden = true;

    const foot = document.createElement('div');
    foot.className = 'lms-qs-foot';
    const keysHint = document.createElement('span');
    keysHint.textContent = '↑↓ 이동 · Enter 열기 · Esc 닫기';
    countEl = document.createElement('span');
    foot.append(keysHint, countEl);

    dialog.append(head, list, emptyEl, foot);
    document.body.appendChild(dialog);

    dialog.addEventListener('click', (e) => {
      if (e.target === dialog) closePalette();
    });
    dialog.addEventListener('close', () => {
      if (lastTrigger && typeof lastTrigger.focus === 'function') {
        lastTrigger.focus();
      }
      lastTrigger = null;
    });

    input.addEventListener('input', () => {
      renderResults(input.value);
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (filtered.length) moveSelection((activeIndex + 1) % filtered.length);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (filtered.length) moveSelection((activeIndex - 1 + filtered.length) % filtered.length);
      } else if (e.key === 'Enter') {
        if (filtered.length && filtered[activeIndex] && filtered[activeIndex].url) {
          e.preventDefault();
          const targetUrl = filtered[activeIndex].url;
          closePalette();
          window.location.assign(targetUrl);
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closePalette();
      }
    });

    return dialog;
  }

  function scoreItem(item, tokens) {
    const title = String(item.title || '').toLowerCase();
    const group = String(item.group || '').toLowerCase();
    const keywords = String(item.keywords || '').toLowerCase();
    const description = String(item.description || '').toLowerCase();
    const haystack = `${title} ${group} ${keywords} ${description}`;

    for (const token of tokens) {
      if (!haystack.includes(token)) return -1;
    }
    let score = 1;
    for (const token of tokens) {
      if (title.startsWith(token)) score += 20;
      else if (title.includes(token)) score += 10;
      else if (keywords.includes(token)) score += 5;
    }
    return score;
  }

  function renderResults(query) {
    const tokens = String(query || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!tokens.length) {
      filtered = allItems.slice();
    } else {
      filtered = allItems
        .map((item, idx) => ({ item, idx, score: scoreItem(item, tokens) }))
        .filter((entry) => entry.score >= 0)
        .sort((a, b) => b.score - a.score || a.idx - b.idx)
        .map((entry) => entry.item);
    }

    activeIndex = 0;
    list.replaceChildren();
    emptyEl.hidden = filtered.length > 0;
    list.hidden = filtered.length === 0;
    if (countEl) countEl.textContent = `${filtered.length}개 기능`;

    filtered.forEach((item, index) => {
      const li = document.createElement('li');
      li.setAttribute('role', 'none');

      const link = document.createElement('a');
      link.className = 'lms-qs-item' + (index === activeIndex ? ' is-active' : '');
      link.href = item.url || '#';
      link.setAttribute('role', 'option');
      link.setAttribute('aria-selected', index === activeIndex ? 'true' : 'false');

      const main = document.createElement('div');
      main.className = 'lms-qs-item-main';

      const top = document.createElement('div');
      top.className = 'lms-qs-item-top';

      const title = document.createElement('span');
      title.className = 'lms-qs-item-title';
      title.textContent = item.title || '';

      const badge = document.createElement('span');
      const isStaff = item.group === '운영진';
      badge.className = 'lms-qs-badge' + (isStaff ? ' lms-qs-badge-staff' : '');
      badge.textContent = item.group || '';

      top.append(title);
      if (item.group) top.append(badge);
      main.append(top);

      if (item.description) {
        const desc = document.createElement('div');
        desc.className = 'lms-qs-item-desc';
        desc.textContent = item.description;
        main.append(desc);
      }

      const enter = document.createElement('span');
      enter.className = 'lms-qs-enter';
      enter.textContent = '열기 ↵';

      link.append(main, enter);
      link.addEventListener('mousemove', () => {
        if (activeIndex !== index) moveSelection(index);
      });
      link.addEventListener('click', () => {
        closePalette();
      });

      li.append(link);
      list.append(li);
    });
  }

  function moveSelection(nextIndex) {
    activeIndex = nextIndex;
    const links = list.querySelectorAll('.lms-qs-item');
    links.forEach((link, idx) => {
      const selected = idx === activeIndex;
      link.classList.toggle('is-active', selected);
      link.setAttribute('aria-selected', selected ? 'true' : 'false');
      if (selected && typeof link.scrollIntoView === 'function') {
        link.scrollIntoView({ block: 'nearest' });
      }
    });
  }

  function openPalette(trigger) {
    const dlg = ensureDialog();
    lastTrigger = trigger || document.activeElement;
    input.value = '';
    renderResults('');
    if (!dlg.open) {
      if (typeof dlg.showModal === 'function') {
        dlg.showModal();
      } else {
        dlg.setAttribute('open', '');
      }
    }
    requestAnimationFrame(() => input.focus());
  }

  function closePalette() {
    if (!dialog || !dialog.open) return;
    if (typeof dialog.close === 'function') {
      dialog.close();
    } else {
      dialog.removeAttribute('open');
      if (lastTrigger && typeof lastTrigger.focus === 'function') {
        lastTrigger.focus();
      }
      lastTrigger = null;
    }
  }

  document.addEventListener('click', (e) => {
    const trigger = e.target && e.target.closest ? e.target.closest('[data-lms-quick-search]') : null;
    if (!trigger) return;
    e.preventDefault();
    openPalette(trigger);
  });

  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && String(e.key || '').toLowerCase() === 'k') {
      e.preventDefault();
      if (dialog && dialog.open) {
        closePalette();
      } else {
        openPalette(document.activeElement);
      }
    }
  });
})();
