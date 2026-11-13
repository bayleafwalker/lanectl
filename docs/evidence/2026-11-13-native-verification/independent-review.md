# Native verification follow-up review

Read-only native Claude Code / claude-sonnet-5-5. Full gate completed after review:
**958 passed in 109.68s** (`uv run --locked pytest -q`).

**Verdict: PASS for integration.** I found no permission widening, no false-completion path and no CLI serialization defect. I did not run anything. This is source review only, and I did not independently check the Claude CLI behavior you cited.

**Permission widening: none found**
- `build_command` (`adapters_claude.py:63-70`) emits `--permission-mode acceptEdits` plus one `Bash(<declared>)` rule per command. It never emits bare `Bash`, `Bash(*)`, or bypass or skip-permissions flags.
- `_verification_commands` (`:47-60`) refuses `* \r \n \0 , & | ;`, so wildcard, list-splitting and compound inputs fail closed. It also rejects non-strings, blank strings and a bare string.
- Rules equal the declared commands. There is no wrapper normalization, and the `shutil.which` stub in the tests shows `snip` presence doesn't change the rule.
- The runner call site (`runner.py:548`) forwards only `rel.acceptance.exec`. It does so only when `adapter_fn is None` and `c.worker == "claude"`, so injected adapters and other workers are unaffected.
- `--` follows the variadic `--allowedTools` and precedes the prompt, so the prompt can't be consumed as a rule.

**False completion: none found**
- Any truthy `permission_denials` now makes `parse_result` return `escalated` (`:161-162`). If the model's own escalation marker is present, its reason is kept.
- The fixed denial reason doesn't copy the command input, and the test asserts the sentinel is absent.
- In `run_claude`, a `done` outcome with a nonzero exit becomes `failed`, and the timeout path is unchanged.
- A `ValueError` from validation is caught at `:280` and recorded as `failed` with a status file written. The attempt can't proceed unvalidated.

**Non-blocking limitations (compatibility, not security)**
1. **Legacy behavior change on the default path.** The denial-to-escalation rule lives in `parse_result`, so it applies to calls with no `verification_commands`. Under plain `acceptEdits`, any Bash attempt is denied. A run that tried `ls`, was denied, recovered and finished used to be `done` and is now `escalated`. This fails safe (over-escalation, not false success). It does contradict the "legacy keeps existing behavior" claim, which is only true for argv. Either gate the rule on `verification_commands` being non-empty or record it as intentional.
2. **Valid acceptance commands now fail the whole attempt.** Frozen commands containing `&`, `|`, `;` or `,` fail the whole claude attempt with "claude launch failed". That includes `2>&1`, `||` and `a,b` inside an argument. Previously those attempts ran without Bash. It is fail-closed, but a planner will see an unexplained launch failure. Consider a clearer error message (it should name the offending character class, not the command) or a pre-release lint.
3. **Characters not refused.** `(`, `)`, `$(`, backtick, `<`, `>`, `"` and `\` pass through. They can't widen anything, because the rule is the whole literal string. Rules containing `)` may parse oddly in the CLI's `Tool(content)` syntax and cause denials, which now escalate. Leading and trailing whitespace is kept in the rule, so a padded command may not match.
4. **Exact rule doesn't mean exact effect.** The allowed `pytest` command executes worker-authored tests and `conftest`, so it is effectively arbitrary code inside the OS sandbox. That is inherent in frozen acceptance and rests on the sandbox and protected paths, as you stated.
5. **Prompt wording.** "No additional Bash commands are authorized" is slightly stronger than reality, since the CLI auto-allows some read-only commands. It is harmless, and the commands are also already listed under Acceptance in `render_prompt`.

**Test gaps (optional)**
- Only `&&` is covered for the compound case. Add `|`, `;`, single `&` and `2>&1`.
- Add a `run_claude` case where invalid commands return `failed` and no CLI is launched.
- Add a legacy case with denials and no `verification_commands`, so limitation 1 is pinned either way.
- Add a case where an escalation marker is present alongside denials, to pin that the model's reason wins.

Integrate once the full suite is green. I'd resolve limitation 1 (gate it or document it) first. It is small and doesn't block.
