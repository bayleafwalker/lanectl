/* Used verbatim in page.evaluateAll and synthetic DOM-expression controls. */
function componentsDisjoint(nodes) {
 for (let i=0;i<nodes.length;i++)
  for (let j=i+1;j<nodes.length;j++)
   if (nodes[i]===nodes[j] || nodes[i].contains(nodes[j]) || nodes[j].contains(nodes[i])) return false;
 return true;
}
module.exports = componentsDisjoint;
