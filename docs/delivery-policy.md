# Delivery policy binding

A new outcome's first publication records the effective lane policy as
`lanectl.delivery-policy/v1`. Later publications inherit it. Claims carry the
same snapshot, so changes to lane configuration do not reinterpret an attempt.
The `routing.delivery_policy` lane setting is `legacy` when absent; setting it
to `review-progress` affects newly published outcomes only.

Review-progress retains line counts and attempts as diagnostics. A failed
terminal attempt parks pending an agent's recorded judgment. The agent uses
`lanectl review-progress ATTEMPT continue|stop --progress TEXT --remaining TEXT
--reason TEXT` to record actual progress, remaining requirements and the reason
for its judgment. Acceptance, protected paths, resource and effect controls
remain in force. A new revision does not reopen a terminal outcome.

Historical publications without a snapshot remain legacy. Where the first claim
records a lane revision and digest, lanectl searches retained Git history for
matching lane bytes; without matching evidence it leaves policy unresolved and
refuses decisions that depend on it. Diagnostic ratios with no denominator are
unavailable. Historical event projections keep their original semantics.

The snapshot is not an authority grant. Admission and execution also apply the
current lane's restrictions: model eligibility is intersected, path and data
restrictions are combined, and capacity, timeout and size eligibility use the
stricter limit. Changes to sandbox or effect policies fail closed because they
cannot be safely ordered. Recovery does not accept recorded gate results when
current authority has tightened since publication; those checks need to run again.
