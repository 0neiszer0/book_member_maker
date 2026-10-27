(function(){
  const dialog = document.getElementById('lms-feedback-dialog');
  const openButton = document.getElementById('lms-feedback-open');
  const closeButton = document.getElementById('lms-feedback-close');
  const cancelButton = document.getElementById('lms-feedback-cancel');
  const form = document.getElementById('lms-feedback-form');
  if (!dialog || !openButton || !form) return;

  function closeDialog(){ if (dialog.open) dialog.close(); }
  openButton.addEventListener('click', function(){
    document.getElementById('lms-feedback-status').textContent = '';
    dialog.showModal();
    setTimeout(function(){ document.getElementById('lms-feedback-title').focus(); }, 0);
  });
  closeButton.addEventListener('click', closeDialog);
  cancelButton.addEventListener('click', closeDialog);
  dialog.addEventListener('click', function(event){
    if (event.target === dialog) closeDialog();
  });

  form.addEventListener('submit', async function(event){
    event.preventDefault();
    const title = document.getElementById('lms-feedback-title');
    const description = document.getElementById('lms-feedback-description');
    const submitButton = document.getElementById('lms-feedback-submit');
    const status = document.getElementById('lms-feedback-status');
    if (!title.checkValidity() || !description.checkValidity()) {
      status.textContent = '제목과 내용을 조금 더 자세히 적어주세요.';
      return;
    }
    submitButton.disabled = true;
    status.classList.remove('success');
    status.textContent = '보내는 중입니다…';
    try {
      const response = await fetch('/api/bug-reports', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          category: document.getElementById('lms-feedback-category').value,
          title: title.value.trim(),
          description: description.value.trim(),
          source_page: dialog.dataset.sourcePage
        })
      });
      const payload = await response.json();
      if (!response.ok || payload.status !== 'success') throw new Error(payload.message || '제보를 보내지 못했습니다.');
      form.reset();
      status.classList.add('success');
      status.textContent = '제보가 접수되었습니다. 확인 후 개선하겠습니다.';
      setTimeout(closeDialog, 1400);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      submitButton.disabled = false;
    }
  });
})();
