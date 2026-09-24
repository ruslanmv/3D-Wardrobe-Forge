/**
 * Wardrobe Studio: pick an avatar, design a garment, judge the fit, export.
 *
 * Nothing here decides anything the server should. The controls are built from
 * `/v1/vocabulary`, so the editor never offers a colour or a cut the planner
 * would ignore; jobs go to `/v1/library/{slug}/jobs`, where the server — not the
 * browser — supplies the avatar and the licence its provenance manifest grants;
 * and the progress list is the pipeline's own state machine, not a timer
 * pretending to be one.
 */

import { api, auth, ApiError } from './api.js';
import { Viewer } from './viewer.js';

const $ = (id) => document.getElementById(id);

const STEP_LABELS = {
    queued: 'Queued',
    validating: 'Checking the avatar',
    'analyzing-avatar': 'Measuring the body',
    'planning-outfit': 'Planning the outfit',
    'generating-garment': 'Building the garment',
    fitting: 'Fitting to the body',
    skinning: 'Binding to the skeleton',
    'resolving-clipping': 'Checking clearance',
    exporting: 'Exporting the VRM',
    'validating-output': 'Validating the result',
    'rendering-preview': 'Rendering a preview',
};

const HEM_WORDS = { mini: 'mini', knee: 'knee-length', midi: 'midi', ankle: 'ankle-length', floor: 'floor-length' };

const CHECKS = [
    ['vrmValid', 'VRM valid'],
    ['humanoidValid', 'Humanoid intact'],
    ['weightsValid', 'Skin weights'],
    ['skeletonPreserved', 'Skeleton kept'],
    ['expressionsPreserved', 'Expressions kept'],
    ['sourceRecoverable', 'Source recoverable'],
];

const POLL_MS = 600;

const state = {
    caps: null,
    vocab: null,
    library: [],
    avatar: null,
    design: { category: null, templateId: null, silhouette: null, hem: null, color: null },
    promptDirty: false,
    wardrobe: null,
    activeLookId: null,
    jobId: null,
    urls: { original: null, look: null, previews: [] },
};

let viewer = null;

// ---------------------------------------------------------------- helpers
function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key === 'style') node.style.cssText = value;
        else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) if (child) node.append(child);
    return node;
}

function setStatus(message, isError = false) {
    const node = $('stage-status');
    node.textContent = message || '';
    node.classList.toggle('error', Boolean(isError));
}

function describe(error) {
    if (error instanceof ApiError && error.status === 401) return 'This Space needs an API key — use the key button.';
    return error && error.message ? error.message : String(error);
}

