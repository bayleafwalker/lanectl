# Review of LANECTL candidate 974e694: not cleared for integration

I read `src/lanectl/lifecycle.py` and the surrounding tests with Read/Grep only. I ran no code and did not read the real owner catalog, which is private. I did not verify that any tests pass.

The fix does what was asked for the reported case: const and enum are checked together with type, wrong authority and state are rejected, `unavailable` stays unknown, and bool is kept distinct from number. The one blocker is a fail-closed change that could turn every owner read into unknown.

## Blocker

**B1. The keyword allowlist is much narrower than real catalog schemas, and it applies to input schemas too.**
- `lifecycle.py:137-142` rejects any schema keyword outside `type`, `const`, `enum`, `properties`, `required` and `items`. The rejection covers nested schemas, including unused ones, via lines 155 and 160.
- The old `_valid` ignored unknown keywords on objects, so this is a behaviour change, not only a new check.
- Catalogs in this repo use more keywords than that. `vuoro_adapter.py:17-18,24-25` uses `minimum`, `maximum`, `minLength`, `maxLength`, `minItems` and `maxItems`. The Vuoro tool schemas I can see use `description` and `additionalProperties:false`.
- If the sprintctl list, item, lease, run or evidence schemas carry any of these, the effects are:
  - Results fail at `lifecycle.py:282` with the message "does not match catalog result schema". That message is misleading when the real cause is an unsupported schema.
  - Input properties such as `work_id` with `minimum:1` fail at `lifecycle.py:216`. Every item and lease read then becomes unknown before any call is made.
- The new tests only exercise `pattern` as an unsupported keyword (`test_lifecycle_literals.py:57`). No test uses a catalog-realistic keyword.
- **To clear it,** either confirm against a captured real catalog that all six operations use only the supported keywords, in both input and result schemas, or change the validator. Two options for the validator:
  - Ignore annotation keywords that don't validate (`description`, `title`, `$comment`, `default`, `examples`, `$schema`, `$id`, `deprecated`) and either enforce or explicitly reject the numeric, string and array bounds.
  - Report "unsupported schema keyword X" as a distinct reason from a value mismatch.

## Advisories

- **A1. Arrays without `items` are newly rejected, even when empty.**
  - `lifecycle.py:160` calls `_schema_supported(schema.get("items"))`, which returns False for a missing `items`.
  - The old code defaulted to `{}` and accepted `[]` (the old `_valid` array branch).
  - `{"type":"array"}` is a plausible catalog shape. No test covers it.
- **A2. Authority provenance depends entirely on the catalog containing the const.**
  - `lifecycle.py:284-286` only checks `state` and only when `"authority"` is present. Nothing checks `authority == "sprintctl"` independently.
  - A catalog that omits the const, or a result that omits `authority` when the schema doesn't require it, would be observed.
  - This is probably acceptable as catalog-driven, but you should decide it deliberately.
- **A3. Unsupported-schema errors are indistinguishable from mismatches.** Both `lifecycle.py:216-217` and `lifecycle.py:282-283` give the same message. This hurts operator diagnosis, and it is how B1 would present.
- **A4. Unhandled non-CoordinationError exceptions.**
  - `_fact` only catches `CoordinationError` (`lifecycle.py:298`).
  - Deeply nested results or schemas can raise `RecursionError` from `_json_value` or `_schema_supported`, and that would propagate out of `ready_work` and `lifecycle`.
  - `_valid` re-runs `_json_value` and `_schema_supported` at every recursion level and for every array item (`lifecycle.py:171,186`), which costs O(depth×size). This is minor.
- **A5. Duplicate enum members are rejected (`lifecycle.py:150`).** Draft 2020-12 only says SHOULD be unique, so this is stricter than the spec. Duplicate `required` entries are rejected too (`lifecycle.py:158`), and that one is acceptable. Both are unlikely to matter.
- **A6. `float` NaN or Infinity in results is now rejected** (`lifecycle.py:106-107`). `json.loads` accepts these by default, so this is a behaviour change, though arguably correct. Only a NaN const is tested (`test_lifecycle_literals.py:56`), not NaN or Infinity in a value.
- **A7. `str` and `int` subclasses.** `_json_equal` falls through to `type(left) is type(right)` at `lifecycle.py:125`. An enum-like `str` subclass would not equal its plain-string const. Results come from JSON, so this is low risk.

## Test gaps

I did not execute any of these, so "covered" means a test exists in the diff.

- **Covered:**
  - The observed list shape and correlated result.
  - Wrong authority and wrong state.
  - `unavailable` staying unknown.
  - A wrong `as_of` type.
  - Items that are not an array.
  - Const, enum and type in conjunction.
  - Bool versus number, including nested.
  - 1 versus 1.0.
  - Malformed enum (non-list, empty).
  - Unsupported `type` and `pattern`.
  - A NaN const.
  - Unsupported keywords inside an unused nested schema.
- **Missing:**
  - Empty schema `{}`, `{"type": None}` and a list-valued `type`.
  - Annotation-only keywords.
  - Arrays without `items`.
  - Real-shape catalog keywords (B1).
  - Nested equality mismatches: dict key sets, list lengths and order.
  - Python non-JSON values in results (tuple, set, bytes, non-string keys, NaN or Infinity).
  - Malformed `required`, and `properties` that aren't a dict.
  - Input-schema rejection through `_arguments` (`lifecycle.py:216`).
  - The reason string for the unavailable case.
  - Absence of `value` on unknown facts.
  - Gateway correlation. The test fake ignores the envelope and `invoke` returns the result directly, so request_id and catalog_revision correlation is not exercised here. That is out of scope for `lifecycle.py` but is a gap in what the tests show.

## Scope

The diff touches only `lifecycle.py` and a new test file. It changes no credentials, grants, config or authority.

## Verdict

**Not cleared for integration until B1 is resolved.**

The fix is correct for the reported case, but it makes validation stricter for every catalog read. The full suite has not been qualified. The only evidence on suite status is your report of 58 lifecycle tests passing, which I did not check.

I handled this review directly with no delegation. I have no timing figures, and effort was one read pass.
