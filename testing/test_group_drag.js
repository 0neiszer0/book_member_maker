const assert = require('node:assert/strict');
const {mount} = require('../static/group_drag.js');
class Node {
    constructor(kind) {
        this.kind = kind; this.children = []; this.style = {}; this.dataset = {};
        this.classes = new Set(); this.listeners = {}; this.isConnected = true;
        this.classList = {add: x => this.classes.add(x), remove: x => this.classes.delete(x)};
        this.offsetWidth = 170; this.offsetHeight = 70;
    }
    addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
    emit(type, event = {}) { (this.listeners[type] || []).forEach(fn => fn(event)); }
    append(...nodes) { nodes.forEach(node => { node.parent = this; this.children.push(node); }); }
    appendChild(node) { this.append(node); }
    remove() { this.removed = true; if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); }
    setAttribute() {}
    closest(selector) {
        if (selector === '.ge-member' && this.kind === 'member') return this;
        if (selector === '.ge-chip' && this.kind === 'chip') return this;
        if (selector === '[data-destination]' && this.kind === 'destination') return this;
        return this.parent?.closest(selector) || null;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0]; }
    querySelectorAll(selector) {
        const descendants = this.children.flatMap(node => [node, ...node.querySelectorAll('*')]);
        if (selector === '*') return descendants;
        if (selector === '.ge-drop-target') return descendants.filter(node => node.classes.has('ge-drop-target'));
        if (selector === '.ge-unassign') return descendants.filter(node => node.kind === 'unassign');
        if (selector === 'button') return descendants.filter(node => ['member', 'unassign'].includes(node.kind));
        return [];
    }
    contains(node) { return this.querySelectorAll('*').includes(node); }
    cloneNode() {
        const cloned = new Node(this.kind); cloned.classes = new Set(this.classes);
        this.children.forEach(node => cloned.append(node.cloneNode()));
        return cloned;
    }
    setPointerCapture() { this.captured = true; }
    hasPointerCapture() { return this.captured; }
    releasePointerCapture() { this.captured = false; }
}
const body = new Node('body'), container = new Node('container'), destination = new Node('destination');
const chip = new Node('chip'), member = new Node('member');
member.dataset.member = '김가람'; destination.dataset.destination = '1';
chip.append(member, new Node('unassign')); container.append(chip, destination);
let timer, frame, scrolls = [], moves = [], finishes = 0;
global.innerWidth = 1200; global.innerHeight = 800;
global.document = {body, createElement: () => new Node('div'), elementFromPoint: x => x >= 0 && x < 1100 ? destination : null};
global.setTimeout = fn => { timer = fn; return 1; };
global.clearTimeout = () => { timer = null; };
global.requestAnimationFrame = fn => { frame = fn; return 2; };
global.cancelAnimationFrame = () => { frame = null; };
global.scrollBy = (x,y) => scrolls.push(y);
const windowEvents = new Node('window');
global.addEventListener = (...args) => windowEvents.addEventListener(...args);
mount(container, {groupName: () => '두 번째 조', onFinish: () => finishes++, onMove: (...args) => moves.push(args)});
function pointer(type, x, y, extra = {}) {
    const event = {target:member,pointerType:'mouse',pointerId:1,button:0,clientX:x,clientY:y,preventDefault(){this.prevented=true;},...extra};
    container.emit(type, event); return event;
}
function touch(type, x, y, extra = {}) {
    const item = {identifier:9,clientX:x,clientY:y};
    const event = {target:member,touches:[item],changedTouches:[item],cancelable:true,preventDefault(){this.prevented=true;},...extra};
    container.emit(type,event); return event;
}
pointer('pointerdown', 100, 200);
pointer('pointermove', 102, 200);
assert.equal(body.children.length, 0);
pointer('pointermove', 200, 250);
assert.equal(body.children.length, 1);
assert.equal(body.children[0].style.left, '214px');
assert.equal(body.children[0].style.top, '270px');
assert.equal(chip.classes.has('ge-drag-origin'), true);
assert.equal(moves.length, 0);
pointer('pointermove', 400, 350);
assert.equal(body.children[0].style.left, '414px');
assert.match(body.children[0].children[1].textContent, /두 번째 조/);
pointer('pointerup', 400, 350);
assert.deepEqual(moves, [['김가람','1']]);
assert.equal(body.children.length, 0);
assert.equal(chip.classes.has('ge-drag-origin'), false);
// Invalid drop, Escape, capture loss and blur never commit.
for (const cancel of ['outside','Escape','lostpointercapture','blur']) {
    pointer('pointerdown', 100, 200); pointer('pointermove', 200, 250);
    if (cancel === 'outside') pointer('pointerup', 1300, 250);
    else if (cancel === 'Escape') windowEvents.emit('keydown',{key:'Escape'});
    else if (cancel === 'blur') windowEvents.emit('blur');
    else pointer(cancel,200,250);
    assert.equal(body.children.length,0);
    assert.equal(moves.length,1);
}
// Quick swipe cancels hold and does not prevent native scrolling.
touch('touchstart',100,200);
assert.equal(touch('touchmove',100,220).prevented,undefined);
assert.equal(timer,null);
touch('touchend',100,220);
assert.equal(moves.length,1);
// Long press creates a floating preview before moving, then tracks the finger.
touch('touchstart',100,200); timer();
assert.equal(body.children.length,1);
assert.equal(touch('touchmove',300,400).prevented,true);
assert.equal(body.children[0].style.left,'314px');
assert.equal(body.children[0].style.top,'314px');
assert.equal(touch('touchend',300,400).prevented,true);
assert.equal(moves.length,2);
assert.equal(body.children.length,0);
// Edge scroll and multi-touch cancellation clean up pending animation.
touch('touchstart',100,200); timer();
touch('touchmove',300,790); frame();
assert.ok(scrolls.some(y=>y>0));
touch('touchstart',100,200,{touches:[{},{}]});
assert.equal(frame,null);
assert.equal(body.children.length,0);
assert.equal(moves.length,2);
touch('touchstart',100,200); timer();
touch('touchmove',300,400,{cancelable:false});
assert.equal(body.children.length,0);
assert.equal(moves.length,2);
assert.ok(finishes >= 7);
console.log('Group drag: cursor/finger preview, threshold, long press, scroll, valid/invalid drop, Escape, capture loss, multi-touch and cleanup passed.');
