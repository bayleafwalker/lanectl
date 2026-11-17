const { test, expect } = require("@playwright/test");

// Match the complete text of an individually visible element. A hidden descendant,
// a longer amount such as 1700, or an amount with a different unit cannot satisfy it.
function amountPattern(currency, amount) {
  const unit = currency === "EUR" ? "(?:€|EUR)" : "(?:US\\$|\\$|USD)";
  const number = `${amount}(?:[.,]00)?`;
  return new RegExp(`^\\s*(?:${unit}\\s*${number}|${number}\\s*${unit})\\s*$`);
}
async function hasVisibleAmount(container, currency, amount) {
  const matches = container.getByText(amountPattern(currency, amount));
  for (const element of await matches.all()) {
    if (await element.isVisible() && await element.evaluate((node) => node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }))) return true;
  }
  return false;
}
async function expectAmount(container, currency, amount) {
  await expect.poll(() => hasVisibleAmount(container, currency, amount)).toBe(true);
}
function disjointReportValid(rows) {
  const has = (currency, field, amount) => rows.some((r) => r.currency === currency && r[field] != null && Number(r[field]) === amount);
  const noWrongNonzero = (field, allowed) => rows.every((r) => r[field] == null || Number(r[field]) === 0 || r.currency === allowed);
  return has("USD", "cashflow_net", 250) && has("EUR", "utility_cost_total", 300)
    && noWrongNonzero("cashflow_net", "USD") && noWrongNonzero("utility_cost_total", "EUR");
}
async function visibleWrongNonzeroAmounts(container, currency) {
  return container.locator("*").evaluateAll((nodes, expected) => {
    const allowed = expected === "USD" ? ["USD", "$", "US$"] : ["EUR", "€"];
    const pattern = /^\s*\(?\s*(?:[-+]?\s*([A-Z]{3}|US\$|\p{Sc})\s*([-+]?\d[\d.,\s]*)|([-+]?\d[\d.,\s]*)\s*([A-Z]{3}|US\$|\p{Sc}))\s*\)?\s*$/u;
    return nodes.flatMap((node) => {
      if (!(node instanceof HTMLElement) || !node.getClientRects().length || !node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return [];
      const text = node.innerText.trim();
      const match = text.match(pattern);
      if (!match) return [];
      const unit = match[1] || match[4];
      const amount = match[2] || match[3];
      return !allowed.includes(unit) && /[1-9]/.test(amount) ? [text] : [];
    });
  }, currency);
}
function panels(page) {
  return {
    cashflow: page.locator("article").filter({ has: page.getByRole("heading", { name: "Monthly cashflow" }) }),
    utilities: page.locator("article").filter({ hasText: "Utilities" }),
  };
}

test("visible amount oracle rejects larger and hidden values", async ({ page }) => {
  await page.setContent('<article><span>€170</span><span>$80.00</span><span>€1700</span><span>$800</span><span hidden>€200</span><span style="display:none">$100</span><span style="opacity:0">€300</span></article>');
  const container = page.locator("article");
  expect(await hasVisibleAmount(container, "EUR", 170)).toBe(true);
  expect(await hasVisibleAmount(container, "USD", 80)).toBe(true);
  expect(await hasVisibleAmount(container, "EUR", 1700)).toBe(true);
  expect(await hasVisibleAmount(container, "USD", 800)).toBe(true);
  expect(await hasVisibleAmount(container, "EUR", 200)).toBe(false);
  expect(await hasVisibleAmount(container, "USD", 100)).toBe(false);
  expect(await hasVisibleAmount(container, "EUR", 300)).toBe(false);
  await page.setContent('<article><span>€1700</span><span>$800</span><span hidden>€170</span><span style="display:none">$80</span></article>');
  expect(await hasVisibleAmount(container, "EUR", 170)).toBe(false);
  expect(await hasVisibleAmount(container, "USD", 80)).toBe(false);
  await page.setContent('<article><span>US$80.00</span></article>');
  expect(await hasVisibleAmount(container, "USD", 80)).toBe(true);
  await page.setContent('<article><span>US$800.00</span><span hidden>US$80.00</span></article>');
  expect(await hasVisibleAmount(container, "USD", 80)).toBe(false);
  const clean = [{currency:"USD",cashflow_net:250,utility_cost_total:0}, {currency:"EUR",cashflow_net:null,utility_cost_total:300}];
  const duplicated = [{currency:"USD",cashflow_net:250,utility_cost_total:300}, {currency:"EUR",cashflow_net:250,utility_cost_total:300}];
  expect(disjointReportValid(clean)).toBe(true);
  expect(disjointReportValid(duplicated)).toBe(false);
  await page.setContent('<article><span>$250</span><span>€250</span><span>€0</span><span hidden>£99</span></article>');
  expect(await visibleWrongNonzeroAmounts(container, "USD")).toContain("€250");
  await page.setContent('<article><span>$250</span><span>€0</span><span hidden>€250</span></article>');
  expect(await visibleWrongNonzeroAmounts(container, "USD")).toEqual([]);
  await page.setContent('<article><span>€300</span><span>$300</span></article>');
  expect(await visibleWrongNonzeroAmounts(container, "EUR")).toContain("$300");
  await page.setContent('<article><span>$250</span><span>ZZZ 17</span></article>');
  expect(await visibleWrongNonzeroAmounts(container, "USD")).toContain("ZZZ 17");
  await page.setContent('<article><span>$250</span><span>-€1</span><span>(ZZZ 17)</span></article>');
  expect(await visibleWrongNonzeroAmounts(container, "USD")).toEqual(expect.arrayContaining(["-€1", "(ZZZ 17)"]));
});

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
  const { cashflow } = panels(page);
  await expect(cashflow).toBeVisible();
  await expectAmount(cashflow, "EUR", 170);
  await expectAmount(cashflow, "USD", 80);
});

