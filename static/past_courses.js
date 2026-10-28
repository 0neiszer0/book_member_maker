(() => {
  const root=document.getElementById('past-courses');if(!root)return;
  const status=document.getElementById('past-courses-status'),toggle=document.getElementById('past-courses-toggle');let courses=[];
  const csrf=document.querySelector('meta[name="lms-csrf"]').content;
  function render(){root.replaceChildren();courses.filter(c=>!c.hidden||toggle.checked).forEach(course=>{
    const card=document.createElement('article');card.className='lms-course-card lms-past-course';
    const body=document.createElement('div');body.className='lms-course-card-body';
    const title=document.createElement(course.term_id?'a':'h3');title.textContent=course.name;if(course.term_id)title.href='/seminars?term_id='+encodeURIComponent(course.term_id);
    const note=document.createElement('p');note.className='lms-small';note.textContent=`확정된 세미나 참여 ${course.count}회${course.hidden?' · 숨김':''}`;
    const button=document.createElement('button');button.type='button';button.className='lms-button';button.textContent=course.hidden?'다시 표시':'숨기기';
    button.onclick=async()=>{button.disabled=true;try{const r=await fetch('/api/my/courses/visibility',{method:'POST',headers:{'Content-Type':'application/json','X-App-CSRF':csrf},body:JSON.stringify({key:course.key,hidden:!course.hidden})});if(!r.ok)throw Error();course.hidden=!course.hidden;render();}catch{status.textContent='설정을 저장하지 못했습니다. 다시 시도해주세요.';button.disabled=false;}};
    body.append(title,note,button);card.append(body);root.append(card);
  });status.textContent=!courses.length?'이전 학기에 연결된 확정 참여 기록이 없습니다.':!root.children.length?'이전 학기 강의실을 모두 숨겼습니다.':'';}
  toggle.onchange=render;
  fetch('/api/my/courses',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{courses=data.courses;render();}).catch(()=>{status.textContent='이전 학기 기록을 불러오지 못했습니다. 새로고침해 다시 시도해주세요.';});
})();
