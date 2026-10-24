import { defineConfig, devices } from '@playwright/test';

// UI-012. Runs against a Forge that serves the built Studio (`npm run build`, then
// `uvicorn apps.api.main:app --port 8781`): the same origin and routes a Space serves.
// STUDIO_URL points elsewhere; PLAYWRIGHT_CHROMIUM uses an installed Chromium.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM || undefined;

export default defineConfig({
    testDir: './e2e',
    timeout: 60_000,
    retries: 0,
    reporter: [['list']],
    use: {
        baseURL: process.env.STUDIO_URL || 'http://127.0.0.1:8781/studio/next/',
        launchOptions: {
            executablePath,
            args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
        },
    },
    projects: [
        { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
        { name: 'mobile', use: { ...devices['Pixel 7'] } },
    ],
});
