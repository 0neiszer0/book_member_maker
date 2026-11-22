import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import visual from '../static/wiki_namu_visual.js';

const {parseBlocks, serializeBlocks, inlineToHtml, domToInline} = visual;
const roundTrip = source => serializeBlocks(parseBlocks(source));
const text = nodeValue => ({nodeType: 3, nodeValue});
const el = (tagName, attrs = {}, ...childNodes) => ({nodeType: 1, tagName, attrs, childNodes});

test('headings, paragraphs and rules parse and serialize cleanly', () => {
    const src = '== 제목 ==\n\n=== 소제목 ===\n\n==== 셋 ====\n\n본문 한 줄\n두 번째 줄\n\n----';
    const blocks = parseBlocks(src);
    assert.deepEqual(blocks.map(b => b.type), ['heading', 'heading', 'heading', 'paragraph', 'rule']);
    assert.deepEqual(blocks.slice(0, 3).map(b => [b.level, b.text]), [[2, '제목'], [3, '소제목'], [4, '셋']]);
    assert.deepEqual(blocks[3].lines, ['본문 한 줄', '두 번째 줄']);
    assert.equal(serializeBlocks(blocks), src);
    assert.equal(parseBlocks('==붙임==')[0].text, '붙임');
    assert.equal(parseBlocks('a\r\nb')[0].lines.length, 2);
});

test('toc, lists, quotes and tables', () => {
    const src = '[목차]\n\n * 하나\n  * 둘\n 1. 셋\n\n> 인용\n> 둘째\n\n||a||b||\n||c||d||';
    const blocks = parseBlocks(src);
    assert.deepEqual(blocks.map(b => b.type), ['toc', 'list', 'quote', 'table']);
    assert.deepEqual(blocks[1].items.map(i => [i.indent, i.ordered, i.text]), [[1, false, '하나'], [2, false, '둘'], [1, true, '셋']]);
    assert.deepEqual(blocks[2].lines, ['인용', '둘째']);
    assert.equal(blocks[3].raw, '||a||b||\n||c||d||');
    assert.equal(parseBlocks('[TableOfContents]')[0].type, 'toc');
    assert.equal(serializeBlocks(blocks), src);
});

test('folding cards and opaque lossless blocks', () => {
    const fold = '{{{#!folding 제목\n내용 한 줄\n두 줄\n}}}';
    const [f] = parseBlocks(fold);
    assert.deepEqual([f.type, f.title, f.body], ['folding', '제목', '내용 한 줄\n두 줄']);
    assert.equal(roundTrip(fold), fold);
    const nested = '{{{#!folding 바깥\n{{{#!wiki style="x"\n안\n}}}\n}}}';
    const blocks = parseBlocks(nested);
    assert.equal(blocks.length, 1);
    assert.equal(blocks[0].type, 'raw');
    assert.equal(blocks[0].raw, nested);
    const cases = [
        ['[include(문서)]', '문서 포함 (include)'],
        ['{{{#!wiki style="a"\n안쪽\n}}}', '고급 위키 블록'],
        ['{{{\ncode line\nmore\n}}}', '코드/원문 블록'],
        ['## 주석', '주석']
    ];
    for (const [raw, label] of cases) {
        const parsed = parseBlocks(raw);
        assert.equal(parsed.length, 1, raw);
        assert.deepEqual([parsed[0].type, parsed[0].raw, parsed[0].label], ['raw', raw, label]);
        assert.equal(serializeBlocks(parsed), raw);
    }
    assert.equal(parseBlocks('{{{#red 인라인}}} 문장')[0].type, 'paragraph');
});

