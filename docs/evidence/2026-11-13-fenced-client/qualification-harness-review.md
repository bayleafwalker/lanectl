# Qualification harness review

Read-only Sage review found two blockers in the first harness drafts:

- A120s setsid child could expire before the600s acknowledged stop bound.
- A successful O_CREAT followed by failed unlink could be recorded as denial.

Corrected source uses3600s child/parent lifetimes and requires cancellation
completion under60s, before the180s independent command timeout. Successful
opens always remain OPENED; cleanup errors are separate and fail qualification.
The template query is labelled a configuration snapshot. Documentation says
only persistent host directories, preserving private temporary writes.

The same reviewer read the corrected source and returned PASS, contingent on
replacing the earlier observations with corrected live reruns before commit.
Both corrected reruns completed: cancellation0.109s with prior live PID/start
ticks, acknowledged stop, child gone/unit terminal/checkout removed; old-host
boundary still correctly fails on readable undeclared /etc/issue.

The reviewer did not execute harnesses. The coordinator measured the live results.