function revoke(url) {
    if (url) URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- boot
async function boot() {
    viewer = new Viewer($('stage-canvas'));
    bindChrome();

    let loaded;
    try {
        loaded = await Promise.all([api.capabilities(), api.vocabulary(), api.library()]);
    } catch (error) {
        setStatus(describe(error), true);
        $('library-note').textContent = 'unavailable';
        if (error instanceof ApiError && error.status === 401) $('key-dialog').showModal();
        return;
    }
    const [caps, vocab, library] = loaded;
    state.caps = caps;
    state.vocab = vocab;
    state.library = library.avatars;

    renderCaps();
    renderLibrary(library);
    renderDesigner();

    const wanted = new URLSearchParams(location.search).get('avatar');
    const first =
        state.library.find((avatar) => avatar.slug === wanted && avatar.available) ||
        state.library.find((avatar) => avatar.available);
    if (first) selectAvatar(first.slug);
    else setStatus(library.problem || 'No avatar in the library is available — run tools/fetch_library.py.', true);
}

function bindChrome() {
    document.querySelectorAll('[data-tab-target]').forEach((button) =>
        button.addEventListener('click', () => {
            $('library').closest('.app').dataset.tab = button.dataset.tabTarget;
            document
                .querySelectorAll('[data-tab-target]')
                .forEach((other) => other.setAttribute('aria-selected', String(other === button)));
        })
    );

    $('view-mode').addEventListener('click', (event) => {
        const button = event.target.closest('[data-mode]');
        if (button && !button.disabled) setViewMode(button.dataset.mode);
    });

    $('pose-btn').addEventListener('click', (event) => {
        const rest = event.currentTarget.getAttribute('aria-pressed') !== 'true';
        event.currentTarget.setAttribute('aria-pressed', String(rest));
        viewer.setPose(rest ? 'rest' : 'relaxed');
    });

    $('spin-btn').addEventListener('click', (event) => {
        const on = event.currentTarget.getAttribute('aria-pressed') !== 'true';
        event.currentTarget.setAttribute('aria-pressed', String(on));
        viewer.setTurntable(on);
    });

    $('frame-btn').addEventListener('click', () => viewer.frame());

    $('key-btn').addEventListener('click', () => {
        $('key-input').value = auth.key;
        $('key-dialog').showModal();
    });
    $('key-dialog').addEventListener('close', () => {
        const choice = $('key-dialog').returnValue;
        if (choice === 'save') auth.key = $('key-input').value.trim();
        if (choice === 'clear') auth.key = '';
        if (choice === 'save' || choice === 'clear') location.reload();
    });
    $('key-btn').classList.toggle('has-key', Boolean(auth.key));

    $('design-form').addEventListener('submit', (event) => {
        event.preventDefault();
        generate();
    });
    $('prompt').addEventListener('input', () => {
        state.promptDirty = $('prompt').value.trim().length > 0;
        updatePreview();
    });
    $('export-btn').addEventListener('click', exportBundle);
}

// ---------------------------------------------------------------- capabilities
function renderCaps() {
    const { engines, templates, strictLicensing } = state.caps;
    const pills = [
        [`Engine: ${engines.blender ? 'Blender' : 'native'}`, 'on'],
        [
            engines.bodyMasking ? 'Body masking on' : 'Body masking off',
            engines.bodyMasking ? 'on' : 'off',
            engines.bodyMasking
                ? 'Covered body polygons are removed under the garment.'
                : 'The native engine cannot hide the body under a garment. Layered garments fit best.',
        ],
        [`${templates} templates`, 'on'],
        [strictLicensing ? 'Strict licensing' : 'Licensing relaxed', strictLicensing ? 'on' : 'off'],
    ];
    $('caps').replaceChildren(
        ...pills.map(([text, tone, title]) => el('span', { class: `pill ${tone}`, title, text }))
    );
}

// ---------------------------------------------------------------- library
function renderLibrary(library) {
    const available = state.library.filter((avatar) => avatar.available).length;
    $('library-note').textContent = `${available} of ${state.library.length}`;
    $('provenance').textContent = library.licenseNote || '';
    $('avatar-list').replaceChildren(
        ...state.library.map((avatar) =>
            el(
                'li',
                {},
                el(
                    'button',
                    {
                        class: 'avatar',
                        type: 'button',
                        'data-slug': avatar.slug,
                        disabled: !avatar.available,
                        title: avatar.problem || `${avatar.license} · sha256 ${avatar.sha256.slice(0, 12)}…`,
                        onclick: () => {
                            selectAvatar(avatar.slug);
                            $('library').closest('.app').dataset.tab = 'design';
                            document
                                .querySelectorAll('[data-tab-target]')
                                .forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tabTarget === 'design')));
                        },
                    },
                    el('span', { class: 'avatar-glyph', text: initials(avatar.name) }),
                    el(
                        'span',
                        { class: 'avatar-meta' },
                        el('span', { class: 'avatar-name', text: avatar.name }),
                        el('span', {
                            class: 'avatar-sub',
                            text: avatar.available
                                ? `${avatar.presentation || 'avatar'} · ${(avatar.sizeBytes / 1048576).toFixed(1)} MB`
                                : avatar.problem,
                        })
                    ),
                    el('span', {
                        class: `avatar-badge${avatar.available ? '' : ' missing'}`,
                        text: avatar.available ? avatar.license : 'missing',
                    })
                )
            )
        )
    );
}

