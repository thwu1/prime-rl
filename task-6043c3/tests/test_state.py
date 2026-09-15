"""Tests for Git pack file recovery with dual corruption.

Verifies that the solver correctly repairs the pack checksum, builds a
working pack parser, rebuilds the index, creates a recovery bundle,
and generates a verification report.
"""


import subprocess
import os
import re
import hashlib
import pytest

GIT_DIR = "/app/repo/.git"
REPO_DIR = "/app/repo"
PACKPARSE = "/app/packparse.py"
PACK_DIR = os.path.join(GIT_DIR, "objects", "pack")
BUNDLE_PATH = "/app/recovered.bundle"
REPORT_PATH = "/app/verify_report.txt"

SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
VALID_TYPES = {"commit", "tree", "blob", "tag"}


@pytest.fixture(scope="session")
def rebuilt_index():
    """Rebuild the pack index via the solver's --rebuild-index command.

    This fixture runs once per session before any test that needs git
    commands to work. It invokes the solver's parser to regenerate the
    .idx file that was deleted during environment setup.
    """
    if not os.path.exists(PACKPARSE):
        pytest.fail("Parser not found at " + PACKPARSE)

    result = subprocess.run(
        ["python3", PACKPARSE, GIT_DIR, "--rebuild-index"],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    assert result.returncode == 0, (
        f"--rebuild-index failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    idx_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".idx")]
    assert len(idx_files) >= 1, "No .idx file was created by --rebuild-index"
    return True


def git_text(args):
    """Run git command and return stdout as text."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=REPO_DIR
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout


def git_binary(args):
    """Run git command and return stdout as bytes."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, cwd=REPO_DIR
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed: "
        f"{result.stderr.decode(errors='replace')}"
    )
    return result.stdout


def parser_text(args):
    """Run packparse.py and return stdout as text."""
    result = subprocess.run(
        ["python3", PACKPARSE] + args,
        capture_output=True, text=True, cwd=REPO_DIR
    )
    assert result.returncode == 0, (
        f"packparse {' '.join(args)} failed: {result.stderr}"
    )
    return result.stdout


def parser_binary(args):
    """Run packparse.py and return stdout as bytes."""
    result = subprocess.run(
        ["python3", PACKPARSE] + args,
        capture_output=True, cwd=REPO_DIR
    )
    assert result.returncode == 0, (
        f"packparse {' '.join(args)} failed: "
        f"{result.stderr.decode(errors='replace')}"
    )
    return result.stdout


def get_all_objects(rebuilt_index):
    """Get all objects from the pack file using git verify-pack."""
    idx_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".idx")]
    assert idx_files, "No pack index files found"

    result = subprocess.run(
        ["git", "verify-pack", "-v", os.path.join(PACK_DIR, idx_files[0])],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    assert result.returncode == 0, f"verify-pack failed: {result.stderr}"

    objects = []
    delta_shas = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 5 and SHA1_RE.match(parts[0]) and parts[1] in VALID_TYPES:
            sha1 = parts[0]
            obj_type = parts[1]
            is_delta = len(parts) >= 7
            objects.append({"sha1": sha1, "type": obj_type, "is_delta": is_delta})
            if is_delta:
                delta_shas.append(sha1)

    return objects, delta_shas


class TestPackRepair:
    """Verify the pack file's SHA-1 checksum has been correctly repaired."""

    def test_pack_checksum_valid(self):
        """The pack file's trailing 20-byte SHA-1 must match the hash of all preceding bytes."""
        pack_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".pack")]
        assert pack_files, "No pack files found"
        pack_path = os.path.join(PACK_DIR, pack_files[0])
        with open(pack_path, "rb") as f:
            data = f.read()
        computed = hashlib.sha1(data[:-20]).digest()
        stored = data[-20:]
        assert computed == stored, (
            f"Pack checksum mismatch: stored={stored.hex()}, "
            f"computed={computed.hex()}. "
            "The trailing 20-byte SHA-1 checksum must be repaired in-place."
        )

    def test_pack_checksum_not_zeros(self):
        """The trailing checksum must not be all zeros (i.e., must be repaired)."""
        pack_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".pack")]
        assert pack_files, "No pack files found"
        pack_path = os.path.join(PACK_DIR, pack_files[0])
        with open(pack_path, "rb") as f:
            f.seek(-20, 2)
            trailing = f.read(20)
        assert trailing != b"\x00" * 20, (
            "Pack checksum is still all zeros — it has not been repaired"
        )

    def test_pack_header_valid(self):
        """Pack file must have valid PACK header and version 2."""
        pack_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".pack")]
        assert pack_files, "No pack files found"
        pack_path = os.path.join(PACK_DIR, pack_files[0])
        with open(pack_path, "rb") as f:
            magic = f.read(4)
            version = int.from_bytes(f.read(4), "big")
        assert magic == b"PACK", f"Invalid pack magic: {magic!r}"
        assert version == 2, f"Unexpected pack version: {version}"


