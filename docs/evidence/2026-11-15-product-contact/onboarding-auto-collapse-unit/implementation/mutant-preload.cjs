const Module = require("node:module");
const needle = "if (compact || allCoreActive)";
const orig = Module.prototype._compile;
Module.prototype._compile = function (content, filename) {
  if (filename.endsWith("components/onboarding-checklist.js")) {
    if (content.split(needle).length !== 2) throw new Error("expected exactly one match");
    content = content.replace(needle, "if (compact)");
    console.error("MUTANT APPLIED");
  }
  return orig.call(this, content, filename);
};
