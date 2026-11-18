const {test, expect} = require("@playwright/test");

const domains = ["Finance", "Utilities", "Homelab"];

function cardGroup(page) {
  return page.getByRole("region", {name:"Domain cards", exact:true});
}

function readCard(page, domain) {
  return cardGroup(page).getByRole("article").filter({
    has: page.getByRole("heading", {name:domain, exact:true}),
  });
}

function amount(unit, value) {
  const token = unit === "USD" ? "(?:USD|US\\$|\\$)" : "(?:EUR|€)";
  return new RegExp(`^\\s*(?:${token}\\s*${value}(?:[.,]00)?|${value}(?:[.,]00)?\\s*${token})\\s*$`);
}

async function expectAmount(card, unit, value) {
  const matches = card.getByText(amount(unit, value));
  await expect.poll(async () => {
    for (const match of await matches.all()) {
      if (await match.isVisible() && await match.evaluate((el) =>
        el.checkVisibility({checkOpacity:true, checkVisibilityCSS:true}))) return true;
    }
    return false;
  }).toBe(true);
}

async function checkCards(page) {
  const url = process.env.DOMAIN_CARDS_WEB_URL;
  if (!url) throw new Error("DOMAIN_CARDS_WEB_URL is required");
  await page.goto(url);
  const group = cardGroup(page);
  await expect(group).toBeVisible();
  await expect(group.getByRole("article")).toHaveCount(3);
  for (const name of domains) {
    await expect(group.getByRole("heading", {name, exact:true})).toHaveCount(1);
    await expect(readCard(page, name)).toBeVisible();
  }
}

async function trendLists(card, count) {
  await expect(card.getByRole("heading", {name:"Trend", exact:true})).toBeVisible();
  const lists = card.getByRole("list", {name:/\btrend\b/i});
  await expect(lists).toHaveCount(count);
  for (const list of await lists.all()) {
    await expect(list).toBeVisible();
    const dates = [];
    for (const time of await list.locator("time[datetime]").all()) {
      await expect(time).toBeVisible();
      const actual = await time.getAttribute("datetime");
      expect(Number.isNaN(Date.parse(actual))).toBe(false);
      dates.push(actual);
    }
    expect(dates.length).toBeGreaterThanOrEqual(2);
    expect(dates).toEqual([...dates].sort());
    expect(new Set(dates).size).toBe(dates.length);
  }
  return lists;
}

test("domain cards show observed headlines trends and source attention", async ({page}) => {
  await checkCards(page);
  const finance = readCard(page, "Finance");
  const utilities = readCard(page, "Utilities");
  const homelab = readCard(page, "Homelab");
  await expectAmount(finance, "EUR", 180);
  await expectAmount(finance, "USD", 260);
  await expectAmount(utilities, "EUR", 150);
  await expectAmount(utilities, "USD", 0);
  await expect(homelab.getByText(/(?:4\s+services|\b4\b.*(?:unhealthy|degraded|stopped))/i).first()).toBeVisible();

  const financeTrend = await trendLists(finance, 2);
  await expectAmount(financeTrend, "EUR", 100);
  await expectAmount(financeTrend, "USD", 200);
  const utilityTrend = await trendLists(utilities, 2);
  await expectAmount(utilityTrend, "USD", 80);
  await expectAmount(utilityTrend, "EUR", 100);
  const serviceTrend = await trendLists(homelab, 1);
  await expect(serviceTrend.getByText(/^1 services?$/i)).toBeVisible();
  await expect(serviceTrend.getByText(/^4 services?$/i)).toBeVisible();


  for (const [card, focus, other] of [
    [finance, /Unusual transaction: Anchor Books/i, /Low subscription|Harbor Utility|Zeta relay/i],
    [utilities, /Upcoming renewal: Harbor Utility/i, /Upland Utility|Anchor Books|Zeta relay/i],
    [homelab, /Zeta relay/i, /Alpha proxy|Anchor Books|Harbor Utility/i],
  ]) {
    await expect(card.getByText(focus).first()).toBeVisible();
    await expect(card.getByText(other)).toHaveCount(0);
  }
});

test("domain cards keep empty sources distinct from unavailable", async ({page}) => {
  const unavailable = process.env.DOMAIN_CARDS_SCENARIO === "unavailable";
  await checkCards(page);
  if (unavailable) {
    await expect(page.getByText("No attention items. All clear.", { exact: true })).toHaveCount(0);
  }
  for (const name of domains) {
    const card = readCard(page, name);
    if (unavailable) {
      await expect(card.getByText(/unavailable|could not load/i).first()).toBeVisible();
    } else {
      await expect(card.getByText(/no (?:.* )?(?:data|observations?|bills?|services?|transactions?|costs?)|nothing to show/i).first()).toBeVisible();
      await expect(card.getByText(/unavailable|could not load/i)).toHaveCount(0);
    }
  }
});