test("dashboard visibly retains both utility groups", async ({ page }) => {
  const frontend = process.env.CURRENCY_ACCEPTANCE_WEB_URL;
  if (!frontend) throw new Error("Set CURRENCY_ACCEPTANCE_WEB_URL");
  await page.goto(frontend);
  const { utilities } = panels(page);
  await expect(utilities).toBeVisible();
  await expectAmount(utilities, "EUR", 200);
  await expectAmount(utilities, "USD", 100);
});

test("disjoint household report retains finance and utility units", async ({ request }) => {
  const backend = process.env.CURRENCY_ACCEPTANCE_DISJOINT_API_URL;
  if (!backend) throw new Error("Set disjoint API URL");
  const response = await request.get(`${backend}/reports/household-overview`);
  expect(response.status()).toBe(200);
  const rows = (await response.json()).rows;
  expect(disjointReportValid(rows)).toBe(true);
});

test("disjoint household visibly retains finance and utility units", async ({ page }) => {
  const frontend = process.env.CURRENCY_ACCEPTANCE_DISJOINT_WEB_URL;
  if (!frontend) throw new Error("Set disjoint web URL");
  await page.goto(frontend);
  const { cashflow, utilities } = panels(page);
  await expect(cashflow).toBeVisible();
  await expect(utilities).toBeVisible();
  await expectAmount(cashflow, "USD", 250);
  await expectAmount(utilities, "EUR", 300);
  await expect.poll(() => visibleWrongNonzeroAmounts(cashflow, "USD")).toEqual([]);
  await expect.poll(() => visibleWrongNonzeroAmounts(utilities, "EUR")).toEqual([]);
});


const projectionColumns = {
  "Baseline income": "baseline_income",
  "Scenario income": "scenario_income",
  "Baseline expense": "baseline_expense",
  "Scenario expense": "scenario_expense",
  "Baseline net": "baseline_net",
  "Scenario net": "scenario_net",
  "Net delta": "net_delta",
};

async function projectionMatches(panel, currency, rows, columns = projectionColumns) {
  return panel.evaluate((root, { currency, rows, columns }) => {
    const visible = (el) => Boolean(el?.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) && el.getClientRects().length);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const explicitUnits = currency === "USD" ? new Set(["USD", "US$"]) : new Set(["EUR", "€"]);
    let explicit = false;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!visible(node.parentElement)) continue;
      for (const token of node.textContent.match(/\b[A-Z]{3}\b|[A-Za-z]+\$|\p{Sc}/gu) || []) {
        if (explicitUnits.has(token)) explicit = true;
        else if (!(currency === "USD" && token === "$")) return false;
      }
    }
    if (!explicit) return false;

    const headers = Array.from(root.querySelectorAll("thead th"), (cell) => cell.innerText.trim());
    const displayedRows = [...root.querySelectorAll("tbody tr")].filter(visible);
    if (!rows.length || displayedRows.length !== rows.length) return false;
    const value = (text) => {
      const number = text.replace(/USD|EUR|US\$|[€$]/g, "").replace(/[,\s]/g, "").replace("−", "-");
      return /^[+-]?\d+(?:\.\d+)?$/.test(number) ? Number(number) : NaN;
    };
    return displayedRows.every((element, index) => {
      const cells = element.querySelectorAll("td");
      return Object.entries(columns).every(([heading, field]) => {
        const cell = cells[headers.indexOf(heading)];
        const amount = rows[index][field];
        return visible(cell) && amount != null && value(cell.innerText) === Number(amount);
      });
    });
  }, { currency, rows, columns });
}

