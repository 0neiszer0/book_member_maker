const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/integrated_calendar.js', 'utf8');
class Element {
  constructor() {this.children = []; this.dataset = {}; this.handlers = {}; this.attributes={}; this.classList = {add() {}}; this.hidden = false;}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children = children;}
  setAttribute(name,value) {this.attributes[name]=value;}
  addEventListener(name, fn) {this.handlers[name] = fn;}
}
async function scenario(fail, mobile) {
  const elements = Object.fromEntries(['ic-view','ic-date','ic-status','ic-error','ic-content','ic-range','ic-refresh','ic-today','ic-prev','ic-next','ic-title','ic-filters'].map(x => [x, new Element()]));
  elements['ic-date'].value = '2026-10-27';
  const root = new Element(); root.dataset = {today: '2026-10-27', member: 'false', term: ''};
  const tabs = ['week','month','agenda'].map(view => {const e = new Element(); e.dataset.calendarView=view; return e;});
  root.querySelectorAll = selector => selector.includes('data-calendar-view') ? tabs : [];
  elements['ic-filters'].querySelectorAll = () => ['seminar','deadline','room','blocked'].map(type => {const e = new Element(); e.dataset.filter=type;return e;});
  let calls = 0;
  const rows = [{kind:'regular',id:'public-id',starts_at:'2026-10-29T09:00:00+09:00',ends_at:'2026-10-29T10:00:00+09:00',representative:'대표'},
    {kind:'blocked',starts_at:'2026-10-29T11:00:00+09:00',ends_at:'2026-10-29T12:00:00+09:00'},
    {kind:'blocked',starts_at:'2026-10-29T02:00:00Z',ends_at:'2026-10-29T03:00:00Z'}];
  vm.runInNewContext(source, {document:{querySelector:()=>root,getElementById:id=>elements[id],createElement:()=>new Element()}, matchMedia:query=>{assert.equal(query,'(max-width: 767px)');return {matches:mobile};}, fetch:async()=>({ok:!(fail && ++calls === 1),json:async()=>({bookings:rows})}), URLSearchParams, Date, Intl, Set, Map, Promise, Number});
  await new Promise(resolve => setImmediate(resolve));
  const all = []; const visit = e => {all.push(e); e.children.forEach(visit);}; visit(elements['ic-content']);
  assert.equal(all.filter(e => e.className === 'ic-event ic-room').length, 1, 'cross-window room ID dedup');
  assert.equal(all.filter(e => e.className === 'ic-event ic-blocked').length, 1, 'anonymous meeting normalized time dedup');
  assert.equal(all.find(e => e.className === 'ic-event ic-room').href, '/club-room?date=2026-10-29&booking=public-id');
  assert.equal(all.find(e => e.className === 'ic-event ic-blocked').href, '/club-room?date=2026-10-29&at=11%3A00');
  assert.equal(elements['ic-error'].hidden, !fail);
  if (fail) assert.match(elements['ic-error'].textContent, /빈 시간으로 판단하지/);
  assert.equal(elements['ic-view'].value, 'month', 'Canvas keeps month default on mobile too');
  assert.equal(elements['ic-title'].textContent,'2026년 10월');
  assert.equal(tabs.find(tab=>tab.dataset.calendarView===elements['ic-view'].value).attributes['aria-selected'],'true');
  if (!mobile) {
    assert.equal(all.filter(e=>e.className==='ic-weekday').length,7);
    assert.equal(all.filter(e=>e.className==='ic-cell').length,35,'five-week October grid');
    tabs[0].handlers.click(); await new Promise(resolve=>setImmediate(resolve));
    assert.equal(elements['ic-view'].value,'week');
    assert.equal(tabs[0].attributes['aria-selected'],'true');
  }
  tabs[2].handlers.click(); await new Promise(resolve=>setImmediate(resolve));
  assert.equal(elements['ic-view'].value,'agenda','agenda remains an explicit selectable view');
}
(async()=>{await scenario(false,false);await scenario(true,false);await scenario(false,true);console.log('Integrated calendar: public dedup, anonymous blocks, partial failure, month default and explicit tabs passed.');})().catch(e=>{console.error(e);process.exitCode=1;});