function initials(name) {
    return (
        name
            .split(/\s+/)
            .map((word) => word[0])
            .join('')
            .slice(0, 2)
            .toUpperCase() || '?'
    );
}

async function selectAvatar(slug) {
    const avatar = state.library.find((item) => item.slug === slug);
    if (!avatar || !avatar.available) return;
    state.avatar = avatar;
    state.activeLookId = null;
    history.replaceState(null, '', `?avatar=${encodeURIComponent(slug)}`);

    document
        .querySelectorAll('.avatar')
        .forEach((node) => node.setAttribute('aria-current', String(node.dataset.slug === slug)));
    $('stage-name').textContent = avatar.name;
    $('stage-sub').textContent = `${avatar.license} · ${avatar.presentation || 'avatar'}`;
    $('stage-empty').hidden = true;
    $('generate-btn').disabled = false;
    $('report').hidden = true;
    updatePreview();

    viewer.clear('look');
    revoke(state.urls.look);
    state.urls.look = null;
    setViewMode('original');

    setStatus(`Loading ${avatar.name}…`);
    const token = slug;
    try {
        const url = await api.blobUrl(avatar.fileUrl);
        if (state.avatar.slug !== token) return revoke(url);
        revoke(state.urls.original);
        state.urls.original = url;
        const landed = await viewer.load('original', url);
        if (landed) {
            viewer.frame();
            setStatus('');
        }
    } catch (error) {
        setStatus(`Could not load ${avatar.name}: ${describe(error)}`, true);
    }
    await loadWardrobe();
}

// ---------------------------------------------------------------- view modes
function setViewMode(mode) {
    const hasLook = viewer.has('look');
    if (mode !== 'original' && !hasLook) mode = 'original';
    document.querySelectorAll('#view-mode [data-mode]').forEach((button) => {
        button.disabled = button.dataset.mode !== 'original' && !hasLook;
        button.setAttribute('aria-checked', String(button.dataset.mode === mode));
    });
    viewer.setMode(mode);
}

// ---------------------------------------------------------------- designer
function renderDesigner() {
    const { overrides, promptWords } = state.vocab;

    const categoryChips = [null, ...overrides.category].map((category) =>
        el('button', {
            class: 'chip',
            type: 'button',
            role: 'radio',
            'aria-checked': String(category === state.design.category),
            text: category || 'Any',
            onclick: () => {
                state.design.category = category;
                state.design.templateId = null;
                renderDesigner();
                loadTemplates();
            },
        })
    );
    $('category-chips').replaceChildren(...categoryChips);

    fillSelect($('silhouette-select'), overrides.silhouette, state.design.silhouette, (value) => {
        state.design.silhouette = value;
        updatePreview();
    });
    fillSelect($('hem-select'), overrides.hem, state.design.hem, (value) => {
        state.design.hem = value;
        updatePreview();
    });

    const swatches = [
        el('button', {
            class: 'swatch auto',
            type: 'button',
            role: 'radio',
            title: 'Planner chooses',
            'aria-label': 'Planner chooses',
            'aria-checked': String(state.design.color === null),
            onclick: () => pickColor(null),
        }),
        ...overrides.color.map((color) =>
            el('button', {
                class: 'swatch',
                type: 'button',
                role: 'radio',
                title: color.name,
                'aria-label': color.name,
                'aria-checked': String(state.design.color === color.name),
                style: `--swatch:${color.hex}`,
                onclick: () => pickColor(color.name),
            })
        ),
    ];
    $('swatches').replaceChildren(...swatches);
    $('color-value').textContent = state.design.color || 'Planner chooses';

    const words = [...promptWords.fabric, ...Object.values(promptWords.sleeve)];
    $('word-chips').replaceChildren(
        ...words.map((word) =>
            el('button', {
                class: 'chip',
                type: 'button',
                'aria-pressed': String(hasWord(word)),
                text: word,
                onclick: () => toggleWord(word),
            })
        )
    );

    if (!$('template-select').options.length) loadTemplates();
    updatePreview();
}

