# Operator UI delivery closeout — 2026-11-12

## Intended outcome and delivered scope

The approved [operator UI horizon](../ideation/2026-11-11-functionality-and-ui.md)
and served items lanectl#2895–#2898 define this delivery. UI-01–UI-04 already
existed. This delivery completes UI-05–UI-08 and repairs their integration with
the existing lifecycle projection. See the [operator guide](../operator-ui.md).

| Item | Result | Principal regression evidence |
| --- | --- | --- |
| UI-05 / #2895 | Preview-bound claim-and-run, fresh owner/configuration checks, existing coordinated runner; advanced reasoned claim-only hold with finite owner expiry and exact recovery | `test_claim_preview*`, `test_acc_ui_integration.py`, `test_acc_claim_hold.py`, `test_claim_hold*` |
| UI-06 / #2896 | Shared verification bundle and TUI evidence view: gates, checked commit, deploy, landing, chain, reported outcome and owner decision | `test_acc_verification.py`, `test_verification.py`, `test_acc_ui_integration.py` |
| UI-07 / #2897 | Read-only static lifecycle export, known identity round-trips, corresponding TUI command, safe references and per-source freshness | `test_lifecycle_web.py`, `test_acc_ui_web_integration.py`, `test_lifecycle_links*`, `test_lifecycle_final_review.py` |
| UI-08 / #2898 | Queue/execution/integration/verification intervals, retry waits, lane/operator units, estimated prices and explicit attribution limits | `test_acc_accounting.py`, `test_accounting*`, `test_acc_accounting_coverage.py`, `test_ui_web_coverage.py` |

No owner ledger, event type, runtime dependency or broader effect authority was
introduced. Owner outages are unknown; a report stays pending until the owner
reports done/accepted. Work IDs and release IDs remain distinct. Missing phase
endpoints and unpriced usage do not become complete totals. Advanced holds use
the existing coordination journal, start no worker, and send no heartbeat.

## Verification and product-intention pass

The baseline suite had 813 tests. The final integrated train passed 944 tests
after two small contract-review fixes. The v0.2.2 release tree also passed all
944 tests (`uv run --locked pytest -q`, 109.99 seconds). Each native release had frozen
acceptance verified to fail on its base before publication and passed its
deterministic gates before independent integration review.

A combined synthetic-owner smoke exercised the real lifecycle query, shared
verification/accounting projection, an 80×24 terminal frame, plain output, static
export and owner outage. It verified joined work/release/attempt/train identities,
visible checked/landed commit evidence, pending owner acceptance, a known partial
cost subtotal with unknown total, and exclusion of raw-body sentinels. Chromium
desktop and 390-pixel mobile screenshots were inspected. A separate HTTP-server
regression resolves percent-encoded repository names to the actual exported file.

This is local and simulated-owner qualification. No live product work was
claimed, and no cluster or NixOS configuration was changed. The separate fenced
train backend item #2889 remains pending; host qualification and hosted product
flow evidence are not supplied by this UI delivery.

## Native outcome-routing observations

Ten bounded releases ran through the governed implementation lane, with frozen
acceptance, worker isolation, deterministic gates and one integration owner.
Explicit native routing admitted ten DeepSeek V4.1 Flash attempts and seven
DeepSeek V4 Pro attempts through OpenCode Go. All ten releases were integrated.
Seventeen attempts were admitted; seven required another attempt:

- Two infrastructure abandonments followed the initial runner-session loss.
  Recovery required proof that each recorded runner was dead and its sandbox
  inactive. Subsequent runner/check units survived chat turns through systemd.
- Two accounting model errors hid partly priced usage and unfinished execution.
  Reproduced failures became frozen regression acceptance before requeue.
- One permalink attempt exceeded the hard size budget (701 versus 700 lines).
  The native prompt now states the exact added-plus-deleted limit and asks for
  formatting margin.
- One integration retry corrected a planner-owned obsolete read-time digest
  assertion; the reviewed implementation was reused unchanged.
- One claim-hold retry repaired shell quoting in generated commands and preserved
  an acknowledged run ID across acquisition uncertainty. Both were reproduced.

Independent review also required three bounded spec-gap fixes: owner unavailable
payload handling and native budget guidance (20 lines), shared web attribution
coverage (24 lines), and request-scoped train selection plus visible commit
details/updated assertion (26 lines). Each stayed within the 30-line per-attempt
authority and was rechecked on the exact train tip. The final recheck initially
caught the obsolete assertion forbidding the `landed_sha` field name; raw-body,
credential-reference and unsafe-link checks remain in force. These are planner
and integration findings, not evidence that preliminary gate acceptance alone
guarantees product correctness.

Observed lane execution sums to 9,923 seconds across attempts; overlapping work
means this is not wall-clock delivery time. Fifteen recorded lane-usage events
give a **known token-cost subtotal of USD 1.597065 estimated**, using allocation
price revision 11. Every release's full cost remains unknown because not all
reported components are priced. Operator model usage and active human/coordinator
minutes were not measured; no complete economic or precision claim is made.

Git source, frozen acceptance and this closeout are cross-host-replicated.
Served work status is durable-authoritative. Local event/journal evidence is
host-persistent; scratch smoke scripts, exports and screenshots under `/tmp` are
session-local and are not the authoritative record.
