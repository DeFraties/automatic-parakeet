import { expect, test } from '@playwright/test';

for (const difficulty of ['Normal', 'Hard'] as const) {
  test(`Classic ${difficulty}: 5 guesses → summary → share`, async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /Ballpark/ })).toBeVisible();
    await page.getByRole('radio', { name: new RegExp(difficulty) }).click();
    await page.getByRole('button', { name: /Classic/ }).click();

    for (let n = 1; n <= 5; n++) {
      await expect(page.getByText(`Round ${n}/5`)).toBeVisible();
      // Browse the listing photos (demo placeholders served by our own site).
      const frame = page.getByLabel(/^Photo 1 of \d+\./);
      await expect(frame).toBeVisible();
      const lead = page.locator('.carousel-slide img').first();
      await expect(lead).toHaveJSProperty('complete', true);
      expect(await lead.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
      await page.getByRole('button', { name: 'Next photo' }).click();
      await expect(page.getByLabel(/^Photo 2 of \d+\./)).toBeVisible();
      await expect(page.getByText('Photos: DEMO data (fictional)')).toBeVisible();
      if (difficulty === 'Hard') {
        await expect(page.locator('main')).not.toContainText('USD');
      }
      const input = page.getByLabel('Your guess');
      await input.fill('');
      await input.pressSequentially(difficulty === 'Hard' ? '1m' : '400k');
      await input.press('Enter');
      await expect(page.getByLabel(/points$/)).toBeVisible();
      await page.getByRole('button', { name: n < 5 ? 'Next round' : 'See results' }).click();
    }

    await expect(page.locator('.summary-total')).toContainText('/ 25,000');
    await expect(page.locator('.summary-table tbody tr')).toHaveCount(5);

    // Force the clipboard path (mobile emulation would otherwise prefer the Web Share API).
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'share', { value: undefined, configurable: true });
    });
    await page.getByRole('button', { name: 'Share result' }).click();
    await expect(page.getByText('Copied to clipboard!')).toBeVisible();
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied).toMatch(/^Ballpark Classic — [\d,]+ \/ 25,000/);
    expect(copied.split('\n')).toHaveLength(3);
    if (difficulty === 'Hard') expect(copied).toContain('🔥 HARD');
  });
}

test('Daily: play once, submit to leaderboard, Home shows done', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Daily Challenge/ }).click();
  for (let n = 1; n <= 5; n++) {
    await expect(page.getByText(`Round ${n}/5`)).toBeVisible();
    await expect(page.getByText(/^Daily #\d+ · Normal$/)).toBeVisible();
    await page.getByLabel('Your guess').pressSequentially('350k');
    await page.getByLabel('Your guess').press('Enter');
    await expect(page.getByLabel(/points$/)).toBeVisible();
    await page.getByRole('button', { name: n < 5 ? 'Next round' : 'See results' }).click();
  }
  await expect(page.locator('.summary-total')).toContainText('/ 25,000');
  const nick = `E2E${test.info().project.name.slice(0, 3)}`;
  await page.getByLabel('Submit to leaderboard').fill(nick);
  await page.getByRole('button', { name: 'Submit' }).click();
  await expect(page.getByText(/on this board/)).toBeVisible();

  await page.goto('/#/leaderboards');
  await expect(page.getByRole('row', { name: new RegExp(nick) })).toBeVisible();

  await page.goto('/');
  await expect(page.getByText(/✓ Done today/)).toBeVisible();
});

test('About page and removal form', async ({ page }) => {
  await page.goto('/#/about');
  await expect(page.getByRole('heading', { name: 'How it works' })).toBeVisible();
  await expect(page.getByText(/GHS-SMOD/).first()).toBeVisible();
  await page.getByLabel('Your email').fill('owner@example.com');
  await page.getByLabel('Listing link or property ID').fill('https://example.com/demo/demo-001');
  await page.getByRole('button', { name: 'Send removal request' }).click();
  await expect(page.getByRole('status')).toContainText('within 72 hours');
});
