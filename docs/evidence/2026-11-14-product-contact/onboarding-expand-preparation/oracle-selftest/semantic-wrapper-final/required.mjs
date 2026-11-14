import * as real from "file:///tmp/hla-onboarding-acceptance-draft-20261114/oracle-selftest/checkout/apps/web/frontend/lib/onboarding-checklist-state.mjs";
export const freshDatasetNames=real.freshDatasetNames;
export const checklistView=real.checklistView;
export function checklistProgress(sources,fresh){return real.checklistProgress(sources.map(s=>({...s,required:true})),fresh)}
