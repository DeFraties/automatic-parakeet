import { expect, test } from '@playwright/test';

for (const difficulty of ['Normal', 'Hard'] as const) {
  test(`Classic ${difficulty}: 5 guesses → summary → share`, async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /Ballpark/ })).toBeVisible();
    await page.getByRole('radio', { name: new RegExp(difficulty) }).click();
    await page.getByRole('button', { name: /Classic/ }).click();

    for (let n = 1; n <= 5; n++) {
      await expect(page.getByText(`Round ${n}/5`)).toBeVisible();
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
