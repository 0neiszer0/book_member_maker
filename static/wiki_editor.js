/* The source textarea remains the document of record. Grid slots share a cell
 * object across its entire span, so row and column edits retain geometry. */
(() => {
'use strict';

const unsupported = '복잡한 표는 원문에서 편집해 주세요.';
const newCell = () => ({text: ' ', tags: []});
const matrix = (rows, cols) => Array.from({length: rows}, () => Array.from({length: cols}, newCell));
const percent = n => Math.round(n * 100) / 100;

function equalWidths(count) {
    const widths = Array(count).fill(percent(100 / count));
    widths[count - 1] = percent(100 - widths[0] * (count - 1));
    return widths;
}

function resizeWidths(initial, index, delta) {
    const widths = initial.slice();
    const pair = widths[index] + widths[index + 1];
    const min = Math.min(8, pair / 3);
    widths[index] = percent(Math.max(min, Math.min(pair - min, widths[index] + delta)));
    widths[index + 1] = percent(pair - widths[index]);
    return widths;
}

function tableAt(source, cursor) {
    let start = source.lastIndexOf('\n', cursor - 1) + 1;
    let end = source.indexOf('\n', cursor);
    if (end < 0) end = source.length;
    if (!source.startsWith('||', start)) return null;
    while (start > 0) {
        const previous = source.lastIndexOf('\n', start - 2) + 1;
        if (!source.startsWith('||', previous)) break;
        start = previous;
    }
    while (source.startsWith('||', end + 1)) {
        end = source.indexOf('\n', end + 1);
        if (end < 0) end = source.length;
    }
    return {start, end, source: source.slice(start, end)};
}

function tagValue(tags, key) {
    return tags.find(t => t.startsWith(key + '='))?.slice(key.length + 1) || '';
}

function setTag(tags, matches, value) {
    const index = tags.findIndex(matches);
    if (index < 0) {
        if (value) tags.push(value);
    } else if (value) tags[index] = value;
    else tags.splice(index, 1);
}

function spanOf(grid, r, c) {
    const cell = grid[r][c];
    let w = 1, h = 1;
    while (grid[r][c + w] === cell) w++;
    while (grid[r + h]?.[c] === cell) h++;
    return {w, h};
}

function parseTable(source) {
    const lines = source.split(/\r?\n/).map(line => line.trimEnd());
    const grid = lines.map(() => []);
    const tableTags = [];
    // Avoid interpreting separators in escaped text or multiline constructs.
    // Such tables remain editable in their original source.
    if (lines.length > 200 || /\\\||\{\{\{#!|^\|[^|]/m.test(source)) throw Error(unsupported);
    for (const [r, line] of lines.entries()) {
        if (!line.startsWith('||') || !line.endsWith('||') || line.length < 4) throw Error(unsupported);
        let c = 0, pending = 0;
        for (let raw of line.slice(2, -2).split('||')) {
            // An empty piece is NamuMark shorthand: ||||x|| spans two columns.
            if (raw === '') { pending++; continue; }
            while (grid[r][c]) c++;
            const tags = [];
            let w = 1 + pending, h = 1, explicit = false;
            pending = 0;
            while (/^\s*</.test(raw)) {
                const match = /^\s*<([^<>]+)>/.exec(raw);
                if (!match) break;
                const tag = match[1];
                if (/^table/.test(tag)) {
                    if (r || c) throw Error(unsupported);
                    tableTags.push(tag);
                } else {
                    tags.push(tag);
                    if (/^[-|]/.test(tag)) {
                        if (!/^[-|][1-9]\d*$/.test(tag)) throw Error(unsupported);
                        if (tag[0] === '-') {
                            if (w > 1) throw Error(unsupported);
                            w = Number(tag.slice(1));
                            explicit = true;
                        } else h = Number(tag.slice(1));
                    }
                }
                raw = raw.slice(match[0].length);
            }
            if (explicit && w < 1) throw Error(unsupported);
            if (c + w > 64 || r + h > lines.length ||
                (raw.match(/\{\{\{/g) || []).length !== (raw.match(/\}\}\}/g) || []).length ||
                (raw.match(/\[\[/g) || []).length !== (raw.match(/\]\]/g) || []).length) throw Error(unsupported);
            const cell = {text: raw, tags};
            for (let y = r; y < r + h; y++) {
                for (let x = c; x < c + w; x++) {
                    if (grid[y][x]) throw Error(unsupported);
                    grid[y][x] = cell;
                }
            }
            c += w;
        }
        if (pending) throw Error(unsupported);
    }
    const count = grid[0].length;
    if (grid.some(row => row.length !== count || Array.from(row).includes(undefined))) throw Error(unsupported);
    return {grid, tableTags, widths: readWidths(grid), widthsChanged: false};
}

function readWidths(grid) {
    const widths = grid[0].map((cell, i) => {
        for (const row of grid) {
            if (row[i] === row[i-1] || row[i] === row[i+1]) continue;
            const raw = tagValue(row[i].tags, 'width');
            if (/^\d+(?:\.\d+)?%$/.test(raw) && parseFloat(raw) > 0) return parseFloat(raw);
        }
        return 0;
    });
    const total = widths.reduce((a,b) => a+b, 0);
    const missing = widths.filter(n => !n).length;
    if (!total || total > 100.05 || (missing && total >= 100)) return equalWidths(widths.length);
    const filled = widths.map(n => percent(n || (100 - total) / missing));
    if (!missing && Math.abs(100-total) > 0.05) return equalWidths(widths.length);
    filled[filled.length-1] = percent(100 - filled.slice(0,-1).reduce((a,b) => a+b, 0));
    return filled;
}

function serializeTable(model) {
    const {grid, widths, tableTags} = model;
    return grid.map((row, r) => {
        let line = '||';
        row.forEach((cell, c) => {
            if (cell === row[c-1] || cell === grid[r-1]?.[c]) return;
            const {w,h} = spanOf(grid, r, c);
            const tags = cell.tags.slice();
            setTag(tags, t => /^-\d+$/.test(t), w > 1 ? '-' + w : '');
            setTag(tags, t => /^\|\d+$/.test(t), h > 1 ? '|' + h : '');
            if (model.widthsChanged) {
                const width = percent(widths.slice(c,c+w).reduce((a,b) => a+b, 0));
                setTag(tags, t => t.startsWith('width='), 'width=' + width + '%');
            }
            if (!r && !c) tags.unshift(...tableTags);
            const value = cell.text.replace(/\r?\n/g, '[br]');
            if (value.includes('||') || /^[|]|[|\\]$/.test(value)) throw Error('셀 가장자리의 | 또는 연속된 || 기호는 원문에서 편집해 주세요.');
            line += tags.map(t => '<' + t + '>').join('') + (value || ' ') + '||';
        });
        if (line === '||') throw Error('행마다 하나 이상의 독립된 셀이 필요합니다.');
        return line;
    }).join('\n');
}

// All table blocks in document order, i.e. the order openNamu renders <table>s.
function findAllTables(source) {
    const found = [];
    let pos = 0, depth = 0, current = null;
    while (pos <= source.length) {
        let end = source.indexOf('\n', pos);
        if (end < 0) end = source.length;
        const text = source.slice(pos, end);
        if (depth === 0 && text.startsWith('||')) {
            if (!current) current = {start: pos};
            current.end = end;
        } else {
            if (current) found.push(current);
            current = null;
            depth = Math.max(0, depth + (text.match(/\{\{\{/g) || []).length - (text.match(/\}\}\}/g) || []).length);
        }
        pos = end + 1;
    }
    if (current) found.push(current);
    return found.map((t, index) => ({index, start: t.start, end: t.end, source: source.slice(t.start, t.end)}));
}

function setTableWidth(model, widthPercent) {
    const width = Math.max(25, Math.min(100, Math.round(Number(widthPercent)) || 100));
    setTag(model.tableTags, t => t.startsWith('tablewidth='), 'tablewidth=' + width + '%');
    return width;
}

// Pair rendered <table> shapes [{rows, cols}] with parsed source tables. Any
// count mismatch (e.g. [include] macros) or shape mismatch yields null, never a guess.
function matchTables(source, shapes) {
    const blocks = findAllTables(source);
    if (blocks.length !== shapes.length) return shapes.map(() => null);
    return blocks.map((block, index) => {
        try {
            const model = parseTable(block.source);
            if (model.grid.length !== shapes[index].rows || model.grid[0].length !== shapes[index].cols) return null;
            return {index, block, model};
        } catch { return null; }
    });
}

if (typeof module !== 'undefined' && module.exports) module.exports = {parseTable, serializeTable, tableAt, equalWidths, resizeWidths, findAllTables, setTableWidth, matchTables};
if (typeof document === 'undefined') return;
const $ = selector => document.querySelector(selector);
const source = $('#wiki-content');
if (!source) return;
const ribbon = $('#wiki-ribbon');
const live = $('#wiki-live');
const gridDialog = $('#wiki-table');
const gridElement = $('#wiki-grid');
const picker = $('#wiki-picker');
const link = $('#wiki-link');
const commandButton = name => document.querySelector('[data-command="' + name + '"]');
const selection = () => [source.selectionStart, source.selectionEnd];
const selected = () => source.value.slice(...selection());
const undo = [], redo = [];
const visualApi = window.WikiNamuVisual;
const workspace = $('#wiki-workspace');
const visual = $('#wiki-visual');
const templateDialog = $('#wiki-template-dialog');
let mode = 'raw', visualDirty = false, visualEdit = null, userClosedLive = false;
let block, model, target, row = 0, col = 0;
let previewTimer, controller, previewVersion = 0;

function schedulePreview(delay = 450) {
    clearTimeout(previewTimer);
    controller?.abort();
    const version = ++previewVersion;
    if (live.hidden) return;
    live.querySelector('[role=status]').textContent = '미리보기 갱신 중…';
    previewTimer = setTimeout(async () => {
        controller = new AbortController();
        const data = new FormData();
        data.set('wiki_csrf', source.form.elements.wiki_csrf.value);
        data.set('content', source.value);
        try {
            const response = await fetch(source.form.dataset.previewUrl, {method:'POST', body:data, signal:controller.signal});
            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.ok) throw Error(result.error || '미리보기를 불러오지 못했습니다. 편집 화면을 새로 열어 주세요.');
            if (version !== previewVersion) return;
            live.querySelector('article').innerHTML = result.html;
            live.querySelector('[role=status]').textContent = '';
            try { decorateTables(); } catch { /* direct resizing is optional */ }
        } catch (error) {
            if (version === previewVersion) live.querySelector('[role=status]').textContent = error.message;
        }
    }, delay);
}

// ---- Direct resizing on rendered preview tables ------------------------------
let shells = [], observers = [];
const tip = live.querySelector('.wiki-live-tip');
const shapeOf = table => ({rows: table.rows.length,
    cols: [...(table.rows[0]?.cells || [])].reduce((n, cell) => n + cell.colSpan, 0)});

function badgeAt(text, x, y) {
    let badge = $('.wiki-resize-badge');
    if (!badge) {
        badge = document.createElement('div');
        badge.className = 'wiki-resize-badge';
        document.body.append(badge);
    }
    badge.textContent = text;
    badge.style.left = (x + 14) + 'px';
    badge.style.top = (y + 14) + 'px';
}
const clearBadge = () => $('.wiki-resize-badge')?.remove();

// Re-read the source block at commit time; refuse when the text moved on since rendering.
function freshBinding(binding) {
    const found = findAllTables(source.value)[binding.index];
    if (!found || found.source !== binding.source) {
        live.querySelector('[role=status]').textContent = '원문이 바뀌었습니다. 미리보기가 갱신된 뒤 다시 조절해 주세요.';
        schedulePreview(0);
        return null;
    }
    try { return {block: found, model: parseTable(found.source)}; } catch { return null; }
}

function commitTable(binding, fresh) {
    const result = serializeTable(fresh.model);
    replace(fresh.block.start, fresh.block.end, result, 0, 0, {focus: false});
    binding.source = result;
    binding.refresh?.(fresh.model);
}

function measuredWidths(ref, table) {
    const total = table.getBoundingClientRect().width || 1;
    const widths = [...ref.cells].map(cell => percent(cell.getBoundingClientRect().width * 100 / total));
    widths[widths.length - 1] = percent(100 - widths.slice(0, -1).reduce((a, b) => a + b, 0));
    return widths;
}

function paintLiveWidths(table, widths) {
    let group = table.querySelector('colgroup.wiki-live-cols');
    if (!group) {
        group = document.createElement('colgroup');
        group.className = 'wiki-live-cols';
        widths.forEach(() => group.append(document.createElement('col')));
        table.prepend(group);
    }
    table.style.tableLayout = 'fixed';
    widths.forEach((w, i) => group.children[i].style.width = w + '%');
}

function dragHandle(handle, start, move, end) {
    handle.addEventListener('pointerdown', event => {
        if (event.button) return;
        event.preventDefault();
        event.stopPropagation();
        const state = start(event);
        if (!state) return;
        handle.setPointerCapture(event.pointerId);
        handle.classList.add('dragging');
        const onMove = e => move(state, e);
        const finish = (e, commit) => {
            handle.removeEventListener('pointermove', onMove);
            handle.removeEventListener('pointerup', onUp);
            handle.removeEventListener('pointercancel', onCancel);
            handle.classList.remove('dragging');
            clearBadge();
            end(state, e, commit);
        };
        const onUp = e => finish(e, true), onCancel = e => finish(e, false);
        handle.addEventListener('pointermove', onMove);
        handle.addEventListener('pointerup', onUp);
        handle.addEventListener('pointercancel', onCancel);
    });
}

function decorateTables() {
    observers.forEach(o => o.disconnect());
    observers = [];
    shells = [];
    const tables = [...live.querySelector('article').querySelectorAll('table')];
    const matches = matchTables(source.value, tables.map(shapeOf));
    let bound = 0;
    tables.forEach((table, i) => {
        const match = matches[i];
        if (!match) return;
        bound++;
        const binding = {index: match.index, source: match.block.source};
        const shell = document.createElement('div');
        shell.className = 'wiki-table-shell';
        table.replaceWith(shell);
        shell.append(table);
        const columns = shapeOf(table).cols;
        const ref = [...table.rows].find(tr => tr.cells.length === columns &&
            [...tr.cells].every(cell => cell.colSpan === 1 && cell.rowSpan === 1));

        const bar = document.createElement('div');
        bar.className = 'wiki-table-bar';
        const label = document.createElement('span');
        const edit = document.createElement('button'), equal = document.createElement('button');
        edit.type = equal.type = 'button';
        edit.textContent = '표 편집';
        equal.textContent = '균등';
        equal.disabled = !ref;
        bar.append(label);
        const presets = [100, 85, 70].map(pct => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = pct + '%';
            btn.dataset.tableWidth = String(pct);
            btn.setAttribute('aria-label', '표 너비 ' + pct + '%');
            btn.onclick = () => {
                const fresh = freshBinding(binding);
                if (!fresh) return;
                setTableWidth(fresh.model, pct);
                table.style.width = pct + '%';
                commitTable(binding, fresh);
                layout();
            };
            return btn;
        });
        bar.append(...presets, equal, edit);
        const widthLabel = model => label.textContent = '너비 ' + (tagValue(model.tableTags, 'tablewidth') || '자동');
        widthLabel(match.model);
        binding.refresh = fresh => widthLabel(fresh.model);
        edit.onclick = () => {
            const fresh = freshBinding(binding);
            if (!fresh) return;
            block = fresh.block;
            openGrid();
        };
        equal.onclick = () => {
            const fresh = freshBinding(binding);
            if (!fresh) return;
            fresh.model.widths = equalWidths(fresh.model.widths.length);
            fresh.model.widthsChanged = true;
            paintLiveWidths(table, fresh.model.widths);
            commitTable(binding, fresh);
        };
        shell.prepend(bar);

        const handles = [];
        const edge = document.createElement('div');
        edge.className = 'wiki-table-edge';
        edge.setAttribute('role', 'separator');
        edge.setAttribute('aria-label', '표 너비 조절');
        shell.append(edge);
        dragHandle(edge, event => {
            const fresh = freshBinding(binding);
            if (!fresh) return null;
            return {fresh, x: event.clientX, width: table.getBoundingClientRect().width,
                    box: shell.getBoundingClientRect().width || 1, pct: null};
        }, (state, event) => {
            const px = state.width + event.clientX - state.x;
            state.pct = Math.max(25, Math.min(100, Math.round(px * 100 / state.box)));
            table.style.width = state.pct + '%';
            badgeAt('표 너비 ' + state.pct + '%', event.clientX, event.clientY);
            layout();
        }, (state, event, commit) => {
            if (commit && state.pct !== null) {
                setTableWidth(state.fresh.model, state.pct);
                commitTable(binding, state.fresh);
            }
            layout();
        });

        if (ref) for (let k = 0; k < columns - 1; k++) {
            const handle = document.createElement('div');
            handle.className = 'wiki-col-handle';
            handle.setAttribute('role', 'separator');
            handle.setAttribute('aria-label', (k + 1) + '열 너비 조절');
            shell.append(handle);
            handles.push(handle);
            dragHandle(handle, event => {
                const fresh = freshBinding(binding);
                if (!fresh || fresh.model.widths.length !== columns) return null;
                return {fresh, x: event.clientX, initial: measuredWidths(ref, table),
                        width: table.getBoundingClientRect().width || 1, widths: null};
            }, (state, event) => {
                state.widths = resizeWidths(state.initial, k, (event.clientX - state.x) * 100 / state.width);
                paintLiveWidths(table, state.widths);
                badgeAt(Math.round(state.widths[k]) + '% | ' + Math.round(state.widths[k + 1]) + '%', event.clientX, event.clientY);
                layout();
            }, (state, event, commit) => {
                if (commit && state.widths) {
                    state.fresh.model.widths = state.widths;
                    state.fresh.model.widthsChanged = true;
                    commitTable(binding, state.fresh);
                }
                layout();
            });
        }

        function layout() {
            const left = table.offsetLeft, top = table.offsetTop, w = table.offsetWidth, h = table.offsetHeight;
            edge.style.cssText = 'left:' + (left + w - 6) + 'px;top:' + top + 'px;height:' + h + 'px';
            if (ref) {
                const cells = [...ref.cells];
                handles.forEach((handle, k) => {
                    const cell = cells[k];
                    handle.style.cssText = 'left:' + (left + cell.offsetLeft + cell.offsetWidth - 5) +
                        'px;top:' + top + 'px;height:' + h + 'px';
                });
            }
        }
        shell.layout = layout;
        shells.push(shell);
        layout();
        if (window.ResizeObserver) {
            const observer = new ResizeObserver(layout);
            observer.observe(table);
            observers.push(observer);
        }
    });
    if (tip) tip.hidden = !bound;
}
window.addEventListener('resize', () => shells.forEach(shell => shell.layout()));

function context() {
    if (mode === 'visual') return updateUndoButtons();
    block = tableAt(source.value, source.selectionStart);
    const bar = $('#wiki-context');
    bar.hidden = !block;
    if (block) {
        try {
            const {grid} = parseTable(block.source);
            bar.firstElementChild.textContent = '표가 감지되었습니다 (' + grid.length + '행 × ' + grid[0].length + '열)';
            commandButton('editTable').disabled = false;
        } catch {
            bar.firstElementChild.textContent = unsupported;
            commandButton('editTable').disabled = true;
        }
    }
    const start = source.value.lastIndexOf('\n', source.selectionStart - 1) + 1;
    const heading = /^(={2,4}) (.*?) \1(?:\n|$)/.exec(source.value.slice(start));
    $('#wiki-style').value = heading?.[1] || '';
    commandButton('undo').disabled = !undo.length;
    commandButton('redo').disabled = !redo.length;
}

function replace(start, end, value, a=value.length, b=a, {focus = true} = {}) {
    undo.push({start, before:source.value.slice(start,end), after:value, old:selection(), next:[start+a,start+b]});
    if (undo.length > 80) undo.shift();
    redo.length = 0;
    source.setRangeText(value,start,end);
    if (focus) source.focus();
    source.setSelectionRange(start+a,start+b);
    context();
    schedulePreview();
}

function history(back) {
    const from = back ? undo : redo;
    const step = from.pop();
    if (!step) return;
    const [old, next] = back ? [step.after,step.before] : [step.before,step.after];
    source.setRangeText(next,step.start,step.start + old.length);
    (back ? redo : undo).push(step);
    source.focus();
    source.setSelectionRange(...(back ? step.old : step.next));
    context();
    schedulePreview();
}

function wrap(open, close, placeholder) {
    const [a,b] = selection();
    const value = selected();
    const before = source.value.slice(0,a), after = source.value.slice(b);
    // Two and three apostrophes share a prefix. A bold run alone is not italic.
    const apostrophes = open === "''" || open === "'''";
    const exact = text => !apostrophes || [open.length,5].includes(text.match(/^'+/)?.[0].length);
    if (before.endsWith(open) && after.startsWith(close) && exact([...before].reverse().join('')) && exact(after))
        replace(a-open.length,b+close.length,value,0,value.length);
    else if (value.length >= open.length + close.length && value.startsWith(open) && value.endsWith(close) && exact(value) && exact([...value].reverse().join(''))) {
        const inner = value.slice(open.length, -close.length);
        replace(a,b,inner,0,inner.length);
    } else {
        const inner = value || placeholder;
        replace(a,b,open+inner+close,open.length,open.length+inner.length);
    }
}

function lines(transform) {
    const [a,b] = selection();
    const start = a ? source.value.lastIndexOf('\n',a-1)+1 : 0;
    const next = source.value.indexOf('\n', b > a ? b-1 : b);
    const end = next < 0 ? source.value.length : next;
    const result = source.value.slice(start,end).split('\n').map(transform).join('\n');
    replace(start,end,result,0,result.length);
}

function insertBlock(value, a, b) {
    const prefix = a && source.value[a-1] !== '\n' ? '\n' : '';
    const suffix = b < source.value.length && source.value[b] !== '\n' ? '\n' : '';
    replace(a,b,prefix+value+suffix);
}

const inline = {
    bold:["'''","'''",'굵은 글씨'], italic:["''","''",'기울임'], underline:['__','__','밑줄'],
    strike:['~~','~~','취소선'], large:['{{{+1 ','}}}','내용'], small:['{{{-1 ','}}}','내용'],
    note:['[* ',']','각주 내용']
};

source.addEventListener('input', () => {
    // Native text edits invalidate stored toolbar offsets.
    undo.length = redo.length = 0;
    context();
    schedulePreview();
});
for (const event of ['click','keyup','select','selectionchange']) source.addEventListener(event, context);
source.addEventListener('keydown', event => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return;
    const cmd = {b:'bold',i:'italic',u:'underline',k:'link'}[event.key.toLowerCase()];
    if (cmd) {
        event.preventDefault();
        event.stopPropagation();
        run(cmd);
    }
});
$('#wiki-color').onchange = event => {
    if (mode === 'visual') {
        if (event.target.value) formatSelection('color', event.target.value);
        event.target.value = '';
        return;
    }
    if (event.target.value) wrap('{{{'+event.target.value+' ','}}}','내용');
    event.target.value = '';
};
$('#wiki-style').onchange = event => {
    const mark = event.target.value;
    if (mode === 'visual') return visualStyle(mark);
    lines(line => {
        const plain = line.replace(/^(={1,6})\s+(.*?)\s+\1$/, '$2');
        return mark ? mark+' '+(plain || '제목')+' '+mark : plain;
    });
};

function setSelect(select, value) {
    select.querySelector('[data-custom]')?.remove();
    if (![...select.options].some(option => option.value === value)) {
        const option = new Option(value,value);
        option.dataset.custom = '';
        select.add(option);
    }
    select.value = value;
}

function focusCell(r,c) {
    const cell = model.grid[r][c];
    while (r && model.grid[r-1][c] === cell) r--;
    while (c && model.grid[r][c-1] === cell) c--;
    row = r;
    col = c;
    $('#wiki-grid .current')?.classList.remove('current');
    gridElement.querySelector('[data-row="'+r+'"][data-col="'+c+'"]')?.parentElement.classList.add('current');
    $('#cell-align').value = cell.tags.find(t => ['(',':',')'].includes(t)) || '';
    setSelect($('#cell-bg'),tagValue(cell.tags,'bgcolor'));
}

function paintWidths() {
    gridElement.querySelectorAll('col').forEach((el,i) => el.style.width = model.widths[i]+'%');
    gridElement.querySelectorAll('th output').forEach((el,i) => el.textContent = model.widths[i]+'%');
    gridElement.querySelectorAll('[role=slider]').forEach((el,i) => el.setAttribute('aria-valuenow',model.widths[i]));
}

function resizeHandle(th, i) {
    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'col-handle';
    handle.setAttribute('role','slider');
    handle.setAttribute('aria-label',(i+1)+'열 너비');
    handle.setAttribute('aria-valuemin','0');
    handle.setAttribute('aria-valuemax','100');
    th.append(handle);
    handle.onpointerdown = event => {
        event.preventDefault();
        const initial = model.widths.slice(), x = event.clientX, width = gridElement.getBoundingClientRect().width;
        handle.setPointerCapture(event.pointerId);
        handle.onpointermove = move => {
            model.widths = resizeWidths(initial,i,(move.clientX-x)*100/width);
            model.widthsChanged = true;
            paintWidths();
        };
        handle.onlostpointercapture = () => handle.onpointermove = null;
    };
    handle.onkeydown = event => {
        if (!['ArrowLeft','ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        model.widths = resizeWidths(model.widths,i,event.key === 'ArrowRight' ? 1 : -1);
        model.widthsChanged = true;
        paintWidths();
    };
}

function drawGrid() {
    const {grid} = model;
    gridElement.replaceChildren();
    const columns = document.createElement('colgroup');
    gridElement.append(columns);
    const head = gridElement.createTHead().insertRow();
    model.widths.forEach((width,i) => {
        columns.append(document.createElement('col'));
        const th = document.createElement('th');
        th.scope = 'col';
        th.append((i+1)+'열 ', document.createElement('output'));
        head.append(th);
        if (i+1 < model.widths.length) resizeHandle(th,i);
    });
    const body = gridElement.createTBody();
    grid.forEach((cells,r) => {
        const tr = body.insertRow();
        cells.forEach((cell,c) => {
            if (cell === cells[c-1] || cell === grid[r-1]?.[c]) return;
            const {w,h} = spanOf(grid,r,c);
            const td = tr.insertCell();
            td.colSpan = w;
            td.rowSpan = h;
            td.style.backgroundColor = tagValue(cell.tags,'bgcolor');
            const input = document.createElement('textarea');
            input.rows = 2;
            input.dataset.row = r;
            input.dataset.col = c;
            input.setAttribute('aria-label',(r+1)+'행 '+(c+1)+'열');
            input.value = cell.text;
            input.style.textAlign = {'(':'left',':':'center',')':'right'}[cell.tags.find(t => ['(',':',')'].includes(t))] || '';
            input.oninput = () => cell.text = input.value;
            input.onfocus = () => focusCell(r,c);
            input.onkeydown = event => {
                const direction = {ArrowUp:[-1,0],ArrowDown:[h,0],ArrowLeft:[0,-1],ArrowRight:[0,w]}[event.key];
                if (!direction || event.shiftKey || event.isComposing) return;
                if (event.key === 'ArrowLeft' && input.selectionStart ||
                    event.key === 'ArrowRight' && input.selectionEnd !== input.value.length) return;
                const y = r + direction[0], x = c + direction[1];
                if (!grid[y]?.[x]) return;
                event.preventDefault();
                focusCell(y,x);
                gridElement.querySelector('.current textarea').focus();
            };
            td.append(input);
        });
    });
    focusCell(Math.min(row,grid.length-1),Math.min(col,grid[0].length-1));
    setSelect($('#table-width'),tagValue(model.tableTags,'tablewidth'));
    const header = [...new Set(grid[0])].every(isHeader);
    commandButton('header').setAttribute('aria-pressed',String(header));
    paintWidths();
}

function isHeader(cell) {
    return tagValue(cell.tags,'bgcolor') === '#f5f5f5' && /^\s*'''[\s\S]*'''\s*$/.test(cell.text);
}

function openGrid(rows, cols) {
    row = col = 0;
    if (rows) visualEdit = null;
    $('#table-message').textContent = '';
    try {
        model = rows ? {grid:matrix(rows,cols),widths:equalWidths(cols),widthsChanged:true,tableTags:['tablewidth=100%']} : parseTable(block.source);
        target = rows ? selection() : [block.start,block.end];
        model.isNew = Boolean(rows);
        drawGrid();
        gridDialog.showModal();
        gridElement.querySelector('textarea').focus();
    } catch (error) {
        $('#wiki-context span').textContent = error.message;
    }
}

function editStructure(cmd) {
    const {grid} = model;
    const cell = grid[row][col], {w,h} = spanOf(grid,row,col);
    if (cmd === 'above' || cmd === 'below') {
        const at = row + (cmd === 'below' ? h : 0);
        if (grid.length >= 200) throw Error('최대 200행까지 편집할 수 있습니다.');
        grid.splice(at,0,grid[0].map((_,c) => grid[at]?.[c] && grid[at][c] === grid[at-1]?.[c] ? grid[at][c] : newCell()));
        row = at;
    } else if (cmd === 'left' || cmd === 'right') {
        if (grid[0].length >= 64) throw Error('최대 64열까지 편집할 수 있습니다.');
        const at = col + (cmd === 'right' ? w : 0);
        grid.forEach(cells => cells.splice(at,0,cells[at] && cells[at] === cells[at-1] ? cells[at] : newCell()));
        col = at;
    } else if (cmd === 'delRow') {
        if (grid.length === 1) throw Error('한 행 이상 필요합니다.');
        grid.splice(row,1);
    } else if (cmd === 'delCol') {
        if (grid[0].length === 1) throw Error('한 열 이상 필요합니다.');
        grid.forEach(cells => cells.splice(col,1));
    } else if (cmd === 'unmerge') {
        for (let y=row; y<row+h; y++) for (let x=col; x<col+w; x++) {
            if (y!==row || x!==col) grid[y][x] = newCell();
        }
    } else if (cmd === 'mergeRight' || cmd === 'mergeDown') {
        const y = cmd === 'mergeDown' ? row+h : row, x = cmd === 'mergeRight' ? col+w : col;
        const neighbor = grid[y]?.[x];
        if (!neighbor || neighbor === grid[y-1]?.[x] || neighbor === grid[y][x-1]) throw Error('병합할 인접 셀을 선택해 주세요.');
        const other = spanOf(grid,y,x);
        if (cmd === 'mergeRight' ? h !== other.h : w !== other.w) throw Error('맞닿은 셀의 크기가 달라 병합할 수 없습니다.');
        if (cmd === 'mergeDown' && grid[y].every((item,i) => item === neighbor || item === grid[y-1][i]))
            throw Error('행마다 하나 이상의 독립된 셀이 필요합니다.');
        if (neighbor.text.trim()) cell.text = cell.text.trim() ? cell.text+'[br]'+neighbor.text : neighbor.text;
        for (let dy=y; dy<y+other.h; dy++) for (let dx=x; dx<x+other.w; dx++) grid[dy][dx] = cell;
    } else if (cmd === 'header') {
        const cells = [...new Set(grid[0])], enable = !cells.every(isHeader);
        cells.forEach(item => {
            setTag(item.tags,t => t.startsWith('bgcolor='),enable ? 'bgcolor=#f5f5f5' : '');
            if (enable && !/^\s*'''[\s\S]*'''\s*$/.test(item.text)) item.text = "'''"+item.text+"'''";
            if (!enable) item.text = item.text.replace(/^(\s*)'''([\s\S]*)'''(\s*)$/,'$1$2$3');
        });
    }
    if (['left','right','delCol','equal'].includes(cmd)) {
        model.widths = equalWidths(grid[0].length);
        model.widthsChanged = true;
    }
    drawGrid();
}

for (const [id,key] of [['table-width','tablewidth'],['cell-bg','bgcolor'],['cell-align','align']]) {
    $('#'+id).onchange = event => {
        const value = event.target.value, tags = key === 'tablewidth' ? model.tableTags : model.grid[row][col].tags;
        if (key === 'align') setTag(tags,t => ['(',':',')'].includes(t),value);
        else setTag(tags,t => t.startsWith(key+'='),value ? key+'='+value : '');
        drawGrid();
    };
}

function highlightPicker(r,c) {
    picker.querySelectorAll('.picker-grid button').forEach((button,i) =>
        button.classList.toggle('picked', Math.floor(i/6)<r && i%6<c));
    picker.querySelector('output').textContent = r+' × '+c+' 표 삽입';
}
for (let r=1; r<=6; r++) for (let c=1; c<=6; c++) {
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-label',r+'행 '+c+'열 표 삽입');
    button.onmouseenter = button.onfocus = () => highlightPicker(r,c);
    button.onclick = () => { picker.close(); openGrid(r,c); };
    picker.querySelector('.picker-grid').append(button);
}
link.querySelector('form').onsubmit = event => {
    event.preventDefault();
    const {target:dest,caption} = event.target.elements;
    const name = dest.value.trim();
    if (!name || /[\]|\r\n]/.test(name) || /[\]\r\n]/.test(caption.value)) {
        dest.setCustomValidity('문서명과 표시 텍스트의 괄호 또는 구분 기호를 확인해 주세요.');
        dest.reportValidity();
        return;
    }
    link.close();
    if (mode === 'visual') return visualLink(name, caption.value);
    replace(...selection(),'[['+name+(caption.value ? '|'+caption.value : '')+']]');
};
link.oninput = () => link.querySelector('[name=target]').setCustomValidity('');

function setLive(open) {
    live.hidden = !open;
    workspace.classList.toggle('split',open);
    commandButton('split').setAttribute('aria-pressed',String(open));
    schedulePreview(0);
}

function run(cmd) {
    if (cmd === 'modeVisual' || cmd === 'modeRaw') return setMode(cmd === 'modeVisual' ? 'visual' : 'raw');
    if (cmd === 'template') return openTemplateDialog();
    if (mode === 'visual' && visualRun(cmd)) return;
    if (inline[cmd]) return wrap(...inline[cmd]);
    if (cmd === 'undo' || cmd === 'redo') return history(cmd === 'undo');
    if (cmd === 'split') {
        userClosedLive = !live.hidden;
        return setLive(live.hidden);
    }
    if (cmd === 'refresh') return schedulePreview(0);
    if (cmd === 'table') return picker.showModal();
    if (cmd === 'editTable') { visualEdit = null; return openGrid(); }
    if (cmd === 'link') {
        link.querySelector('form').reset();
        link.querySelector('[name=target]').setCustomValidity('');
        link.querySelector('[name=caption]').value = selected();
        return link.showModal();
    }
    const prefix = {bullets:' * ',numbers:' 1. ',quote:'> '}[cmd];
    if (prefix) return lines(line => prefix+(line || (cmd === 'quote' ? '인용문' : '항목')));
    if (cmd === 'fold') return insertBlock('{{{#!folding 제목\n'+(selected() || '내용')+'\n}}}',...selection());
    if (cmd === 'rule') return insertBlock('----',...selection());
    if (cmd === 'toc' || cmd === 'break') return replace(...selection(),cmd === 'toc' ? '[목차]' : '[br]');
    const message = $('#table-message');
    message.textContent = '';
    try {
        if (cmd === 'apply') {
            const result = serializeTable(model);
            gridDialog.close();
            if (mode === 'visual') return visualApplyTable(result);
            if (model.isNew) insertBlock(result,...target);
            else replace(...target,result);
            schedulePreview(0);
        } else editStructure(cmd);
    } catch (error) {
        message.textContent = error.message;
    }
}
for (const area of [source.form, link, picker, gridDialog, templateDialog].filter(Boolean)) {
    area.addEventListener('click',event => {
        const cmd = event.target.closest('[data-command]')?.dataset.command;
        if (cmd === 'close') area.close();
        else if (cmd) run(cmd);
    });
}
// ---- Visual (WYSIWYG-first) mode ---------------------------------------------
// `blocks` mirrors the document; #wiki-content is only overwritten once the user
// actually edits (visualDirty), so untouched pages save byte-identical NamuMark.
let blocks = [], canvas, addBar, hintEl, hintTimer, syncTimer, recordTimer;
let composing = false, lastSource = source.value, activeBlock = null, savedRange = null, editingLink = null;
let vUndo = [], vRedo = [], vCurrent = '', vObservers = [];
const tableModels = new WeakMap();
const mk = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text) el.textContent = text;
    return el;
};
const setHtml = (el, text) => { el.innerHTML = visualApi.inlineToHtml(text); };
const textOfDom = el => visualApi.domToInline(el);
const newParagraph = (text = '') => ({type: 'paragraph', lines: [text]});
const emptyText = block => (block.type === 'paragraph' && !block.lines.join('').trim()) ||
    (block.type === 'heading' && !String(block.text).trim()) ||
    (block.type === 'quote' && !block.lines.join('').trim()) || (block.type === 'list' && !block.items.length);
const currentSource = () => visualApi.serializeBlocks(blocks.filter(b => !emptyText(b)));

function hint(text) {
    hintEl.textContent = text;
    hintEl.hidden = false;
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => { hintEl.hidden = true; }, 3500);
}

function updateUndoButtons() {
    commandButton('undo').disabled = !vUndo.length;
    commandButton('redo').disabled = !vRedo.length;
}

// ---- snapshot history (Ctrl+Z / Ctrl+Y in visual mode)
function record() {
    clearTimeout(recordTimer);
    const snapshot = JSON.stringify(blocks);
    if (snapshot !== vCurrent) {
        vUndo.push(vCurrent);
        if (vUndo.length > 80) vUndo.shift();
        vCurrent = snapshot;
        vRedo.length = 0;
    }
    updateUndoButtons();
}

function syncNow() {
    clearTimeout(syncTimer);
    if (mode !== 'visual' || !visualDirty) return;
    source.value = lastSource = currentSource();
}
function scheduleSync() {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => { if (!composing) syncNow(); }, 150);
}
function changed() {
    visualDirty = true;
    scheduleSync();
}
function edited() {
    changed();
    clearTimeout(recordTimer);
    recordTimer = setTimeout(record, 500);
}

function visualHistory(back) {
    record();
    const from = back ? vUndo : vRedo, to = back ? vRedo : vUndo;
    if (!from.length) return;
    to.push(vCurrent);
    vCurrent = from.pop();
    blocks = JSON.parse(vCurrent);
    activeBlock = null;
    visualDirty = true;
    syncNow();
    renderVisual({index: blocks.length - 1, where: 'end'});
    updateUndoButtons();
}

// ---- focus and caret helpers
function focusEl(el, where = 'start') {
    el.focus();
    if (el.tagName === 'INPUT' || !el.isContentEditable) return;
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(where === 'start');
    const selected = window.getSelection();
    selected.removeAllRanges();
    selected.addRange(range);
}
function focusBlock(index, where = 'start') {
    const wrap = canvas.children[index];
    if (!wrap) return;
    const fields = wrap.querySelectorAll('[contenteditable=true], input');
    if (fields.length) focusEl(fields[where === 'end' ? fields.length - 1 : 0], where);
    else wrap.focus();
}
function caretIn(host) {
    const selected = window.getSelection();
    if (!selected.rangeCount || !host.contains(selected.anchorNode)) return null;
    return selected.getRangeAt(0);
}
function splitAtCaret(host) {
    const range = caretIn(host);
    if (!range) return null;
    range.deleteContents();
    const tail = document.createRange();
    tail.setStart(range.endContainer, range.endOffset);
    tail.setEnd(host, host.childNodes.length);
    const holder = mk('div');
    holder.append(tail.extractContents());
    return {head: textOfDom(host), tail: textOfDom(holder)};
}
function atEnd(host) {
    const range = caretIn(host);
    if (!range || !range.collapsed) return false;
    const tail = document.createRange();
    tail.setStart(range.endContainer, range.endOffset);
    tail.setEnd(host, host.childNodes.length);
    const holder = mk('div');
    holder.append(tail.cloneContents());
    return textOfDom(holder) === '';
}
function insertNodeAtCaret(host, node) {
    const range = caretIn(host);
    if (!range) return false;
    range.deleteContents();
    range.insertNode(node);
    range.setStartAfter(node);
    range.collapse(true);
    const selected = window.getSelection();
    selected.removeAllRanges();
    selected.addRange(range);
    return true;
}
function insertBr(host) {
    const br = mk('br');
    if (!insertNodeAtCaret(host, br)) return;
    // A browser needs a trailing <br> to show a caret on the new last line.
    if (!br.nextSibling) br.after(mk('br'));
    touch(host);
}
function insertPlain(host, value, single) {
    const range = caretIn(host);
    if (!range) return;
    const flat = value.replace(/\r\n?/g, '\n');
    const parts = (single ? flat.replace(/\s*\n\s*/g, ' ') : flat).split('\n');
    const fragment = document.createDocumentFragment();
    parts.forEach((part, i) => {
        if (i) fragment.append(mk('br'));
        if (part) fragment.append(document.createTextNode(part));
    });
    range.deleteContents();
    const last = fragment.lastChild;
    range.insertNode(fragment);
    if (last) range.setStartAfter(last);
    range.collapse(true);
    const selected = window.getSelection();
    selected.removeAllRanges();
    selected.addRange(range);
    touch(host);
}
// Push one edited element's content back into its block and the textarea.
function touch(el) {
    const wrap = el.closest('.wiki-v-block');
    if (wrap && wrap._read) wrap._read(el);
    edited();
}

// ---- block rendering
function listItemElement(item) {
    const li = mk('li', 'wiki-v-li');
    li.contentEditable = 'true';
    li._item = item;
    li.style.marginLeft = (item.indent - 1) * 1.5 + 'em';
    setHtml(li, item.text);
    return li;
}
function renumber(list) {
    const counters = {};
    [...list.children].forEach(li => {
        const d = li._item.indent;
        Object.keys(counters).forEach(k => { if (Number(k) > d) delete counters[k]; });
        if (li._item.ordered) {
            counters[d] = (counters[d] || 0) + 1;
            li.dataset.marker = counters[d] + '.';
        } else {
            delete counters[d];
            li.dataset.marker = '•';
        }
    });
}
function syncItems(wrap) {
    wrap._block.items = [...wrap.querySelectorAll('li')].map(li => li._item);
    renumber(wrap.querySelector('ul, ol'));
}

function deleteButton(label) {
    const button = mk('button', 'wiki-v-delete', '×');
    button.type = 'button';
    button.title = label;
    button.setAttribute('aria-label', label);
    return button;
}

const builders = {
    heading(wrap, b) {
        const h = mk('h' + b.level, 'wiki-v-edit');
        h.contentEditable = 'true';
        h.dataset.placeholder = '제목';
        wrap.dataset.badge = 'H' + b.level;
        setHtml(h, b.text);
        wrap.append(h);
        wrap._read = () => { b.text = textOfDom(h).replace(/\[br\]/gi, ' ').trim(); };
    },
    paragraph(wrap, b) {
        const p = mk('p', 'wiki-v-edit');
        p.contentEditable = 'true';
        p.dataset.placeholder = '내용을 입력하세요...';
        setHtml(p, b.lines.join('\n'));
        wrap.append(p);
        wrap._read = () => { b.lines = [textOfDom(p)]; };
    },
    list(wrap, b) {
        const list = mk(b.items.every(i => i.ordered) ? 'ol' : 'ul', 'wiki-v-list');
        b.items.forEach(item => list.append(listItemElement(item)));
        renumber(list);
        wrap.append(list);
        wrap._read = el => {
            const li = el.closest('li');
            if (li) li._item.text = textOfDom(li);
        };
    },
    quote(wrap, b) {
        const q = mk('blockquote', 'wiki-v-edit');
        q.contentEditable = 'true';
        q.dataset.placeholder = '인용문';
        q.innerHTML = b.lines.map(line => visualApi.inlineToHtml(line)).join('<br>');
        wrap.append(q);
        wrap._read = () => { b.lines = textOfDom(q).split(/\[br\]/i); };
    },
    folding(wrap, b) {
        wrap.classList.add('wiki-v-fold');
        const head = mk('div', 'wiki-v-fold-head');
        const title = mk('input', 'wiki-v-fold-title');
        title.type = 'text';
        title.value = b.title;
        title.placeholder = '펼쳐 보기';
        title.setAttribute('aria-label', '접기 제목');
        const body = mk('div', 'wiki-v-fold-body');
        body.contentEditable = 'true';
        body.dataset.placeholder = '내용';
        setHtml(body, b.body);
        head.append(title, deleteButton('접기 블록 삭제'));
        wrap.append(head, body);
        wrap._read = () => {
            b.title = title.value.replace(/[\r\n]+/g, ' ');
            b.body = textOfDom(body).replace(/\[br\]/gi, '\n');
        };
    },
    toc(wrap) {
        wrap.classList.add('wiki-v-toc');
        wrap.tabIndex = 0;
        wrap.append(mk('span', 'wiki-v-chip', '목차'), deleteButton('목차 삭제'));
    },
    rule(wrap) {
        wrap.classList.add('wiki-v-rule');
        wrap.tabIndex = 0;
        wrap.append(mk('hr'), deleteButton('가로선 삭제'));
    },
    raw(wrap, b, label) {
        wrap.classList.add('wiki-v-raw-card');
        wrap.dataset.namuRaw = b.raw;
        const snippet = b.raw.split('\n').slice(0, 6).join('\n');
        const edit = mk('button', 'wiki-v-raw-edit', '원문에서 편집');
        edit.type = 'button';
        wrap.append(mk('span', 'wiki-v-raw-tag', label || b.label || '고급 위키 문법 · 원문 유지'),
            mk('pre', 'wiki-v-raw-snippet', snippet.length > 240 ? snippet.slice(0, 240) + '…' : snippet), edit);
    },
    table(wrap, b) {
        let tableModel;
        try {
            tableModel = parseTable(b.raw);
        } catch {
            return builders.raw(wrap, b, '복잡한 표 · 원문 유지');
        }
        tableModels.set(b, tableModel);
        wrap.classList.add('wiki-v-table-block');
        wrap.append(tableShell(b, tableModel));
        wrap._read = el => {
            const td = el.closest('td');
            if (!td || !td._cell) return;
            td._cell.text = td._cell._lead + textOfDom(td).trim() + td._cell._trail;
            commitVisualTable(b);
        };
        wrap._rebuild = () => {
            const old = wrap.querySelector('.wiki-table-shell');
            wrap.replaceChild(tableShell(b, tableModels.get(b)), old);
        };
    }
};

function blockElement(b) {
    const wrap = mk('div', 'wiki-v-block');
    wrap.dataset.type = b.type;
    wrap._block = b;
    (builders[b.type] || builders.raw)(wrap, b);
    return wrap;
}

function renderVisual(focus) {
    const y = window.scrollY;
    vObservers.forEach(o => o.disconnect());
    vObservers = [];
    if (!blocks.length) blocks.push(newParagraph());
    canvas.replaceChildren(...blocks.map(blockElement));
    window.scrollTo(window.scrollX, y);
    if (focus) focusBlock(Math.max(0, Math.min(focus.index, blocks.length - 1)), focus.where);
    updateStyleSelect();
}

function updateStyleSelect() {
    if (mode !== 'visual') return;
    const select = $('#wiki-style');
    select.querySelector('[data-custom]')?.remove();
    const level = activeBlock && activeBlock.type === 'heading' ? activeBlock.level : 0;
    setSelect(select, level ? '='.repeat(level) : '');
}

// ---- block operations (each is one undo step)
function structural(change, focus) {
    record();
    change();
    changed();
    renderVisual(focus);
    record();
}
function insertAfter(ref, newBlock, where = 'start') {
    const at = ref && blocks.includes(ref) ? blocks.indexOf(ref) + 1 : blocks.length;
    structural(() => blocks.splice(at, 0, newBlock), {index: at, where});
}
function replaceBlock(old, newBlock, where = 'end') {
    const at = blocks.indexOf(old);
    structural(() => blocks.splice(at, 1, newBlock), {index: at, where});
}
function removeBlock(old, where = 'start') {
    const at = blocks.indexOf(old);
    structural(() => blocks.splice(at, 1), {index: at, where});
}
const newTableBlock = (rows = 3, cols = 3) => ({type: 'table', raw: serializeTable(
    {grid: matrix(rows, cols), widths: equalWidths(cols), widthsChanged: true, tableTags: ['tablewidth=100%']})});
function newBlockOf(kind) {
    if (kind === 'heading') return {type: 'heading', level: 2, text: ''};
    if (kind === 'list') return {type: 'list', items: [{indent: 1, ordered: false, marker: '*', text: ''}]};
    if (kind === 'quote') return {type: 'quote', lines: ['']};
    if (kind === 'table') return newTableBlock();
    return newParagraph();
}
const lastBlock = () => blocks[blocks.length - 1];
const insertAtActive = (newBlock, where) => insertAfter(activeBlock || lastBlock(), newBlock, where);

function visualStyle(mark) {
    const b = activeBlock;
    if (!b || !['paragraph', 'heading'].includes(b.type) || !blocks.includes(b)) {
        updateStyleSelect();
        return hint('문단이나 제목을 클릭한 뒤 스타일을 바꿔 주세요.');
    }
    const text = b.type === 'heading' ? b.text : b.lines.join('[br]');
    const next = mark ? {type: 'heading', level: mark.length, text: text.replace(/\[br\]/gi, ' ').trim()} : newParagraph(text);
    activeBlock = next;
    replaceBlock(b, next, 'end');
}

function convertList(cmd) {
    const b = activeBlock, ordered = cmd === 'numbers';
    const item = text => ({indent: 1, ordered, marker: ordered ? '1.' : '*', text});
    if (b && blocks.includes(b) && b.type === 'paragraph') {
        const parts = b.lines.join('[br]').split(/\[br\]/i);
        const next = {type: 'list', items: parts.map(item)};
        activeBlock = next;
        return replaceBlock(b, next, 'end');
    }
    if (b && blocks.includes(b) && b.type === 'list') {
        return structural(() => b.items.forEach(i => { i.ordered = ordered; i.marker = ordered ? '1.' : '*'; }),
            {index: blocks.indexOf(b), where: 'end'});
    }
    insertAtActive({type: 'list', items: [item('항목')]}, 'end');
}
function convertQuote() {
    const b = activeBlock;
    if (b && blocks.includes(b) && b.type === 'paragraph') {
        const next = {type: 'quote', lines: b.lines.join('[br]').split(/\[br\]/i)};
        activeBlock = next;
        return replaceBlock(b, next, 'end');
    }
    if (b && blocks.includes(b) && b.type === 'quote') {
        const next = newParagraph(b.lines.join('[br]'));
        activeBlock = next;
        return replaceBlock(b, next, 'end');
    }
    insertAtActive({type: 'quote', lines: ['인용문']}, 'end');
}

// ---- inline formatting
function currentRange() {
    const selected = window.getSelection();
    if (selected.rangeCount && visual.contains(selected.anchorNode)) return selected.getRangeAt(0);
    return savedRange;
}
function hostOf(range) {
    if (!range) return null;
    const node = range.commonAncestorContainer;
    const host = (node.nodeType === 1 ? node : node.parentElement)?.closest('[contenteditable=true]');
    return host && visual.contains(host) ? host : null;
}
function selectContents(node) {
    const range = document.createRange();
    range.selectNodeContents(node);
    const selected = window.getSelection();
    selected.removeAllRanges();
    selected.addRange(range);
    savedRange = range.cloneRange();
}
const FORMATS = {
    bold: ['strong, b', 'strong', '굵은 글씨'], italic: ['em, i', 'em', '기울임'],
    underline: ['u', 'u', '밑줄'], strike: ['s, del, strike', 's', '취소선']
};
function formatSelection(kind, value) {
    const range = currentRange(), host = hostOf(range);
    if (!host) return hint('먼저 글자를 클릭하거나 드래그해서 선택해 주세요.');
    record();
    const start = range.commonAncestorContainer;
    const around = (start.nodeType === 1 ? start : start.parentElement);
    let el, existing;
    if (FORMATS[kind]) {
        existing = around.closest(FORMATS[kind][0]);
        el = mk(FORMATS[kind][1]);
    } else if (kind === 'color') {
        existing = around.closest('[data-namu-color]');
        el = mk('span', 'wiki-v-color');
    } else {
        existing = around.closest('[data-namu-size]');
        el = mk('span', 'wiki-v-size');
    }
    if (existing && !host.contains(existing)) existing = null;
    const size = kind === 'large' ? '+1' : '-1';
    if (existing && kind === 'color') {
        existing.dataset.namuColor = value;
        existing.style.color = value;
    } else if (existing && (FORMATS[kind] || existing.dataset.namuSize === size)) {
        existing.replaceWith(...existing.childNodes);
    } else if (existing) {
        existing.dataset.namuSize = size;
        existing.style.fontSize = size === '+1' ? '1.18em' : '0.88em';
    } else {
        if (kind === 'color') { el.dataset.namuColor = value; el.style.color = value; }
        if (kind === 'large' || kind === 'small') {
            el.dataset.namuSize = size;
            el.style.fontSize = size === '+1' ? '1.18em' : '0.88em';
        }
        if (range.collapsed) el.textContent = FORMATS[kind] ? FORMATS[kind][2] : '내용';
        else el.append(range.extractContents());
        range.insertNode(el);
        selectContents(el);
    }
    touch(host);
    record();
}

function visualLink(name, caption) {
    record();
    if (editingLink) {
        const a = editingLink;
        a.dataset.namuLink = name;
        a.dataset.namuHasCaption = caption ? '1' : '0';
        a.textContent = caption || name;
        editingLink = null;
        touch(a.closest('[contenteditable=true]') || a);
        return record();
    }
    const range = currentRange(), host = hostOf(range);
    if (!host) return hint('링크를 넣을 위치를 먼저 클릭해 주세요.');
    const a = mk('a', 'wiki-v-link', caption || name);
    a.href = '#';
    a.dataset.namuLink = name;
    a.dataset.namuHasCaption = caption ? '1' : '0';
    a.contentEditable = 'false';
    range.deleteContents();
    range.insertNode(a);
    range.setStartAfter(a);
    range.collapse(true);
    savedRange = range.cloneRange();
    touch(host);
    record();
}

function editNote(note) {
    const old = note.dataset.namuNote;
    const value = window.prompt('각주 내용을 입력하세요 (비우면 각주를 지웁니다)', old.trim());
    if (value === null) return;
    const host = note.closest('[contenteditable=true]');
    record();
    if (!value.trim()) note.remove();
    else {
        note.dataset.namuNote = (/^\s/.test(old) ? ' ' : '') + value.trim();
        note.title = value.trim();
    }
    if (host) touch(host);
    record();
}
function insertNote() {
    const range = currentRange(), host = hostOf(range);
    if (!host) return hint('각주를 넣을 위치를 먼저 클릭해 주세요.');
    const value = window.prompt('각주 내용을 입력하세요');
    if (!value || !value.trim()) return;
    record();
    const note = mk('span', 'wiki-v-note', '각주');
    note.dataset.namuNote = ' ' + value.trim();
    note.title = value.trim();
    note.contentEditable = 'false';
    range.collapse(false);
    range.insertNode(note);
    range.setStartAfter(note);
    range.collapse(true);
    savedRange = range.cloneRange();
    touch(host);
    record();
}

// ---- tables
const commitVisualTable = b => {
    try {
        b.raw = serializeTable(tableModels.get(b));
        edited();
        return true;
    } catch (error) {
        hint(error.message);
        return false;
    }
};

function tableShell(b, tableModel) {
    const grid = tableModel.grid, columns = grid[0].length;
    const shell = mk('div', 'wiki-table-shell');
    const table = mk('table', 'wiki-v-table');
    const group = mk('colgroup', 'wiki-live-cols');
    tableModel.widths.forEach(w => { const c = document.createElement('col'); c.style.width = w + '%'; group.append(c); });
    table.append(group);
    table.style.tableLayout = 'fixed';
    table.style.width = tagValue(tableModel.tableTags, 'tablewidth') || '100%';
    const body = table.createTBody();
    grid.forEach((cells, r) => {
        const tr = body.insertRow();
        cells.forEach((cell, c) => {
            if (cell === cells[c - 1] || cell === grid[r - 1]?.[c]) return;
            const {w, h} = spanOf(grid, r, c);
            const td = tr.insertCell();
            td.colSpan = w;
            td.rowSpan = h;
            td.contentEditable = 'true';
            td.style.backgroundColor = tagValue(cell.tags, 'bgcolor');
            td.style.textAlign = {'(': 'left', ':': 'center', ')': 'right'}[cell.tags.find(t => ['(', ':', ')'].includes(t))] || '';
            td._cell = cell;
            if (!cell.text.trim()) { cell._lead = ' '; cell._trail = ' '; }
            else { cell._lead = /^\s*/.exec(cell.text)[0]; cell._trail = /\s*$/.exec(cell.text)[0]; }
            setHtml(td, cell.text.trim());
        });
    });
    shell.append(table);
    const ref = [...table.rows].find(tr => tr.cells.length === columns &&
        [...tr.cells].every(cell => cell.colSpan === 1 && cell.rowSpan === 1));

    const bar = mk('div', 'wiki-table-bar');
    const label = mk('span');
    const showWidth = () => { label.textContent = '너비 ' + (tagValue(tableModel.tableTags, 'tablewidth') || '자동'); };
    showWidth();
    const button = (text, handler, extra) => {
        const btn = mk('button', extra || '', text);
        btn.type = 'button';
        btn.onclick = handler;
        return btn;
    };
    const change = (fn, focusCell) => {
        record();
        fn();
        if (commitVisualTable(b)) {
            const wrap = shell.closest('.wiki-v-block');
            vObservers.forEach(o => o.disconnect());
            vObservers = [];
            wrap._rebuild();
            if (focusCell) focusCell(wrap);
        }
        record();
    };
    const presets = [100, 85, 70].map(pct => {
        const btn = button(pct + '%', () => {
            record();
            setTableWidth(tableModel, pct);
            table.style.width = pct + '%';
            commitVisualTable(b);
            showWidth();
            layout();
            record();
        });
        btn.dataset.tableWidth = String(pct);
        btn.setAttribute('aria-label', '표 너비 ' + pct + '%');
        return btn;
    });
    const equal = button('균등', () => {
        record();
        tableModel.widths = equalWidths(columns);
        tableModel.widthsChanged = true;
        paintLiveWidths(table, tableModel.widths);
        commitVisualTable(b);
        record();
    });
    equal.disabled = !ref;
    const addRow = button('+ 행', () => {
        if (grid.length >= 200) return hint('최대 200행까지 편집할 수 있습니다.');
        change(() => grid.push(Array.from({length: columns}, newCell)),
            wrap => wrap.querySelector('tr:last-child td')?.focus());
    });
    const addCol = button('+ 열', () => {
        if (columns >= 64) return hint('최대 64열까지 편집할 수 있습니다.');
        change(() => {
            grid.forEach(cells => cells.push(newCell()));
            tableModel.widths = equalWidths(columns + 1);
            tableModel.widthsChanged = true;
        });
    });
    const edit = button('표 편집', () => {
        visualEdit = {block: b};
        block = {source: b.raw};
        openGrid();
    });
    const remove = button('삭제', () => removeBlock(b), 'wiki-table-delete');
    bar.append(label, ...presets, equal, addRow, addCol, edit, remove);
    shell.prepend(bar);

    const handles = [];
    const edge = mk('div', 'wiki-table-edge');
    edge.setAttribute('role', 'separator');
    edge.setAttribute('aria-label', '표 너비 조절');
    shell.append(edge);
    dragHandle(edge, event => ({x: event.clientX, width: table.getBoundingClientRect().width,
            box: shell.getBoundingClientRect().width || 1, pct: null}), (state, event) => {
        const px = state.width + event.clientX - state.x;
        state.pct = Math.max(25, Math.min(100, Math.round(px * 100 / state.box)));
        table.style.width = state.pct + '%';
        badgeAt('표 너비 ' + state.pct + '%', event.clientX, event.clientY);
        layout();
    }, (state, event, commit) => {
        if (commit && state.pct !== null) {
            record();
            setTableWidth(tableModel, state.pct);
            commitVisualTable(b);
            showWidth();
            record();
        }
        layout();
    });
    if (ref) for (let k = 0; k < columns - 1; k++) {
        const handle = mk('div', 'wiki-col-handle');
        handle.setAttribute('role', 'separator');
        handle.setAttribute('aria-label', (k + 1) + '열 너비 조절');
        shell.append(handle);
        handles.push(handle);
        dragHandle(handle, event => ({x: event.clientX, initial: measuredWidths(ref, table),
                width: table.getBoundingClientRect().width || 1, widths: null}), (state, event) => {
            state.widths = resizeWidths(state.initial, k, (event.clientX - state.x) * 100 / state.width);
            paintLiveWidths(table, state.widths);
            badgeAt(Math.round(state.widths[k]) + '% | ' + Math.round(state.widths[k + 1]) + '%', event.clientX, event.clientY);
            layout();
        }, (state, event, commit) => {
            if (commit && state.widths) {
                record();
                tableModel.widths = state.widths;
                tableModel.widthsChanged = true;
                commitVisualTable(b);
                record();
            }
            layout();
        });
    }
    function layout() {
        const left = table.offsetLeft, top = table.offsetTop, w = table.offsetWidth, h = table.offsetHeight;
        edge.style.cssText = 'left:' + (left + w - 6) + 'px;top:' + top + 'px;height:' + h + 'px';
        if (ref) {
            const cells = [...ref.cells];
            handles.forEach((handle, k) => {
                handle.style.cssText = 'left:' + (left + cells[k].offsetLeft + cells[k].offsetWidth - 5) +
                    'px;top:' + top + 'px;height:' + h + 'px';
            });
        }
    }
    shell.layout = layout;
    if (window.ResizeObserver) {
        const observer = new ResizeObserver(layout);
        observer.observe(table);
        vObservers.push(observer);
    }
    requestAnimationFrame(layout);
    return shell;
}
window.addEventListener('resize', () => visual.querySelectorAll('.wiki-table-shell').forEach(shell => shell.layout && shell.layout()));

function visualApplyTable(result) {
    const edit = visualEdit;
    visualEdit = null;
    if (edit) {
        structural(() => { edit.block.raw = result; }, {index: blocks.indexOf(edit.block), where: 'start'});
    } else {
        insertAtActive({type: 'table', raw: result});
    }
}

// ---- templates
const templates = (() => {
    try { return JSON.parse($('#wiki-templates-data').textContent); } catch { return []; }
})();
function openTemplateDialog() {
    if (!templateDialog) return;
    syncNow();
    templateDialog.querySelector('fieldset').hidden = !source.value.trim();
    templateDialog.showModal();
}
function applyTemplate(content, replaceAll) {
    syncNow();
    const base = source.value;
    const next = replaceAll || !base.trim() ? content : base.replace(/\s+$/, '') + '\n\n' + content;
    if (mode !== 'visual') return replace(0, source.value.length, next, 0, 0);
    record();
    blocks = visualApi.parseBlocks(next);
    activeBlock = null;
    visualDirty = true;
    syncNow();
    renderVisual({index: 0, where: 'start'});
    record();
}
document.addEventListener('click', event => {
    const card = event.target.closest && event.target.closest('[data-template-key]');
    const chosen = card && templates.find(t => t.key === card.dataset.templateKey);
    if (!chosen || !chosen.content) return;
    event.preventDefault();
    const inDialog = templateDialog && templateDialog.contains(card);
    const choice = inDialog && templateDialog.querySelector('[name=template-mode]:checked');
    applyTemplate(chosen.content, Boolean(choice && choice.value === 'replace'));
    if (inDialog) templateDialog.close();
    $('#wiki-starter-bar')?.remove();
});

// ---- command routing while the visual canvas is active
function visualRun(cmd) {
    if (['bold', 'italic', 'underline', 'strike', 'large', 'small'].includes(cmd)) return formatSelection(cmd), true;
    if (cmd === 'undo' || cmd === 'redo') return visualHistory(cmd === 'undo'), true;
    if (cmd === 'bullets' || cmd === 'numbers') return convertList(cmd), true;
    if (cmd === 'quote') return convertQuote(), true;
    if (cmd === 'fold') return insertAtActive({type: 'folding', title: '제목', body: '내용'}, 'start'), true;
    if (cmd === 'rule') return insertAtActive({type: 'rule'}, 'end'), true;
    if (cmd === 'toc') return insertAtActive({type: 'toc', raw: '[목차]'}, 'end'), true;
    if (cmd === 'break') {
        const host = hostOf(currentRange());
        if (host) { record(); insertBr(host); record(); } else hint('줄을 바꿀 위치를 먼저 클릭해 주세요.');
        return true;
    }
    if (cmd === 'link') {
        editingLink = null;
        link.querySelector('form').reset();
        link.querySelector('[name=target]').setCustomValidity('');
        const range = currentRange();
        link.querySelector('[name=caption]').value = range ? range.toString() : '';
        link.showModal();
        return true;
    }
    if (cmd === 'note') return insertNote(), true;
    if (cmd === 'table') return picker.showModal(), true;
    return ['split', 'refresh', 'editTable'].includes(cmd);
}

// ---- mode switching
function applyModeUI() {
    const isVisual = mode === 'visual';
    workspace.dataset.mode = mode;
    source.form.dataset.mode = mode;
    visual.hidden = !isVisual;
    source.hidden = isVisual;
    source.required = !isVisual;
    const label = document.querySelector('label[for="wiki-content"]');
    if (label) label.textContent = isVisual ? '문서 편집 (화면에서 바로 수정)' : '문서 내용 (나무마크 원문)';
    commandButton('modeVisual').setAttribute('aria-pressed', String(isVisual));
    commandButton('modeRaw').setAttribute('aria-pressed', String(!isVisual));
    commandButton('split').hidden = isVisual;
    const help = document.querySelector('.wiki-syntax-help');
    if (help && isVisual) help.open = false;
    if (isVisual) {
        $('#wiki-context').hidden = true;
        setLive(false);
        updateStyleSelect();
        updateUndoButtons();
    } else {
        context();
        // Wide screens show the rendered preview below the raw text.
        if (window.matchMedia && window.matchMedia('(min-width: 960px)').matches && !userClosedLive) setLive(true);
    }
}

function setMode(next) {
    if (!visualApi || next === mode) return;
    if (next === 'raw') {
        syncNow();
        record();
        mode = 'raw';
        return applyModeUI();
    }
    mode = 'visual';
    if (source.value !== lastSource) {
        blocks = visualApi.parseBlocks(source.value);
        lastSource = source.value;
        visualDirty = false;
        activeBlock = null;
        renderVisual();
        record();
    }
    applyModeUI();
}

function editInRaw(b) {
    syncNow();
    setMode('raw');
    const at = source.value.indexOf(b.raw);
    if (at < 0) return;
    source.focus();
    source.setSelectionRange(at, at + b.raw.length);
    source.scrollTop = Math.max(0, (source.value.slice(0, at).split('\n').length - 1) * 24 - 80);
}

// ---- events on the canvas
function startVisual() {
    canvas = mk('div', 'wiki-visual-canvas wiki-prose');
    addBar = mk('div', 'wiki-visual-add');
    addBar.setAttribute('role', 'group');
    addBar.setAttribute('aria-label', '블록 추가');
    for (const [kind, text] of [['paragraph', '+ 문단'], ['heading', '+ 제목'], ['list', '+ 목록'], ['table', '+ 표'], ['quote', '+ 인용']]) {
        const btn = mk('button', '', text);
        btn.type = 'button';
        btn.dataset.add = kind;
        addBar.append(btn);
    }
    hintEl = mk('p', 'wiki-visual-hint');
    hintEl.setAttribute('role', 'status');
    hintEl.hidden = true;
    visual.append(canvas, addBar, hintEl);
    blocks = visualApi.parseBlocks(source.value);
    lastSource = source.value;
    renderVisual();
    vCurrent = JSON.stringify(blocks);
    mode = 'visual';
    applyModeUI();
}

if (visualApi && visual) {
    const elementOf = node => node.nodeType === 1 ? node : node.parentElement;
    visual.addEventListener('input', event => {
        const el = event.target;
        if (!composing && el.isContentEditable && el.innerHTML === '<br>') el.innerHTML = '';
        touch(el);
    });
    visual.addEventListener('compositionstart', () => { composing = true; });
    visual.addEventListener('compositionend', event => {
        composing = false;
        touch(elementOf(event.target));
        syncNow();
    });
    visual.addEventListener('focusout', () => { syncNow(); record(); });
    visual.addEventListener('focusin', event => {
        const wrap = elementOf(event.target).closest('.wiki-v-block');
        if (wrap) { activeBlock = wrap._block; updateStyleSelect(); }
    });
    document.addEventListener('selectionchange', () => {
        if (mode !== 'visual') return;
        const selected = window.getSelection();
        if (!selected.rangeCount || !selected.anchorNode || !visual.contains(selected.anchorNode)) return;
        savedRange = selected.getRangeAt(0).cloneRange();
        const wrap = elementOf(selected.anchorNode).closest('.wiki-v-block');
        if (wrap && wrap._block !== activeBlock) { activeBlock = wrap._block; updateStyleSelect(); }
    });
    ribbon.addEventListener('mousedown', event => {
        // Keep the caret and selection in the canvas while a ribbon button is pressed.
        if (mode === 'visual' && event.target.closest('button')) event.preventDefault();
    });
    source.form.addEventListener('submit', () => { if (mode === 'visual') syncNow(); });
    visual.addEventListener('paste', event => {
        const host = elementOf(event.target).closest('[contenteditable=true]');
        if (!host) return;
        event.preventDefault();
        const single = host.matches('h2, h3, h4, h5, h6, li');
        insertPlain(host, event.clipboardData.getData('text/plain'), single);
    });

    visual.addEventListener('click', event => {
        const target = event.target;
        const wrap = target.closest('.wiki-v-block');
        if (target.closest('.wiki-v-link')) {
            event.preventDefault();
            editingLink = target.closest('.wiki-v-link');
            link.querySelector('form').reset();
            link.querySelector('[name=target]').value = editingLink.dataset.namuLink;
            link.querySelector('[name=caption]').value = editingLink.dataset.namuHasCaption === '1' ? editingLink.textContent : '';
            return link.showModal();
        }
        if (target.closest('.wiki-v-note')) return editNote(target.closest('.wiki-v-note'));
        if (target.closest('.wiki-v-delete') && wrap) return removeBlock(wrap._block);
        if (target.closest('.wiki-v-raw-edit') && wrap) return editInRaw(wrap._block);
        const add = target.closest('[data-add]');
        if (add) {
            const last = lastBlock();
            if (add.dataset.add === 'paragraph' && last && last.type === 'paragraph' && emptyText(last)) return focusBlock(blocks.length - 1);
            return insertAfter(last, newBlockOf(add.dataset.add), 'start');
        }
        if (target === canvas || target === visual) {
            const last = lastBlock();
            if (last && last.type === 'paragraph' && emptyText(last)) return focusBlock(blocks.length - 1, 'end');
            insertAfter(last, newParagraph(), 'start');
        }
    });

    visual.addEventListener('keydown', event => {
        if (event.isComposing || event.keyCode === 229) return;
        const modifier = event.ctrlKey || event.metaKey;
        if (modifier && !event.altKey) {
            const key = event.key.toLowerCase();
            if (key === 'z' || key === 'y') {
                event.preventDefault();
                return visualHistory(key === 'z' && !event.shiftKey);
            }
            const cmd = event.shiftKey ? '' : {b: 'bold', i: 'italic', u: 'underline', k: 'link'}[key];
            if (cmd) { event.preventDefault(); run(cmd); }
            return;
        }
        const target = event.target;
        const wrap = target.closest('.wiki-v-block');
        if (!wrap) return;
        const b = wrap._block;
        if (target === wrap) {
            if (['Backspace', 'Delete'].includes(event.key) && ['toc', 'rule'].includes(b.type)) {
                event.preventDefault();
                removeBlock(b);
            }
            return;
        }
        const host = target.closest('[contenteditable=true]');
        if (!host) return;
        const at = blocks.indexOf(b);
        if (event.key === 'Enter') {
            if (b.type === 'paragraph' && !event.shiftKey) {
                event.preventDefault();
                const parts = splitAtCaret(host);
                if (!parts) return;
                record();
                b.lines = [parts.head];
                blocks.splice(at + 1, 0, newParagraph(parts.tail));
                changed();
                renderVisual({index: at + 1, where: 'start'});
                record();
            } else if (b.type === 'heading') {
                event.preventDefault();
                const parts = splitAtCaret(host);
                if (!parts) return;
                record();
                b.text = parts.head.replace(/\[br\]/gi, ' ').trim();
                blocks.splice(at + 1, 0, newParagraph(parts.tail));
                changed();
                renderVisual({index: at + 1, where: 'start'});
                record();
            } else if (b.type === 'list') {
                event.preventDefault();
                const li = host.closest('li');
                if (!textOfDom(li).trim()) {
                    record();
                    li.remove();
                    syncItems(wrap);
                    if (!b.items.length) blocks.splice(at, 1, newParagraph());
                    else blocks.splice(at + 1, 0, newParagraph());
                    changed();
                    renderVisual({index: b.items.length ? at + 1 : at, where: 'start'});
                    record();
                    return;
                }
                const parts = splitAtCaret(li);
                if (!parts) return;
                record();
                li._item.text = parts.head;
                const item = {indent: li._item.indent, ordered: li._item.ordered, marker: li._item.marker, text: parts.tail};
                const next = listItemElement(item);
                li.after(next);
                syncItems(wrap);
                changed();
                focusEl(next, 'start');
                record();
            } else if (b.type === 'quote' && !event.shiftKey) {
                event.preventDefault();
                const text = textOfDom(host);
                if (!text || (atEnd(host) && /\[br\]$/i.test(text))) {
                    record();
                    const lines = text.replace(/(\[br\])+$/i, '');
                    const para = newParagraph();
                    if (lines) { b.lines = lines.split(/\[br\]/i); blocks.splice(at + 1, 0, para); }
                    else blocks.splice(at, 1, para);
                    changed();
                    renderVisual({index: lines ? at + 1 : at, where: 'start'});
                    record();
                } else insertBr(host);
            } else {
                event.preventDefault();
                insertBr(host);
            }
        } else if (event.key === 'Backspace') {
            const range = caretIn(host);
            if (!range || !range.collapsed || textOfDom(host) !== '') return;
            if (b.type === 'list') {
                event.preventDefault();
                const li = host.closest('li');
                const siblings = [...wrap.querySelectorAll('li')];
                record();
                if (siblings.length === 1) {
                    blocks.splice(at, 1, newParagraph());
                    changed();
                    renderVisual({index: at, where: 'start'});
                } else {
                    const index = siblings.indexOf(li);
                    const neighbor = siblings[index ? index - 1 : 1];
                    li.remove();
                    syncItems(wrap);
                    changed();
                    focusEl(neighbor, index ? 'end' : 'start');
                }
                record();
            } else if (b.type === 'paragraph' && at > 0) {
                event.preventDefault();
                structural(() => blocks.splice(at, 1), {index: at - 1, where: 'end'});
            }
        } else if (event.key === 'Tab') {
            if (b.type === 'list') {
                event.preventDefault();
                const item = host.closest('li')._item;
                const indent = event.shiftKey ? Math.max(1, item.indent - 1) : Math.min(Math.max(4, item.indent), item.indent + 1);
                if (indent === item.indent) return;
                record();
                item.indent = indent;
                host.closest('li').style.marginLeft = (indent - 1) * 1.5 + 'em';
                renumber(wrap.querySelector('ul, ol'));
                changed();
                record();
            } else if (b.type === 'table') {
                const cells = [...wrap.querySelectorAll('td')];
                const next = cells[cells.indexOf(host) + (event.shiftKey ? -1 : 1)];
                if (next) { event.preventDefault(); focusEl(next, 'start'); }
            }
        }
    });
}
// ---- drag-selection quick actions (floating bar above selected text)
const selectionBar = $('#wiki-selection-bar'), actionToast = $('#wiki-action-toast');
let toastTimer = null;
function hideSelectionBar() { if (selectionBar) selectionBar.hidden = true; }
function selectionTitleOk(text) {
    if (!text || text.length > 60 || /[\n\r\[\]|\u0000-\u001f\u007f]/.test(text)) return false;
    return !text.split('/').some(part => part === '.' || part === '..');
}
function selectedTitle() {
    if (mode !== 'visual' || composing) return null;
    const selected = window.getSelection();
    if (!selected.rangeCount || selected.isCollapsed) return null;
    const range = selected.getRangeAt(0), host = hostOf(range);
    if (!host || range.collapsed) return null;
    const text = range.toString().trim();
    return selectionTitleOk(text) ? {text, range, host} : null;
}
function updateSelectionBar() {
    if (!selectionBar) return;
    const found = selectedTitle();
    if (!found) return hideSelectionBar();
    selectionBar.hidden = false;
    const rect = found.range.getBoundingClientRect();
    const width = selectionBar.offsetWidth, height = selectionBar.offsetHeight;
    selectionBar.style.top = Math.max(8, rect.top - height - 8) + 'px';
    selectionBar.style.left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.left + rect.width / 2 - width / 2)) + 'px';
}
function editUrl(title, query = '') {
    return (source.form.dataset.editBase || '/wiki/edit/__TITLE__').replace('__TITLE__', encodeURIComponent(title)) + query;
}
function showActionToast(title) {
    if (!actionToast) return;
    actionToast.replaceChildren();
    const message = mk('span', 'wiki-action-toast-text', '[[' + title + ']] 링크를 만들었어요.');
    const open = mk('a', 'wiki-action-toast-main', "'" + title + "' 문서 바로 만들기 ↗");
    const person = mk('a', 'wiki-action-toast-sub', '인물 틀로 만들기');
    open.href = editUrl(title);
    person.href = editUrl(title, '?template=person');
    for (const a of [open, person]) { a.target = '_blank'; a.rel = 'noopener'; }
    const close = mk('button', 'wiki-action-toast-close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', '닫기');
    close.addEventListener('click', () => { actionToast.hidden = true; });
    actionToast.append(message, open, person, close);
    actionToast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { actionToast.hidden = true; }, 8000);
}
function selectionNewDoc(found) {
    record();
    const a = mk('a', 'wiki-v-link', found.text);
    a.href = '#';
    a.dataset.namuLink = found.text;
    a.dataset.namuHasCaption = '0';
    a.contentEditable = 'false';
    found.range.deleteContents();
    found.range.insertNode(a);
    found.range.setStartAfter(a);
    found.range.collapse(true);
    savedRange = found.range.cloneRange();
    touch(found.host);
    visualDirty = true;
    syncNow();
    record();
    window.getSelection().removeAllRanges();
    showActionToast(found.text);
}
function selectionSectionBelow(found) {
    const wrap = found.host.closest('.wiki-v-block');
    const at = wrap ? blocks.indexOf(wrap._block) : -1;
    if (at < 0) return hint('문단을 만들 위치를 찾지 못했어요.');
    record();
    blocks.splice(at + 1, 0, {type: 'heading', level: 2, text: found.text}, newParagraph());
    activeBlock = null;
    changed();
    syncNow();
    renderVisual({index: at + 2, where: 'start'});
    record();
    const fresh = canvas.children[at + 2];
    if (fresh && fresh.scrollIntoView) fresh.scrollIntoView({block: 'center', behavior: 'smooth'});
}
if (selectionBar && visualApi && visual) {
    selectionBar.addEventListener('mousedown', event => event.preventDefault());
    selectionBar.addEventListener('click', event => {
        const button = event.target.closest('[data-selection-action]');
        if (!button) return;
        const action = button.dataset.selectionAction;
        const found = selectedTitle() || null;
        if (['bold', 'italic', 'strike'].includes(action)) {
            formatSelection(action);
        } else if (found && action === 'newDoc') selectionNewDoc(found);
        else if (found && action === 'sectionBelow') selectionSectionBelow(found);
        hideSelectionBar();
    });
    visual.addEventListener('mouseup', () => setTimeout(updateSelectionBar, 0));
    visual.addEventListener('keyup', event => {
        if (event.key === 'Escape') hideSelectionBar();
        else if (!event.isComposing) updateSelectionBar();
    });
    document.addEventListener('selectionchange', () => {
        if (selectionBar.hidden) return;
        if (!selectedTitle()) hideSelectionBar();
    });
    document.addEventListener('mousedown', event => {
        if (!selectionBar.contains(event.target) && !visual.contains(event.target)) hideSelectionBar();
    });
    window.addEventListener('scroll', hideSelectionBar, {passive: true});
}
context();
ribbon.hidden = false;
if (visualApi && visual) {
    startVisual();
} else if (window.matchMedia && window.matchMedia('(min-width: 960px)').matches) {
    // Without the visual module, wide screens open with the rendered preview.
    run('split');
}
})();
