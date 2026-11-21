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
    for (const src of ['||{{{#!wiki ||nested||}}}||', '||a||b||\n||c||', '||<|99999>bad||',
                       '||[[link||label]]||']) assert.throws(() => table.parseTable(src));
    const model = table.parseTable('||a||');
    model.grid[0][0].text = 'a||b';
    assert.throws(() => table.serializeTable(model));
    model.grid[0][0].text = '첫줄\n둘째';
    assert.equal(table.serializeTable(model),'||첫줄[br]둘째||');
});

test('findAllTables returns every table with exact offsets in document order', () => {
    const t1 = '||a||b||\n||c||d||', t2 = '||<tablewidth=50%>x||y||   ', t3 = '||z||';
    const text = '== 하나 ==\n' + t1 + '\n\n본문\n' + t2 + '\n\n{{{\n||코드||\n}}}\n' + t3;
    const found = table.findAllTables(text);
    assert.equal(found.length, 3);
    [t1, t2, t3].forEach((src, i) => {
        assert.equal(found[i].index, i);
        assert.equal(found[i].source, src);
        assert.equal(text.slice(found[i].start, found[i].end), src);
    });
    assert.deepEqual(table.findAllTables('prose only'), []);
});

test('real openNamu tables: trailing spaces, leading spaces before tags, || shorthand colspan', () => {
    let model = table.parseTable('||<tablewidth=100%> <width=30%> 내용 ||b||   \n|| c || d ||  ');
    assert.deepEqual(model.widths, [30, 70]);
    assert.deepEqual(model.tableTags, ['tablewidth=100%']);
    assert.equal(model.grid[0][0].text, ' 내용 ');
    model = table.parseTable('||||제목||\n||a||b||');
    assert.equal(model.grid[0][0], model.grid[0][1]);
    assert.equal(table.serializeTable(model), '||<-2>제목||\n||a||b||');
    model = table.parseTable('||||||긴 제목||\n||a||b||c||');
    assert.equal(model.grid[0].length, 3);
    for (const src of ['||a||||', '||||<-2>a||b||', '||a||b||\n||c||d||e||']) assert.throws(() => table.parseTable(src), src);
});

test('setTableWidth inserts, replaces, clamps and round-trips', () => {
    const model = table.parseTable('||a||b||');
    assert.equal(table.setTableWidth(model, 75), 75);
    assert.equal(table.serializeTable(model), '||<tablewidth=75%>a||b||');
    assert.equal(table.setTableWidth(model, 78.4), 78);
    assert.deepEqual(model.tableTags, ['tablewidth=78%']);
    assert.equal(table.setTableWidth(model, 3), 25);
    assert.equal(table.setTableWidth(model, 900), 100);
    const again = table.parseTable(table.serializeTable(model));
    assert.deepEqual(again.tableTags, ['tablewidth=100%']);
    assert.equal(again.grid[0].length, 2);
});

test('matchTables binds only on identical shapes and skips included or unsupported tables', () => {
    const text = '||a||b||\n||c||d||\n\n||{{{#!wiki x}}}||\n\n||e||f||f||';
    const shapes = [{rows: 2, cols: 2}, {rows: 1, cols: 1}, {rows: 1, cols: 3}];
    const m = table.matchTables(text, shapes);
    assert.equal(m[0].index, 0);
    assert.equal(m[0].block.source, '||a||b||\n||c||d||');
    assert.equal(m[1], null);          // unsupported nested block
    assert.equal(m[2].index, 2);
    assert.equal(table.matchTables(text, [{rows: 3, cols: 2}, shapes[1], shapes[2]])[0], null);
    // [include] macro rendering an extra <table>: counts differ, nothing is bound.
    assert.deepEqual(table.matchTables(text, shapes.concat([{rows: 1, cols: 1}])), [null, null, null, null]);
});
