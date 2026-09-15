"""
Tests for the pre-receive hook repository governance system.
Verifies that the hook enforces protected branches, commit message format,
file size limits, forbidden files, tag policies, and merge policies.
"""

import os
import subprocess
import shutil
import pytest


HOOK_PATH = "/app/hooks/pre-receive"

POLICY_CONTENT = """\
[protected-branches]
pattern = main
pattern = release/*

[commit-message]
regex = ^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\\([a-zA-Z0-9_-]+\\))?(!)?: .+

[file-size-limit]
default = 5242880
*.bin = 0
*.sql = 10485760

[forbidden-files]
pattern = *.exe
pattern = *.dll
pattern = .env
pattern = *.pem

[tag-policy]
require-annotated = true
no-delete = true

[merge-policy]
require-linear-history = true
"""


def run(cmd, cwd=None, check=True, input_data=None):
    """Run a shell command and return the result."""
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, input=input_data,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {cmd}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


@pytest.fixture
def repo_env(tmp_path):
    """Create a bare repo + working clone, commit policy, install hook."""
    bare = tmp_path / "bare.git"
    work = tmp_path / "work"

    # Create bare repo
    run(f"git init --bare --initial-branch=main {bare}")
    run("git config receive.denyNonFastForwards false", cwd=str(bare))
    run("git config receive.denyDeleteCurrent ignore", cwd=str(bare))

    # Create working clone (manual init since bare is empty)
    run(f"git init --initial-branch=main {work}")
    run("git config user.email 'test@example.com'", cwd=str(work))
    run("git config user.name 'Test User'", cwd=str(work))
    run(f"git remote add origin {bare}", cwd=str(work))

    # Write the policy file
    policy_path = work / ".repo-policy"
    policy_path.write_text(POLICY_CONTENT)
    run("git add .repo-policy", cwd=str(work))
    # Use a non-conventional commit message for the initial commit.
    # This commit is pushed BEFORE the hook is installed, so it succeeds.
    # It exposes new-branch enumeration issues: broken code re-checks all history.
    run('git commit -m "initial setup of repository"', cwd=str(work))
    run("git push -u origin main", cwd=str(work))

    # Install the hook into the bare repo
    hook_dest = bare / "hooks" / "pre-receive"
    shutil.copy2(HOOK_PATH, str(hook_dest))
    os.chmod(str(hook_dest), 0o755)

    return {"bare": bare, "work": work}


# ── Protected Branches ──────────────────────────────────────────────