function fillSelect(select, values, current, onChange) {
    select.replaceChildren(
        el('option', { value: '', text: 'Planner chooses' }),
        ...values.map((value) => el('option', { value, text: value, selected: value === current }))
    );
    select.onchange = () => onChange(select.value || null);
}

async function loadTemplates() {
    const select = $('template-select');
    try {
        const templates = await api.templates(state.design.category);
        select.replaceChildren(
            el('option', { value: '', text: state.design.category ? 'Planner chooses' : 'Planner chooses from all' }),
            ...templates.map((template) =>
                el('option', {
                    value: template.id,
                    text: `${template.name} · ${template.category}`,
                    'data-name': template.name.toLowerCase(),
                    selected: template.id === state.design.templateId,
                })
            )
        );
        select.onchange = () => {
            state.design.templateId = select.value || null;
            updatePreview();
        };
    } catch (error) {
        select.replaceChildren(el('option', { value: '', text: 'Templates unavailable' }));
    }
    updatePreview();
}

function pickColor(name) {
    state.design.color = name;
    renderDesigner();
}

function hasWord(word) {
    return new RegExp(`(^|\\s)${word}(\\s|$)`, 'i').test($('prompt').value);
}

/**
 * Fabric and sleeve have no override field — the planner reads them only from
 * the prompt — so the chip edits the prompt, visibly, rather than pretending to
 * send a value the API does not accept.
 */
function toggleWord(word) {
    const prompt = $('prompt');
    // An untouched prompt is only a placeholder; start from the composed description
    // so one chip adds a word to "black pencil knee-length skirt" rather than
    // replacing the whole request with "satin".
    if (!state.promptDirty) prompt.value = composedPrompt();
    prompt.value = hasWord(word)
        ? prompt.value.replace(new RegExp(`(^|\\s)${word}(?=\\s|$)`, 'i'), ' ').replace(/\s+/g, ' ').trim()
        : `${word} ${prompt.value}`.trim();
    state.promptDirty = prompt.value.length > 0;
    renderDesigner();
}

/** What the planner will be asked, composed from the controls when the user has not written it. */
function composedPrompt() {
    const typed = $('prompt').value.trim();
    if (state.promptDirty && typed) return typed;
    const templateName = $('template-select').selectedOptions[0]?.dataset?.name;
    const parts = [
        state.design.color,
        state.design.silhouette,
        state.design.hem ? HEM_WORDS[state.design.hem] : null,
        state.design.category || templateName || 'outfit',
    ].filter(Boolean);
    return parts.join(' ');
}

function outfitRequest() {
    const outfit = { prompt: composedPrompt(), mode: 'template' };
    for (const key of ['category', 'color', 'silhouette', 'hem']) if (state.design[key]) outfit[key] = state.design[key];
    if (state.design.templateId) outfit.templateId = state.design.templateId;
    return outfit;
}

function updatePreview() {
    const outfit = outfitRequest();
    if (!state.promptDirty) $('prompt').placeholder = outfit.prompt;
    const fields = Object.entries(outfit)
        .filter(([key]) => key !== 'prompt' && key !== 'mode')
        .map(([key, value]) => `${key}=${value}`);
    $('request-preview').textContent = state.avatar
        ? `→ ${state.avatar.slug} · ${fields.join(' · ') || 'planner decides'} · "${outfit.prompt}"`
        : '';
}

// ---------------------------------------------------------------- generation
async function generate() {
    if (!state.avatar || state.jobId) return;
    const slug = state.avatar.slug;
    const outfit = outfitRequest();
    if (outfit.prompt.length < 2) return setStatus('Describe the garment first.', true);

    $('generate-btn').disabled = true;
    $('report').hidden = true;
    showJob({ state: 'queued', events: [] }, outfit.prompt);

    let job;
    try {
        job = await api.createLibraryJob(slug, {
            outfit,
            options: { renderPreview: true, engine: state.caps.engines.default || 'auto' },
        });
    } catch (error) {
        return finishJob({ state: 'failed', error: describe(error), events: [] }, slug, outfit.prompt);
    }

    state.jobId = job.id;
    while (state.jobId === job.id) {
        try {
            job = await api.job(job.id);
        } catch (error) {
            return finishJob({ state: 'failed', error: describe(error), events: [] }, slug, outfit.prompt);
        }
        showJob(job, outfit.prompt);
        if (state.vocab.terminalStates.includes(job.state)) break;
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    }
    await finishJob(job, slug, outfit.prompt);
}

