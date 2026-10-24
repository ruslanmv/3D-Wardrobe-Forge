import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Request } from '@playwright/test';

/** Every request the page makes, so a test can say what it must never ask for. */
function record(page: Page): Request[] {
    const seen: Request[] = [];
    page.on('request', (request) => seen.push(request));
    return seen;
}

async function open(page: Page) {
    await page.goto('./');
    await expect(page.getByRole('heading', { name: 'Garments' })).toBeVisible();
    await expect(page.getByText(/\d+ of \d+ garments/)).toBeVisible();
}

test('the gallery lists the public catalogue and searching narrows it', async ({ page }) => {
    await open(page);
    const cards = page.getByRole('list').first().getByRole('button');
    const total = await cards.count();
    expect(total).toBeGreaterThan(10);
    await page.getByRole('searchbox', { name: 'Search garments' }).fill('mini');
    await expect.poll(() => cards.count()).toBeLessThan(total);
    await expect(page.getByText(/^\d+ of \d+ garments$/)).toBeVisible();
});

test('choosing a garment shows what Forge says about it, and nothing invented', async ({ page, isMobile }) => {
    await open(page);
    const first = page.getByRole('list').first().getByRole('button').first();
    const name = (await first.locator('span').first().textContent())!.trim();
    await first.click();
    // A phone switches to the Garment panel (the gallery unmounts); a desktop keeps both in view.
    if (isMobile) await expect(page.getByRole('button', { name: 'Garment' })).toHaveAttribute('aria-current', 'page');
    else await expect(first).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name, level: 3 })).toBeVisible();
    await page.getByRole('tab', { name: 'Design' }).click();
    // UI-006. Controls come from the garment's parameter schema; construction is shown, not offered.
    await expect(page.getByRole('heading', { name: 'What you can change' })).toBeVisible();
    await expect(page.getByRole('radiogroup', { name: 'Colour' })).toBeVisible();
    await expect(page.getByText('Not offered yet, and why')).toBeVisible();
});

test('a see-through setting waits for an avatar declared adult, and Forge confirms what it would build', async ({
    page,
}) => {
    await open(page);
    await page.getByRole('list').first().getByRole('button').first().click(); // the tee
    if (await page.getByRole('button', { name: 'Garment' }).isVisible()) {
        await page.getByRole('button', { name: 'Garment' }).click();
    }
    await page.getByRole('tab', { name: 'Design' }).click();
    const opacity = page.getByRole('spinbutton', { name: /Opacity/ });
    // The startup avatar is not declared adult: opacity stays at 1 and says why.
    await expect(opacity).toBeDisabled();
    await expect(page.getByText(/See-through needs the avatar declared adult/)).toBeVisible();

    await page.getByRole('combobox', { name: 'Avatar' }).selectOption('fem-vroid');
    await expect(opacity).toBeEnabled();
    // Typed exactly, and the slider follows: never a slider alone.
    await opacity.fill('0.6');
    await expect(page.getByRole('slider', { name: /Opacity/ })).toHaveAttribute('aria-valuenow', '0.6');
    await page.getByRole('button', { name: 'Check with Forge' }).click();
    const result = page.getByTestId('check-result');
    await expect(result).toBeVisible({ timeout: 30_000 });
    await expect(result).toContainText('Forge would build this.');
    await expect(result).toContainText('0.6');
});

test('the viewer loads an avatar and every camera action has a button', async ({ page }) => {
    await open(page);
    const summary = page.getByTestId('viewer-summary');
    await expect(summary).toHaveText(/relaxed pose/, { timeout: 45_000 });
    await page.getByRole('button', { name: 'Back', exact: true }).click();
    await expect(summary).toHaveText(/back view/);
    await page.getByRole('button', { name: 'Rest pose' }).click();
    await expect(summary).toHaveText(/rest pose/);
    await expect(page.getByRole('button', { name: 'Reframe' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Look' })).toBeDisabled(); // no look generated here yet
});

test('changing avatar keeps exactly one viewer', async ({ page }) => {
    await open(page);
    const summary = page.getByTestId('viewer-summary');
    await expect(summary).toHaveText(/relaxed pose/, { timeout: 45_000 });
    const picker = page.getByRole('combobox', { name: 'Avatar' });
    const options = await picker.locator('option').allTextContents();
    await picker.selectOption({ label: options[1] });
    await expect(summary).toHaveText(new RegExp(options[1]), { timeout: 45_000 });
    await expect(page.getByTestId('viewer-host').locator('canvas')).toHaveCount(1);
});

test('restricted lingerie is never asked for', async ({ page }) => {
    const requests = record(page);
    await open(page);
    await page.getByTestId('viewer-summary').waitFor({ state: 'attached' });
    await page.waitForLoadState('networkidle');
    const urls = requests.map((r) => r.url());
    expect(urls.some((u) => u.includes('includeRestricted'))).toBe(false);
    expect(urls.some((u) => /\/v1\/catalog\/garments\/under-/.test(u))).toBe(false);
});

test('a phone gets the viewer first and no sideways scrolling', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'phone layout');
    await open(page);
    await expect(page.getByRole('navigation', { name: 'Studio sections' })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
});

test('keyboard alone reaches search and a garment', async ({ page, isMobile }) => {
    test.skip(isMobile, 'keyboard flow is checked on the desktop layout');
    await open(page);
    const search = page.getByRole('searchbox', { name: 'Search garments' });
    for (let i = 0; i < 12 && !(await search.evaluate((el) => el === document.activeElement)); i++)
        await page.keyboard.press('Tab');
    await expect(search).toBeFocused();
    await page.keyboard.type('tee');
    await expect(page.getByText(/^\d+ of \d+ garments$/)).toBeVisible();
});

test('no serious or critical accessibility violations', async ({ page }) => {
    await open(page);
    const results = await new AxeBuilder({ page }).exclude('canvas').analyze();
    const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(bad.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
});

test('a narrow screen, before the avatar lands, is still keyboard-reachable', async ({ page, isMobile }) => {
    // CI's slower runner found it: on a narrow screen the camera toolbar scrolls sideways, and while
    // the avatar is still loading every button in it is disabled, so nothing in it could take focus.
    test.skip(!isMobile, 'phone layout');
    await page.setViewportSize({ width: 320, height: 700 });
    await page.route('**/*.vrm', () => {}); // hold the avatar: the viewer stays loading
    await open(page);
    const results = await new AxeBuilder({ page }).exclude('canvas').analyze();
    const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(bad.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
});
