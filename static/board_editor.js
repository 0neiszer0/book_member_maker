(() => {
  const form = document.querySelector('.lms-board-form'); if (!form) return;
  const content = document.getElementById('post-content'), format = document.getElementById('content-format');
  const editor = document.getElementById('post-editor'), count = document.getElementById('post-count');
  let quill;
  if (window.Quill) {
    quill = new Quill(editor, {theme:'snow', formats:['bold','italic','underline','strike','header','list','blockquote','link'],
      modules:{toolbar:'#post-toolbar'}});
    if (format.value === 'html') quill.clipboard.dangerouslyPasteHTML(content.value);
    else quill.setText(content.value);
    content.hidden = true; content.required = false; editor.hidden = false; format.value = 'html';
    quill.root.setAttribute('aria-label','본문'); quill.root.setAttribute('role','textbox'); quill.root.setAttribute('aria-multiline','true');
    quill.on('text-change', () => {content.value = quill.getSemanticHTML(); count.textContent = `${Math.max(0,quill.getLength()-1).toLocaleString()}자`;});
    document.querySelectorAll('#post-toolbar button').forEach(button => button.title = button.getAttribute('aria-label'));
    document.getElementById('post-undo').onclick = () => quill.history.undo();
    document.getElementById('post-redo').onclick = () => quill.history.redo();
  } else document.getElementById('post-toolbar').hidden = true;
  form.addEventListener('submit', e => {
    if (quill) content.value = quill.getSemanticHTML();
    if ((quill && !quill.getText().trim()) || content.value.length > 50000) {
      e.preventDefault(); count.textContent = '본문을 입력해주세요. 최대 50,000자입니다.'; quill?.focus();
    }
  });
  const input = document.getElementById('images'), drop = document.getElementById('image-drop'), preview = document.getElementById('preview');
  const error = document.getElementById('image-error'), maximum = 5 - Number(input.dataset.existing || 0);
  let files = [], urls = [];
  function sync() {
    urls.forEach(URL.revokeObjectURL); urls = []; preview.replaceChildren();
    const transfer = new DataTransfer(); files.forEach((file,i) => {
      transfer.items.add(file); const wrap = document.createElement('div'); wrap.className='lms-board-preview';
      const img=document.createElement('img'); img.src=URL.createObjectURL(file); urls.push(img.src); img.alt=file.name;
      img.className='lms-board-thumbnail'; const button=document.createElement('button'); button.type='button';
      button.textContent='×'; button.className='lms-board-remove-image'; button.setAttribute('aria-label',file.name+' 첨부 취소');
      button.onclick=()=>{files.splice(i,1);sync();};wrap.append(img,button);preview.append(wrap);
    }); input.files=transfer.files;
  }
  function add(incoming) {
    const list=Array.from(incoming); error.textContent='';
    if (files.length+list.length>maximum) {error.textContent=`기존 첨부를 포함해 최대 5개입니다. 추가 가능한 개수: ${Math.max(0,maximum-files.length)}`;sync();return;}
    if(list.some(f=>!['image/jpeg','image/png','image/webp','image/gif'].includes(f.type)||f.size>10*1024*1024)) {error.textContent='JPG·PNG·WebP·GIF, 파일당 10MB 이하만 첨부할 수 있습니다.';sync();return;}
    files.push(...list);sync();
  }
  input.addEventListener('change',()=>add(input.files));
  drop.addEventListener('dragover',e=>e.preventDefault());drop.addEventListener('drop',e=>{e.preventDefault();add(e.dataTransfer.files);});
  form.addEventListener('paste',e=>{const images=Array.from(e.clipboardData.files).filter(f=>f.type.startsWith('image/'));if(images.length){e.preventDefault();add(images);}});
  window.addEventListener('pagehide',()=>urls.forEach(URL.revokeObjectURL));
})();
