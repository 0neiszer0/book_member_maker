const assert = require('node:assert/strict');
const {ScheduleDrafts} = require('../static/seminar_schedule.js');
const rows = [
    {id:'w1',book_title:'원래 책',book_author:'저자',note:'유지',sessions:[
        {id:'thu',day_type:'thu',meeting_date:'2026-09-03',moderator_name:'목사회자'},
        {id:'mon',day_type:'mon',meeting_date:'2026-09-07',moderator_name:'월사회자'}]},
    {id:'w2',book_title:'두 번째',book_author:'두 저자',note:'',sessions:[
        {id:'thu2',day_type:'thu',meeting_date:'2026-09-10',moderator_name:''}]}
];
const drafts = new ScheduleDrafts(rows);
assert.equal(drafts.changed.length, 0);
drafts.get('w1').sessions[1].moderator_name = '새 월사회자';
assert.deepEqual(drafts.payload(drafts.get('w1')).moderators, [{id:'mon',moderator_name:'새 월사회자'}]);
assert.equal(rows[0].sessions[1].moderator_name, '월사회자');
drafts.stage('2026-09-03 | 새 책 | |\n2026-09-10\t다음 책\t새 저자');
assert.equal(drafts.changed.length, 2);
assert.equal(drafts.get('w1').book_author, '저자');
assert.equal(drafts.get('w1').note, '유지');
assert.equal(drafts.get('w1').sessions[1].moderator_name, '새 월사회자');
const before = JSON.stringify(drafts.rows);
assert.throws(() => drafts.stage('2026-09-03 | 오류면 미반영\n2099-01-01 | 없는 날짜'), /2행/);
assert.equal(JSON.stringify(drafts.rows), before);
assert.throws(() => drafts.stage('2026-09-03 | 책\n2026-09-07 | 같은 주'), /중복/);
assert.throws(() => drafts.stage('2026-09-03 |'), /하나 이상/);
assert.throws(() => drafts.stage('2026-09-03 | ' + '가'.repeat(501)), /너무 깁니다/);
assert.equal(JSON.stringify(drafts.rows), before);
drafts.markSaved(drafts.get('w1'));
assert.equal(drafts.changed.length, 1); // A successful first row does not clean an unsaved/failed second row.
drafts.get('w1').book_title = '다시 수정';
assert.equal(drafts.changed.length, 2);
assert.deepEqual(drafts.payload(drafts.get('w1')).moderators, []);
console.log('Schedule drafts: shared dates, separate moderators, paste validation, blank preservation, partial-save retry passed.');
