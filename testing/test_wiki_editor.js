const test = require('node:test');
const assert = require('node:assert/strict');
const {resizeTableEdge} = require('../static/wiki_editor.js');

const snapped = (res, box) => res.tablePct / 100 * box;

test('dragging the right edge only changes the last column', () => {
    const colPx = [200, 150, 250];
    for (const dx of [-120, -30, 0, 60, 400]) {
        const res = resizeTableEdge(colPx, 1000, dx);
        const total = snapped(res, 1000);
        for (let i = 0; i < colPx.length - 1; i++) {
            assert.ok(Math.abs(total * res.widths[i] / 100 - colPx[i]) < 0.6, `col ${i} moved at dx=${dx}`);
        }
        assert.ok(Math.abs(res.widths.reduce((a, b) => a + b, 0) - 100) < 0.011);
    }
    const out = resizeTableEdge(colPx, 1000, 100);
    assert.equal(out.tablePct, 70);
    assert.ok(Math.abs(snapped(out, 1000) * out.widths[2] / 100 - 350) < 0.6);
});

test('respects right bound, minimum last column and table minimum', () => {
    const grow = resizeTableEdge([300, 300, 100], 1000, 5000);
    assert.equal(grow.tablePct, 100);
    assert.ok(grow.widths[2] * 10 >= 99 && grow.widths[2] * 10 <= 401);
    const shrink = resizeTableEdge([300, 300, 300], 1000, -5000);
    assert.ok(snapped(shrink, 1000) * shrink.widths[2] / 100 >= 59);
    assert.ok(shrink.widths[2] >= 5);
    assert.ok(Math.abs(snapped(shrink, 1000) * shrink.widths[0] / 100 - 300) < 0.6);
    assert.ok(resizeTableEdge([100, 100], 1000, -5000).tablePct >= 25);
});

test('handles one-column and invalid input', () => {
    assert.deepEqual(resizeTableEdge([400], 1000, 100), {tablePct: 50, widths: [100]});
    assert.equal(resizeTableEdge([], 1000, 10), null);
    assert.equal(resizeTableEdge([100], 0, 10), null);
});

const {unlistListItem} = require('../static/wiki_editor.js');
const visual = require('../static/wiki_namu_visual.js');
const items = (...texts) => texts.map(text => ({indent: 1, ordered: true, marker: '1.', text}));

test('unlistListItem turns a single item into a paragraph', () => {
    const blocks = [{type: 'paragraph', lines: ['앞']}, {type: 'list', items: items('내용')}];
    assert.deepEqual(unlistListItem(blocks, 1, 0, '내용'), {focusIndex: 1});
    assert.deepEqual(blocks, [{type: 'paragraph', lines: ['앞']}, {type: 'paragraph', lines: ['내용']}]);
});

test('unlistListItem on the first item keeps the rest as a list', () => {
    const blocks = [{type: 'list', items: items('첫째', '둘째')}];
    assert.deepEqual(unlistListItem(blocks, 0, 0, '첫째'), {focusIndex: 0});
    assert.deepEqual(blocks, [{type: 'paragraph', lines: ['첫째']}, {type: 'list', items: items('둘째')}]);
});

test('unlistListItem splits a middle item into list + paragraph + list', () => {
    const blocks = [{type: 'list', items: items('첫째', '둘째', '셋째')}];
    assert.deepEqual(unlistListItem(blocks, 0, 1, '둘째'), {focusIndex: 1});
    assert.deepEqual(blocks.map(b => b.type), ['list', 'paragraph', 'list']);
    assert.equal(visual.serializeBlocks(blocks), ' 1. 첫째\n\n둘째\n\n 1. 셋째');
});

test('unlistListItem on the last item', () => {
    const blocks = [{type: 'list', items: items('첫째', '둘째')}];
    assert.deepEqual(unlistListItem(blocks, 0, 1, '둘째'), {focusIndex: 1});
    assert.deepEqual(blocks, [{type: 'list', items: items('첫째')}, {type: 'paragraph', lines: ['둘째']}]);
});

test('unlistListItem preserves [br] and inline markup', () => {
    const content = "'''굵게'''[br][[링크]]";
    const blocks = [{type: 'list', items: items(content)}];
    unlistListItem(blocks, 0, 0, content);
    assert.deepEqual(blocks, [{type: 'paragraph', lines: [content]}]);
    assert.equal(visual.serializeBlocks(blocks), content);
});
