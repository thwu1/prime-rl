
import pytest
import subprocess
import json
import os
import glob

REPO_DIR = "/app/repo"
GIT_DIR = os.path.join(REPO_DIR, ".git")


def git_run(args, check=True):
    """Run a git command in the repo directory."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=REPO_DIR
    )
    if check:
        assert result.returncode == 0, (
            f"git {' '.join(args)} failed (rc={result.returncode}): "
            f"{result.stderr}"
        )
    return result


class TestRepoHealth:
    """Core repository health checks."""

    def test_git_fsck_exit_code(self):
        result = git_run(["fsck", "--full"], check=False)
        assert result.returncode == 0, (
            f"git fsck --full failed with rc={result.returncode}. "
            f"stderr: {result.stderr}"
        )

    def test_git_fsck_no_errors(self):
        result = git_run(["fsck", "--full"], check=False)
        error_lines = [
            line for line in result.stderr.strip().split('\n')
            if line.strip() and line.strip().startswith('error')
        ]
        assert len(error_lines) == 0, (
            f"git fsck produced errors: {error_lines}"
        )

    def test_commit_count(self):
        result = git_run(["log", "--all", "--oneline"])
        lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
        assert len(lines) == 6, (
            f"Expected 6 commits, found {len(lines)}. "
            f"Output: {result.stdout}"
        )

    def test_all_commit_messages_present(self):
        result = git_run(["log", "--all", "--format=%s"])
        messages = set(result.stdout.strip().split('\n'))
        expected = {
            "Initial commit: project skeleton",
            "Add math functions, tests, and calculator",
            "Add configuration module and update README",
            "Add string utility functions",
            "Integrate config into main module",
            "Merge feature/string-utils into master",
        }
        missing = expected - messages
        assert not missing, f"Missing commit messages: {missing}"

    def test_master_branch_resolves(self):
        result = git_run(["rev-parse", "master"])
        sha = result.stdout.strip()
        assert len(sha) == 40, f"Invalid SHA for master: {sha}"

    def test_feature_branch_resolves(self):
        result = git_run(["rev-parse", "feature/string-utils"])
        sha = result.stdout.strip()
        assert len(sha) == 40, (
            f"Invalid SHA for feature/string-utils: {sha}"
        )

    def test_feature_branch_is_commit(self):
        result = git_run(["cat-file", "-t", "feature/string-utils"])
        assert result.stdout.strip() == "commit", (
            f"feature/string-utils should be a commit, "
            f"got: {result.stdout.strip()}"
        )

    def test_verify_pack_succeeds(self):
        idx_files = glob.glob(
            os.path.join(GIT_DIR, "objects/pack/*.idx")
        )
        assert len(idx_files) >= 1, "No .idx files found in pack directory"
        for idx in idx_files:
            result = subprocess.run(
                ["git", "verify-pack", "-v", idx],
                capture_output=True, text=True, cwd=REPO_DIR
            )
            assert result.returncode == 0, (
                f"git verify-pack failed for {idx}: {result.stderr}"
            )

    def test_head_valid(self):
        result = git_run(["symbolic-ref", "HEAD"])
        assert result.stdout.strip() == "refs/heads/master", (
            f"HEAD should point to refs/heads/master, "
            f"got: {result.stdout.strip()}"
        )


class TestFileIntegrity:
    """Verify file contents are intact on each branch."""

    def test_master_main_py(self):
        result = git_run(["show", "master:src/main.py"])
        assert "from config import Config" in result.stdout
        assert "Config.APP_NAME" in result.stdout

    def test_master_config_py(self):
        result = git_run(["show", "master:src/config.py"])
        assert "class Config:" in result.stdout
        assert 'APP_NAME = "SampleApp"' in result.stdout

    def test_master_math_ops(self):
        result = git_run(["show", "master:src/utils/math_ops.py"])
        assert "def multiply" in result.stdout
        assert "def divide" in result.stdout

    def test_master_readme(self):
        result = git_run(["show", "master:README.md"])
        assert "## Configuration" in result.stdout

    def test_feature_string_ops(self):
        result = git_run([
            "show", "feature/string-utils:src/utils/string_ops.py"
        ])
        assert "def reverse" in result.stdout
        assert "def is_palindrome" in result.stdout
        assert "def truncate" in result.stdout

    def test_feature_test_string(self):
        result = git_run([
            "show", "feature/string-utils:src/test_string.py"
        ])
        assert "class TestStringOps" in result.stdout

    def test_master_has_string_ops_from_merge(self):
        """After merge, master should also have string_ops.py."""
        result = git_run(["show", "master:src/utils/string_ops.py"])
        assert "def reverse" in result.stdout

    def test_merge_commit_has_two_parents(self):
        """The merge commit on master should have exactly 2 parents."""
        result = git_run([
            "log", "master", "--format=%H %P %s"
        ])
        for line in result.stdout.strip().split('\n'):
            if "Merge feature/string-utils" in line:
                parts = line.split()
                # SHA + parent1 + parent2 + message words
                # Parents are space-separated after the commit SHA
                sha = parts[0]
                cat_result = git_run(["cat-file", "-p", sha])
                parents = [
                    l.split()[1] for l in cat_result.stdout.split('\n')
                    if l.startswith("parent ")
                ]
                assert len(parents) == 2, (
                    f"Merge commit should have 2 parents, "
                    f"found {len(parents)}"
                )
                return
        pytest.fail("Merge commit not found on master")

    def test_feature_log_has_correct_commits(self):
        """feature/string-utils log should show 4 commits."""
        result = git_run([
            "log", "feature/string-utils", "--oneline"
        ])
        lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
        assert len(lines) == 4, (
            f"Expected 4 commits on feature/string-utils, "
            f"found {len(lines)}: {result.stdout}"
        )

    def test_feature_log_includes_branch_commit(self):
        result = git_run([
            "log", "feature/string-utils", "--format=%s"
        ])
        messages = result.stdout.strip().split('\n')
        assert "Add string utility functions" in messages


class TestCorruptionCleanup:
    """Verify specific corruption artifacts are cleaned up."""

    def test_no_shallow_file(self):
        shallow_path = os.path.join(GIT_DIR, "shallow")
        assert not os.path.exists(shallow_path), (
            ".git/shallow should not exist after repair"
        )

    def test_head_points_to_master(self):
        head_path = os.path.join(GIT_DIR, "HEAD")
        with open(head_path, 'r') as f:
            content = f.read().strip()
        assert content == "ref: refs/heads/master", (
            f"HEAD should be 'ref: refs/heads/master', got: '{content}'"
        )

    def test_pack_index_exists(self):
        idx_files = glob.glob(
            os.path.join(GIT_DIR, "objects/pack/*.idx")
        )
        assert len(idx_files) >= 1, (
            "At least one .idx file should exist after repair"
        )

    def test_pack_file_exists(self):
        pack_files = glob.glob(
            os.path.join(GIT_DIR, "objects/pack/*.pack")
        )
        assert len(pack_files) >= 1, (
            "At least one .pack file should exist"
        )

    def test_git_config_valid(self):
        result = subprocess.run(
            ["git", "config", "--list"],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        assert result.returncode == 0, (
            f"git config --list failed: {result.stderr}"
        )


class TestDiagnosisReport:
    """Verify the diagnosis report is complete and well-structured."""

    def test_diagnosis_file_exists(self):
        assert os.path.exists("/app/diagnosis.json"), (
            "diagnosis.json not found at /app/diagnosis.json"
        )

    def test_diagnosis_valid_json(self):
        with open("/app/diagnosis.json", 'r') as f:
            data = json.load(f)
        assert isinstance(data, dict), "diagnosis.json should be a JSON object"

    def test_diagnosis_has_issues_key(self):
        with open("/app/diagnosis.json", 'r') as f:
            data = json.load(f)
        assert "issues" in data, (
            "diagnosis.json must have an 'issues' key"
        )
        assert isinstance(data["issues"], list), (
            "'issues' must be a list"
        )

    def test_diagnosis_minimum_issue_count(self):
        with open("/app/diagnosis.json", 'r') as f:
            data = json.load(f)
        assert len(data["issues"]) >= 4, (
            f"Should document at least 4 corruption issues, "
            f"found {len(data['issues'])}"
        )

    def test_diagnosis_issue_structure(self):
        with open("/app/diagnosis.json", 'r') as f:
            data = json.load(f)
        for i, issue in enumerate(data["issues"]):
            assert "category" in issue, (
                f"Issue {i} missing 'category' field"
            )
            assert "description" in issue, (
                f"Issue {i} missing 'description' field"
            )
            assert isinstance(issue["category"], str) and len(issue["category"]) > 0, (
                f"Issue {i}: 'category' must be a non-empty string"
            )
            assert isinstance(issue["description"], str) and len(issue["description"]) >= 15, (
                f"Issue {i}: 'description' must be a string of at least "
                f"15 characters"
            )


class TestAntiCheat:
    """Ensure the repository was repaired, not recreated."""

    def test_original_commit_messages_preserved(self):
        """All original commit messages must be present (not recreated)."""
        result = git_run([
            "log", "--all", "--format=%s", "--reverse"
        ])
        messages = result.stdout.strip().split('\n')
        expected_ordered = [
            "Initial commit: project skeleton",
            "Add math functions, tests, and calculator",
            "Add configuration module and update README",
        ]
        # First three commits should appear in order
        found = [m for m in messages if m in expected_ordered]
        assert found == expected_ordered, (
            f"Commit history appears to have been recreated. "
            f"Expected order: {expected_ordered}, found: {found}"
        )

    def test_objects_in_pack_format(self):
        """Objects should still be in pack format (not unpacked loose)."""
        pack_files = glob.glob(
            os.path.join(GIT_DIR, "objects/pack/*.pack")
        )
        assert len(pack_files) >= 1, (
            "Pack files should exist (repo should not have been "
            "reinitialized)"
        )

    def test_author_is_test_user(self):
        """Commits should be authored by 'Test User', not recreated."""
        result = git_run([
            "log", "--all", "--format=%an <%ae>"
        ])
        authors = set(result.stdout.strip().split('\n'))
        assert "Test User <test@test.com>" in authors, (
            f"Original author 'Test User' not found. "
            f"Authors: {authors}"
        )
