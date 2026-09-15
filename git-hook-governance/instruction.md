A pre-receive hook skeleton exists at `/app/hooks/pre-receive`. It partially implements a policy enforcement system driven by a `.repo-policy` INI file stored in the repository. The hook receives ref updates on stdin in the format `<old-oid> SP <new-oid> SP <ref-name> LF` and must handle multiple ref updates per push.

**Policy source**: The hook reads `.repo-policy` from the tree of the newest branch-update commit in the push. When no branch update is present (tag-only or deletion-only pushes), it must fall back to reading from the repository HEAD.

**`[protected-branches]`**: Multiple `pattern` keys specify branch-name globs (`main`, `release/*`). Pushes to matching branches must be fast-forward only — reject non-fast-forward updates and branch deletions. Wildcard matching is required (`release/*` must match `release/v1.0`).

**`[commit-message]`**: The `regex` key is a PCRE pattern. Every new commit's subject line must match. For new branches (old-oid all-zeros), validate only commits not reachable from any existing ref — do not re-validate commits already present in other branches.

**`[file-size-limit]`**: `default` sets a maximum blob size in bytes. Additional keys are file glob patterns with per-type overrides (`*.bin = 0`). Check each added or modified blob against the applicable limit.

**`[forbidden-files]`**: Each `pattern` key is a file glob. Reject any added or modified file matching a forbidden pattern.

**`[tag-policy]`**: `require-annotated = true` rejects lightweight tags. `no-delete = true` rejects tag deletion.

**`[merge-policy]`**: `require-linear-history = true` rejects pushes to protected branches that introduce merge commits (commits with more than one parent). Applies only to branches matching `[protected-branches]` patterns. For new branches, check only commits not reachable from existing refs.

On any violation, print `POLICY VIOLATION:` followed by a description to stderr and exit non-zero. All checks must execute for every ref update — report all violations before exiting, not just the first.

The skeleton has defects and missing functionality. Analyze it against this specification, fix all issues, and implement any missing policy enforcement so the hook fully conforms.
