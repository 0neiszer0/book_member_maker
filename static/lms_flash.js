(() => {
  // One-shot notices: close button for every flash, auto-hide for view-switch toasts.
  const remove = el => { if (el && el.parentNode) el.parentNode.removeChild(el); };
  document.querySelectorAll('[data-lms-flash]').forEach(el => {
    const button = el.querySelector('[data-lms-flash-close]');
    if (button) button.addEventListener('click', () => remove(el));
    const delay = parseInt(el.dataset.autohide || '', 10);
    if (delay > 0) setTimeout(() => remove(el), delay);
  });
})();
