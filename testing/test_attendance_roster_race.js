const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(dataset = {}) { this.dataset = dataset; this.listeners = {}; this.hidden = false; this.value = ''; this.children = []; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  emit(name) { return this.listeners[name]?.({target:this}); }
  setAttribute() {}
  scrollIntoView() {}
  replaceChildren() { this.children = []; }
  append(child) { this.children.push(child); }
}

function harness() {
  const ids = Object.fromEntries(['attendance-status','roster-preview','apply-roster','roster-text','roster-file',
    'roster-search','actual-search','preview-roster','actual-count','confirm-attendance'].map(id=>[id,new Element()]));
  const methods = ['text','selected','file'].map(method=>new Element({method}));
  const panels = ['text','selected','file'].map(inputPanel=>new Element({inputPanel}));
  const checkbox = new Element();
  const root = new Element({sessionId:'seminar', csrf:'test'});
  root.querySelectorAll = selector => selector==='[data-method]' ? methods : selector==='[data-input-panel]' ? panels
    : selector==='#roster-text,#roster-file,.roster-choice' ? [ids['roster-text'],ids['roster-file'],checkbox] : [];
  const requests = [];
  const context = {
    document:{querySelector:()=>root,getElementById:id=>ids[id],createElement:()=>new Element()},
    fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve})),
    FormData:class {}, confirm:()=>true, location:{reload(){}},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/attendance_roster.js'),'utf8'),context);
  const resolve = token => requests.at(-1).resolve({ok:true,json:async()=>({status:'success',expected_count:1,
    matched:[{name:'테스트'}],added:[],removed:[],issues:[],token})});
  return {ids,methods,checkbox,requests,resolve};
}

(async()=>{
  for (const mutate of [h=>{h.ids['roster-text'].value='새 명단';h.ids['roster-text'].emit('input');},
                         h=>h.methods[1].emit('click'), h=>h.checkbox.emit('input'), h=>h.ids['roster-file'].emit('input')]) {
    const h=harness();
    const pending=h.ids['preview-roster'].emit('click');
    assert.equal(h.requests.length,1);
    mutate(h);
    h.resolve('stale-token');
    await pending;
    assert.equal(h.ids['apply-roster'].hidden,true,'Edited input must keep old apply token unavailable.');
    assert.equal(h.ids['roster-preview'].hidden,true,'Edited input must not display stale preview.');
    assert.match(h.ids['attendance-status'].textContent,/다시 미리보기/);
    await h.ids['apply-roster'].emit('click');
    assert.equal(h.requests.length,1,'No apply request may use a stale token.');
  }
  const h=harness();
  let pending=h.ids['preview-roster'].emit('click');h.resolve('fresh-token');await pending;
  assert.equal(h.ids['apply-roster'].hidden,false,'Unchanged input still displays usable preview.');
  h.ids['roster-text'].emit('input');assert.equal(h.ids['apply-roster'].hidden,true);
  pending=h.ids['preview-roster'].emit('click');h.resolve('new-token');await pending;
  assert.equal(h.ids['apply-roster'].hidden,false,'User can preview again after changing the input.');
  console.log('Attendance preview race checks passed (text/mode/checkbox/file/retry).');
})().catch(error=>{console.error(error);process.exitCode=1;});
