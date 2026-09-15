A Git repository at `/app/repo` has suffered data corruption — standard git commands (`git log`, `git status`, `git ls-tree`, `git cat-file`) all fail with errors. The repository contains important project history across multiple branches including merge commits.

A manifest at `/app/manifest.json` describes the expected working state of the repository when fully repaired.

Diagnose all sources of corruption in the repository and write a repair tool at `/app/repair.py` that restores it to a fully functional state matching the manifest. Your repair code must not delegate recovery to `git index-pack` or `git unpack-objects`. After repair, `git fsck --no-dangling`, `git verify-pack`, `git log`, `git ls-tree`, and `git cat-file` must all succeed cleanly against the repository.