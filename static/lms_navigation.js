(() => {
  const dialog = document.getElementById('lms-menu-dialog');
  const trigger = document.getElementById('lms-menu-open');
  if (!dialog || !trigger) return;
  trigger.addEventListener('click', () => {
    dialog.showModal();
    trigger.setAttribute('aria-expanded', 'true');
  });
  document.getElementById('lms-menu-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => {
    trigger.setAttribute('aria-expanded', 'false');
    trigger.focus();
  });
})();
