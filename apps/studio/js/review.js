/**
 * CG4. Character review: a person looks at the exact file, and records their own finding for it.
 *
 * The one thing this page must not get wrong is *which bytes* a finding is about. So it never
 * renders from a URL and hashes something else: it fetches the character's file once, hashes those
 * bytes here with SubtleCrypto, renders those same bytes from a blob URL, and only offers the form
 * when that hash equals the library pin the server reports. The server checks the hash again
 * against the file on its disk before anything is written (apps/api/routes/reviews.py).
 *
 * The other thing is *whose* finding it is. No outcome is pre-selected, nothing is suggested from
 * the operator's declaration or the file's terms, the reviewer types their own name, and they tick
 * that they looked themselves. A missing review is shown as pending work, never as a rejection;
 * only a recorded finding other than clearly-adult blocks a file.
 */
import { admin, api, ApiError } from './api.js';
import { Viewer } from './viewer.js';

const $ = (id) => document.getElementById(id);

export const OUTCOME_TEXT = {
    'clearly-adult': 'Clearly adult in design',
    'age-ambiguous': 'Age-ambiguous: could reasonably be read as under 18',
    'appears-minor': 'Appears to be a minor',
    'not-assessable': 'Cannot be assessed from what is shown',
};

const STATUS_TONE = { eligible: 'ok', blocked: 'bad' };

export function reviewLabel(state) {
    return state === 'pending' ? 'Pending: not reviewed yet' : `Reviewed: ${state}`;
}

export function bodyLabel(body) {
    if (!body) return 'not measured';
    const files = body.bodyStateFiles ? ` (${body.bodyStateFiles} body-state file imported)` : '';
    switch (body.state) {
        case 'complete':
            return `Complete: separate clothing over a closed body${files}`;
        case 'painted-on':
            return `Clothing painted on the skin: needs a separate bare body-state file${files}`;
        case 'body-missing':
            return `Body missing under the clothes (${(body.missingBands || []).join(', ')})${files}`;
        default:
            return 'Not measured';
    }
}

export function licenceLabel(licence) {
    if (!licence) return 'unknown';
    const sexual = licence.sexualUse ? 'sexual use allowed' : 'sexual use refused by the file';
    const modification = licence.modification
        ? `modification allowed (${licence.modificationSource})`
        : 'modification not stated';
    return `${sexual}; ${modification}`;
}

/** Whether the form may be sent: every field the person's own, and the file the one shown. */
export function canSubmit({ outcome, reviewer, evidence, examined, localHash, pinnedHash, reviewState }) {
    return Boolean(
        outcome &&
        reviewer &&
        reviewer.trim() &&
        evidence &&
        evidence.trim() &&
        examined &&
        localHash &&
        localHash === pinnedHash &&
        reviewState === 'pending'
    );
}

async function sha256Hex(buffer) {
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

const state = {
    characters: [],
    outcomes: [],
    current: null,
    localHash: null,
    viewer: null,
    blobUrl: null,
    filter: 'all',
    notOnDisk: [],
};

/**
 * CG10. Where each character stands, in the order an auditor works through them: nobody has
 * looked yet; found clearly adult but not yet reviewed for body detail; cleared for detail;
 * blocked by a finding. One word per character, from the server's own answers — never guessed.
 */
export function stage(row) {
    if (row.reviewState === 'pending') return 'needs-review';
    if (row.status === 'blocked' || (row.review && row.review.outcome && row.review.outcome !== 'clearly-adult'))
        return 'blocked';
    if (row.detail && row.detail.cleared) return 'detail-cleared';
    return 'needs-detail';
}

export const STAGE_TEXT = {
    'needs-review': 'Needs review',
    'needs-detail': 'Needs detail review',
    'detail-cleared': 'Cleared for detail',
    blocked: 'Blocked',
};

const STAGE_TONE = { 'needs-review': 'warn', 'needs-detail': 'warn', 'detail-cleared': 'ok', blocked: 'bad' };

/** Whether the detail-review form may be sent (the server checks every part again). */
export function canSubmitDetail({ reviewer, evidence, examined, localHash, pinnedHash, packetReady, needed = 40 }) {
    return Boolean(
        reviewer &&
        reviewer.trim() &&
        evidence &&
        evidence.trim().length >= needed &&
        examined &&
        packetReady &&
        localHash &&
        localHash === pinnedHash
    );
}

function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) if (child !== null && child !== undefined && child !== false) node.append(child);
    return node;
}

