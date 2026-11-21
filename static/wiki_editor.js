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
    replace(fresh.block.start, fresh.block.end, result, 0, 0);
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
        bar.append(label, edit, equal);
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
        shell.append(bar);

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
            bar.style.cssText = 'left:' + (left + w - 6) + 'px;top:' + (top + 4) + 'px';
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

function replace(start, end, value, a=value.length, b=a) {
    undo.push({start, before:source.value.slice(start,end), after:value, old:selection(), next:[start+a,start+b]});
    if (undo.length > 80) undo.shift();
    redo.length = 0;
    source.setRangeText(value,start,end);
    source.focus();
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
    if (event.target.value) wrap('{{{'+event.target.value+' ','}}}','내용');
    event.target.value = '';
};
$('#wiki-style').onchange = event => {
    const mark = event.target.value;
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
    replace(...selection(),'[['+name+(caption.value ? '|'+caption.value : '')+']]');
};
link.oninput = () => link.querySelector('[name=target]').setCustomValidity('');

function run(cmd) {
    if (inline[cmd]) return wrap(...inline[cmd]);
    if (cmd === 'undo' || cmd === 'redo') return history(cmd === 'undo');
    if (cmd === 'split') {
        live.hidden = !live.hidden;
        $('#wiki-workspace').classList.toggle('split',!live.hidden);
        commandButton(cmd).setAttribute('aria-pressed',String(!live.hidden));
        return schedulePreview(0);
    }
    if (cmd === 'refresh') return schedulePreview(0);
    if (cmd === 'table') return picker.showModal();
    if (cmd === 'editTable') return openGrid();
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
            if (model.isNew) insertBlock(result,...target);
            else replace(...target,result);
            schedulePreview(0);
        } else editStructure(cmd);
    } catch (error) {
        message.textContent = error.message;
    }
}
for (const area of [source.form, link, picker, gridDialog]) {
    area.addEventListener('click',event => {
        const cmd = event.target.closest('[data-command]')?.dataset.command;
        if (cmd === 'close') area.close();
        else if (cmd) run(cmd);
    });
}
context();
ribbon.hidden = false;
// Wide screens open with the rendered preview so tables can be resized directly.
if (window.matchMedia && window.matchMedia('(min-width: 960px)').matches) run('split');
})();