function showJob(job, prompt) {
    const reached = new Set((job.events || []).map((event) => event.state));
    reached.add(job.state);
    const terminal = state.vocab.terminalStates.includes(job.state);
    $('job').hidden = false;
    $('job').classList.toggle('failed', job.state === 'failed' || job.state === 'rejected');
    $('job-title').textContent = prompt ? `“${prompt}”` : 'Generating';
    $('job-state').textContent = terminal ? job.state : STEP_LABELS[job.state] || job.state;
    $('steps').replaceChildren(
        ...state.vocab.jobStates.map((step) => {
            const done = reached.has(step) && (terminal || step !== job.state);
            const active = !terminal && step === job.state;
            return el('li', { class: done ? 'done' : active ? 'active' : '', text: STEP_LABELS[step] || step });
        })
    );
    const last = (job.events || []).at(-1);
    $('job-message').textContent = job.error || (last && last.message) || '';
}

async function finishJob(job, slug, prompt) {
    state.jobId = null;
    $('generate-btn').disabled = !state.avatar;
    showJob(job, prompt);
    if (job.state !== 'completed') {
        $('job-message').textContent = job.error || `The job ended ${job.state}.`;
        return;
    }
    renderReport(job.fitReport);
    if (state.avatar && state.avatar.slug === slug) {
        await loadWardrobe();
        if (job.look) await wearLook(job.look.id, { mode: 'compare' });
    }
}

function renderReport(report) {
    if (!report) return;
    const passed =
        CHECKS.every(([key]) => key === 'expressionsPreserved' || report[key]) &&
        ['passed', 'clearance-only', 'warnings'].includes(report.clippingCheck);
    const clippingWarning = (report.warnings || []).find((warning) => /intersect|clip/i.test(warning));
    const lines = [
        el('h3', { text: passed ? 'Fit report · passed' : 'Fit report · needs work' }),
        el(
            'ul',
            { class: 'checks' },
            CHECKS.map(([key, label]) => el('li', { class: report[key] ? '' : 'no', text: label }))
        ),
        el('p', {
            class: `report-line ${report.clippingCheck === 'failed' ? 'bad' : report.clippingCheck === 'warnings' ? 'warn' : ''}`,
            text: `Clearance: ${report.clippingCheck}${clippingWarning ? ` — ${clippingWarning}` : ''}`,
        }),
        el('p', {
            class: 'report-line',
            text: `${report.garmentVertices} vertices · ${report.garmentTriangles} triangles · ${report.engine} engine`,
        }),
    ];
    if (report.clippingCheck === 'failed' && !state.caps.engines.bodyMasking) {
        lines.push(
            el('p', {
                class: 'report-line warn',
                text: 'This engine cannot hide the body under a garment, so what she was already wearing shows through. Garments that layer over the outfit — skirts, jackets — fit best here; replacing a garment needs the Blender engine.',
            })
        );
    }
    $('report').replaceChildren(...lines);
    $('report').hidden = false;
}

// ---------------------------------------------------------------- wardrobe
async function loadWardrobe() {
    const slug = state.avatar && state.avatar.slug;
    if (!slug) return;
    let manifest = null;
    try {
        manifest = await api.wardrobe(slug);
    } catch (error) {
        setStatus(`Wardrobe unavailable: ${describe(error)}`, true);
    }
    if (!state.avatar || state.avatar.slug !== slug) return;
    state.wardrobe = manifest;
    await renderWardrobe();
}