function renderAudit() {
    const rows = state.characters;
    const count = (name) => rows.filter((r) => stage(r) === name).length;
    const stat = (label, value, tone) =>
        el('div', { class: 'review-stat', 'data-tone': tone || '' }, el('b', { text: String(value) }), el('span', { text: label }));
    $('review-summary').replaceChildren(
        stat('characters', rows.length),
        stat('need review', count('needs-review'), count('needs-review') ? 'warn' : ''),
        stat('need detail review', count('needs-detail'), count('needs-detail') ? 'warn' : ''),
        stat('cleared for detail', count('detail-cleared'), 'ok'),
        stat('blocked', count('blocked'), count('blocked') ? 'bad' : ''),
        state.notOnDisk.length ? stat('not on this disk', state.notOnDisk.length, 'warn') : null
    );
    const filters = [['all', 'All'], ...Object.entries(STAGE_TEXT)];
    $('review-filters').replaceChildren(
        ...filters.map(([id, label]) =>
            el('button', {
                type: 'button',
                role: 'radio',
                class: 'review-filter',
                'aria-checked': String(state.filter === id),
                text: id === 'all' ? `${label} ${rows.length}` : `${label} ${count(id)}`,
                onclick: () => {
                    state.filter = id;
                    renderAudit();
                    renderList();
                },
            })
        )
    );
    const head = ['Character', 'File', 'Licence', 'Declared', 'Design review', 'Body detail', 'Missing', 'Bare looks', 'Detailed', 'Thumbnails', 'Status'];
    const body = rows.map((r) =>
        el(
            'tr',
            { onclick: () => select(r.slug), 'aria-current': String(state.current && state.current.slug === r.slug) },
            el('td', {}, el('strong', { text: r.name || r.slug }), el('small', { text: r.slug })),
            el('td', {}, el('code', { text: (r.sha256 || '').slice(0, 12) })),
            el('td', { text: licenceLabel(r.licence) }),
            el('td', { text: r.operatorDeclaration ? 'yes' : 'no' }),
            el('td', { text: r.review ? `${r.review.outcome} · ${r.review.reviewer} · ${r.review.date}` : 'not yet' }),
            el(
                'td',
                {},
                el('span', { class: 'review-chip', 'data-tone': STAGE_TONE[stage(r)], text: r.detail && r.detail.cleared ? `✓ ${r.detail.kind}` : '✗ not cleared' })
            ),
            el('td', { text: ((r.detail && r.detail.missing) || []).join('; ') || '—' }),
            el('td', { text: String(r.bareLooks || 0) }),
            el('td', { text: String(r.detailedLooks || 0) }),
            el('td', { text: String(r.thumbnails || 0) }),
            el('td', {}, el('span', { class: 'review-chip', 'data-tone': STAGE_TONE[stage(r)], text: STAGE_TEXT[stage(r)] }))
        )
    );
    $('review-table').replaceChildren(el('thead', {}, el('tr', {}, head.map((h) => el('th', { text: h })))), el('tbody', {}, body));
    $('review-audit').hidden = false;
}

function showError(message) {
    const box = $('review-error');
    box.textContent = message || '';
    box.hidden = !message;
}

