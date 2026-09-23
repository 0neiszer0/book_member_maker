/* Drafts are local only, never proof of submission or permission to edit. */
(function (scope) {
    'use strict';
    class TopicDraftStore {
        constructor(storage, now = () => Date.now()) { this.storage = storage; this.now = now; }
        key(eventId, studentId) { return 'topic-draft:v1:' + encodeURIComponent(eventId) + ':' + encodeURIComponent(studentId); }
        read(eventId, studentId) {
            try {
                const key = this.key(eventId, studentId), raw = this.storage.getItem(key);
                if (!raw) return {draft: null, ok: true};
                const draft = JSON.parse(raw);
                if (draft.version !== 1 || !Number.isFinite(draft.savedAt) || this.now() - draft.savedAt > 7 * 86400000 ||
                    !Array.isArray(draft.topics) || draft.topics.length > 100 ||
                    draft.topics.some(t => !t || ['topic', 'page', 'reference'].some(k => typeof t[k] !== 'string'))) {
                    this.storage.removeItem(key); return {draft: null, ok: true};
                }
                return {draft, ok: true};
            } catch (_) { return {draft: null, ok: false}; }
        }
        save(eventId, studentId, topics) {
            try {
                this.storage.setItem(this.key(eventId, studentId), JSON.stringify({version: 1, savedAt: this.now(), topics}));
                return true;
            } catch (_) { return false; }
        }
        remove(eventId, studentId) {
            try { this.storage.removeItem(this.key(eventId, studentId)); return true; }
            catch (_) { return false; }
        }
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = {TopicDraftStore};
    else scope.TopicDraftStore = TopicDraftStore;
})(typeof window !== 'undefined' ? window : globalThis);
