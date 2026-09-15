
import subprocess
import os
import json
import pytest

REPO = "/app/repo"
MANIFEST = "/app/manifest.json"


def sh(cmd, cwd=REPO, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(
            f"{cmd!r} failed (rc={r.returncode})\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
    return r


@pytest.fixture(scope="session")
def manifest():
    with open(MANIFEST) as f:
        return json.load(f)


class TestGitRepoRecovery:

    def test_repo_exists(self):
        assert os.path.isdir(REPO), f"{REPO} does not exist"
        assert os.path.isdir(os.path.join(REPO, ".git")), ".git directory missing"

    def test_git_fsck_passes(self):
        """git fsck --full must exit 0 with no errors."""
        r = sh("git fsck --full 2>&1", check=False)
        output = r.stdout + (r.stderr or "")
        error_words = ["error", "missing", "broken", "corrupt", "fatal"]
        errors = [
            line for line in output.splitlines()
            if any(w in line.lower() for w in error_words)
        ]
        assert r.returncode == 0, (
            f"git fsck exited {r.returncode}:\n{output}"
        )
        assert not errors, (
            "git fsck reported errors:\n" + "\n".join(errors)
        )

    def test_branches_exist(self, manifest):
        """All branches from the manifest must exist."""
        r = sh("git branch")
        existing = set()
        for b in r.stdout.strip().splitlines():
            existing.add(b.strip().lstrip("* "))
        for branch in manifest["branches"]:
            assert branch in existing, f"Branch '{branch}' is missing"

    def test_tags_exist(self, manifest):
        """All tags from the manifest must exist."""
        r = sh("git tag")
        existing = {t.strip() for t in r.stdout.strip().splitlines()}
        for tag in manifest["tags"]:
            assert tag in existing, f"Tag '{tag}' is missing"

    def test_main_commit_history(self, manifest):
        """Commit subjects on main must match the manifest in order."""
        r = sh("git log --format=%s main")
        subjects = [s.strip() for s in r.stdout.strip().splitlines()]
        expected = [c["subject"] for c in manifest["commits_main"]]
        assert subjects == expected, (
            f"Main history mismatch:\n"
            f"  Got:      {subjects}\n"
            f"  Expected: {expected}"
        )

    def test_feature_commit_history(self, manifest):
        """Commit subjects on feature/auth must match the manifest."""
        r = sh("git log --format=%s feature/auth")
        subjects = [s.strip() for s in r.stdout.strip().splitlines()]
        expected = [c["subject"] for c in manifest["commits_feature_auth"]]
        assert subjects == expected, (
            f"Feature branch history mismatch:\n"
            f"  Got:      {subjects}\n"
            f"  Expected: {expected}"
        )

    def test_head_file_contents(self, manifest):
        """File contents at HEAD must be byte-identical to the manifest."""
        for path, expected in manifest["files_at_head"].items():
            r = sh(f"git show HEAD:{path}")
            assert r.stdout == expected, (
                f"Content mismatch for {path}: "
                f"expected {len(expected)} chars, got {len(r.stdout)} chars"
            )

    def test_refs_resolve_to_expected_shas(self, manifest):
        """Every ref in the manifest must resolve to its recorded SHA."""
        for ref_name, expected_sha in manifest["refs"].items():
            r = sh(f"git rev-parse {ref_name}", check=False)
            assert r.returncode == 0, (
                f"Ref '{ref_name}' does not resolve: {r.stderr.strip()}"
            )
            actual = r.stdout.strip()
            assert actual == expected_sha, (
                f"Ref '{ref_name}': expected {expected_sha}, got {actual}"
            )

    def test_checkout_branches(self, manifest):
        """Every branch must be checkable-out without error."""
        for branch in manifest["branches"]:
            r = sh(f"git checkout {branch}", check=False)
            assert r.returncode == 0, (
                f"Cannot checkout '{branch}': {r.stderr.strip()}"
            )

    def test_no_salvaged_directory(self):
        """The .git/salvaged/ artifact directory must be cleaned up."""
        salvaged = os.path.join(REPO, ".git", "salvaged")
        assert not os.path.isdir(salvaged), (
            ".git/salvaged/ still exists — corruption artifacts remain"
        )

    def test_no_refs_to_missing_objects(self):
        """No ref should point to a non-existent object."""
        r = sh("git for-each-ref --format='%(refname) %(objectname)'", check=False)
        if r.returncode != 0:
            pytest.fail(f"git for-each-ref failed: {r.stderr}")
        for line in r.stdout.strip().splitlines():
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                ref, sha = parts
                r2 = sh(f"git cat-file -e {sha}", check=False)
                assert r2.returncode == 0, (
                    f"Ref {ref} points to non-existent object {sha}"
                )

    def test_annotated_tags_intact(self, manifest):
        """Annotated tags must be dereferenceable with readable messages."""
        for tag in manifest["tags"]:
            r = sh(f"git cat-file -t {tag}", check=False)
            assert r.returncode == 0, f"Cannot read tag '{tag}'"
            obj_type = r.stdout.strip()
            if obj_type == "tag":
                r2 = sh(f"git cat-file tag {tag}", check=False)
                assert r2.returncode == 0, (
                    f"Cannot read annotated tag '{tag}' content"
                )
                assert len(r2.stdout.strip()) > 0, (
                    f"Annotated tag '{tag}' has empty content"
                )
