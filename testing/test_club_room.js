const assert = require('node:assert/strict');
const {kst, shiftDate, weekStart, slotState, freeRanges} = require('../static/club_room.js');
const now = Date.parse('2026-10-05T10:20:00+09:00');
assert.equal(kst('2026-10-04T15:00:00Z'), '2026-10-05T00:00');
assert.equal(shiftDate('2026-12-31', 1), '2027-01-01');
assert.equal(weekStart('2026-10-11'), '2026-10-05');
const rows = [
  {kind:'regular', representative:'테스트 대표', starts_at:'2026-10-05T12:00:00+09:00', ends_at:'2026-10-05T14:00:00+09:00'},
  {kind:'blocked', starts_at:'2026-10-05T18:00:00+09:00', ends_at:'2026-10-06T01:00:00+09:00'}
];
assert.equal(slotState(rows, '2026-10-05', 9, now).past, true);
assert.equal(slotState(rows, '2026-10-05', 10, now).past, false);
assert.equal(slotState(rows, '2026-10-05', 12, now).blocked, false);
assert.equal(slotState(rows, '2026-10-05', 14, now).rows.length, 0);
assert.equal(slotState(rows, '2026-10-06', 0, now).blocked, true);
assert.equal(slotState(rows, '2026-10-06', 1, now).blocked, false);
assert.deepEqual(freeRanges(rows, '2026-10-05', now), [[10,12], [14,18]]);
assert.deepEqual(freeRanges([], '2026-10-04', now), []);
assert.deepEqual(freeRanges([], '2026-10-06', now), [[9,24]]);
assert.deepEqual(freeRanges(rows, '2026-10-06', now), [[9,24]]);
console.log('Room calendar: KST, week/year boundaries, shared/blocked slots, midnight and free ranges passed.');
