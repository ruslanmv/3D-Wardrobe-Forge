#!/usr/bin/env node
// F4. A reference proxy for a Forge that a browser must not reach directly.
//
// Nothing uses this until someone deploys it. It exists for one situation: the Forge
// is private (a private Hugging Face Space, or WARDROBE_AUTH_MODE=api_key with the
// trusted-origin fallback turned off), and a public page still has to create looks.
// A page cannot hold the credential, so this small server holds it and the page talks
// to this instead. Three things it gets right that a naive `fetch` relay does not:
//
// 1. **Only Try-On's routes pass** (docs/TRY_ON_INTEGRATION.md). The admin sign-in,
//    avatar upload and everything else answer 404 here, so the credential this holds
//    cannot be spent on anything the page was never meant to do.
// 2. **The credential is added here and the caller's is dropped.** An Authorization
//    or Cookie header from the browser never reaches the Forge.
// 3. **Asset URLs are rewritten to come back through here.** A completed job names its
//    look as an absolute Forge URL; the 3D loader fetches that with no auth header, and
//    against a private Forge it would fail. JSON answers have the Forge's origin
//    replaced with this proxy's, and /v1/assets/* is proxied like the rest.
//
// Node 20, no dependencies:
//   FORGE_URL=https://you-forge.hf.space FORGE_TOKEN=... PUBLIC_URL=https://wardrobe.example.com \
//   ALLOWED_ORIGINS=https://yourfriend.online PORT=8787 node deploy/proxy/wardrobe-proxy.mjs

import { createServer } from 'node:http';
import { Readable } from 'node:stream';

const FORGE_URL = (process.env.FORGE_URL || '').replace(/\/+$/, '');
const FORGE_TOKEN = process.env.FORGE_TOKEN || '';
const PUBLIC_URL = (process.env.PUBLIC_URL || '').replace(/\/+$/, '');
const ALLOWED_ORIGINS = new Set(
    (process.env.ALLOWED_ORIGINS || '')
        .split(',')
        .map((origin) => origin.trim().replace(/\/+$/, '').toLowerCase())
        .filter(Boolean)
);
const PORT = Number(process.env.PORT || 8787);
// A job request is a prompt and a few options; nothing Try-On sends comes near this.
const MAX_BODY_BYTES = 256 * 1024;

// [method, pattern] — the whole surface Try-On uses, and nothing else.
export const ROUTES = [
    ['GET', /^\/health$/],
    ['GET', /^\/v1\/capabilities$/],
    ['GET', /^\/v1\/library$/],
    ['POST', /^\/v1\/library\/[a-z0-9-]+\/jobs$/],
    ['POST', /^\/v1\/generate$/],
    ['GET', /^\/v1\/jobs\/[A-Za-z0-9_-]+$/],
    ['GET', /^\/v1\/looks\/[A-Za-z0-9_-]+$/],
    ['GET', /^\/v1\/wardrobes\/[A-Za-z0-9_-]+$/],
    ['GET', /^\/v1\/assets\/[A-Za-z0-9_.\/-]+$/],
];

export function allowed(method, pathname) {
    if (pathname.includes('..')) return false;
    return ROUTES.some(([verb, pattern]) => verb === method && pattern.test(pathname));
}

/** The Forge's absolute URLs in a JSON answer, pointed back through this proxy. */
export function rewrite(text, forgeUrl, publicUrl) {
    if (!forgeUrl || !publicUrl) return text;
    return text.split(forgeUrl).join(publicUrl);
}

function corsHeaders(origin) {
    const normalized = (origin || '').replace(/\/+$/, '').toLowerCase();
    if (!normalized || !ALLOWED_ORIGINS.has(normalized)) return {};
    return {
        'access-control-allow-origin': origin,
        'access-control-allow-methods': 'GET, POST, OPTIONS',
        'access-control-allow-headers': 'content-type',
        'access-control-expose-headers': 'retry-after',
        vary: 'origin',
    };
}

async function readBody(request) {
    const chunks = [];
    let size = 0;
    for await (const chunk of request) {
        size += chunk.length;
        if (size > MAX_BODY_BYTES) throw Object.assign(new Error('request too large'), { status: 413 });
        chunks.push(chunk);
    }
    return Buffer.concat(chunks);
}

async function handle(request, response) {
    const url = new URL(request.url, 'http://proxy.local');
    const cors = corsHeaders(request.headers.origin);
    if (request.method === 'OPTIONS') {
        response.writeHead(cors['access-control-allow-origin'] ? 204 : 403, cors).end();
        return;
    }
    if (!allowed(request.method, url.pathname)) {
        response.writeHead(404, { 'content-type': 'application/json', ...cors });
        response.end(JSON.stringify({ detail: { reason: 'not_found', message: 'not available here' } }));
        return;
    }

    const headers = { accept: request.headers.accept || '*/*' };
    if (FORGE_TOKEN) headers.authorization = `Bearer ${FORGE_TOKEN}`;
    // The Forge counts visitors by this (WARDROBE_FORWARDED_HOPS): with this proxy in
    // front of a Space's own proxy, that is 2.
    const peer = request.socket.remoteAddress || '';
    const prior = request.headers['x-forwarded-for'];
    headers['x-forwarded-for'] = prior ? `${prior}, ${peer}` : peer;
    let body;
    if (request.method === 'POST') {
        headers['content-type'] = 'application/json';
        body = await readBody(request);
    }

    const upstream = await fetch(FORGE_URL + url.pathname + url.search, { method: request.method, headers, body });
    const type = upstream.headers.get('content-type') || 'application/octet-stream';
    const out = { 'content-type': type, ...cors };
    for (const name of ['retry-after', 'cache-control', 'etag', 'last-modified']) {
        const value = upstream.headers.get(name);
        if (value) out[name] = value;
    }
    if (type.includes('application/json')) {
        const text = rewrite(await upstream.text(), FORGE_URL, PUBLIC_URL);
        response.writeHead(upstream.status, out).end(text);
        return;
    }
    const length = upstream.headers.get('content-length');
    if (length) out['content-length'] = length;
    response.writeHead(upstream.status, out);
    if (upstream.body) Readable.fromWeb(upstream.body).pipe(response);
    else response.end();
}

export function start(port = PORT) {
    if (!FORGE_URL) throw new Error('FORGE_URL is required');
    const server = createServer((request, response) => {
        handle(request, response).catch((error) => {
            // Fail soft: the page gets a reason it already knows how to say (offline / busy).
            const status = error.status || 502;
            if (!response.headersSent) {
                response.writeHead(status, { 'content-type': 'application/json' });
                response.end(JSON.stringify({ detail: { reason: 'upstream_unavailable', message: error.message } }));
            } else {
                response.destroy();
            }
        });
    });
    server.listen(port);
    return server;
}

if (import.meta.url === `file://${process.argv[1]}`) {
    start();
    console.log(`wardrobe proxy on :${PORT} → ${FORGE_URL}`);
}
