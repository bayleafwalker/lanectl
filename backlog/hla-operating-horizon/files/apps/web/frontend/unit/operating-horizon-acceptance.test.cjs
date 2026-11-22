"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");
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
