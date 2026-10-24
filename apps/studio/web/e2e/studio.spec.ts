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
    await expect(page.getByText(/parameter schema/)).toBeVisible();
    await expect(page.getByRole('slider')).toHaveCount(0); // no control Forge would ignore
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
