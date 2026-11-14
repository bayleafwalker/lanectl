# Findings-first rereview of LANECTL 7dcb22d

I read the source, the fixture and the tests by static inspection only. I executed nothing. I did not check the `/tmp` prior review, the installed 0.2.9 client state, the public client read or the hosted flow. The Bash tool was disabled, so I could not run `git rev-parse` to confirm the checkout is at 7dcb22d. I reviewed the files in the worktree, and they match the diff you supplied.

## Blockers

None.

## Advisories

**A1. The non-null nested branches of the captured schemas are never matched.**
- `tests/stage9/test_catalog_schema.py:15-22` builds `RESULTS` only with the empty or null branches.
  - `work.evidence.tail-v1` uses `item: None`.
  - `work.lease.read-v1` uses `leases: []`, `outcome_reports: []` and `current_lease: None`.
  - `work.public.item-v1` uses `priority: None` and `blocked_by: []`.
- `test_captured_lease_non_null_branch_checks_nested_constraints` (lines 95-106) covers only `current_lease`.
- Never matched:
  - the evidence `item` object with `claims`, the `freshness` anyOf and `validity`;
  - `leases[]` rows;
  - `outcome_reports[]` rows, including `checks` and `parked`;
  - non-null `superseded_by` and `takeover_of`;
  - non-empty `blocked_by`.
- `_supported` does walk these branches, because every fixture schema goes through `valid()` and so through `_supported`. The gap is in matching, not in keyword coverage. I found no defect by reading, but a regression there would pass the suite.

**A2. The new input-validation branches have no direct test.**
- `src/lanectl/lifecycle.py:116-117`, the unsupported input schema case, is not exercised.
- Lines 121-122, the arguments-mismatch case, are not exercised.
- Neither are the `ready_work` or `_fact` outcomes they cause. The expected outcome is an `unknown` fact with a reason.
- A grep found none of these error strings in any test.

**A3. Lines 123-126 of `lifecycle.py` are effectively dead.**
- `_valid(result, schema)` at line 121 already enforces `required` and the per-property constraints.
- The required-missing case now reports "do not match input schema" instead of "cannot construct required read arguments". Still unknown, only the reason text changes.
- No test depends on the old message.

**A4. The pattern error handler cannot trigger, and the OverflowError regression no longer tests it.**
- `src/lanectl/catalog_schema.py:105-108` catches `re.error`, `OverflowError` and `RecursionError` after the allowlist at lines 101-104.
  - Every string that passes the allowlist compiles, so this handler is unreachable.
- In `tests/stage9/test_catalog_schema.py:109-113`, the `x{999999999999999999999999}` case is rejected by the allowlist. It never reaches `re.compile`.
- That is safe and fails closed, but the test name and comment overstate what it exercises.

**A5. No test covers over-deep data values.**
- `_json` (`catalog_schema.py:28-30`) caps value depth at 64, so a RecursionError cannot come from this module.
- `test_excessive_depth_fails_closed` (test file lines 66-70) covers only schema depth.

**A6. Cosmetic: extra blank lines at `lifecycle.py:99-102`.** The old `_valid` was removed and three blank lines remain.

## Verified by reading

- **Regex scope:**
  - `catalog_schema.py:101-104` accepts only the five exact catalog strings or the literal form `\^?[A-Za-z0-9_-]+\$?`, with a length cap of 256.
  - `.`, `\w`, classes, groups and repeats outside the five strings fail closed.
  - The module docstring claims only this restricted subset. It does not claim arbitrary ECMA/Python equivalence.
- **Fixture patterns:** I listed all 20 `"pattern"` values in `catalog_schemas.json`. Each is one of the five strings in `_CATALOG_PATTERNS`, with the JSON `\\+` unescaping to the source's `\+`.
- **End anchor:**
  - `catalog_schema.py:154` rewrites a trailing `$` to `\Z`.
  - The regression `test_pattern_end_anchor_rejects_final_line_terminators` (test lines 115-120) covers `\r`, `\n`, U+2028 and U+2029 on both a literal pattern and the captured `run_id` pattern. It also covers a prefix before `^`.
  - The pattern is applied only to strings and `^` is not multiline, as in ECMA.
- **Dot/CR mismatch:** `^a.b$` is rejected up front, so no dot semantics are asserted.
- **Equality:**
  - `_equal` (lines 42-51) keeps bool apart from numbers at every nesting level and treats `1 == 1.0`.
  - It compares dicts by key set. NaN and Infinity are refused by `_json`.
  - `const` and `enum` work without `type`, and duplicate enum members are rejected.
  - The tests at `test_lifecycle_literals.py:48-54` cover these cases.
- **Conjunction semantics:** `_matches` applies `type`, `const`, `enum`, `anyOf` and the object, array, string and numeric constraints together as a conjunction.
  - Keywords apply only to the matching value type.
  - `additionalProperties: false` closes the object. Absent or `true` leaves it open. A schema as the value fails closed.
- **Unused branches:** `_supported` recurses through `anyOf`, `properties` and `items`, so an unknown keyword in a branch the value never takes invalidates the whole schema. Tests cover this at `test_catalog_schema.py:55` and `test_lifecycle_literals.py:56-57`.
- **Unavailable state:** `test_catalog_schema.py:31-40` asserts that `state: "unavailable"` gives `unknown` with no `value` key. This relies on the existing check at `lifecycle.py:193-195`.
- **Scope:** the diff touches only `lifecycle.py`, the new `catalog_schema.py` and files under `tests/stage9`.
  - There are no credential, grant, config or authority changes.
  - A case-insensitive grep of the fixture for token, secret, password, credential, bearer and api key found nothing.
  - By reading, it holds schema shapes only.
- **Other tests:** other tests' stub catalogs use only `type`, `properties`, `required`, `items` and `$schema`-free simple schemas. I saw no unsupported keywords, so I expect no fail-closed regression there. I did not run them.

## Verdict

**Clear for integration.** There are no blockers, and A1 to A6 can be follow-ups. The B1 keyword-incompatibility finding is resolved for the measured catalog subset. The regex handling is conservative and does not claim arbitrary regex semantics. No test execution is claimed. The source candidate is not integrated, released or installed, and the installed client remains 0.2.9.
