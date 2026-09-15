A git repository at `/app/repo` has been corrupted in multiple independent ways. Standard git operations (`git log`, `git fsck`, `git status`) all fail. The repository originally contained 6 commits across two branches (`master` and `feature/string-utils`), including a merge commit.

Your objectives:

1. **Diagnose and repair all corruptions** so that:
   - `git fsck --full` exits cleanly with no errors
   - `git log --all --oneline` shows all 6 original commits
   - Both branches (`master` and `feature/string-utils`) resolve to valid commits with correct file contents
   - `git verify-pack` succeeds on all packfiles

2. **Write `/app/diagnosis.json`** — a JSON object with an `"issues"` key containing an array of objects, each with `"category"` (string) and `"description"` (string, >=15 chars explaining what was corrupted and how you fixed it). Document at least 4 issues.

Corruptions span multiple layers of git internals: references, metadata files, and binary object storage. Some failures mask others — fixing one issue may reveal the next.

**Constraints:**
- Do not reinitialize the repository (`git init`), clone from external sources, or delete/recreate `.git`
- The original commit author is "Test User" and all commits must retain their original messages and authorship
- Objects must remain in pack format (do not fully unpack into loose objects as a workaround)