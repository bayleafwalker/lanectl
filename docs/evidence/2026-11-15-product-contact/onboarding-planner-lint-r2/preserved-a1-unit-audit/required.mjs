import * as real from "file:///projects/dev/_wt/hla-onboarding-a1-audit-20261115/apps/web/frontend/lib/onboarding-checklist-state.mjs";
export const freshDatasetNames=real.freshDatasetNames;
export const checklistView=real.checklistView;
export function checklistProgress(sources,fresh){return real.checklistProgress(sources.map(s=>({...s,required:true})),fresh)}