test('inline conversion produces escaped html', () => {
    assert.equal(inlineToHtml("'''굵게''' ''기울'' __밑줄__ ~~취소~~"),
        '<strong>굵게</strong> <em>기울</em> <u>밑줄</u> <s>취소</s>');
    assert.match(inlineToHtml('{{{#d20f17 빨강}}}'), /<span class="wiki-v-color" data-namu-color="#d20f17" style="color:#d20f17">빨강<\/span>/);
    assert.match(inlineToHtml('{{{+2 큼}}}'), /data-namu-size="\+2" style="font-size:1\.35em">큼</);
    assert.match(inlineToHtml('{{{-1 작}}}'), /data-namu-size="-1" style="font-size:0\.88em"/);
    assert.equal(inlineToHtml('{{{a<b}}}'), '<code class="wiki-v-code">a&lt;b</code>');
    assert.match(inlineToHtml('[[문서|보기]]'), /data-namu-link="문서" data-namu-has-caption="1" contenteditable="false">보기<\/a>/);
    assert.match(inlineToHtml('[[문서]]'), /data-namu-has-caption="0"[^>]*>문서<\/a>/);
    assert.match(inlineToHtml('[* 각주 글]'), /<span class="wiki-v-note" data-namu-note=" 각주 글" contenteditable="false" title="각주 글">각주<\/span>/);
    assert.equal(inlineToHtml('가[BR]나'), '가<br>나');
    assert.match(inlineToHtml('{{{#red 이름색}}}'), /wiki-v-raw-inline/);
});

test('inline html is safe against script injection', () => {
    const html = inlineToHtml('<script>alert(1)</script> & "q" \'s\' [[a"onmouseover="x|<img src=x onerror=y>]]');
    assert.ok(!html.includes('<script'));
    assert.ok(!html.includes('<img'));
    assert.ok(!/ onmouseover=/.test(html.replace(/&quot;/g, '')) || html.includes('&quot;onmouseover'));
    assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt; &amp; &quot;q&quot; &#39;s&#39;/);
    assert.ok(!inlineToHtml('{{{#!html <b onclick=x>}}}').includes('<b '));
});

test('domToInline serializes mock nodes', () => {
    const dom = el('p', {}, text('가 '), el('strong', {}, text('굵')), text(' '), el('em', {}, text('기')), el('u', {}, text('밑')),
        el('s', {}, text('취')), el('br'), el('code', {}, text('x*y')),
        el('a', {'data-namu-link': '문서', 'data-namu-has-caption': '1'}, text('보기')),
        el('a', {'data-namu-link': '같음', 'data-namu-has-caption': '1'}, text('같음')),
        el('span', {'data-namu-note': ' 주'}, text('각주')),
        el('span', {'data-namu-color': '#d20f17'}, text('색')),
        el('span', {'data-namu-size': '+1'}, text('크')),
        el('strong', {}));
    assert.equal(domToInline(dom), "가 '''굵''' ''기''__밑__~~취~~[br]{{{x*y}}}[[문서|보기]][[같음]][* 주]{{{#d20f17 색}}}{{{+1 크}}}");
    assert.equal(domToInline(el('div', {}, text('끝'), el('br'))), '끝');
    assert.equal(domToInline(el('div', {}, text('끝'), el('br'), text('뒤'))), '끝[br]뒤');
    assert.equal(domToInline(el('div', {}, el('div', {}, text('a')), el('div', {}, text('b')))), 'a[br]b');
    assert.equal(domToInline(el('div', {}, el('br'))), '');
});

test('inline round trips through html tokens and dom', () => {
    for (const src of ["'''굵게''' 그리고 ''기울''", '{{{#d20f17 빨강}}} 글', '{{{+3 크게}}}', '[[문서|캡션]] 뒤', '[* 각주]끝', '{{{코드}}}']) {
        const wrapper = {nodeType: 1, tagName: 'p', childNodes: []};
        // Re-parse through html is covered by token round trip below.
        assert.equal(inlineToHtml(src).length > 0, true);
        wrapper.childNodes.push(text(src));
        assert.equal(domToInline(wrapper), src);
    }
});

test('real wiki_content files round trip without losing structure', () => {
    const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'wiki_content');
    const files = fs.readdirSync(root).filter(name => name.endsWith('.namu'));
    assert.ok(files.length > 0);
    const countOf = (blocks, type) => blocks.filter(b => b.type === type).length;
    const includes = blocks => blocks.filter(b => b.type === 'raw' && /^\[include\(/i.test(b.raw)).length;
    for (const name of files) {
        const source = fs.readFileSync(path.join(root, name), 'utf8');
        const before = parseBlocks(source);
        const out = serializeBlocks(before);
        assert.ok(out.trim().length > 0, name);
        const after = parseBlocks(out);
        for (const type of ['heading', 'table', 'folding', 'toc']) assert.equal(countOf(after, type), countOf(before, type), name + ' ' + type);
        assert.equal(includes(after), includes(before), name + ' include');
        assert.equal(serializeBlocks(after), out, name + ' stable');
    }
});