function renderList() {
    const list = $('review-characters');
    list.replaceChildren(
        ...state.characters.filter((row) => state.filter === 'all' || stage(row) === state.filter).map((row) => {
            const item = document.createElement('li');
            const button = document.createElement('button');
            button.type = 'button';
            button.setAttribute('aria-current', String(state.current && state.current.slug === row.slug));
            const name = document.createElement('strong');
            name.textContent = row.name || row.title || row.slug;
            const chip = document.createElement('span');
            chip.className = 'review-chip';
            chip.dataset.tone = STAGE_TONE[stage(row)] || STATUS_TONE[row.status] || 'warn';
            chip.textContent = STAGE_TEXT[stage(row)];
            const sub = document.createElement('small');
            sub.textContent =
                `${reviewLabel(row.reviewState)} · ${row.bodyState ? row.bodyState.state : 'body ?'}` +
                ` · ${row.detailedLooks || 0} detailed looks · ${row.thumbnails || 0} thumbnails`;
            button.append(name, chip, sub);
            button.addEventListener('click', () => select(row.slug));
            item.append(button);
            return item;
        })
    );
}

function renderDetail() {
    const row = state.current;
    $('review-detail').hidden = !row;
    if (!row) return;
    $('review-name').textContent = row.name || row.title || row.slug;
    $('review-hash-pin').textContent = row.sha256;
    $('review-hash-local').textContent = state.localHash || 'loading…';
    const match = state.localHash ? state.localHash === row.sha256 : null;
    $('review-hash-match').textContent = match === null ? '' : match ? '✓ same file' : '✗ different file';
    $('review-licence').textContent = licenceLabel(row.licence);
    $('review-declared').textContent = row.operatorDeclaration ? 'yes (a declaration, not a review)' : 'no';
    $('review-body').textContent = bodyLabel(row.bodyState);
    $('review-state').textContent = row.review
        ? `${row.review.outcome}, by ${row.review.reviewer} on ${row.review.date}`
        : reviewLabel(row.reviewState);
    $('review-status').textContent = row.status;
    $('review-needs').replaceChildren(
        ...(row.requirements || []).map((need) => {
            const li = document.createElement('li');
            li.textContent = `${need.owner}: ${need.what}`;
            return li;
        })
    );
    renderDetailClearance(row);
    const pending = row.reviewState === 'pending';
    $('review-form').hidden = !pending;
    if (pending) {
        $('review-outcomes').replaceChildren(
            ...state.outcomes.map((outcome) => {
                const label = document.createElement('label');
                label.className = 'review-outcome';
                const input = document.createElement('input');
                input.type = 'radio';
                input.name = 'outcome';
                input.value = outcome;
                input.addEventListener('change', updateSubmit);
                const text = document.createElement('span');
                text.textContent = OUTCOME_TEXT[outcome] || outcome;
                label.append(input, text);
                return label;
            })
        );
    }
    updateSubmit();
}

/** CG10. Body detail: cleared or not, what is missing, and the packet and form when it can be done. */
function renderDetailClearance(row) {
    const d = row.detail || { cleared: false, missing: ['not known'] };
    $('review-detail-state').textContent = d.cleared
        ? `Cleared (${d.kind}${d.reviewer ? `, ${d.reviewer} on ${d.date}` : ''}).`
        : 'Not cleared: no body detail is painted on her, and her private looks and thumbnails are refused.';
    $('review-detail-missing').replaceChildren(...(d.missing || []).map((m) => el('li', { text: `Missing: ${m}` })));
    // The second look is possible only on a clearly-adult finding, and only once.
    const canWork = !d.cleared && !d.detailRecorded && row.review && row.review.outcome === 'clearly-adult';
    $('review-detail-work').hidden = !canWork;
    $('review-detail-form').hidden = !(canWork && row.packetReady);
    $('review-packet-btn').textContent = row.packetReady ? 'Make the review packet again' : 'Make the review packet';
    updateDetailSubmit();
}

function detailValues() {
    const row = state.current;
    return {
        reviewer: $('review-detail-reviewer').value,
        evidence: $('review-detail-evidence').value,
        examined: $('review-detail-examined').checked,
        localHash: state.localHash,
        pinnedHash: row && row.sha256,
        packetReady: Boolean(row && row.packetReady && !$('review-packet').hidden),
        needed: (row && row.detail && row.detail.needed) || 40,
    };
}

