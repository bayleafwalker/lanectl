const { test, expect } = require("@playwright/test");

// This is a live candidate frontend and real synthetic backend, not route mocks.
// See QUALIFICATION.md for required fixture, source binding and process cleanup.
test("fixture serves every published currency group", async ({ request }) => {
  const backend = process.env.CURRENCY_ACCEPTANCE_API_URL;
  if (!backend) throw new Error("Set CURRENCY_ACCEPTANCE_API_URL");
  for (const [route, field, totals] of [
    ["/reports/monthly-cashflow", "net", { EUR: 170, USD: 80 }],
    ["/reports/utility-cost-trend", "total_cost", { EUR: 200, USD: 100 }],
  ]) {
    const response = await request.get(`${backend}${route}`);
    expect(response.status()).toBe(200);
    const rows = (await response.json()).rows;
    expect(rows.length).toBe(2);
    expect(Object.fromEntries(rows.map((r) => [r.currency, Number(r[field])]))).toEqual(totals);
  }
});

test("dashboard visibly retains both cashflow groups", async ({ page }) => {
  const frontend = process.env.CURRENCY_ACCEPTANCE_WEB_URL;
  if (!frontend) throw new Error("Set CURRENCY_ACCEPTANCE_WEB_URL");
  await page.goto(frontend);
  const cashflow = page.locator("article").filter({ has: page.getByRole("heading", { name: "Monthly cashflow" }) });
  await expect(cashflow).toBeVisible();
  // Currency symbol/code may precede or follow the amount, including NBSP.
  const money = (currency, amount) => {
    const unit = currency === "EUR" ? "(?:€|EUR)" : "(?:\\$|USD)";
    const number = `${amount}(?:[.,]00)?`;
    return new RegExp(`(?:${unit}\\s*${number}|${number}\\s*${unit})`);
  };
  await expect(cashflow).toContainText(money("EUR", 170));
  await expect(cashflow).toContainText(money("USD", 80));
});

test("dashboard visibly retains both utility groups", async ({ page }) => {
  const frontend = process.env.CURRENCY_ACCEPTANCE_WEB_URL;
  if (!frontend) throw new Error("Set CURRENCY_ACCEPTANCE_WEB_URL");
  await page.goto(frontend);
  const utilities = page.locator("article").filter({ hasText: "Utilities" });
  await expect(utilities).toBeVisible();
  const money = (unit, amount) => new RegExp(`(?:${unit}\\s*${amount}(?:[.,]00)?|${amount}(?:[.,]00)?\\s*${unit})`);
  await expect(utilities).toContainText(money("(?:€|EUR)", 200));
  await expect(utilities).toContainText(money("(?:\\$|USD)", 100));
});
