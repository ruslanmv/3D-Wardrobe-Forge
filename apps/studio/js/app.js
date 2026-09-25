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
    design: {
        category: null,
        templateId: null,
        silhouette: null,
        hem: null,
        color: null,
        finish: null,
        pattern: null,
        opacity: null,
        coverage: null,
        straps: null,
        neckline: null,
    },
    // Hosiery & suspenders: off until asked for; a preset fills the rest (wardrobe.hosiery).
    hosiery: {
        on: false,
        preset: null,
        reveal: 'glimpse',
        type: 'sheer',
        denier: 20,
        topStyle: 'wide',
        rolledEdge: true,
        seam: false,
        belt: 'classic',
        strapCount: 4,
        hardware: 'silver',
    },
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
    $('build-on').addEventListener('change', updatePreview);
    $('plan-btn').addEventListener('click', checkPlan);
    $('base-body-select').addEventListener('change', () => ($('plan-report').hidden = true));
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
                : 'The native engine cannot hide body polygons, but it takes off the avatar\'s own clothes where it can recognise them.',
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
    $('plan-btn').disabled = false;
    $('plan-report').hidden = true;
    $('report').hidden = true;
    if (state.vocab) renderDesigner();

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

    const adult = Boolean(state.avatar && state.avatar.depictsAdult);
    const needsAdult = (category) => state.vocab.intimateCategories.includes(category);
    const categoryChips = [null, ...overrides.category].map((category) =>
        el('button', {
            class: 'chip',
            type: 'button',
            role: 'radio',
            'aria-checked': String(category === state.design.category),
            text: category || 'Any',
            disabled: category && needsAdult(category) && !adult,
            title:
                category && needsAdult(category) && !adult
                    ? 'Needs this avatar declared as depicting an adult, by the operator, in assets/library/policy.json'
                    : undefined,
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

    renderStyle(adult);
    renderHosiery(adult);

    const words = [...promptWords.fabric, ...Object.values(promptWords.sleeve), ...(promptWords.cut || [])];
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

/**
 * The style layer. Every choice is an ``OutfitRequest`` override, so it wins
 * over the prompt. Choices that make the body show through — sheer levels and
 * fishnet — are disabled, with the reason, for an avatar the operator has not
 * declared adult; the server refuses them anyway, this only says so first.
 */
function renderStyle(adult) {
    const { overrides } = state.vocab;
    const seeThrough = new Set(state.vocab.seeThroughPatterns || []);
    const reason = 'Shows the body: needs this avatar declared as depicting an adult (assets/library/policy.json)';

    const chips = (id, key, values, { label = (v) => v, value = (v) => v, gated = () => false } = {}) =>
        $(id).replaceChildren(
            ...[null, ...values].map((item) => {
                const v = item === null ? null : value(item);
                const blocked = item !== null && gated(item) && !adult;
                if (blocked && state.design[key] === v) state.design[key] = null;
                return el('button', {
                    class: 'chip',
                    type: 'button',
                    role: 'radio',
                    'aria-checked': String(state.design[key] === v),
                    text: item === null ? 'Auto' : label(item),
                    disabled: blocked,
                    title: blocked ? reason : undefined,
                    onclick: () => {
                        state.design[key] = v;
                        renderDesigner();
                    },
                });
            })
        );

    chips('finish-chips', 'finish', overrides.finish);
    chips('pattern-chips', 'pattern', overrides.pattern.filter((p) => p !== 'none'), {
        gated: (p) => seeThrough.has(p),
    });
    chips('opacity-chips', 'opacity', overrides.opacity.filter((o) => o.value < 1), {
        label: (o) => o.name,
        value: (o) => o.value,
        gated: () => true,
    });
    chips('coverage-chips', 'coverage', overrides.coverage);
    fillSelect($('straps-select'), overrides.straps, state.design.straps, (value) => {
        state.design.straps = value;
        updatePreview();
    });
    fillSelect($('neckline-select'), overrides.neckline, state.design.neckline, (value) => {
        state.design.neckline = value;
        updatePreview();
    });
    const underwearBase = $('base-body-select').querySelector('option[value="underwear-base"]');
    underwearBase.disabled = !adult;
    underwearBase.title = adult ? '' : 'Underwear needs this avatar declared as depicting an adult';
    if (!adult && $('base-body-select').value === 'underwear-base') $('base-body-select').value = 'replace-outer';
    $('style-hint').textContent = adult ? 'overrides the prompt' : 'overrides the prompt · see-through needs an adult declaration';
}

const REVEAL_HINTS = {
    discreet: 'Hidden standing, walking and seated',
    glimpse: 'Hidden standing and walking; the tops show when she sits',
    statement: 'Tops, clasps and strap ends show below the hem',
};

/**
 * Hosiery & Suspenders, disclosed a step at a time: one switch, then the look (a preset)
 * and the reveal, then the stockings, and the belt and hardware folded away. The whole
 * section needs an adult declaration: a suspender belt is underwear and sheer or fishnet
 * stockings show the body. The server refuses it anyway; this only says so first.
 */
function renderHosiery(adult) {
    const vocab = state.vocab.hosiery;
    const h = state.hosiery;
    if (!vocab) return ($('hosiery-fieldset').hidden = true);
    $('hosiery-on').disabled = !adult;
    if (!adult) h.on = false;
    $('hosiery-on').checked = h.on;
    $('hosiery-on').onchange = () => {
        h.on = $('hosiery-on').checked;
        renderDesigner();
    };
    $('hosiery-hint').textContent = adult
        ? 'stockings publish their tops; straps clip to them'
        : 'needs this avatar declared as depicting an adult (assets/library/policy.json)';
    $('hosiery-controls').hidden = !h.on;
    if (!h.on) return;

    const radio = (id, values, current, label, pick) =>
        $(id).replaceChildren(
            ...values.map((value) =>
                el('button', {
                    class: 'chip',
                    type: 'button',
                    role: 'radio',
                    'aria-checked': String(current === value),
                    text: label(value),
                    onclick: () => {
                        pick(value);
                        renderDesigner();
                    },
                })
            )
        );
    radio('hosiery-presets', vocab.presets.map((p) => p.id), h.preset, (id) => vocab.presets.find((p) => p.id === id).title, (id) => {
        const preset = vocab.presets.find((p) => p.id === id);
        h.preset = id;
        h.reveal = preset.reveal.level;
        Object.assign(h, {
            type: preset.hosiery.type || 'sheer',
            denier: preset.hosiery.denier || (preset.hosiery.type === 'fishnet' ? 60 : 20),
            topStyle: preset.hosiery.topStyle || 'plain',
            seam: Boolean(preset.hosiery.backSeam && preset.hosiery.backSeam.enabled) || preset.hosiery.type === 'seamed',
            belt: preset.suspenderBelt.style,
            strapCount: preset.suspenderBelt.strapCount || 4,
            hardware: (preset.suspenderBelt.hardware || {}).color || 'silver',
        });
        state.promptDirty = true;
        $('prompt').value = preset.prompt;
    });
    radio('reveal-chips', vocab.revealLevels, h.reveal, (v) => v[0].toUpperCase() + v.slice(1), (v) => (h.reveal = v));
    $('reveal-hint').textContent = REVEAL_HINTS[h.reveal] || '';
    radio('top-chips', vocab.topStyles, h.topStyle, (v) => v, (v) => (h.topStyle = v));
    radio('hardware-chips', vocab.hardwareColors, h.hardware, (v) => v, (v) => (h.hardware = v));
    const select = (id, values, current, label, pick) => {
        $(id).replaceChildren(...values.map((v) => el('option', { value: String(v), text: label(v), selected: v === current })));
        $(id).onchange = () => {
            pick($(id).value);
            updatePreview();
        };
    };
    select('hosiery-type', vocab.types, h.type, (v) => v.replace('_', ' '), (v) => (h.type = v));
    select('hosiery-denier', vocab.deniers, h.denier, (v) => `${v} den`, (v) => (h.denier = Number(v)));
    select('belt-style', vocab.beltStyles, h.belt, (v) => v.replace('_', '-'), (v) => (h.belt = v));
    select('strap-count', vocab.strapCounts, h.strapCount, (v) => `${v} straps`, (v) => (h.strapCount = Number(v)));
    $('rolled-edge').checked = h.rolledEdge;
    $('rolled-edge').onchange = () => (h.rolledEdge = $('rolled-edge').checked);
    $('back-seam').checked = h.seam;
    $('back-seam').onchange = () => (h.seam = $('back-seam').checked);
}

function hosieryRequest() {
    const h = state.hosiery;
    if (!h.on) return {};
    return {
        ...(h.preset ? { preset: h.preset } : {}),
        hosiery: {
            type: h.type,
            ...(h.type === 'fishnet' ? {} : { denier: h.denier }),
            topStyle: h.topStyle,
            rolledEdge: h.rolledEdge,
            backSeam: { enabled: h.seam },
        },
        suspenderBelt: {
            style: h.belt,
            strapCount: h.strapCount,
            hardware: { color: h.hardware },
        },
        reveal: { level: h.reveal },
    };
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
    const opacity = (state.vocab.overrides.opacity || []).find((o) => o.value === state.design.opacity);
    const parts = [
        state.design.color,
        opacity && opacity.value < 1 ? opacity.name : null,
        state.design.finish && state.design.finish !== 'matte' ? state.design.finish : null,
        state.design.pattern,
        state.design.coverage && state.design.coverage !== 'standard' ? state.design.coverage : null,
        state.design.silhouette,
        state.design.hem ? HEM_WORDS[state.design.hem] : null,
        state.design.category || templateName || 'outfit',
    ].filter(Boolean);
    return parts.join(' ');
}

function outfitRequest() {
    const outfit = { prompt: composedPrompt(), mode: 'template' };
    for (const key of ['category', 'color', 'silhouette', 'hem', 'finish', 'pattern', 'coverage', 'straps', 'neckline'])
        if (state.design[key]) outfit[key] = state.design[key];
    if (state.design.opacity !== null && state.design.opacity < 1) outfit.opacity = state.design.opacity;
    if (state.design.templateId) outfit.templateId = state.design.templateId;
    return { ...outfit, ...hosieryRequest() };
}

function updatePreview() {
    const outfit = outfitRequest();
    if (!state.promptDirty) $('prompt').placeholder = outfit.prompt;
    const fields = Object.entries(outfit)
        .filter(([key]) => key !== 'prompt' && key !== 'mode')
        .map(([key, value]) => (typeof value === 'object' ? key : `${key}=${value}`));
    const base = buildOnLook();
    $('request-preview').textContent = state.avatar
        ? `→ ${state.avatar.slug}${base ? ` + ${base.name}` : ''} · ${fields.join(' · ') || 'planner decides'} · "${outfit.prompt}"`
        : '';
}

/** The look on stage, when the user asked to build on it (an outfit set). */
function buildOnLook() {
    const look = state.wardrobe && state.activeLookId && state.wardrobe.looks.find((l) => l.id === state.activeLookId);
    const box = $('build-on');
    box.disabled = !look;
    if (!look) box.checked = false;
    $('build-on-text').textContent = look ? `Build on “${look.name}”` : 'Build on the look on stage';
    return look && box.checked ? look : null;
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
        const base = buildOnLook();
        job = await api.createLibraryJob(slug, jobBody(outfit));
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

function jobBody(outfit) {
    const base = buildOnLook();
    return {
        outfit,
        ...(base ? { baseLookId: base.id } : {}),
        options: {
            renderPreview: true,
            engine: state.caps.engines.default || 'auto',
            baseBody: $('base-body-select').value,
        },
    };
}

/** "Before you generate": each garment's layer and gate, what comes off, and the body under it. */
async function checkPlan() {
    if (!state.avatar) return;
    const box = $('plan-report');
    box.hidden = false;
    box.replaceChildren(el('p', { class: 'report-line', text: 'Checking…' }));
    let report;
    try {
        report = await api.planLibrary(state.avatar.slug, jobBody(outfitRequest()));
    } catch (error) {
        return box.replaceChildren(el('p', { class: 'report-line bad', text: describe(error) }));
    }
    const lines = report.garments.map((g) =>
        el(
            'li',
            { class: g.allowed ? '' : 'no', title: g.refusal || '' },
            el('span', { class: 'plan-layer', text: `${g.layer}` }),
            ` ${g.garment} · ${g.role}`,
            el('span', {
                class: 'plan-sub',
                text: ` ${g.finish}${g.opacity < 1 ? ` · opacity ${g.opacity}` : ''}${g.pattern !== 'none' ? ` · ${g.pattern}` : ''}${g.coverage !== 'standard' ? ` · ${g.coverage}` : ''}`,
            })
        )
    );
    const body = report.body;
    const missing = body ? Object.entries(body.regions).filter(([, r]) => !r.present).map(([k]) => k) : [];
    box.replaceChildren(
        el('ol', { class: 'plan-layers' }, lines),
        ...[...new Set(report.garments.filter((g) => !g.allowed).map((g) => g.refusal))].map((refusal) =>
            el('p', { class: 'report-line bad', text: `✕ ${refusal}` })
        ),
        el('p', {
            class: 'report-line',
            text: report.remove.length
                ? `✓ Her ${report.remove.join(' and ')} will come off${report.retain.length ? `; ${report.retain.join(', ')} stay` : ''}`
                : report.wearing.length
                  ? `The new outfit layers over her ${[...new Set(report.wearing.map((w) => w.slot))].join(', ')}`
                  : 'She wears no removable clothing',
        }),
        body
            ? el('p', {
                  class: `report-line ${missing.length ? 'bad' : ''}`,
                  text: missing.length
                      ? `! No body under her clothes at ${missing.join(', ')} — that part stays on`
                      : '✓ Complete body under what comes off',
              })
            : null,
        el('p', {
            class: `report-line ${report.allowed ? '' : 'bad'}`,
            text: report.allowed ? `→ ${report.garments.length} layer(s) will be built` : 'This outfit will be refused',
        })
    );
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
    renderReport(job.fitReport, job.look);
    if (state.avatar && state.avatar.slug === slug) {
        await loadWardrobe();
        if (job.look) await wearLook(job.look.id, { mode: 'compare' });
    }
}

function renderReport(report, look = null) {
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
                text: 'Something under the garment still shows through. If it is her own clothing, this model does not mark it in a way the Forge recognises, so it was layered over rather than taken off.',
            })
        );
    }
    if (report.hosiery) lines.push(...hosieryReport(report.hosiery, look));
    $('report').replaceChildren(...lines);
    $('report').hidden = false;
}

