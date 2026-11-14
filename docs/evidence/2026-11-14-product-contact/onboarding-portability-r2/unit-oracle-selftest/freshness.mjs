import * as real from "file:///tmp/hla-onboarding-acceptance-draft-20261114/oracle-selftest/checkout/apps/web/frontend/lib/onboarding-checklist-state.mjs";
export const checklistProgress=real.checklistProgress;
export const checklistView=real.checklistView;
export function freshDatasetNames(rows,now){const result=real.freshDatasetNames(rows,now);return [...result,...rows.filter(r=>r.landed_at && now-new Date(r.landed_at).getTime()===7*86400000 && !result.includes(r.dataset_name)).map(r=>r.dataset_name)]}
