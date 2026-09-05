const assert = require('node:assert/strict');
const {TermRosterDraft} = require('../static/term_membership.js');
const data = {
  term: {id:'fall', start_date:'2026-09-01'},
  terms: [{id:'spring', start_date:'2026-03-01', roster_initialized_at:'yes'}, {id:'summer', start_date:'2026-07-01', roster_initialized_at:'yes'}, {id:'fall', start_date:'2026-09-01'}, {id:'winter', start_date:'2027-01-01', roster_initialized_at:'yes'}],
  members: [{id:1}, {id:2}, {id:3}, {id:4}],
  memberships: [
    {term_id:'spring', member_id:2, status:'active', entry_type:'new'},
    {term_id:'summer', member_id:1, status:'active', entry_type:'new'},
    {term_id:'summer', member_id:3, status:'paused', entry_type:'new'},
    {term_id:'fall', member_id:4, status:'paused', entry_type:'new'},
  ],
};
const before = JSON.stringify(data);
const draft = new TermRosterDraft(data);
assert.equal(draft.suggestedType(1), 'continuing');
assert.equal(draft.suggestedType(2), 'returning');
assert.equal(draft.suggestedType(4), 'new');
assert.equal(draft.dirty, false);
assert.equal(draft.carry('summer'), 1);
assert.equal(draft.carry('summer'), 0);
assert.equal(draft.entries.get(4).status, 'paused');
assert.equal(draft.entries.has(3), false);
assert.equal(draft.dirty, true);
draft.setStatus(1, 'left');
assert.equal(draft.carry('summer'), 0);
assert.equal(draft.entries.get(1).status, 'left');
assert.throws(() => draft.carry('winter'));
assert.throws(() => draft.carry('missing'));
assert.equal(JSON.stringify(data), before, 'past semester data must not be mutated');
console.log('PASS: carry-forward, new/returning classification, draft isolation, explicit pause/end preservation');