/** The hosiery block: the reveal in each pose, each strap's stretch, and the close-up and seated views. */
function hosieryReport(h, look) {
    const out = [el('h3', { text: 'Hosiery' })];
    if (h.reveal) out.push(el('p', { class: `report-line ${h.reveal.achieved === h.reveal.requested ? '' : 'warn'}`, text: h.reveal.summary }));
    if (h.clips) out.push(el('p', { class: 'report-line', text: `${h.clips.count} clips on the fitted tops · furthest ${h.clips.maxBandDistanceMm} mm from the band` }));
    const tension = h.straps && h.straps.tension;
    if (tension) {
        const poses = ['stand', 'walk', 'sit'];
        out.push(
            el(
                'table',
                { class: 'tension' },
                el('tr', {}, el('th', { text: 'Strap' }), ...poses.map((p) => el('th', { text: p }))),
                ...Object.entries(tension).map(([code, strap]) =>
                    el(
                        'tr',
                        {},
                        el('td', { text: code, title: strap.strap }),
                        ...poses.map((p) =>
                            el('td', {
                                class: strap.status[p],
                                text: `${(strap.stretch[p] * 100).toFixed(1)}%`,
                                title: strap.status[p],
                            })
                        )
                    )
                )
            )
        );
    }
    for (const warning of h.warnings || []) out.push(el('p', { class: 'report-line warn', text: warning }));
    const previews = (look && look.previews) || {};
    const pics = ['detail', 'preview-sit', 'preview-walk', 'preview-back'].filter((k) => previews[k]);
    if (pics.length)
        out.push(el('div', { class: 'hosiery-previews' }, ...pics.map((k) => el('img', { src: previews[k], alt: k, title: k, loading: 'lazy' }))));
    if (h.previews && h.previews.note) out.push(el('p', { class: 'report-line warn', text: h.previews.note }));
    return out;
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
        updatePreview();
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