async function renderWardrobe() {
    state.urls.previews.forEach(revoke);
    state.urls.previews = [];
    const looks = ((state.wardrobe && state.wardrobe.looks) || []).filter(
        (look) => look.type !== 'source' && look.vrmUrl
    );
    $('look-count').textContent = looks.length ? `${looks.length}` : '';
    $('export-btn').disabled = looks.length === 0;

    if (!looks.length) {
        $('looks').replaceChildren(
            el('p', { class: 'looks-empty', text: 'No looks yet — design one and it appears here.' })
        );
        return;
    }

    const cards = looks
        .slice()
        .reverse()
        .map((look) => {
            const picture = el('span', { class: 'look-ph', text: '👗' });
            if (look.previewUrl) {
                api.blobUrl(look.previewUrl)
                    .then((url) => {
                        state.urls.previews.push(url);
                        picture.replaceWith(el('img', { src: url, alt: '', loading: 'lazy' }));
                    })
                    .catch(() => {});
            }
            return el(
                'article',
                { class: 'look', 'data-look': look.id, 'aria-current': String(look.id === state.activeLookId) },
                el(
                    'button',
                    { class: 'look-open', type: 'button', title: look.prompt || look.name, onclick: () => wearLook(look.id) },
                    picture,
                    el(
                        'span',
                        { class: 'look-body' },
                        el('span', { class: 'look-name', text: look.name }),
                        el('span', {
                            class: `look-fit${look.fitPassed === false ? ' failed' : ''}`,
                            text: look.fitPassed === false ? 'fit needs work' : look.fitPassed ? 'fit passed' : 'unchecked',
                        })
                    )
                ),
                el('button', {
                    class: 'look-del',
                    type: 'button',
                    title: 'Remove from wardrobe',
                    'aria-label': `Remove ${look.name}`,
                    text: '×',
                    onclick: () => removeLook(look),
                })
            );
        });
    $('looks').replaceChildren(...cards);
}

async function wearLook(lookId, { mode = null } = {}) {
    const look = state.wardrobe && state.wardrobe.looks.find((item) => item.id === lookId);
    if (!look) return;
    state.activeLookId = lookId;
    document
        .querySelectorAll('.look')
        .forEach((node) => node.setAttribute('aria-current', String(node.dataset.look === lookId)));
    setStatus(`Loading ${look.name}…`);
    try {
        const url = await api.blobUrl(look.vrmUrl);
        if (state.activeLookId !== lookId) return revoke(url);
        const landed = await viewer.load('look', url);
        if (!landed) return revoke(url);
        revoke(state.urls.look);
        state.urls.look = url;
        setViewMode(mode || (viewer.mode === 'original' ? 'compare' : viewer.mode));
        setStatus(look.prompt ? `“${look.prompt}”` : look.name);
    } catch (error) {
        setStatus(`Could not load ${look.name}: ${describe(error)}`, true);
    }
}

async function removeLook(look) {
    if (!confirm(`Remove “${look.name}” from ${state.avatar.name}'s wardrobe?`)) return;
    try {
        await api.removeLook(state.avatar.slug, look.id);
    } catch (error) {
        return setStatus(describe(error), true);
    }
    if (state.activeLookId === look.id) {
        state.activeLookId = null;
        viewer.clear('look');
        revoke(state.urls.look);
        state.urls.look = null;
        setViewMode('original');
    }
    await loadWardrobe();
}

async function exportBundle() {
    if (!state.avatar) return;
    const button = $('export-btn');
    button.disabled = true;
    button.textContent = 'Packing…';
    try {
        const blob = await api.bundle(state.avatar.slug, $('passed-only').checked);
        const url = URL.createObjectURL(blob);
        const link = el('a', { href: url, download: `${state.avatar.slug}-wardrobe.zip` });
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        setStatus(`Exported ${(blob.size / 1048576).toFixed(1)} MB — unzip into vendor/wardrobe/.`);
    } catch (error) {
        setStatus(describe(error), true);
    } finally {
        button.textContent = 'Export bundle';
        button.disabled = false;
    }
}

boot();
