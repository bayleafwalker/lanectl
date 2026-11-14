import * as real from "file:///tmp/hla-onboarding-acceptance-draft-20261114/oracle-selftest/checkout/apps/web/frontend/lib/onboarding-checklist-state.mjs";
export const freshDatasetNames=real.freshDatasetNames;
export const checklistProgress=real.checklistProgress;
export function checklistView(state){return real.checklistView({...state,userExpanded:false})}
