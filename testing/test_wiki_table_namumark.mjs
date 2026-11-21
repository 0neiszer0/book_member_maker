import test from 'node:test';
import assert from 'node:assert/strict';
import table from '../static/wiki_editor.js';

test('round trip with spans, table and cell directives, links and breaks', () => {
    const src = "||<tablewidth=100%><tablealign=center><tablebgcolor=white><width=35%><(><bgcolor=#f5f5f5> '''항목''' ||<-2><:>[[안내|읽기]][br]다음||\n" +
                '||<|2><)>오른쪽||가||나||\n||다||라||';
    const parsed = table.parseTable(src);
    assert.deepEqual(parsed.widths,[35,32.5,32.5]);
    assert.equal(parsed.grid[0][1],parsed.grid[0][2]);
    assert.equal(parsed.grid[1][0],parsed.grid[2][0]);
    assert.equal(table.serializeTable(parsed),src);
});

test('resizing preserves neighbor total and respects minimum at both extremes', () => {
    assert.deepEqual(table.resizeWidths([35,35,30],0,1000),[62,8,30]);
    assert.deepEqual(table.resizeWidths([35,35,30],1,-1000),[35,8,57]);
    for (const n of [1,3,6,12]) {
        const widths = table.equalWidths(n);
        assert.ok(Math.abs(widths.reduce((a,b) => a+b,0)-100)<1e-9);
        assert.ok(Math.max(...widths)-Math.min(...widths)<0.1);
    }
    const model = table.parseTable('||<width=30%>a||b||');
    model.widths = table.resizeWidths(model.widths,0,5);
    model.widthsChanged = true;
    assert.equal(table.serializeTable(model),'||<width=35%>a||<width=65%>b||');
});

test('cursor detection returns exact block and leaves neighboring prose intact', () => {
    const block = '||a||b||\n||c||d||';
    const text = '머리말\n\n'+block+'\n\n[목차]\n||다음||';
    const start = text.indexOf(block);
    for (const pos of [start,start+2,start+8,start+12,start+block.length]) {
        assert.deepEqual(table.tableAt(text,pos),{start,end:start+block.length,source:block});
    }
    assert.equal(table.tableAt(text,text.indexOf('[목차]')),null);
    assert.equal(table.tableAt(text,text.length).source,'||다음||');
});

test('complex structures refuse visual editing and ambiguous edits never serialize', () => {
    for (const src of ['||{{{#!wiki ||nested||}}}||', '||a||||b||', '||a||b||\n||c||', '||<|99999>bad||',
                       '||[[link||label]]||']) assert.throws(() => table.parseTable(src));
    const model = table.parseTable('||a||');
    model.grid[0][0].text = 'a||b';
    assert.throws(() => table.serializeTable(model));
    model.grid[0][0].text = '첫줄\n둘째';
    assert.equal(table.serializeTable(model),'||첫줄[br]둘째||');
});

