const { test, expect } = require("@playwright/test");

async function historyUnavailableVisible(page) {
  const panels = page.locator("article").filter({ hasText: /unavailable/i }).filter({ hasText: /currency|denomination|monetary|cashflow|household/i });
  for (const panel of await panels.all()) {
    if (!(await panel.isVisible())) continue;
    if ((await panel.getByText(/no history/i).count()) !== 0) continue;
    const text = panel.getByText(/unavailable/i);
    for (const element of await text.all()) {
      if (await element.isVisible() && await element.evaluate((node) => node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }))) return true;
    }
  }
  return false;
}

test("legacy history display oracle rejects false empty and hidden status", async ({ page }) => {
  await page.setContent('<article><span>Household currency unavailable</span></article>');
  expect(await historyUnavailableVisible(page)).toBe(true);
  await page.setContent('<article><span>No history for household</span></article>');
  expect(await historyUnavailableVisible(page)).toBe(false);
  await page.setContent('<article><span hidden>Household currency unavailable</span><span>No history</span></article>');
  expect(await historyUnavailableVisible(page)).toBe(false);
});

test("past household view presents unavailable legacy denomination", async ({ page, request }) => {
  const api = process.env.CURRENCY_LEGACY_API_URL;
  const web = process.env.CURRENCY_LEGACY_WEB_URL;
  if (!api || !web) throw new Error("Legacy API and web URLs are required");
  const response = await request.get(`${api}/reports/household-overview?as_of=2026-01`);
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.as_of_status).toBe("legacy_denomination_unavailable");
  expect(body.rows).toEqual([]);
  await page.goto(`${web}/?asof=2026-01`);
  await expect.poll(() => historyUnavailableVisible(page)).toBe(true);
});