function projectionApiUnitMatches(body, currency) {
  if (!Array.isArray(body.assumptions) || !Array.isArray(body.cashflow_rows)) return false;
  const baseline = body.assumptions.filter((row) => row.assumption_key === "baseline_utility_cost");
  if (baseline.length !== 1 || baseline[0].unit !== currency) return false;
  return [body, ...body.cashflow_rows].every((row) =>
    ["currency", "unit", "currency_unit"].every((field) => !(field in row) || row[field] === currency)
  );
}

test("scenario projection currency oracle rejects ambiguous and missing values", async ({ page }) => {
  const table = (label, cell) => `<article><p>${label}</p><table><thead><tr><th>Scenario expense</th></tr></thead><tbody><tr><td>${cell}</td></tr></tbody></table></article>`;
  const panel = page.locator("article");
  const rows = [{scenario_expense:"110.00"}];
  const columns = {"Scenario expense":"scenario_expense"};
  const baseline = {assumption_key:"baseline_utility_cost", unit:"USD"};
  const unrelated = {assumption_key:"tariff_pct_delta", unit:"%"};
  const body = {cashflow_rows:rows, assumptions:[baseline, unrelated]};
  expect(projectionApiUnitMatches(body, "USD")).toBe(true);
  expect(projectionApiUnitMatches({...body, assumptions:[{...unrelated, unit:"USD"}]}, "USD")).toBe(false);
  expect(projectionApiUnitMatches({...body, assumptions:[baseline, {...baseline, unit:"CAD"}]}, "USD")).toBe(false);
  expect(projectionApiUnitMatches({...body, cashflow_rows:[{...rows[0], currency:"CAD"}]}, "USD")).toBe(false);
  for (const [label, cell, expected] of [
    ["Currency USD", "$110.00", true],
    ["Currency USD", "110.00", true],
    ["Currency EUR", "110.00", false],
    ["<span hidden>USD</span>", "110.00", false],
    ["", "$110.00", false],
    ["Currency USD CAD", "110.00", false],
    ["Currency USD", "CA$110.00", false],
    ["Currency USD", "A$110.00", false],
    ["Currency USD", "NZ$110.00", false],
    ["Currency USD", "", false],
    ["Currency USD", "111.00", false],
  ]) {
    await page.setContent(table(label, cell));
    expect(await projectionMatches(panel, "USD", rows, columns)).toBe(expected);
  }
  await page.setContent('<article><p>Currency USD</p></article>');
  expect(await projectionMatches(panel, "USD", rows, columns)).toBe(false);
});

async function verifyScenarioProjection(page, request, currency) {
  const api = process.env.CURRENCY_ACCEPTANCE_API_URL;
  const web = process.env.CURRENCY_ACCEPTANCE_WEB_URL;
  if (!api || !web) throw new Error("Scenario API and web URLs are required");
  const created = await request.post(`${api}/api/scenarios/tariff-shock`, {data:{tariff_pct_delta:"0.10",utility_type:"electricity",projection_months:1}});
  expect(created.status()).toBe(200);
  const id = (await created.json()).scenario_id;
  expect(typeof id).toBe("string");
  const cashflow = await request.get(`${api}/api/scenarios/${id}/cashflow`);
  expect(cashflow.status()).toBe(200);
  const body = await cashflow.json();
  expect(projectionApiUnitMatches(body, currency)).toBe(true);
  expect(body.cashflow_rows.length).toBeGreaterThan(0);
  await page.goto(`${web}/scenarios/${encodeURIComponent(id)}`);
  const panel = page.locator("article").filter({has:page.getByRole("heading", {name:"12-month outlook"})});
  await expect(panel).toBeVisible();
  const rows = body.cashflow_rows;
  expect(rows.some((row) => Number(row.scenario_expense) > Number(row.baseline_expense))).toBe(true);
  await expect.poll(() => projectionMatches(panel, currency, rows)).toBe(true);
}

test("scenario projection EUR has coherent currency", async ({page, request}) => {
  await verifyScenarioProjection(page, request, "EUR");
});

test("scenario projection USD has coherent currency", async ({page, request}) => {
  await verifyScenarioProjection(page, request, "USD");
});
