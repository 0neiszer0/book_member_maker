const assert = require('node:assert/strict');
const {kst, shiftDate, weekStart, slotState, freeRanges, calendarTarget, targetMatches} = require('../static/club_room.js');
const future = calendarTarget('?date=2027-01-03&booking=public-id', '2026-10-27');
assert.equal(future.date, '2027-01-03');
assert.equal(weekStart(future.date), '2026-12-28');
assert.equal(targetMatches(future, {kind:'regular',id:'public-id'}, '2027-01-03'), true);
assert.equal(targetMatches(future, {kind:'regular',id:'other'}, '2027-01-03'), false);
assert.equal(calendarTarget('?date=2027-02-30&booking=public-id', '2026-10-27').date, '2026-10-27');
const block = calendarTarget('?date=2027-01-03&at=11%3A00', '2026-10-27');
assert.equal(targetMatches(block, {kind:'blocked',starts_at:'2027-01-03T02:00:00Z'}, block.date), true);
assert.equal(block.booking, '');
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
