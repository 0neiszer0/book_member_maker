// Exercise the real navigation enhancement with server-rendered role menus.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(text = '', href = '', staff = false) {
    this.textContent = text;
    this.href = href;
    this.staff = staff;
    this.attributes = {};
    this.children = [];
    this.classList = { toggle() {}, contains() { return false; } };
  }
  getAttribute(name) { return name === 'href' ? this.href : this.attributes[name]; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  remove() { this.removed = true; }
  closest() { return null; }
  prepend() {}
  insertBefore(node) { this.children.push(node); }
  querySelectorAll(selector) {
    return selector === 'a' ? this.children.filter(link => !link.removed) : [];
  }
}

const source = fs.readFileSync(path.join(__dirname, '../static/app_ui.js'), 'utf8');
// Expose only the actual navigation callback; do not execute unrelated page enhancements.
const instrumented = source.replace('  function bootstrapEnhancements() {',
  '  window.testRoleNavigation = alignRoleNavigation;\n  function bootstrapEnhancements() {');

for (const role of ['officer', 'admin', 'member', '']) {
  const staff = ['admin', 'officer'].includes(role);
  const top = staff ? [new Element('운영 관리', '/admin/seminars', true)] : [];
  const profile = new Element();
  profile.children = [new Element('마이페이지', '/mypage'), new Element('로그아웃', '/logout')];
  if (staff) profile.children.push(
    new Element('운영 관리', '/admin/seminars'), new Element('운영 가이드', '/help/admin'));
  const document = {
    readyState: 'loading', baseURI: 'https://example.test/', addEventListener() {},
    createElement: () => new Element(),
    querySelector: selector => selector === 'meta[name="app-user-role"]' ? { content: role }
      : selector === '#profile-list' ? profile : null,
    querySelectorAll: selector => ['.wd-top-nav a, .wd-tabbar a', '.wd-link-staff'].includes(selector)
      ? top.filter(link => !link.removed) : [],
  };
  const window = { location: { pathname: '/' } };
  vm.runInNewContext(instrumented, { document, window, URL, console });
  window.testRoleNavigation();
  assert.equal(top.filter(link => !link.removed).length, staff ? 1 : 0,
    `${role || 'guest'}: desktop operations navigation must match server authorization`);
  assert.equal(profile.querySelectorAll('a').some(link => link.textContent === '운영 관리'), staff,
    `${role || 'guest'}: mobile/profile menu must retain operations access`);
  if (staff) {
    assert.equal(top[0].href, '/admin/dashboard');
    assert(profile.querySelectorAll('a').some(link => link.textContent === '운영 가이드'));
  }
}
console.log('Staff and member navigation checks passed.');
