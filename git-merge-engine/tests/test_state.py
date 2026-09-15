"""
Tests for git repository reconstruction from JSON archive.
Verifies that the reconstructed repository matches the original.

"""

import subprocess

import pytest

REPO = "/app/repo"


def git(*args, check=True):
    """Run a git command in the repository."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed (rc={result.returncode}):\n{result.stderr}"
        )
    return result


class TestRepositoryIntegrity:
    """Verify overall repository integrity."""

    def test_fsck_clean(self):
        """git fsck --strict --no-dangling must pass with no errors."""
        r = git("fsck", "--strict", "--no-dangling")
        assert r.returncode == 0

    def test_all_commits_visible(self):
        """git log --all must show exactly 6 commits (4 main + 2 unique feature)."""
        r = git("log", "--all", "--oneline")
        lines = [line for line in r.stdout.strip().split("\n") if line.strip()]
        assert len(lines) == 6, f"Expected 6 commits, got {len(lines)}:\n{r.stdout}"


class TestBranches:
    """Verify branch structure."""

    def test_main_exists(self):
        """main branch must exist and resolve to a valid 40-char SHA."""
        r = git("rev-parse", "--verify", "refs/heads/main")
        sha = r.stdout.strip()
        assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)

    def test_feature_streaming_exists(self):
        """feature/streaming branch must exist and resolve to a valid SHA."""
        r = git("rev-parse", "--verify", "refs/heads/feature/streaming")
        sha = r.stdout.strip()
        assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)

    def test_head_points_to_main(self):
        """HEAD must be a symbolic ref pointing to refs/heads/main."""
        r = git("symbolic-ref", "HEAD")
        assert r.stdout.strip() == "refs/heads/main"

    def test_main_commit_count(self):
        """main must have exactly 4 commits in its history."""
        r = git("rev-list", "--count", "main")
        assert int(r.stdout.strip()) == 4

    def test_feature_commit_count(self):
        """feature/streaming must have exactly 4 commits (2 shared + 2 own)."""
        r = git("rev-list", "--count", "feature/streaming")
        assert int(r.stdout.strip()) == 4

    def test_shared_ancestor(self):
        """main and feature/streaming must share a common ancestor."""
        r = git("merge-base", "main", "feature/streaming")
        sha = r.stdout.strip()
        assert len(sha) == 40

    def test_branches_diverge(self):
        """The merge base must not be either branch tip (branches truly diverged)."""
        merge_base = git("merge-base", "main", "feature/streaming").stdout.strip()
        main_head = git("rev-parse", "main").stdout.strip()
        feature_head = git("rev-parse", "feature/streaming").stdout.strip()
        assert merge_base != main_head, "merge-base should not equal main HEAD"
        assert merge_base != feature_head, "merge-base should not equal feature HEAD"


class TestTag:
    """Verify tag structure."""

    def test_v1_tag_exists(self):
        """Tag v1.0 must exist."""
        r = git("rev-parse", "--verify", "v1.0", check=False)
        assert r.returncode == 0, "Tag v1.0 does not exist"

    def test_v1_tag_is_annotated(self):
        """v1.0 must be an annotated tag (type 'tag', not 'commit')."""
        r = git("cat-file", "-t", "v1.0")
        assert r.stdout.strip() == "tag", (
            f"v1.0 should be annotated tag, got type: {r.stdout.strip()}"
        )

    def test_v1_tag_points_to_main_head(self):
        """v1.0 must point to the same commit as main HEAD."""
        tag_commit = git("rev-parse", "v1.0^{commit}").stdout.strip()
        main_head = git("rev-parse", "main").stdout.strip()
        assert tag_commit == main_head


class TestMainBranchContent:
    """Verify file contents at the main branch HEAD."""

    def test_parser_exists_with_hooks(self):
        """src/core/parser.py at main HEAD must have the refactored hook system."""
        r = git("show", "main:src/core/parser.py")
        assert "class DataParser" in r.stdout
        assert "_fire_hooks" in r.stdout
        assert "pre_parse" in r.stdout

    def test_transform_with_error_handling(self):
        """src/core/transform.py at main must have error handling."""
        r = git("show", "main:src/core/transform.py")
        assert "class DataTransformer" in r.stdout
        assert "_error_handler" in r.stdout

    def test_validator_exists(self):
        """src/core/validator.py must exist at main."""
        r = git("show", "main:src/core/validator.py")
        assert "class SchemaValidator" in r.stdout

    def test_pipeline_orchestrator(self):
        """src/pipeline.py must exist at main."""
        r = git("show", "main:src/pipeline.py")
        assert "class Pipeline" in r.stdout

    def test_changelog(self):
        """CHANGELOG.md must reference v1.0.0."""
        r = git("show", "main:CHANGELOG.md")
        assert "v1.0.0" in r.stdout

    def test_config_version(self):
        """config/pipeline.yaml at main must have version 1.0.0."""
        r = git("show", "main:config/pipeline.yaml")
        assert "1.0.0" in r.stdout

    def test_helpers(self):
        """src/utils/helpers.py must exist with utility functions."""
        r = git("show", "main:src/utils/helpers.py")
        assert "compute_checksum" in r.stdout
        assert "deep_merge" in r.stdout


class TestFeatureBranchContent:
    """Verify file contents at feature/streaming HEAD."""

    def test_consumer_with_buffering(self):
        """Consumer must use StreamBuffer (the buffered version)."""
        r = git("show", "feature/streaming:src/streaming/consumer.py")
        assert "StreamConsumer" in r.stdout
        assert "StreamBuffer" in r.stdout

    def test_buffer_module(self):
        """Buffer module must exist with pop_batch method."""
        r = git("show", "feature/streaming:src/streaming/buffer.py")
        assert "class StreamBuffer" in r.stdout
        assert "pop_batch" in r.stdout

    def test_producer_module(self):
        """Producer module must exist."""
        r = git("show", "feature/streaming:src/streaming/producer.py")
        assert "class StreamProducer" in r.stdout

    def test_streaming_config(self):
        """Streaming config must exist."""
        r = git("show", "feature/streaming:config/streaming.yaml")
        assert "buffer_size" in r.stdout

    def test_no_pipeline_on_feature(self):
        """feature/streaming branched before pipeline.py was added; it must NOT exist."""
        r = git("show", "feature/streaming:src/pipeline.py", check=False)
        assert r.returncode != 0, "src/pipeline.py should not exist on feature/streaming"

    def test_parser_at_feature_is_pre_refactor(self):
        """Parser on feature/streaming should have validation but NOT hooks (pre-refactor)."""
        r = git("show", "feature/streaming:src/core/parser.py")
        assert "_run_validators" in r.stdout, "Should have validation support"
        assert "_fire_hooks" not in r.stdout, "Should NOT have hooks (added after fork)"


class TestWorkingTree:
    """Verify working tree state after checkout."""

    def test_clean_checkout_main(self):
        """Checking out main must produce a clean working tree."""
        git("checkout", "main")
        r = git("status", "--porcelain")
        assert r.stdout.strip() == "", (
            f"Working tree not clean after checkout main:\n{r.stdout}"
        )

    def test_clean_checkout_feature(self):
        """Checking out feature/streaming must produce a clean working tree."""
        git("checkout", "feature/streaming")
        r = git("status", "--porcelain")
        assert r.stdout.strip() == "", (
            f"Working tree not clean after checkout feature/streaming:\n{r.stdout}"
        )
        # Switch back
        git("checkout", "main")
