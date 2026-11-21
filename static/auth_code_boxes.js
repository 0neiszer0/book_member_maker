(() => {
  const digitsOnly = value => value.replace(/[^0-9]/g, '').slice(0, 6);

  function enhance(group) {
    const original = group.querySelector('[data-auth-code-value]');
    const controls = group.querySelector('[data-auth-code-controls]');
    const boxes = Array.from(group.querySelectorAll('[data-auth-code-digit]'));
    const toggle = group.querySelector('[data-auth-code-toggle]');
    const error = group.querySelector('[data-auth-code-error]');
    const shouldFocus = document.activeElement === original ||
      (original.autofocus && document.activeElement === document.body);

    function focusBox(index) {
      boxes[Math.max(0, Math.min(index, boxes.length - 1))].focus();
    }

    function clearError() {
      error.textContent = '';
      boxes.forEach(box => box.removeAttribute('aria-invalid'));
    }

    function syncOriginal() {
      original.value = boxes.map(box => box.value).join('');
      clearError();
    }

    function syncBoxes() {
      const digits = digitsOnly(original.value);
      boxes.forEach((box, index) => { box.value = digits[index] || ''; });
      syncOriginal();
    }

    function enterDigits(index, digits) {
      const start = index + digits.length > boxes.length ? 0 : index;
      Array.from(digits).forEach((digit, offset) => {
        boxes[start + offset].value = digit;
      });
      syncOriginal();
      focusBox(start + digits.length);
    }

    boxes.forEach((box, index) => {
      box.addEventListener('focus', () => box.select());
      box.addEventListener('click', () => box.select());
      box.addEventListener('input', () => {
        const digits = digitsOnly(box.value);
        if (digits) enterDigits(index, digits);
        else {
          box.value = '';
          syncOriginal();
        }
      });
      box.addEventListener('paste', event => {
        event.preventDefault();
        const digits = digitsOnly(event.clipboardData.getData('text'));
        if (digits) enterDigits(index, digits);
      });
      box.addEventListener('keydown', event => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        if (event.key === 'Backspace') {
          event.preventDefault();
          const target = box.value ? index : Math.max(0, index - 1);
          boxes[target].value = '';
          syncOriginal();
          focusBox(target);
        } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault();
          focusBox(index + (event.key === 'ArrowLeft' ? -1 : 1));
        }
      });
    });

    if (toggle && group.dataset.digitMask === 'true') {
      toggle.addEventListener('click', () => {
        const show = toggle.getAttribute('aria-pressed') === 'false';
        boxes.forEach(box => { box.type = show ? 'text' : 'password'; });
        toggle.setAttribute('aria-pressed', String(show));
        toggle.textContent = show ? 'PIN 숨기기' : 'PIN 보기';
      });
    }

    original.addEventListener('input', syncBoxes);
    original.addEventListener('change', syncBoxes);
    original.addEventListener('invalid', event => {
      event.preventDefault();
      const firstEmpty = boxes.findIndex(box => !box.value);
      boxes.forEach(box => box.setAttribute('aria-invalid', 'true'));
      error.textContent = '숫자 6자리를 입력해주세요.';
      if (original.form.querySelector(':invalid') === original) {
        focusBox(firstEmpty < 0 ? 0 : firstEmpty);
      }
    });
    original.form.addEventListener('reset', () => requestAnimationFrame(syncBoxes));

    syncBoxes();
    controls.hidden = false;
    original.labels[0].htmlFor = boxes[0].id;
    original.classList.add('auth-code-enhanced');
    original.setAttribute('aria-hidden', 'true');
    original.removeAttribute('autofocus');
    original.tabIndex = -1;
    if (shouldFocus) focusBox(0);
  }

  document.querySelectorAll('[data-auth-code]').forEach(enhance);
})();