class TestParserExists:
    """Verify the parser file exists and is valid Python."""

    def test_file_exists(self):
        assert os.path.exists(PACKPARSE), f"Parser not found at {PACKPARSE}"

    def test_valid_python(self):
        result = subprocess.run(
            ["python3", "-c",
             f"import py_compile; py_compile.compile('{PACKPARSE}', doraise=True)"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_no_subprocess_usage(self):
        """Verify the parser does not shell out to external commands."""
        with open(PACKPARSE) as f:
            content = f.read()
        forbidden = ["subprocess", "os.system(", "os.popen(", "commands."]
        for pattern in forbidden:
            assert pattern not in content, (
                f"Parser must not use '{pattern}' — "
                "implement pack parsing directly without external commands"
            )

    def test_no_git_library_usage(self):
        """Verify the parser does not use git libraries."""
        with open(PACKPARSE) as f:
            content = f.read()
        forbidden_imports = ["pygit2", "dulwich", "gitpython", "git.Repo"]
        for pattern in forbidden_imports:
            assert pattern not in content, (
                f"Parser must not use '{pattern}' — "
                "implement pack parsing from scratch"
            )


class TestIndexRebuild:
    """Verify that --rebuild-index produces a valid pack index."""

    def test_idx_file_created(self, rebuilt_index):
        idx_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".idx")]
        assert len(idx_files) >= 1, "No .idx file was created"

    def test_verify_pack_succeeds(self, rebuilt_index):
        """git verify-pack must accept the generated index."""
        idx_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".idx")]
        result = subprocess.run(
            ["git", "verify-pack", "-v",
             os.path.join(PACK_DIR, idx_files[0])],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        assert result.returncode == 0, (
            f"git verify-pack failed on rebuilt index:\n{result.stderr}"
        )

    def test_correct_object_count(self, rebuilt_index):
        """The rebuilt index must contain all objects from the pack."""
        idx_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".idx")]
        result = subprocess.run(
            ["git", "verify-pack", "-v",
             os.path.join(PACK_DIR, idx_files[0])],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        assert result.returncode == 0

        count = 0
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 5 and SHA1_RE.match(parts[0]):
                count += 1

        assert count >= 15, (
            f"Expected >= 15 objects in index, found {count}"
        )

    def test_git_log_works_after_rebuild(self, rebuilt_index):
        """After rebuilding the index, git log must succeed."""
        result = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        assert result.returncode == 0, f"git log failed: {result.stderr}"
        lines = result.stdout.strip().split("\n")
        assert len(lines) >= 5, (
            f"Expected >= 5 commits in log, got {len(lines)}"
        )

    def test_git_fsck_clean(self, rebuilt_index):
        """After rebuilding the index, git fsck must report no errors."""
        result = subprocess.run(
            ["git", "fsck", "--no-dangling"],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        assert result.returncode == 0, f"git fsck reported errors: {result.stderr}"


class TestObjectTypes:
    """Verify correct type identification for all objects."""

    def test_all_types_correct(self, rebuilt_index):
        objects, _ = get_all_objects(rebuilt_index)
        assert len(objects) > 0, "No objects found in pack"

        errors = []
        for obj in objects:
            sha1 = obj["sha1"]
            expected = git_text(["cat-file", "-t", sha1]).strip()
            actual = parser_text([GIT_DIR, "-t", sha1]).strip()
            if expected != actual:
                errors.append(f"{sha1}: expected '{expected}', got '{actual}'")

        assert not errors, "Type mismatches:\n" + "\n".join(errors)

    def test_has_commits(self, rebuilt_index):
        objects, _ = get_all_objects(rebuilt_index)
        commits = [o for o in objects if o["type"] == "commit"]
        assert len(commits) >= 5, (
            f"Expected >= 5 commits, found {len(commits)}"
        )

    def test_has_trees(self, rebuilt_index):
        objects, _ = get_all_objects(rebuilt_index)
        trees = [o for o in objects if o["type"] == "tree"]
        assert len(trees) >= 3, (
            f"Expected >= 3 trees, found {len(trees)}"
        )

    def test_has_blobs(self, rebuilt_index):
        objects, _ = get_all_objects(rebuilt_index)
        blobs = [o for o in objects if o["type"] == "blob"]
        assert len(blobs) >= 5, (
            f"Expected >= 5 blobs, found {len(blobs)}"
        )


class TestBlobContent:
    """Verify blob content extraction."""

    def test_all_blobs_match(self, rebuilt_index):
        objects, _ = get_all_objects(rebuilt_index)
        blobs = [o for o in objects if o["type"] == "blob"]

        errors = []
        for obj in blobs:
            sha1 = obj["sha1"]
            expected = git_binary(["cat-file", "-p", sha1])
            actual = parser_binary([GIT_DIR, "-p", sha1])
            if expected != actual:
                errors.append(
                    f"Blob {sha1}: expected {len(expected)} bytes, "
                    f"got {len(actual)} bytes"
                )

        assert not errors, "Blob content mismatches:\n" + "\n".join(errors)


class TestCommitContent:
    """Verify commit content extraction."""

    def test_all_commits_match(self, rebuilt_index):
        objects, _ = get_all_objects(rebuilt_index)
        commits = [o for o in objects if o["type"] == "commit"]

        errors = []
        for obj in commits:
            sha1 = obj["sha1"]
            expected = git_binary(["cat-file", "-p", sha1])
            actual = parser_binary([GIT_DIR, "-p", sha1])
            if expected != actual:
                exp_str = expected.decode("utf-8", errors="replace")[:300]
                act_str = actual.decode("utf-8", errors="replace")[:300]
                errors.append(
                    f"Commit {sha1}:\n"
                    f"  expected: {exp_str!r}\n"
                    f"  got:      {act_str!r}"
                )

        assert not errors, "Commit content mismatches:\n" + "\n".join(errors)


class TestTreeContent:
    """Verify tree content pretty-printing."""

    def test_all_trees_match(self, rebuilt_index):
        objects, _ = get_all_objects(rebuilt_index)
        trees = [o for o in objects if o["type"] == "tree"]

        errors = []
        for obj in trees:
            sha1 = obj["sha1"]
            expected = git_binary(["cat-file", "-p", sha1])
            actual = parser_binary([GIT_DIR, "-p", sha1])
            if expected != actual:
                exp_str = expected.decode("utf-8", errors="replace")[:300]
                act_str = actual.decode("utf-8", errors="replace")[:300]
                errors.append(
                    f"Tree {sha1}:\n"
                    f"  expected: {exp_str!r}\n"
                    f"  got:      {act_str!r}"
                )

        assert not errors, "Tree content mismatches:\n" + "\n".join(errors)


class TestDeltaResolution:
    """Verify that delta-encoded objects are correctly resolved."""

    def test_delta_objects_exist(self, rebuilt_index):
        _, delta_shas = get_all_objects(rebuilt_index)
        assert len(delta_shas) > 0, (
            "No delta objects found in pack file. "
            "The repository may not have enough similar content."
        )

    def test_delta_types_correct(self, rebuilt_index):
        _, delta_shas = get_all_objects(rebuilt_index)
        errors = []
        for sha1 in delta_shas:
            expected = git_text(["cat-file", "-t", sha1]).strip()
            actual = parser_text([GIT_DIR, "-t", sha1]).strip()
            if expected != actual:
                errors.append(
                    f"Delta {sha1}: type expected '{expected}', got '{actual}'"
                )
        assert not errors, "Delta type mismatches:\n" + "\n".join(errors)

    def test_delta_content_correct(self, rebuilt_index):
        _, delta_shas = get_all_objects(rebuilt_index)
        errors = []
        for sha1 in delta_shas:
            expected = git_binary(["cat-file", "-p", sha1])
            actual = parser_binary([GIT_DIR, "-p", sha1])
            if expected != actual:
                errors.append(
                    f"Delta {sha1}: content mismatch "
                    f"(expected {len(expected)} bytes, got {len(actual)} bytes)"
                )
        assert not errors, "Delta content mismatches:\n" + "\n".join(errors)


class TestEdgeCases:
    """Test edge cases and robustness."""

    def test_head_commit(self, rebuilt_index):
        head_sha = git_text(["rev-parse", "HEAD"]).strip()
        assert parser_text([GIT_DIR, "-t", head_sha]).strip() == "commit"

        expected = git_binary(["cat-file", "-p", head_sha])
        actual = parser_binary([GIT_DIR, "-p", head_sha])
        assert expected == actual, "HEAD commit content mismatch"

    def test_root_tree(self, rebuilt_index):
        tree_sha = git_text(["rev-parse", "HEAD^{tree}"]).strip()
        assert parser_text([GIT_DIR, "-t", tree_sha]).strip() == "tree"

        expected = git_binary(["cat-file", "-p", tree_sha])
        actual = parser_binary([GIT_DIR, "-p", tree_sha])
        assert expected == actual, "Root tree content mismatch"

    def test_merge_commit_extraction(self, rebuilt_index):
        """Verify a merge commit (multiple parents) is handled correctly."""
        objects, _ = get_all_objects(rebuilt_index)
        commits = [o for o in objects if o["type"] == "commit"]

        merge_found = False
        for obj in commits:
            content = git_text(["cat-file", "-p", obj["sha1"]])
            parent_count = content.count("\nparent ")
            if parent_count >= 2:
                actual = parser_binary([GIT_DIR, "-p", obj["sha1"]])
                expected = git_binary(["cat-file", "-p", obj["sha1"]])
                assert expected == actual, (
                    f"Merge commit {obj['sha1']} content mismatch"
                )
                merge_found = True
                break

        assert merge_found, "No merge commit found in the repository"

    def test_nonexistent_object_fails(self, rebuilt_index):
        fake_sha = "0" * 40
        result = subprocess.run(
            ["python3", PACKPARSE, GIT_DIR, "-t", fake_sha],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        assert result.returncode != 0, (
            "Expected non-zero exit for non-existent object"
        )

    def test_all_objects_extractable(self, rebuilt_index):
        """Every object in the pack must be extractable without error."""
        objects, _ = get_all_objects(rebuilt_index)
        errors = []
        for obj in objects:
            sha1 = obj["sha1"]
            result = subprocess.run(
                ["python3", PACKPARSE, GIT_DIR, "-p", sha1],
                capture_output=True, cwd=REPO_DIR
            )
            if result.returncode != 0:
                errors.append(
                    f"{sha1} ({obj['type']}): "
                    f"{result.stderr.decode(errors='replace').strip()}"
                )
        assert not errors, "Extraction failures:\n" + "\n".join(errors)

    def test_subdirectory_tree(self, rebuilt_index):
        """Verify tree objects for subdirectories parse correctly."""
        tree_sha = git_text(["rev-parse", "HEAD^{tree}"]).strip()
        tree_content = git_text(["cat-file", "-p", tree_sha])

        subtree_sha = None
        for line in tree_content.strip().split("\n"):
            if line.startswith("040000 tree"):
                parts = line.split()
                subtree_sha = parts[2]
                break

        assert subtree_sha is not None, "No subdirectory found in root tree"

        expected = git_binary(["cat-file", "-p", subtree_sha])
        actual = parser_binary([GIT_DIR, "-p", subtree_sha])
        assert expected == actual, f"Subtree {subtree_sha} content mismatch"


class TestDirectPackAccess:
    """Verify parser works without an index file (direct pack scanning)."""

    def test_type_query_without_index(self, rebuilt_index):
        """Parser must work even if the .idx file is temporarily absent."""
        head_sha = git_text(["rev-parse", "HEAD"]).strip()

        idx_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".idx")]
        assert idx_files, "No .idx files found to test with"
        idx_path = os.path.join(PACK_DIR, idx_files[0])

        with open(idx_path, "rb") as f:
            idx_backup = f.read()

        try:
            os.remove(idx_path)
            result = subprocess.run(
                ["python3", PACKPARSE, GIT_DIR, "-t", head_sha],
                capture_output=True, text=True, cwd=REPO_DIR
            )
            assert result.returncode == 0, (
                f"Parser failed without index: {result.stderr}"
            )
            assert result.stdout.strip() == "commit", (
                f"Expected 'commit', got '{result.stdout.strip()}'"
            )
        finally:
            with open(idx_path, "wb") as f:
                f.write(idx_backup)

    def test_content_query_without_index(self, rebuilt_index):
        """Parser must produce correct content without an index file."""
        head_sha = git_text(["rev-parse", "HEAD"]).strip()
        expected = git_binary(["cat-file", "-p", head_sha])

        idx_files = [f for f in os.listdir(PACK_DIR) if f.endswith(".idx")]
        idx_path = os.path.join(PACK_DIR, idx_files[0])

        with open(idx_path, "rb") as f:
            idx_backup = f.read()

        try:
            os.remove(idx_path)
            actual = parser_binary([GIT_DIR, "-p", head_sha])
            assert expected == actual, "Content mismatch when running without index"
        finally:
            with open(idx_path, "wb") as f:
                f.write(idx_backup)


class TestRecoveryBundle:
    """Verify the recovery bundle exists and is valid."""

    def test_bundle_exists(self, rebuilt_index):
        """A recovery bundle must exist at /app/recovered.bundle."""
        assert os.path.exists(BUNDLE_PATH), (
            f"Recovery bundle not found at {BUNDLE_PATH}"
        )

    def test_bundle_not_empty(self, rebuilt_index):
        """The bundle file must not be empty."""
        size = os.path.getsize(BUNDLE_PATH)
        assert size > 0, "Recovery bundle is empty"

    def test_bundle_verify(self, rebuilt_index):
        """The bundle must pass git bundle verify."""
        result = subprocess.run(
            ["git", "bundle", "verify", BUNDLE_PATH],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        assert result.returncode == 0, (
            f"git bundle verify failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_bundle_contains_refs(self, rebuilt_index):
        """The bundle must contain at least one ref (branch)."""
        result = subprocess.run(
            ["git", "bundle", "list-heads", BUNDLE_PATH],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"git bundle list-heads failed: {result.stderr}"
        )
        heads = result.stdout.strip().split("\n")
        assert len(heads) >= 1 and heads[0], (
            "Bundle contains no refs"
        )

    def test_bundle_has_main_branch(self, rebuilt_index):
        """The bundle must contain the main branch."""
        result = subprocess.run(
            ["git", "bundle", "list-heads", BUNDLE_PATH],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "refs/heads/main" in result.stdout, (
            "Bundle does not contain refs/heads/main"
        )


class TestVerifyReport:
    """Verify the verification report exists and has valid content."""

    def test_report_exists(self, rebuilt_index):
        """Verification report must exist at /app/verify_report.txt."""
        assert os.path.exists(REPORT_PATH), (
            f"Verification report not found at {REPORT_PATH}"
        )

    def test_report_not_empty(self, rebuilt_index):
        """The report must not be empty."""
        size = os.path.getsize(REPORT_PATH)
        assert size > 0, "Verification report is empty"

    def test_report_contains_objects(self, rebuilt_index):
        """The report must contain git verify-pack -v output with object listings."""
        with open(REPORT_PATH) as f:
            content = f.read()

        object_lines = []
        for line in content.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 5 and SHA1_RE.match(parts[0]) and parts[1] in VALID_TYPES:
                object_lines.append(line)

        assert len(object_lines) >= 15, (
            f"Report has too few object entries: {len(object_lines)}, expected >= 15. "
            "The report should contain the full output of git verify-pack -v."
        )

    def test_report_object_types_present(self, rebuilt_index):
        """The report must list commits, trees, and blobs."""
        with open(REPORT_PATH) as f:
            content = f.read()

        found_types = set()
        for line in content.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 5 and SHA1_RE.match(parts[0]) and parts[1] in VALID_TYPES:
                found_types.add(parts[1])

        assert "commit" in found_types, "Report missing commit objects"
        assert "tree" in found_types, "Report missing tree objects"
        assert "blob" in found_types, "Report missing blob objects"