class TestProtectedBranches:

    def test_fast_forward_push_to_main(self, repo_env):
        work = repo_env["work"]
        run("echo 'content' > file.txt", cwd=str(work))
        run("git add file.txt", cwd=str(work))
        run('git commit -m "feat: add file"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode == 0, f"FF push to main should pass: {result.stderr}"

    def test_force_push_to_main_rejected(self, repo_env):
        work = repo_env["work"]
        run("echo 'a' > a.txt", cwd=str(work))
        run("git add a.txt", cwd=str(work))
        run('git commit -m "feat: add a"', cwd=str(work))
        run("git push origin main", cwd=str(work))
        # Diverge history
        run("git reset --hard HEAD~1", cwd=str(work))
        run("echo 'b' > b.txt", cwd=str(work))
        run("git add b.txt", cwd=str(work))
        run('git commit -m "feat: add b instead"', cwd=str(work))
        result = run("git push --force origin main", cwd=str(work), check=False)
        assert result.returncode != 0, "Force push to main must be rejected"
        assert "POLICY VIOLATION" in result.stderr

    def test_delete_main_rejected(self, repo_env):
        work = repo_env["work"]
        result = run("git push origin --delete main", cwd=str(work), check=False)
        assert result.returncode != 0, "Deleting main must be rejected"
        assert "POLICY VIOLATION" in result.stderr

    def test_force_push_to_release_branch_rejected(self, repo_env):
        """Glob pattern release/* must match release/v1.0."""
        work = repo_env["work"]
        run("git checkout -b release/v1.0", cwd=str(work))
        run("echo 'v1' > version.txt", cwd=str(work))
        run("git add version.txt", cwd=str(work))
        run('git commit -m "feat: release v1.0"', cwd=str(work))
        run("git push origin release/v1.0", cwd=str(work))
        # Diverge
        run("git reset --hard HEAD~1", cwd=str(work))
        run("echo 'v1-alt' > version.txt", cwd=str(work))
        run("git add version.txt", cwd=str(work))
        run('git commit -m "feat: alt release"', cwd=str(work))
        result = run(
            "git push --force origin release/v1.0", cwd=str(work), check=False
        )
        assert result.returncode != 0, "Force push to release/* must be rejected"
        assert "POLICY VIOLATION" in result.stderr

    def test_force_push_to_feature_branch_allowed(self, repo_env):
        work = repo_env["work"]
        run("git checkout -b feature/test", cwd=str(work))
        run("echo 'a' > a.txt", cwd=str(work))
        run("git add a.txt", cwd=str(work))
        run('git commit -m "feat: add a"', cwd=str(work))
        run("git push origin feature/test", cwd=str(work))
        run("git reset --hard HEAD~1", cwd=str(work))
        run("echo 'b' > b.txt", cwd=str(work))
        run("git add b.txt", cwd=str(work))
        run('git commit -m "feat: add b"', cwd=str(work))
        result = run(
            "git push --force origin feature/test", cwd=str(work), check=False
        )
        assert result.returncode == 0, (
            f"Force push to feature branch should pass: {result.stderr}"
        )


# ── Commit Messages ─────────────────────────────────────────────────

class TestCommitMessages:

    def test_valid_conventional_commit(self, repo_env):
        work = repo_env["work"]
        run("echo 'new' > new.txt", cwd=str(work))
        run("git add new.txt", cwd=str(work))
        run('git commit -m "fix(auth): resolve login timeout"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode == 0, f"Valid commit msg should pass: {result.stderr}"

    def test_invalid_commit_message_rejected(self, repo_env):
        work = repo_env["work"]
        run("echo 'bad' > bad.txt", cwd=str(work))
        run("git add bad.txt", cwd=str(work))
        run('git commit -m "just a random commit message"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode != 0, "Invalid commit msg must be rejected"
        assert "POLICY VIOLATION" in result.stderr

    def test_new_branch_checks_only_new_commits(self, repo_env):
        """New branch must NOT re-validate commits already in other branches."""
        work = repo_env["work"]
        # The initial commit has a non-conventional message ("initial setup
        # of repository") and is already in main. A new branch from main
        # should only check NEW commits, not re-validate the initial one.
        run("git checkout -b feature/new-branch", cwd=str(work))
        run("echo 'new-feature' > feature.txt", cwd=str(work))
        run("git add feature.txt", cwd=str(work))
        run('git commit -m "feat: add new feature"', cwd=str(work))
        result = run(
            "git push origin feature/new-branch", cwd=str(work), check=False
        )
        assert result.returncode == 0, (
            f"New branch with valid new commits should pass: {result.stderr}"
        )

    def test_new_branch_bad_commit_rejected(self, repo_env):
        work = repo_env["work"]
        run("git checkout -b feature/bad-msgs", cwd=str(work))
        run("echo 'bad' > bad.txt", cwd=str(work))
        run("git add bad.txt", cwd=str(work))
        run('git commit -m "this is not conventional"', cwd=str(work))
        result = run(
            "git push origin feature/bad-msgs", cwd=str(work), check=False
        )
        assert result.returncode != 0, "New branch with bad msg must be rejected"
        assert "POLICY VIOLATION" in result.stderr


# ── File Size Limits ─────────────────────────────────────────────────

class TestFileSizeLimit:

    def test_small_file_passes(self, repo_env):
        work = repo_env["work"]
        run("echo 'small content' > small.txt", cwd=str(work))
        run("git add small.txt", cwd=str(work))
        run('git commit -m "feat: add small file"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode == 0, f"Small file should pass: {result.stderr}"

    def test_oversized_file_rejected(self, repo_env):
        work = repo_env["work"]
        # Create a 6 MB file (default limit is 5 MB)
        run(
            "dd if=/dev/urandom of=large.dat bs=1M count=6 2>/dev/null",
            cwd=str(work),
        )
        run("git add large.dat", cwd=str(work))
        run('git commit -m "feat: add large file"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode != 0, "6 MB file must be rejected (limit 5 MB)"
        assert "POLICY VIOLATION" in result.stderr

    def test_bin_file_always_rejected(self, repo_env):
        """*.bin has limit=0, so even a tiny .bin must be rejected."""
        work = repo_env["work"]
        run("echo 'binary data' > data.bin", cwd=str(work))
        run("git add data.bin", cwd=str(work))
        run('git commit -m "feat: add binary file"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode != 0, ".bin file must be rejected (limit=0)"
        assert "POLICY VIOLATION" in result.stderr

    def test_large_sql_within_limit(self, repo_env):
        """SQL files have a 10 MB limit; a 6 MB SQL should pass."""
        work = repo_env["work"]
        run(
            "dd if=/dev/zero of=schema.sql bs=1M count=6 2>/dev/null",
            cwd=str(work),
        )
        run("git add schema.sql", cwd=str(work))
        run('git commit -m "feat: add schema"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode == 0, (
            f"6 MB SQL (limit 10 MB) should pass: {result.stderr}"
        )


# ── Forbidden Files ──────────────────────────────────────────────────

class TestForbiddenFiles:

    def test_exe_rejected(self, repo_env):
        work = repo_env["work"]
        run("echo '#!/bin/sh' > program.exe", cwd=str(work))
        run("git add program.exe", cwd=str(work))
        run('git commit -m "feat: add executable"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode != 0, ".exe must be rejected"
        assert "POLICY VIOLATION" in result.stderr

    def test_env_file_rejected(self, repo_env):
        work = repo_env["work"]
        run("echo 'SECRET=abc' > .env", cwd=str(work))
        run("git add .env", cwd=str(work))
        run('git commit -m "feat: add env file"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode != 0, ".env must be rejected"
        assert "POLICY VIOLATION" in result.stderr

    def test_pem_rejected(self, repo_env):
        work = repo_env["work"]
        run("echo 'fake-cert' > cert.pem", cwd=str(work))
        run("git add cert.pem", cwd=str(work))
        run('git commit -m "feat: add certificate"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode != 0, ".pem must be rejected"
        assert "POLICY VIOLATION" in result.stderr

    def test_normal_files_allowed(self, repo_env):
        work = repo_env["work"]
        run("echo 'code' > app.py", cwd=str(work))
        run("git add app.py", cwd=str(work))
        run('git commit -m "feat: add application code"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode == 0, f"Normal files should pass: {result.stderr}"


# ── Tag Policy ───────────────────────────────────────────────────────

class TestTagPolicy:

    def test_annotated_tag_allowed(self, repo_env):
        work = repo_env["work"]
        run('git tag -a v1.0 -m "Release v1.0"', cwd=str(work))
        result = run("git push origin v1.0", cwd=str(work), check=False)
        assert result.returncode == 0, (
            f"Annotated tag should be allowed: {result.stderr}"
        )

    def test_lightweight_tag_rejected(self, repo_env):
        work = repo_env["work"]
        run("git tag v2.0-light", cwd=str(work))
        result = run("git push origin v2.0-light", cwd=str(work), check=False)
        assert result.returncode != 0, "Lightweight tag must be rejected"
        assert "POLICY VIOLATION" in result.stderr

    def test_tag_deletion_rejected(self, repo_env):
        work = repo_env["work"]
        # Push an annotated tag first (should succeed)
        run('git tag -a v3.0 -m "Release v3.0"', cwd=str(work))
        run("git push origin v3.0", cwd=str(work))
        # Now try to delete it
        result = run(
            "git push origin --delete v3.0", cwd=str(work), check=False
        )
        assert result.returncode != 0, "Tag deletion must be rejected"
        assert "POLICY VIOLATION" in result.stderr


# ── Merge Policy ─────────────────────────────────────────────────────

class TestMergePolicy:

    def test_merge_commit_to_main_rejected(self, repo_env):
        """Merge commit pushed to protected branch main must be rejected."""
        work = repo_env["work"]
        # Create a feature branch with a commit
        run("git checkout -b feature/merge-test", cwd=str(work))
        run("echo 'feature-work' > feature.txt", cwd=str(work))
        run("git add feature.txt", cwd=str(work))
        run('git commit -m "feat: feature work"', cwd=str(work))
        # Go back to main and create a diverging commit
        run("git checkout main", cwd=str(work))
        run("echo 'main-work' > main-work.txt", cwd=str(work))
        run("git add main-work.txt", cwd=str(work))
        run('git commit -m "feat: main work"', cwd=str(work))
        # Merge feature into main (creates merge commit)
        run(
            'git merge feature/merge-test --no-ff -m "feat: merge feature"',
            cwd=str(work),
        )
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode != 0, (
            "Merge commit to protected branch main must be rejected"
        )
        assert "POLICY VIOLATION" in result.stderr

    def test_merge_commit_to_release_rejected(self, repo_env):
        """Merge commit pushed to release/* (protected glob) must be rejected."""
        work = repo_env["work"]
        # Create release branch and push it
        run("git checkout -b release/v2.0", cwd=str(work))
        run("echo 'v2' > version.txt", cwd=str(work))
        run("git add version.txt", cwd=str(work))
        run('git commit -m "feat: start v2.0"', cwd=str(work))
        run("git push origin release/v2.0", cwd=str(work))
        # Create a hotfix branch from release
        run("git checkout -b feature/hotfix", cwd=str(work))
        run("echo 'hotfix' > hotfix.txt", cwd=str(work))
        run("git add hotfix.txt", cwd=str(work))
        run('git commit -m "fix: hotfix for v2.0"', cwd=str(work))
        # Back to release, add another commit to force non-ff merge
        run("git checkout release/v2.0", cwd=str(work))
        run("echo 'release-work' > release-work.txt", cwd=str(work))
        run("git add release-work.txt", cwd=str(work))
        run('git commit -m "feat: release work"', cwd=str(work))
        # Merge hotfix into release (creates merge commit)
        run(
            'git merge feature/hotfix --no-ff -m "feat: merge hotfix"',
            cwd=str(work),
        )
        result = run(
            "git push origin release/v2.0", cwd=str(work), check=False
        )
        assert result.returncode != 0, (
            "Merge commit to release/* must be rejected"
        )
        assert "POLICY VIOLATION" in result.stderr

    def test_merge_commit_to_unprotected_allowed(self, repo_env):
        """Merge commit pushed to unprotected branch should be allowed."""
        work = repo_env["work"]
        # Create two feature branches from main
        run("git checkout -b feature/a", cwd=str(work))
        run("echo 'a' > a.txt", cwd=str(work))
        run("git add a.txt", cwd=str(work))
        run('git commit -m "feat: branch a"', cwd=str(work))
        run("git checkout main", cwd=str(work))
        run("git checkout -b feature/b", cwd=str(work))
        run("echo 'b' > b.txt", cwd=str(work))
        run("git add b.txt", cwd=str(work))
        run('git commit -m "feat: branch b"', cwd=str(work))
        # Merge feature/a into feature/b (creates merge commit)
        run(
            'git merge feature/a --no-ff -m "feat: merge a into b"',
            cwd=str(work),
        )
        result = run(
            "git push origin feature/b", cwd=str(work), check=False
        )
        assert result.returncode == 0, (
            f"Merge commit to unprotected branch should pass: {result.stderr}"
        )


# ── Edge Cases ───────────────────────────────────────────────────────

class TestEdgeCases:

    def test_multiple_violations_reported(self, repo_env):
        """A push with both forbidden file and bad commit message."""
        work = repo_env["work"]
        run("echo 'data' > malware.exe", cwd=str(work))
        run("git add malware.exe", cwd=str(work))
        run('git commit -m "added malware"', cwd=str(work))
        result = run("git push origin main", cwd=str(work), check=False)
        assert result.returncode != 0
        assert "POLICY VIOLATION" in result.stderr

    def test_delete_non_protected_branch(self, repo_env):
        work = repo_env["work"]
        run("git checkout -b temp-branch", cwd=str(work))
        run("echo 'temp' > temp.txt", cwd=str(work))
        run("git add temp.txt", cwd=str(work))
        run('git commit -m "feat: temporary work"', cwd=str(work))
        run("git push origin temp-branch", cwd=str(work))
        run("git checkout main", cwd=str(work))
        result = run(
            "git push origin --delete temp-branch", cwd=str(work), check=False
        )
        assert result.returncode == 0, (
            f"Deleting non-protected branch should pass: {result.stderr}"
        )
