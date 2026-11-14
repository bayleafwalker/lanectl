Status: I've read the diff, `runner.py`, `contracts.py`, `events.py`, `coordination.py`, `claim_preview.py` and the affected tests. Nothing was executed. Here is the review.

# Verdict: **blocked** (no merge)

Finding 1 should block. Findings 2–4 should be fixed in the same revision.

## Findings, most severe first

**1. Prompts with no feedback are no longer byte-identical to before. This breaks replay of in-flight attempts across the upgrade.**
- `src/lanectl/runner.py:401-403` now reads `...collected.\n\n{prior}\n# Escalate`. Before, it read `collected.\n\n# Escalate`. With `prior == ""` that adds an extra `\n`.
- So every prompt changes, including first attempts with no feedback.
- The prompt digest becomes `profile_digest`. That digest is part of the owner identity in `Owner.start` (`coordination.py:230,234`).
- If an attempt was started by 0.2.10 and then replayed by this code, `_call` raises "same operation key has different content" (`coordination.py:181`). `_put` can also raise "different work/model/profile binding" (`coordination.py:221`).
- Either error lands in the wrapper's `except` and the attempt is parked as "owner coordination unavailable".
- That breaks the "recovery must remain" requirement. The break is avoidable: build `prior` so that empty feedback adds zero bytes.
- Replays under the same code are stable. The cutoff is the current claim's log position, and later appends can't change what precedes it.
- No test pins the no-feedback bytes. Add one asserting that `render_prompt(..., feedback=None)` and `feedback=[]` equal the pre-change rendering.

**2. Prompt rendering now runs before the owner and `require_coordination` checks (`runner.py:533-535`).**
- Any render or feedback error is now reported by `_coordination_park` as "owner coordination unavailable: …". That is misattributed, and it also happens for uncoordinated repos.
- `tests/stage9/test_acc_ui_integration.py:66-75` now passes for the wrong reason. Its claim is `SimpleNamespace(repo=...)` with no `.rel`, so `c.rel` raises `AttributeError` before `coordination.configured` is reached. The test no longer exercises the "never fall back to native" branch.
- Fix: render immediately before `owner.start` and before the native call, or give that test a real claim.

**3. `_retry_feedback` trusts the shape of "validated" events.**
- `contracts.validate_event_parts` only checks that keys exist. It does not check types.
- An unhashable `attempt_id` makes `claims[...]` or `in claims` raise `TypeError`. A `reasons` of `None` or an int raises `TypeError`. A string `reasons` is iterated per character, producing one observation per character.
- Because of finding 2, any of these parks the next retry with a misleading message.
- Fix: add `isinstance` guards and fail closed to `[]`.
- Related: dedup keeps the first occurrence, not the latest. That is minor.

**4. Native `execute(..., prompt=None)` forwards `None` to the adapter (`runner.py:612,660`).**
- A direct call to the unwrapped function, for example through `__wrapped__`, would pass `prompt=None`.
- Fall back to `render_prompt(...)` when `prompt is None`.

## Challenge areas that held up

- **Cutoff stability.** `break` at the current claim's log position excludes later appends. The `future` and `current` cases are covered by tests.
- **Filtering.** Other items, other revisions and non-integrator authors (`by != "integrator"`) are filtered. A decision whose `attempt_id` has no earlier same-revision claim is dropped. Integrator `candidate` decisions are excluded.
- **Missing claim.** It returns `[]`, which fails closed.
- **Clipping and encoding.** Model and ID are clipped to 120 characters and reason to 1000. `json.dumps(ensure_ascii=True)` escapes newlines, so a reason can't forge a heading. Worst-case size is bounded (about 36 KB with 3 entries of 12× expansion).
- **Authority and injection.** The observations are labelled as data. That is a prose-level boundary only, which is acceptable because the integrator is a trusted writer. The prompt is unchanged outside the new block, apart from the extra newline in finding 1.
- **Single render.** One prompt string feeds both `owner.start` and `fn(prompt=...)`. Digest equality is structural.
- **Unchanged paths.** The state, gate, sandbox, lease and cancel code is untouched. The extra `log.read()` is read-only.

## Test quality

- **Old-source failure is forced.** The end-to-end test asserts the rejection text appears in the adapter prompt. Old source never passed observations, so that assert fails. The digest assert alone would not fail on old source.
- **Last-3 is not exercised.** Only two observations survive in the unit test (`old` and the clipped `z…`). The separate guard should cover this.
- **`parked` is untested.** The separate guard should cover this too.
- **Other gaps:**
  - No test covers the owner-unconfigured path with the prompt reaching the adapter.
  - No test asserts that the first attempt has no observation section.
  - No test covers malformed events or model/ID clipping.
  - The `len(str(feedback)) < 5000` bound measures Python repr, not the rendered JSON.
- **Execution.** I did not run the 1099-test suite or the new tests.

## Scope

No full provider, workflow or live hosted-claim qualification is claimed or implied. Source integration, release and install remain pending. The installed client is still 0.2.10.
