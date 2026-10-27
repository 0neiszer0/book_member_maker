const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/integrated_calendar.js', 'utf8');
class Element {
  constructor() {this.children = []; this.dataset = {}; this.handlers = {}; this.classList = {add() {}}; this.hidden = false;}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children = children;}
  setAttribute() {}
  addEventListener(name, fn) {this.handlers[name] = fn;}
}
async function scenario(fail, mobile) {
  const elements = Object.fromEntries(['ic-view','ic-date','ic-status','ic-error','ic-content','ic-range','ic-refresh','ic-today','ic-prev','ic-next'].map(x => [x, new Element()]));
  elements['ic-date'].value = '2026-10-27';
  const root = new Element(); root.dataset = {today: '2026-10-27', member: 'false', term: ''};
  root.querySelectorAll = () => ['seminar','deadline','room','blocked'].map(type => {const e = new Element(); e.dataset.filter = type; return e;});
  let calls = 0;
  const rows = [{kind:'regular',id:'public-id',starts_at:'2026-10-29T09:00:00+09:00',ends_at:'2026-10-29T10:00:00+09:00',representative:'대표'},
    {kind:'blocked',starts_at:'2026-10-29T11:00:00+09:00',ends_at:'2026-10-29T12:00:00+09:00'},
    {kind:'blocked',starts_at:'2026-10-29T02:00:00Z',ends_at:'2026-10-29T03:00:00Z'}];
  vm.runInNewContext(source, {document:{querySelector:()=>root,getElementById:id=>elements[id],createElement:()=>new Element()}, matchMedia:()=>({matches:mobile}), fetch:async()=>({ok:!(fail && ++calls === 1),json:async()=>({bookings:rows})}), URLSearchParams, Date, Intl, Set, Map, Promise, Number});
  await new Promise(resolve => setImmediate(resolve));
  const all = []; const visit = e => {all.push(e); e.children.forEach(visit);}; visit(elements['ic-content']);
  assert.equal(all.filter(e => e.className === 'ic-event ic-room').length, 1, 'cross-window room ID dedup');
  assert.equal(all.filter(e => e.className === 'ic-event ic-blocked').length, 1, 'anonymous meeting normalized time dedup');
  assert.equal(all.find(e => e.className === 'ic-event ic-room').href, '/club-room?date=2026-10-29&booking=public-id');
  assert.equal(all.find(e => e.className === 'ic-event ic-blocked').href, '/club-room?date=2026-10-29&at=11%3A00');
  assert.equal(elements['ic-error'].hidden, !fail);
  if (fail) assert.match(elements['ic-error'].textContent, /빈 시간으로 판단하지/);
  assert.equal(elements['ic-view'].value, mobile ? 'agenda' : 'month');
}
(async()=>{await scenario(false,false);await scenario(true,false);await scenario(false,true);console.log('Integrated calendar: public dedup, anonymous blocks, partial failure, mobile agenda passed.');})().catch(e=>{console.error(e);process.exitCode=1;});
