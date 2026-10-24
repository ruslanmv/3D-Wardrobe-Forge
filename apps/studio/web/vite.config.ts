import { fileURLToPath } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// UI-002. Served by Forge's FastAPI at /studio/next/ (apps/api/main.py), same origin as /v1, so
// the API client needs no base URL. `npm run dev` proxies /v1 to a Forge on :8080.
export default defineConfig({
    base: '/studio/next/',
    plugins: [react(), tailwindcss()],
    resolve: {
        alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
        // viewer.js lives in ../js, beside the vanilla Studio, outside this package: its bare
        // imports resolve from here, so the React Studio and the viewer share one three.js.
        dedupe: ['three', '@pixiv/three-vrm'],
    },
    build: {
        outDir: fileURLToPath(new URL('../next', import.meta.url)),
        emptyOutDir: true,
        sourcemap: true,
        rollupOptions: {
            output: {
                // UI-011. The 3D stack is its own chunk, loaded when the viewport mounts: the
                // gallery is usable before three.js has arrived.
                manualChunks: (id) =>
                    id.includes('node_modules/three') || id.includes('node_modules/@pixiv') ? 'viewer3d' : undefined,
            },
        },
    },
    server: { proxy: { '/v1': 'http://127.0.0.1:8080' } },
    test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'] },
});
