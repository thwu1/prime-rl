A git repository at `/app/repo` has suffered multiple forms of corruption after a partial disk recovery. All standard git operations (`git log`, `git status`, `git show`, etc.) fail with errors.

Diagnose every corruption issue and repair the repository in-place so that it is fully functional.

A manifest of the repository's pre-corruption state is at `/app/manifest.json`. The repaired repository must satisfy all of the following:

1. `git fsck --full` completes with exit code 0 and reports no errors
2. Every branch and tag listed in the manifest exists and resolves to its recorded SHA
3. The complete commit history is intact on every branch (correct subjects in correct order)
4. File contents at HEAD are byte-identical to those recorded in the manifest
5. All branches can be checked out successfully
6. No corruption artifacts remain anywhere under `/app/repo/.git`