const assert = require('node:assert/strict');
const disjoint = require('./disjoint.cjs');
// Exercise the same serialized predicate passed to Playwright evaluateAll.
function node() { return {children:[], contains(x) { return this===x || this.children.some(c=>c.contains(x)); }}; }
const row=node(), nested=node(), sibling=node();row.children.push(nested);
assert.equal(disjoint([row]), true, 'one outer row is one component');
assert.equal(disjoint([row,nested]), false, 'nested alias cannot masquerade as two rows');
assert.equal(disjoint([nested,row]), false, 'ancestor overlap rejected in either order');
assert.equal(disjoint([row,sibling]), true, 'two sibling rows are distinct');
assert.equal(disjoint([row,row]), false, 'same node cannot count twice');
console.log('disjoint browser-expression controls passed');
