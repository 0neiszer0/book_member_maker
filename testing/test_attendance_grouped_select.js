const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(dataset = {}, value = '') { this.dataset = dataset; this.listeners = {}; this.hidden = false; this.value = value; this.checked = false; this.textContent = ''; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  emit(name) { return this.listeners[name]?.({target:this, currentTarget:this}); }
  setAttribute() {}
  scrollIntoView() {}
  replaceChildren() {}
  append() {}
}

const ids = Object.fromEntries(['attendance-status','roster-preview','apply-roster','roster-text','roster-file','roster-search',
  'actual-search','preview-roster','actual-count','confirm-attendance'].map(id=>[id,new Element()]));
ids['use-grouped'] = new Element({ids:'[2,3]'});
const choices = [1,2,3,4].map(v=>new Element({}, String(v)));
choices[0].checked = true; choices[3].checked = true;
const root = new Element({sessionId:'seminar', csrf:'test', confirmationToken:'signed'});
root.querySelectorAll = selector => {
  if (selector === '.actual-choice') return choices;
  if (selector === '.actual-choice:checked') return choices.filter(c=>c.checked);
  return [];
};
const requests = [];
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/attendance_roster.js'),'utf8'), {
  document:{querySelector:()=>root,getElementById:id=>ids[id],createElement:()=>new Element()},
  fetch:(url,options)=>{requests.push({url,options});return new Promise(()=>{});},
  FormData:class {}, confirm:()=>true, location:{reload(){}},
});
ids['use-grouped'].emit('click');
assert.deepEqual(choices.map(c=>c.checked), [false,true,true,false], 'Group plan replaces the selection exactly.');
assert.match(ids['actual-count'].textContent, /2명/);
assert.match(ids['attendance-status'].textContent, /조 편성 명단 2명/);
assert.equal(requests.length, 0, 'Selecting the group plan must not confirm anything.');
ids['confirm-attendance'].emit('click');
assert.equal(requests.length, 1);
assert.match(requests[0].url, /\/attendance\/confirm$/);
assert.deepEqual(JSON.parse(requests[0].options.body), {member_ids:[2,3], confirmation_token:'signed'});
console.log('Grouped selection checks passed (select only, explicit confirm with signed token).');