function updateDetailSubmit() {
    const v = detailValues();
    const n = (v.evidence || '').trim().length;
    $('review-detail-count').textContent = `${n} / ${v.needed} characters`;
    $('review-detail-submit').disabled = !canSubmitDetail(v);
}

async function makePacket() {
    const row = state.current;
    if (!row) return;
    showError('');
    $('review-packet-btn').disabled = true;
    try {
        const result = await api.reviewPacket(row.slug);
        row.packetReady = true;
        $('review-packet-text').textContent = result.markdown || JSON.stringify(result.packet, null, 1);
        $('review-packet').hidden = false;
        $('review-packet').open = true;
        renderDetailClearance(row);
    } catch (error) {
        showError(`Could not make the packet: ${error.message}`);
    } finally {
        $('review-packet-btn').disabled = false;
    }
}

async function submitDetail(event) {
    event.preventDefault();
    const v = detailValues();
    if (!canSubmitDetail(v)) return;
    const name = state.current.name || state.current.slug;
    if (!window.confirm(`Record your detail review of ${name} (${v.pinnedHash.slice(0, 12)}…) as ${v.reviewer.trim()}?\n\nIt is permanent for these exact bytes.`))
        return;
    try {
        const result = await api.recordDetailReview(state.current.slug, {
            sha256: v.localHash,
            reviewer: v.reviewer.trim(),
            evidence: v.evidence.trim(),
            examined: true,
        });
        const index = state.characters.findIndex((r) => r.slug === state.current.slug);
        state.characters[index] = result.character;
        state.current = result.character;
        renderAudit();
        renderList();
        renderDetail();
        $('review-done').textContent = `Recorded. To keep it, ${result.persist}.`;
        $('review-done').hidden = false;
    } catch (error) {
        showError(error instanceof ApiError ? error.message : String(error));
    }
}

function formValues() {
    const picked = document.querySelector('input[name="outcome"]:checked');
    return {
        outcome: picked ? picked.value : '',
        reviewer: $('review-reviewer').value,
        evidence: $('review-evidence').value,
        examined: $('review-examined').checked,
        localHash: state.localHash,
        pinnedHash: state.current && state.current.sha256,
        reviewState: state.current && state.current.reviewState,
    };
}

function updateSubmit() {
    $('review-submit').disabled = !canSubmit(formValues());
}

async function select(slug) {
    const row = state.characters.find((r) => r.slug === slug);
    if (!row) return;
    state.current = row;
    state.localHash = null;
    $('review-done').hidden = true;
    $('review-form').reset();
    $('review-detail-form').reset();
    $('review-packet').hidden = true;
    renderList();
    renderDetail();
    // CG4. The previous character leaves the stage before the next one loads, and her hash is
    // usable only once her own bytes have rendered and she is still the one selected: a finding
    // is permanent, so it must never be recordable for one file while another is on screen.
    if (state.viewer) state.viewer.clear('original');
    try {
        const blob = await api.libraryAvatarBlob(slug);
        const buffer = await blob.arrayBuffer();
        if (state.current !== row) return;
        const hash = await sha256Hex(buffer);
        if (state.blobUrl) URL.revokeObjectURL(state.blobUrl);
        state.blobUrl = URL.createObjectURL(new Blob([buffer], { type: 'model/gltf-binary' }));
        if (!state.viewer) state.viewer = new Viewer($('review-stage'));
        state.viewer.setPose('relaxed');
        await state.viewer.load('original', state.blobUrl);
        if (state.current !== row) return;
        state.viewer.frame();
        state.localHash = hash;
        renderDetail();
        updateSubmit();
        renderAudit();
    } catch (error) {
        console.warn('[review] could not load', slug, error);
        showError(`Could not load ${row.name || slug}: ${error.message}`);
    }
}

function wireViews() {
    for (const button of document.querySelectorAll('[data-view]')) {
        button.addEventListener('click', () => {
            if (!state.viewer) return;
            const view = button.dataset.view;
            if (view === 'turntable') {
                state.viewer.setTurntable(!state.viewer.controls.autoRotate);
                return;
            }
            state.viewer.setTurntable(false);
            state.viewer.turnTo(view);
        });
    }
}

