# Native Claude verification profile review

Native Claude Code / claude-sonnet-5-5, read-only tools and read-only repository mount.
The reviewer ran no commands. Subsequent required gate: `uv run --locked pytest -q`
passed **953 tests in 109.86 seconds**. Runtime execution of the exact declared
falsifier remains to be observed on the resumed worker.

Permission syntax reference: https://code.claude.com/docs/en/permissions

**Verdict: PASS for integration.** I found no blocking permission widening and no CLI serialization defect. I read only the three files you named and ran nothing, so I did not run the CLI or the test suite. The full-suite result is still pending on your side.

**Security**
- **Source of the commands.** `runner.py:548` passes `rel.acceptance.exec` only when `adapter_fn is None` and the worker is `claude`. That is planner-frozen data. The same list is already shown to the worker in `render_prompt` under "Acceptance" (`runner.py:339`). Model text never reaches `build_command`.
- **Permission mode.** `acceptEdits` is unchanged, and `build_command` adds no bare `Bash`, no `Bash(*)` and no bypass flag.
- **Rule form.** Each rule is `Bash(<exact string>)`. Because `*` is refused (`adapters_claude.py:64`), none can become a prefix or wildcard rule, including the `:*` form. A worker cannot append arguments to an allowed command.
- **Separator characters.** `, \r \n \0 & | ;` are refused. This blocks both a compound command and a single string that would be read as several rules.
- **Empty rules.** Empty and whitespace-only commands are refused, so no `Bash()` rule is built.
- **Argument order.** `--allowedTools` is variadic, and the `--` is appended only when rules exist (`adapters_claude.py:68`). The prompt is therefore always the final positional argument. A prompt that starts with `-` cannot be read as a flag.
- **Legacy calls.** With no commands, the argv is byte-identical to before.
- **Failure handling.** `ValueError` is caught inside the adapter's `try` (`adapters_claude.py:272`). A refused command gives a `failed` attempt with exit code 1 and a clear reason. It does not crash the runner and it fails closed.
- **Inherited rules.** Deny and ask rules still win, per the docs you cited.

**Optional compatibility limits (not blockers)**
1. **Hard failure on compound or comma commands.** A frozen acceptance command containing `&&`, `|`, `;` or a comma now fails every Claude attempt for that release, with no runner-side fallback. Before this repair, those releases launched but could not run the command. This is the intended refusal, but a planner who writes `cd x && pytest` gets a failed attempt, not a warning. I'd add an admission-time lint or a clearer error message later. Bare `&` and `|` inside quotes are also refused, for example `pytest -k "a|b"`.
2. **Parentheses.** `Bash(` rules containing `(` or `)`, for example `-k "(a or b)"`, may hit the CLI's rule-parser escaping. I could not verify this without running the CLI. The likely outcome is a rule that fails to match, so the worker is prompted or denied. It is not a widening. I'd add a test or refuse parentheses explicitly.
3. **Whitespace and quoting.** Matching is on the exact string. A worker that rewrites a command, such as reordering flags or dropping `uv run`, will be denied. This is correct, but the prompt should tell workers to run the acceptance commands verbatim. It currently only lists them.
4. **Mixed releases.** Any bad command in a release fails the whole attempt, even if the others are fine.
5. **Test gaps.** The tests don't cover backslashes, parentheses, or non-string and `None` entries. The non-string branch in `build_command` is untested. The runner test stubs the adapter, so `run_claude` forwarding into `build_command` is covered only by the unit tests.

I'd hold only if the full suite fails or you want limit 2 verified against the real CLI before merging.
