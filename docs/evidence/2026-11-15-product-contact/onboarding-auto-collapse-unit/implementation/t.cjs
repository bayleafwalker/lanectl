"use strict";
// HLA1597 unit coverage: OnboardingChecklist renders the compact badge on its
// own when both required core datasets are active (no user action).
//
// Scope: the mounted/hook-order seam only. The REAL component and REAL
// onboarding sources are compiled in memory with esbuild. Only the third
// useState (`mounted`) is initialised true, standing in for the post-effect
// render. NOT covered: hydration, localStorage, Expand, manual interaction.
//
// Falsifier: an external preload may patch esbuild.transformSync; nothing here
// knows about it.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");

const FRONTEND = path.resolve(__dirname, "..");
const req = Module.createRequire(path.join(FRONTEND, "package.json"));
const esbuild = req("esbuild");
const React = req("react");
const { renderToStaticMarkup } = req("react-dom/server");

function compile(rel, patchLoad) {
  const filename = path.join(FRONTEND, rel);
  const { code } = esbuild.transformSync(fs.readFileSync(filename, "utf8"), {
    loader: "jsx",
    format: "cjs",
    sourcefile: filename,
  });
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const origLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    const fromSubject = parent === mod;
    if (fromSubject && patchLoad && patchLoad[request]) return patchLoad[request];
    return origLoad.call(this, request, parent, isMain);
  };
  try {
    mod._compile(code, filename);
  } finally {
    Module._load = origLoad;
  }
  return mod.exports;
}

const sources = compile("lib/onboarding-sources.js");
const SOURCES = sources.ONBOARDING_SOURCES;

function load(mountedInitial) {
  const state = { calls: 0 };
  const adapter = {
    ...React,
    useState(initial) {
      state.calls += 1;
      const value = state.calls === 3 ? mountedInitial : initial;
      if (state.calls !== 3) assert.equal(initial, false, `hook ${state.calls} initial`);
      return React.useState(value);
    },
  };
  const { OnboardingChecklist } = compile("components/onboarding-checklist.js", {
    react: adapter,
    "@/lib/onboarding-sources": sources,
  });
  return function render(freshDatasets) {
    state.calls = 0;
    const html = renderToStaticMarkup(
      React.createElement(OnboardingChecklist, { freshDatasets, nextSuggestion: null }),
    );
    assert.equal(state.calls, 3, "exactly 3 useState calls per render");
    return html;
  };
}

const text = (html) =>
  html.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

const HEADING = "Get started — connect your data sources";
const render = load(true);

function full(datasets, active, core) {
  const t = text(render(datasets));
  assert.ok(t.includes(HEADING), t);
  assert.ok(t.includes(`${active} of 5 sources active`), t);
  assert.ok(t.includes(`${core}/2 core sources ready`), t);
}

function compact(datasets, active) {
  const t = text(render(datasets));
  assert.ok(!t.includes(HEADING), t);
  assert.ok(t.includes(`Onboarding: ${active}/5 sources active — core sources ready`), t);
  assert.ok(t.includes("Expand"), t);
}

test("fixture: real sources define 5 datasets, 2 required", () => {
  assert.equal(SOURCES.length, 5);
  assert.equal(SOURCES.filter((s) => s.required).length, 2);
});

test("SSR without mounted renders nothing", () => {
  const ssr = load(false);
  assert.equal(ssr(["account_transactions", "subscriptions"]), "");
});

test("none -> full 0/5 core 0/2", () => full([], 0, 0));
test("one core -> full 1/5 core 1/2", () => full(["account_transactions"], 1, 1));
test("optional only -> full 3/5 core 0/2", () =>
  full(["contract_prices", "budgets", "loan_repayments"], 3, 0));
test("core + partial optional -> full 4/5 core 1/2", () =>
  full(["subscriptions", "contract_prices", "budgets", "loan_repayments"], 4, 1));
test("both cores -> compact 2/5", () => compact(["account_transactions", "subscriptions"], 2));
test("both cores + optional -> compact 3/5", () =>
  compact(["account_transactions", "subscriptions", "budgets"], 3));
test("all five -> compact 5/5", () => compact(SOURCES.map((s) => s.dataset), 5));
test("duplicate core + unknown -> full 1/5 core 1/2", () =>
  full(["account_transactions", "account_transactions", "unknown"], 1, 1));
