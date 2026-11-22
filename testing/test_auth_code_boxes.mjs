import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../static/auth_code_boxes.js', import.meta.url), 'utf8');

function makeEl() {
  const listeners = {};
  return {
    value: '', dataset: {}, hidden: true, classList: { add() {} }, labels: [{}],
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    fire(type, event = {}) { (listeners[type] || []).forEach(fn => fn(event)); },
    setAttribute() {}, removeAttribute() {}, getAttribute() { return 'false'; },
    focus() { this.focused = true; }, select() {}, id: 'x',
  };
}

function setup({ autoSubmit, valid = true }) {
  const calls = { submit: 0, report: 0, focusInvalid: 0 };
  const original = makeEl();
  const boxes = Array.from({ length: 6 }, makeEl);
  const invalidField = makeEl();
  invalidField.focus = () => { calls.focusInvalid++; };
  original.form = {
    addEventListener() {},
    checkValidity: () => valid,
    reportValidity: () => { calls.report++; },
    requestSubmit: () => { calls.submit++; },
    querySelector: () => (valid ? null : invalidField),
  };
  original.autofocus = false;
  const error = makeEl();
  const group = makeEl();
  group.dataset = autoSubmit ? { autoSubmit: 'true', digitMask: 'false' } : { digitMask: 'false' };
  group.querySelector = sel => ({
    '[data-auth-code-value]': original,
    '[data-auth-code-controls]': makeEl(),
    '[data-auth-code-toggle]': null,
    '[data-auth-code-error]': error,
  })[sel];
  group.querySelectorAll = () => boxes;
  const context = {
    document: {
      activeElement: null, body: {},
      querySelectorAll: sel => (sel === '[data-auth-code]' ? [group] : []),
    },
    window: { addEventListener() {} },
    requestAnimationFrame: fn => fn(),
    setTimeout: fn => fn(),
  };
  vm.runInNewContext(source, context);
  return { boxes, calls, original };
}

const type = (boxes, digits) => [...digits].forEach((d, i) => {
  boxes[i].value = d;
  boxes[i].fire('input');
});

test('typing 6 digits auto-submits a valid auto-submit group once', () => {
  const { boxes, calls, original } = setup({ autoSubmit: true });
  type(boxes, '123456');
  assert.equal(original.value, '123456');
  assert.equal(calls.submit, 1);
});

test('pasting 6 digits auto-submits', () => {
  const { boxes, calls } = setup({ autoSubmit: true });
  boxes[0].fire('paste', { preventDefault() {}, clipboardData: { getData: () => '654321' } });
  assert.equal(calls.submit, 1);
});

test('invalid form reports validity and does not submit', () => {
  const { boxes, calls } = setup({ autoSubmit: true, valid: false });
  type(boxes, '123456');
  assert.equal(calls.submit, 0);
  assert.equal(calls.report, 1);
  assert.equal(calls.focusInvalid, 1);
});

test('group without data-auto-submit never auto-submits', () => {
  const { boxes, calls } = setup({ autoSubmit: false });
  type(boxes, '123456');
  assert.equal(calls.submit, 0);
});
