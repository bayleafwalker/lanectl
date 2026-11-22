"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { buildSync } = require("esbuild");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const source = path.resolve("apps/web/frontend/components/operating-picture-view.js");
const compiled = buildSync({
  entryPoints: [source],
  bundle: true,
  format: "cjs",
  loader: { ".js": "jsx" },
  jsx: "automatic",
  packages: "external",
  platform: "node",
  write: false,
}).outputFiles[0].text;
const subject = new Module(source, module);
subject.filename = source;
subject.paths = Module._nodeModulePaths(path.dirname(source));
subject._compile(compiled, source);
const { OperatingPictureView } = subject.exports;

function render(horizonDays, unavailable = {}) {
  return renderToStaticMarkup(React.createElement(OperatingPictureView, {
    freshnessDomains: [],
    horizonDays,
    rankedAttention: [],
    affordabilityRatios: [],
    topCategories: [],
    recentChanges: [],
    unavailable,
  }));
}

test("the horizon renders every action and labels all four kinds", () => {
  const markup = render([
    {
      dateLabel: "Mon 07",
      items: [
        { id: "ap", kind: "approval", label: "Thermostat change" },
        { id: "ex", kind: "export", label: "Bank Partner Transactions" },
        { id: "fc", kind: "fixed_cost", label: "Power bill", amount: 42, currency: "EUR" },
        { id: "rn", kind: "renewal", label: "Energy renewal" },
      ],
    },
    { dateLabel: "Tue 08", items: [] },
  ]);
  for (const label of ["Thermostat change", "Bank Partner Transactions", "Power bill", "Energy renewal", "Tue 08"]) {
    assert.ok(markup.includes(label), `Horizon must render ${label}`);
  }
  for (const kind of [/Approval/i, /Manual export/i, /Fixed cost/i, /Renewal/i]) {
    assert.match(markup, kind);
  }
  assert.match(markup, /EUR/);
  assert.match(markup, /42/);
  assert.doesNotMatch(markup, /Horizon unavailable/);
});

test("an unavailable merged feed is distinct from an empty horizon", () => {
  assert.match(render([], { operatingHorizon: true }), /Horizon unavailable/);
  assert.doesNotMatch(render([{ dateLabel: "Mon 07", items: [] }]), /Horizon unavailable/);
});

test("the API start date determines all seven cells across frontend timezones", () => {
  const page = fs.readFileSync("apps/web/frontend/app/operating-picture/page.js", "utf8");
  const format = page.match(/^function localIsoDate\(.*?^\}/ms)?.[0] || "";
  const build = page.match(/^function buildHorizonDays\(.*?^\}/ms)?.[0];
  assert.ok(build, "Missing horizon day builder");

  class FrontendDate extends Date {
    constructor(...args) {
      super(...(args.length ? args : ["2026-11-23T12:00:00Z"]));
    }
  }

  const row = { id: "approval:cross-midnight", date: "2026-11-22", kind: "approval" };
  const context = { Date: FrontendDate, rows: [row], boundary: "2026-11-22" };
  vm.runInNewContext(
    format + "\n" + build +
      "\nfilled = buildHorizonDays(rows, boundary); empty = buildHorizonDays([], boundary);",
    context,
  );
  assert.equal(context.filled.length, 7);
  assert.equal(context.filled[0].items[0]?.id, row.id);
  assert.equal(context.empty.length, 7);
  assert.equal(context.filled[0].dateLabel, context.empty[0].dateLabel);
  assert.ok(context.empty.every((day) => day.items.length === 0));
});
