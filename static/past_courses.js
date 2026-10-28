(() => {
  const root=document.getElementById('past-courses');if(!root)return;
  const status=document.getElementById('past-courses-status'),toggle=document.getElementById('past-courses-toggle');let courses=[];
  const csrf=document.querySelector('meta[name="lms-csrf"]').content;
  function render(){root.replaceChildren();courses.filter(c=>!c.hidden||toggle.checked).forEach(course=>{
    const card=document.createElement('article');card.className='lms-course-card lms-past-course';
    const href=course.term_id?'/seminars?term_id='+encodeURIComponent(course.term_id):'/my/seminars/archive/'+encodeURIComponent(course.key);
    const cover=document.createElement('a');cover.href=href;cover.className='lms-course-card-color';cover.setAttribute('aria-label',course.name+' 열기');
    const body=document.createElement('div');body.className='lms-course-card-body';
    const title=document.createElement('a');title.href=href;
    const kind=document.createElement('h3');kind.textContent='정기 세미나';
    const name=document.createElement('div');name.textContent=course.name;title.append(kind,name);
    const note=document.createElement('small');note.textContent=`내 확정 참여 ${course.count}회${course.hidden?' · 숨김':''}`;
    const actions=document.createElement('nav');actions.className='lms-course-card-actions';actions.setAttribute('aria-label',course.name+' 바로가기');
    const records=document.createElement('a');records.href='/my/seminars/archive/'+encodeURIComponent(course.key);records.textContent='내 참여 내역';
    const button=document.createElement('button');button.type='button';button.className='lms-button';button.textContent=course.hidden?'다시 표시':'숨기기';
    button.onclick=async()=>{button.disabled=true;try{const r=await fetch('/api/my/courses/visibility',{method:'POST',headers:{'Content-Type':'application/json','X-App-CSRF':csrf},body:JSON.stringify({key:course.key,hidden:!course.hidden})});if(!r.ok)throw Error();course.hidden=!course.hidden;render();}catch{status.textContent='설정을 저장하지 못했습니다. 다시 시도해주세요.';button.disabled=false;}};
    body.append(title,note);actions.append(records,button);card.append(cover,body,actions);root.append(card);
  });status.textContent=!courses.length?'이전 학기에 연결된 확정 참여 기록이 없습니다.':!root.children.length?'이전 학기 강의실을 모두 숨겼습니다.':'';}
  toggle.onchange=render;
  fetch('/api/my/courses',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{courses=data.courses;render();}).catch(()=>{status.textContent='이전 학기 기록을 불러오지 못했습니다. 새로고침해 다시 시도해주세요.';});
})();
