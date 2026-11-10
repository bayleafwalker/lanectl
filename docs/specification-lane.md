# Intent-to-draft specification

`lanectl spec` runs a specification author and an independent adversarial
reviewer in disposable, sandboxed clones. It copies only bounded, validated
acceptance source and the outcome into a new draft release. The planner still
publishes it. Model output cannot choose shell commands, scope, base commit,
release identity, data class, dependencies or grants.

```sh
lanectl spec add-subtraction --repo example --title 'Support subtraction' \
  --intent-file intent.txt --scope 'src/**' \
  --author-model claude-sonnet-5-5 --reviewer-model claude-opus-5-5
lanectl backlog show add-subtraction
lanectl backlog publish add-subtraction
```

Choose installed models appropriate to the repository and subscription. The
author must differ from every currently routed implementation model and from
the reviewer. Restricted intent or a restricted repository requires the existing
first-party allowlist. Public intent may use external models; public classification
is an operator assertion, not a redaction step. The implementation filter retains
the recorded author exclusion after routing changes.

The caller supplies the outcome intent, target repository, allowed scope, size
and work reference (`--work repo#id`). Each model is bounded by `--timeout`
(default 600 seconds, maximum 2700). The intent is limited to 16 KiB, each JSON
response to 64 KiB and a proposal to eight new Python acceptance files. Existing
acceptance/support files and symlink paths cannot be replaced. Generated tests
run only inside the lane's configured sandbox during the base check.

The author returns JSON with `outcome` and `tests` (path-to-source mapping).
The reviewer sees that exact proposal and the base repository, and returns
`verdict`, `reason`, `trivial_pass` and a nonempty `checks` list. The review asks
about constant answers, ignored inputs, mocking away the subject, missing outcome
assertions and an incorrect base failure. It is evidence for the planner, not
proof that all possible trivial implementations were exhausted.

`specification.json` preserves identities, the intent digest, model usage,
adversarial review and lint findings. Its release digest covers the release
contract and every acceptance file. An edit or rebase invalidates the evidence;
review a new draft against the new base instead of overriding it. A negative
review remains a draft and blocks publication even with a lint override. A valid
review also remains a draft until `backlog publish` succeeds. Ordinary manually
authored releases retain their existing publication workflow.

Artifacts under `backlog/` become cross-host-replicated when committed and
pushed. Temporary clones are session-local and removed after each model call.
No specification command changes lane authority, policy or publication state.
