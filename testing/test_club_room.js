const assert = require('node:assert/strict');
const {kst, shiftDate, weekStart, slotState, freeRanges, calendarTarget, targetMatches, nowStatus, shareUrl, monthGridRange, shiftMonth, groupBookingsByDate} = require('../static/club_room.js');
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
const at = text => Date.parse(text);
assert.deepEqual(nowStatus(rows, at('2026-10-05T10:20:00+09:00')), {tone:'free', text:'지금 바로 사용 가능해요 (다음 예약 12:00)'});
assert.deepEqual(nowStatus(rows, at('2026-10-05T12:30:00+09:00')), {tone:'busy', text:'지금 예약이 있어요 · 14:00부터 비어 있어요'});
assert.equal(nowStatus(rows, at('2026-10-05T19:00:00+09:00')).text, '지금 예약이 있어요 · 오늘은 자정까지 이어져요');
assert.equal(nowStatus(rows, at('2026-10-05T07:00:00+09:00')).text, '현재 이용 시간이 아니에요 (09:00~24:00)');
assert.equal(nowStatus([], at('2026-10-05T15:00:00+09:00')).tone, 'free');
assert.equal(shareUrl('https://knu-read.xyz/'), 'https://knu-read.xyz/club-room');
const nov = monthGridRange('2026-11-23');
assert.deepEqual([nov.year, nov.month, nov.start, nov.end, nov.days], [2026, 11, '2026-11-01', '2026-12-05', 35]);
assert.equal(nov.dates.length, 35);
const dec = monthGridRange('2026-12-31');
assert.deepEqual([dec.start, dec.end, dec.days], ['2026-11-29', '2027-01-02', 35]);
const feb = monthGridRange('2026-02-10');
assert.deepEqual([feb.start, feb.end, feb.days], ['2026-02-01', '2026-02-28', 28]);
const leap = monthGridRange('2028-02-29');
assert.deepEqual([leap.start, leap.end, leap.days], ['2028-01-30', '2028-03-04', 35]);
const aug = monthGridRange('2026-08-15');
assert.deepEqual([aug.start, aug.end, aug.days], ['2026-07-26', '2026-09-05', 42]);
for (const ymd of ['2026-01-01', '2026-02-01', '2026-08-01', '2028-02-01', '2027-05-31', '2026-10-31']) {
  const grid = monthGridRange(ymd);
  assert.equal(new Date(grid.start + 'T00:00:00Z').getUTCDay(), 0);
  assert.equal(new Date(grid.end + 'T00:00:00Z').getUTCDay(), 6);
  assert.ok([28, 35, 42].includes(grid.days) && grid.days % 7 === 0);
}
assert.equal(shiftMonth('2026-01-31', 1), '2026-02-28');
assert.equal(shiftMonth('2028-01-31', 1), '2028-02-29');
assert.equal(shiftMonth('2026-12-15', 1), '2027-01-15');
assert.equal(shiftMonth('2026-01-15', -1), '2025-12-15');
assert.equal(shiftMonth('2026-03-31', -1), '2026-02-28');
assert.equal(shiftMonth('2026-05-31', 0), '2026-05-31');
assert.equal(shiftMonth('2026-11-23', 14), '2028-01-23');
const grouped = groupBookingsByDate([
  {kind:'blocked', starts_at:'2026-10-05T18:00:00+09:00', ends_at:'2026-10-05T20:00:00+09:00'},
  {kind:'regular', representative:'B', starts_at:'2026-10-05T15:00:00+09:00', ends_at:'2026-10-05T16:00:00+09:00'},
  {kind:'regular', representative:'A', starts_at:'2026-10-05T09:00:00+09:00', ends_at:'2026-10-05T10:00:00+09:00'},
  {kind:'regular', representative:'N', starts_at:'2026-10-06T23:00:00+09:00', ends_at:'2026-10-07T00:00:00+09:00'}
]);
assert.deepEqual(grouped['2026-10-05'].all.map(row => row.representative || 'blocked'), ['A', 'B', 'blocked']);
assert.equal(grouped['2026-10-05'].regular.length, 2);
assert.equal(grouped['2026-10-05'].blocked.length, 1);
assert.equal(grouped['2026-10-06'].all.length, 1);
assert.equal(grouped['2026-10-07'], undefined);
assert.deepEqual(groupBookingsByDate([]), {});
console.log('Room calendar: KST, week/year boundaries, shared/blocked slots, midnight and free ranges passed.');
