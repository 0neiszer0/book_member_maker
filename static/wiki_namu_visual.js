/* Pure NamuMark <-> visual block / inline conversion. No DOM access except the
 * nodes handed to domToInline, so it runs unchanged in browsers and Node tests.
 * Anything not understood is kept verbatim in opaque raw blocks / raw inline
 * spans so that visual editing never loses source text. */
(function () {
'use strict';

const HEADING = /^(={2,6})\s+(.+?)\s+\1\s*$/;
const HEADING_TIGHT = /^(={2,6})(.+?)\1\s*$/;
const TOC = /^\[(?:목차|tableofcontents)\]\s*$/i;
const RULE = /^-{4,9}\s*$/;
const LIST = /^(\s+)(\*|\d+\.|[aAiI]\.)\s+(.*)$/;
const LIST_BARE = /^(\*)\s+(.*)$/;
const QUOTE = /^>\s?(.*)$/;
const INCLUDE = /^\[include\(.*\)\]\s*$/i;
const FOLDING = /^\{\{\{#!folding(?:[ \t]+(.*))?$/;
const COMMENT = /^##/;

const count = (text, token) => text.split(token).length - 1;
const braceDelta = line => count(line, '{{{') - count(line, '}}}');

function matchHeading(line) {
    const m = HEADING.exec(line) || HEADING_TIGHT.exec(line);
    if (!m || !/[^=\s]/.test(m[2])) return null;
    return {type: 'heading', level: m[1].length, text: m[2].trim()};
}

function listItem(line) {
    let m = LIST.exec(line);
    if (m) return {indent: Math.max(1, m[1].length), ordered: m[2] !== '*', marker: m[2], text: m[3]};
    m = LIST_BARE.exec(line);
    if (m) return {indent: 1, ordered: false, marker: '*', text: m[2]};
    return null;
}

function isBlockStart(line) {
    return !line.trim() || matchHeading(line) || TOC.test(line) || RULE.test(line) || listItem(line) ||
        QUOTE.test(line) || line.startsWith('||') || INCLUDE.test(line) || line.startsWith('{{{#!') ||
        COMMENT.test(line) || (line.startsWith('{{{') && braceDelta(line) > 0);
}

// Returns the index of the line that closes the brace group opened on `start`, or -1.
function closeBrace(lines, start) {
    let depth = 0;
    for (let i = start; i < lines.length; i++) {
        depth += braceDelta(lines[i]);
        if (depth <= 0) return i;
    }
    return -1;
}

function parseBlocks(source) {
    const lines = String(source == null ? '' : source).replace(/\r\n?/g, '\n').split('\n');
    const blocks = [];
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        if (!line.trim()) { i++; continue; }
        const heading = matchHeading(line);
        if (heading) { blocks.push(heading); i++; continue; }
        if (TOC.test(line)) { blocks.push({type: 'toc', raw: line.trim()}); i++; continue; }
        if (RULE.test(line)) { blocks.push({type: 'rule'}); i++; continue; }
        if (INCLUDE.test(line)) { blocks.push({type: 'raw', raw: line, label: '문서 포함 (include)'}); i++; continue; }
        if (COMMENT.test(line)) {
            let j = i;
            while (j + 1 < lines.length && COMMENT.test(lines[j + 1])) j++;
            blocks.push({type: 'raw', raw: lines.slice(i, j + 1).join('\n'), label: '주석'});
            i = j + 1;
            continue;
        }
        if (listItem(line)) {
            const items = [];
            while (i < lines.length && listItem(lines[i])) items.push(listItem(lines[i++]));
            blocks.push({type: 'list', items});
            continue;
        }
        if (QUOTE.test(line)) {
            const quote = [];
            while (i < lines.length && QUOTE.test(lines[i])) quote.push(QUOTE.exec(lines[i++])[1]);
            blocks.push({type: 'quote', lines: quote});
            continue;
        }
        if (line.startsWith('||')) {
            const start = i;
            let depth = 0;
            while (i < lines.length && (depth > 0 || lines[i].startsWith('||'))) depth = Math.max(0, depth + braceDelta(lines[i++]));
            blocks.push({type: 'table', raw: lines.slice(start, i).join('\n')});
            continue;
        }
        const folding = FOLDING.exec(line);
        if (folding && braceDelta(line) === 1) {
            const end = closeBrace(lines, i);
            if (end > i && lines[end].trim() === '}}}') {
                const body = lines.slice(i + 1, end);
                const simple = body.every(l => !l.includes('{{{#!') && braceDelta(l) === 0);
                if (simple) {
                    blocks.push({type: 'folding', title: (folding[1] || '').trim(), body: body.join('\n')});
                    i = end + 1;
                    continue;
                }
            }
        }
        if (line.startsWith('{{{#!') || (line.startsWith('{{{') && braceDelta(line) > 0)) {
            const end = closeBrace(lines, i);
            const last = end < 0 ? lines.length - 1 : end;
            blocks.push({type: 'raw', raw: lines.slice(i, last + 1).join('\n'),
                label: line.startsWith('{{{#!') ? '고급 위키 블록' : '코드/원문 블록'});
            i = last + 1;
            continue;
        }
        const paragraph = [];
        while (i < lines.length && (!paragraph.length || !isBlockStart(lines[i]))) paragraph.push(lines[i++]);
        blocks.push({type: 'paragraph', lines: paragraph});
    }
    return blocks;
}

function serializeBlock(b) {
    switch (b.type) {
    case 'heading': return '='.repeat(b.level) + ' ' + String(b.text).trim() + ' ' + '='.repeat(b.level);
    case 'toc': return b.raw || '[목차]';
    case 'rule': return '----';
    case 'list': return b.items.map(item => ' '.repeat(Math.max(1, item.indent)) + (item.ordered ? '1.' : '*') + ' ' + item.text).join('\n');
    case 'quote': return b.lines.map(line => '> ' + line).join('\n');
    case 'table': return b.raw;
    case 'folding': return '{{{#!folding ' + (b.title || '펼쳐 보기') + '\n' + (b.body || '') + '\n}}}';
    case 'raw': return b.raw;
    default: return (b.lines || []).join('\n');
    }
}

function serializeBlocks(blocks) {
    return blocks.map(serializeBlock).join('\n\n');
}

// ---- inline -----------------------------------------------------------------
const escapeHtml = text => String(text).replace(/[&<>"']/g, ch =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[ch]);
const SIZES = {'+1': 1.18, '+2': 1.35, '+3': 1.55, '+4': 1.8, '+5': 2.1, '-1': 0.88, '-2': 0.8, '-3': 0.72, '-4': 0.65, '-5': 0.58};

function matchBrace(text, start) {
    let depth = 0;
    for (let i = start; i < text.length; i++) {
        if (text.startsWith('{{{', i)) { depth++; i += 2; }
        else if (text.startsWith('}}}', i)) { depth--; i += 2; if (!depth) return i - 2; }
    }
    return -1;
}

function matchPair(text, start, open, close) {
    let depth = 0;
    for (let i = start; i < text.length; i++) {
        if (text.startsWith(open, i)) { depth++; i += open.length - 1; }
        else if (text.startsWith(close, i)) { depth--; if (!depth) return i; i += close.length - 1; }
    }
    return -1;
}

function inlineToTokens(text) {
    text = String(text == null ? '' : text);
    const out = [];
    let buf = '';
    const flush = () => { if (buf) { out.push({t: 'text', v: buf}); buf = ''; } };
    const wrapper = (marker, kind, i) => {
        const end = text.indexOf(marker, i + marker.length);
        if (end <= i + marker.length) return -1;
        flush();
        out.push({t: kind, c: inlineToTokens(text.slice(i + marker.length, end))});
        return end + marker.length;
    };
    let i = 0;
    while (i < text.length) {
        let next = -1;
        if (text.startsWith("'''", i)) next = wrapper("'''", 'strong', i);
        else if (text.startsWith("''", i)) next = wrapper("''", 'em', i);
        else if (text.startsWith('__', i)) next = wrapper('__', 'u', i);
        else if (text.startsWith('~~', i)) next = wrapper('~~', 's', i);
        else if (text.startsWith('{{{', i)) {
            const end = matchBrace(text, i);
            if (end > 0) {
                const inner = text.slice(i + 3, end);
                const color = /^(#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3}))[ \t]+([\s\S]*)$/.exec(inner);
                const size = /^([+-][1-5])[ \t]+([\s\S]*)$/.exec(inner);
                flush();
                if (color) out.push({t: 'color', color: color[1], c: inlineToTokens(color[2])});
                else if (size) out.push({t: 'size', size: size[1], c: inlineToTokens(size[2])});
                else if (/^[#+\-!]/.test(inner)) out.push({t: 'raw', raw: text.slice(i, end + 3)});
                else out.push({t: 'code', v: inner});
                next = end + 3;
            }
        } else if (text.startsWith('[[', i)) {
            const end = matchPair(text, i, '[[', ']]');
            if (end > 0) {
                const inner = text.slice(i + 2, end);
                const bar = inner.indexOf('|');
                flush();
                out.push({t: 'link', target: bar < 0 ? inner : inner.slice(0, bar),
                    caption: bar < 0 ? inner : inner.slice(bar + 1), hasCaption: bar >= 0});
                next = end + 2;
            }
        } else if (text.startsWith('[*', i)) {
            const end = matchPair(text, i, '[', ']');
            if (end > 0) {
                flush();
                out.push({t: 'note', raw: text.slice(i + 2, end)});
                next = end + 1;
            }
        } else if (/^\[br\]/i.test(text.slice(i, i + 4))) {
            flush();
            out.push({t: 'br'});
            next = i + 4;
        } else if (text[i] === '\n') {
            flush();
            out.push({t: 'br'});
            next = i + 1;
        }
        if (next < 0) buf += text[i++];
        else i = next;
    }
    flush();
    return out;
}

function tokensToHtml(tokens) {
    return tokens.map(tok => {
        const kids = () => tokensToHtml(tok.c || []);
        switch (tok.t) {
        case 'text': return escapeHtml(tok.v);
        case 'strong': return '<strong>' + kids() + '</strong>';
        case 'em': return '<em>' + kids() + '</em>';
        case 'u': return '<u>' + kids() + '</u>';
        case 's': return '<s>' + kids() + '</s>';
        case 'color': return '<span class="wiki-v-color" data-namu-color="' + escapeHtml(tok.color) + '" style="color:' + escapeHtml(tok.color) + '">' + kids() + '</span>';
        case 'size': return '<span class="wiki-v-size" data-namu-size="' + tok.size + '" style="font-size:' + SIZES[tok.size] + 'em">' + kids() + '</span>';
        case 'code': return '<code class="wiki-v-code">' + escapeHtml(tok.v) + '</code>';
        case 'link': return '<a class="wiki-v-link" href="#" data-namu-link="' + escapeHtml(tok.target) +
            '" data-namu-has-caption="' + (tok.hasCaption ? '1' : '0') + '" contenteditable="false">' +
            escapeHtml(tok.hasCaption ? tok.caption : tok.target) + '</a>';
        case 'note': return '<span class="wiki-v-note" data-namu-note="' + escapeHtml(tok.raw) +
            '" contenteditable="false" title="' + escapeHtml(tok.raw.trim()) + '">각주</span>';
        case 'raw': return '<span class="wiki-v-raw-inline" data-namu-raw="' + escapeHtml(tok.raw) +
            '" contenteditable="false">' + escapeHtml(tok.raw) + '</span>';
        case 'br': return '<br>';
        default: return '';
        }
    }).join('');
}

const inlineToHtml = text => tokensToHtml(inlineToTokens(text));

// ---- DOM -> NamuMark ----------------------------------------------------------
const tagOf = node => String(node.tagName || node.nodeName || '').toLowerCase();
const isText = node => node.nodeType === 3 || (node.nodeType === undefined && !tagOf(node) && typeof node.nodeValue === 'string');
function attrOf(node, name) {
    if (typeof node.getAttribute === 'function') return node.getAttribute(name);
    const bag = node.attrs || node.attributes;
    if (bag && typeof bag === 'object' && name in bag) return bag[name];
    const camel = name.replace(/^data-/, '').replace(/-(\w)/g, (m, ch) => ch.toUpperCase());
    return node.dataset && camel in node.dataset ? node.dataset[camel] : null;
}
const kidsOf = node => Array.from(node.childNodes || node.children || []);
function textOf(node) {
    if (typeof node.textContent === 'string') return node.textContent;
    return isText(node) ? node.nodeValue : kidsOf(node).map(textOf).join('');
}

function domToInline(root) {
    // A browser-inserted sentinel <br> at the very end of an element is not content.
    let last = root;
    while (kidsOf(last).length) { const kids = kidsOf(last); last = kids[kids.length - 1]; }
    const sentinel = last !== root && tagOf(last) === 'br' ? last : null;
    const walk = node => {
        if (isText(node)) return String(node.nodeValue).replace(/ /g, ' ');
        const tag = tagOf(node);
        if (tag === 'br') return node === sentinel ? '' : '[br]';
        const inner = () => kidsOf(node).map(walk).join('');
        const wrap = mark => { const body = inner(); return body ? mark + body + mark : ''; };
        if (tag === 'strong' || tag === 'b') return wrap("'''");
        if (tag === 'em' || tag === 'i') return wrap("''");
        if (tag === 'u') return wrap('__');
        if (tag === 's' || tag === 'del' || tag === 'strike') return wrap('~~');
        if (tag === 'code') return '{{{' + textOf(node) + '}}}';
        const raw = attrOf(node, 'data-namu-raw');
        if (raw != null) return raw;
        const link = attrOf(node, 'data-namu-link');
        if (link != null) {
            const caption = textOf(node);
            return attrOf(node, 'data-namu-has-caption') === '1' && caption !== link ? '[[' + link + '|' + caption + ']]' : '[[' + link + ']]';
        }
        const note = attrOf(node, 'data-namu-note');
        if (note != null) return '[*' + note + ']';
        const color = attrOf(node, 'data-namu-color');
        if (color) { const body = inner(); return body ? '{{{' + color + ' ' + body + '}}}' : ''; }
        const size = attrOf(node, 'data-namu-size');
        if (size) { const body = inner(); return body ? '{{{' + size + ' ' + body + '}}}' : ''; }
        if (tag === 'div' || tag === 'p') return '\u0000' + inner();
        return inner();
    };
    // Block wrappers add a break only when something precedes them.
    const text = kidsOf(root).map(walk).join('');
    return text.replace(/(^|[^\u0000])\u0000/g, (m, pre) => pre + (pre ? '[br]' : '')).replace(/\u0000/g, '');
}

const api = {parseBlocks, serializeBlocks, serializeBlock, inlineToTokens, inlineToHtml, domToInline, escapeHtml};
if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (typeof window !== 'undefined') window.WikiNamuVisual = api;
})();