async function submit(event) {
    event.preventDefault();
    const values = formValues();
    if (!canSubmit(values)) return;
    const name = state.current.name || state.current.slug;
    const sure = window.confirm(
        `Record "${values.outcome}" for ${name} (${values.pinnedHash.slice(0, 12)}…) as ${values.reviewer.trim()}?\n\n` +
            'A finding is permanent for these exact bytes.'
    );
    if (!sure) return;
    showError('');
    try {
        const result = await api.recordReview(state.current.slug, {
            sha256: values.localHash,
            outcome: values.outcome,
            reviewer: values.reviewer.trim(),
            evidence: values.evidence.trim(),
            examined: true,
        });
        const index = state.characters.findIndex((r) => r.slug === state.current.slug);
        state.characters[index] = result.character;
        state.current = result.character;
        renderAudit();
        renderList();
        renderDetail();
        $('review-done').textContent = `Recorded. To keep it, ${result.persist}.`;
        $('review-done').hidden = false;
    } catch (error) {
        showError(error instanceof ApiError ? error.message : String(error));
    }
}

/** CG9. Sign in right here, then load the characters: no trip back to the Studio. */
function showSignIn() {
    $('review-locked').hidden = false;
    $('review-signin-username').focus();
}

async function signIn(event) {
    event.preventDefault();
    const error = $('review-signin-error');
    error.hidden = true;
    $('review-signin-submit').disabled = true;
    try {
        const result = await api.adminSignIn($('review-signin-username').value.trim(), $('review-signin-password').value);
        admin.token = result.token;
        $('review-signin-password').value = '';
        $('review-locked').hidden = true;
        await start();
    } catch (failure) {
        error.textContent =
            failure instanceof ApiError && failure.status === 401
                ? 'Wrong username or password.'
                : `Could not log in: ${(failure && failure.message) || failure}`;
        error.hidden = false;
    } finally {
        $('review-signin-submit').disabled = false;
    }
}

let wired = false;

async function start() {
    if (!admin.token) {
        showSignIn();
        return;
    }
    try {
        const data = await api.reviews();
        state.characters = data.characters || [];
        state.outcomes = data.outcomes || [];
        state.notOnDisk = data.notOnDisk || [];
        if (data.notOnDisk && data.notOnDisk.length) {
            $('review-missing').textContent = `Not on this disk, not evaluated: ${data.notOnDisk.join(', ')}`;
            $('review-missing').hidden = false;
        }
    } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
            admin.token = '';
            showSignIn();
            return;
        }
        showError(`Could not read the characters: ${error.message}`);
        return;
    }
    $('review-main').hidden = false;
    renderAudit();
    renderList();
    if (!wired) {
        wired = true;
        wireViews();
        for (const id of ['review-reviewer', 'review-evidence', 'review-examined']) {
            $(id).addEventListener('input', updateSubmit);
            $(id).addEventListener('change', updateSubmit);
        }
        $('review-form').addEventListener('submit', submit);
        $('review-packet-btn').addEventListener('click', makePacket);
        $('review-detail-form').addEventListener('submit', submitDetail);
        for (const id of ['review-detail-reviewer', 'review-detail-evidence', 'review-detail-examined']) {
            $(id).addEventListener('input', updateDetailSubmit);
            $(id).addEventListener('change', updateDetailSubmit);
        }
    }
    // CG9. Open a character at once: the first one still waiting for a review, else the first.
    // An empty right-hand two thirds read as a broken page.
    const first =
        state.characters.find((row) => stage(row) === 'needs-review') ||
        state.characters.find((row) => stage(row) === 'needs-detail') ||
        state.characters[0];
    if (first && !state.current) select(first.slug);
}

if (typeof document !== 'undefined' && document.getElementById('review-main')) {
    $('review-locked').addEventListener('submit', signIn);
    start();
}
