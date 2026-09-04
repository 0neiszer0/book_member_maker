/* Visual drag only; assignment and attendance state belong to GroupEditor. */
(function (scope) {
    'use strict';
    function mount(container, options) {
        let drag = null;
        function destinationAt(x, y) {
            const node = document.elementFromPoint(x, y)?.closest('[data-destination]');
            return node && container.contains(node) ? node : null;
        }
        function draw() {
            if (!drag?.active) return;
            const {preview, x, y} = drag;
            preview.style.left = Math.max(8, Math.min(scope.innerWidth - preview.offsetWidth - 8, x + 14)) + 'px';
            preview.style.top = Math.max(8, Math.min(scope.innerHeight - preview.offsetHeight - 8, y + (drag.touch ? -86 : 20))) + 'px';
            const destination = destinationAt(x, y);
            container.querySelectorAll('.ge-drop-target').forEach(node => {
                if (node !== destination) node.classList.remove('ge-drop-target');
            });
            destination?.classList.add('ge-drop-target');
            const label = destination?.dataset.destination === 'unassigned' ? '미배정' : options.groupName(destination?.dataset.destination);
            drag.hint.textContent = destination ? '놓으면 ' + label + '(으)로 이동' : '조 안에 놓으세요 · 밖에 놓으면 취소';
        }
        function frame() {
            if (!drag?.active) return;
            if (!container.isConnected) { finish(true); return; }
            const edge = 76;
            const dy = drag.y < edge ? -(edge - drag.y) / 5 : (drag.y > scope.innerHeight - edge ? (drag.y - scope.innerHeight + edge) / 5 : 0);
            if (dy) scope.scrollBy(0, Math.max(-18, Math.min(18, Math.round(dy))));
            draw();
            drag.frame = scope.requestAnimationFrame(frame);
        }
        function start() {
            if (!drag || drag.active) return;
            drag.active = true;
            drag.member.closest('.ge-chip').classList.add('ge-drag-origin');
            drag.preview = document.createElement('div');
            drag.preview.className = 'ge-drag-preview';
            drag.preview.setAttribute('aria-hidden', 'true');
            const card = drag.member.closest('.ge-chip').cloneNode(true);
            card.classList.remove('ge-drag-origin');
            card.querySelector('.ge-unassign')?.remove();
            card.querySelectorAll('button').forEach(button => button.tabIndex = -1);
            drag.hint = document.createElement('span');
            drag.hint.className = 'ge-drag-hint';
            drag.preview.append(card, drag.hint);
            document.body.appendChild(drag.preview);
            document.body.classList.add('ge-dragging');
            frame();
        }
        function finish(cancelled) {
            const current = drag;
            if (!current) return;
            const destination = current.active && !cancelled ? destinationAt(current.x, current.y) : null;
            drag = null;
            scope.clearTimeout(current.timer);
            scope.cancelAnimationFrame(current.frame);
            current.preview?.remove();
            current.member.closest('.ge-chip')?.classList.remove('ge-drag-origin');
            document.body.classList.remove('ge-dragging');
            container.querySelectorAll('.ge-drop-target').forEach(node => node.classList.remove('ge-drop-target'));
            if (!current.touch && current.member.hasPointerCapture?.(current.id)) current.member.releasePointerCapture(current.id);
            if (!current.active) return;
            options.onFinish();
            if (destination) options.onMove(current.name, destination.dataset.destination);
        }
        function prepare(member, x, y, id, touch) {
            finish(true);
            drag = {name: member.dataset.member, x, y, startX: x, startY: y, id, member, touch, active: false};
            if (touch) drag.timer = scope.setTimeout(start, 320);
        }
        // Touch uses a cancellable touchmove after a stationary long press.
        // Quick swipes cancel the timer and remain native page scrolling.
        container.addEventListener('pointerdown', event => {
            const member = event.target.closest('.ge-member');
            if (!member || event.pointerType === 'touch' || event.button !== 0) return;
            prepare(member, event.clientX, event.clientY, event.pointerId, false);
            member.setPointerCapture?.(event.pointerId);
        });
        container.addEventListener('pointermove', event => {
            if (!drag || drag.touch || drag.id !== event.pointerId) return;
            drag.x = event.clientX; drag.y = event.clientY;
            if (Math.hypot(drag.x - drag.startX, drag.y - drag.startY) > 7) start();
            if (drag.active) { event.preventDefault(); draw(); }
        });
        container.addEventListener('pointerup', event => {
            if (!drag || drag.touch || drag.id !== event.pointerId) return;
            drag.x = event.clientX; drag.y = event.clientY;
            finish(false);
        });
        ['pointercancel', 'lostpointercapture'].forEach(type => container.addEventListener(type, event => {
            if (drag && !drag.touch && drag.id === event.pointerId) finish(true);
        }));
        container.addEventListener('touchstart', event => {
            if (event.touches.length !== 1) { finish(true); return; }
            const member = event.target.closest('.ge-member');
            if (!member) return;
            const touch = event.touches[0];
            prepare(member, touch.clientX, touch.clientY, touch.identifier, true);
        }, {passive: true});
        container.addEventListener('touchmove', event => {
            if (!drag?.touch) return;
            const touch = [...event.touches].find(item => item.identifier === drag.id);
            if (!touch || event.touches.length !== 1) { finish(true); return; }
            drag.x = touch.clientX; drag.y = touch.clientY;
            if (!drag.active) {
                if (Math.hypot(drag.x - drag.startX, drag.y - drag.startY) > 10) finish(true);
                return;
            }
            if (!event.cancelable) { finish(true); return; }
            event.preventDefault(); draw();
        }, {passive: false});
        container.addEventListener('touchend', event => {
            if (!drag?.touch) return;
            const touch = [...event.changedTouches].find(item => item.identifier === drag.id);
            if (!touch) return;
            drag.x = touch.clientX; drag.y = touch.clientY;
            if (drag.active && event.cancelable) event.preventDefault();
            finish(false);
        }, {passive: false});
        container.addEventListener('touchcancel', () => finish(true));
        container.addEventListener('contextmenu', event => {
            if (event.target.closest('.ge-member')) event.preventDefault();
        });
        scope.addEventListener('keydown', event => { if (event.key === 'Escape') finish(true); });
        scope.addEventListener('blur', () => finish(true));
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = {mount};
    else scope.GroupDrag = {mount};
})(typeof window !== 'undefined' ? window : globalThis);
